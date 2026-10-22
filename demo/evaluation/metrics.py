"""计算并保存Demo阶段的舆情指标。

当前按轮计算全局评论趋势、Agent情绪、官方态度和社交传播指标。

单次实验结束后还可基于逐轮指标和Agent状态历史计算过程指标。
"""

import json
import math

from comments.repository import load_comment_pool, load_incremental_comments
from simulation.event_context import load_event_context
from infrastructure.json_storage import append_jsonl, read_jsonl
from infrastructure.llm_service import call_deepseek_json
from evaluation.propagation_metrics import (
    calculate_propagation_metrics,
    load_propagation_events,
)
from project_config import (
    COMMENT_POOL_FILE,
    DECISION_HISTORY_FILE,
    EVENT_FILE,
    EVENT_STATE_FILE,
    INCREMENTAL_COMMENT_FILE,
    METRICS_HISTORY_FILE,
    PROPAGATION_HISTORY_FILE,
    ensure_runtime_directories,
)


TREND_DIRECTIONS = ("improving", "stable", "worsening")
OFFICIAL_ATTITUDES = ("accept", "wait", "question")
EMOTIONS = ("positive", "neutral", "negative")
# 2026/08/24 第三次联调问题修复，新增功能：限制全局趋势说明和证据编号的输出长度。
GLOBAL_TREND_REASON_LIMIT = 100
GLOBAL_TREND_EVIDENCE_LIMIT = 5
GLOBAL_TREND_MAX_TOKENS = 2000


def filter_successful_decisions(decision_records):
    """从决策结果中筛选包含有效decision对象的成功记录。"""
    return [
        record
        for record in decision_records
        if record.get("status") == "success"
        and isinstance(record.get("decision"), dict)
    ]


def load_round_decisions(
    event_id,
    step,
    decision_history_file=DECISION_HISTORY_FILE,
):
    """读取指定事件和时间步的成功Agent决策，自动排除预览和失败记录。"""
    decisions = []
    for record in read_jsonl(decision_history_file):
        if record.get("event_id") != event_id or record.get("step") != step:
            continue
        decisions.append(record)
    return filter_successful_decisions(decisions)


def simplify_comments(comments):
    """只保留趋势分析需要的评论字段，减少LLM输入长度。"""
    return [
        {
            "comment_id": comment.get("comment_id"),
            "text": comment.get("text", ""),
            "emotion": comment.get("emotion"),
            "faction": comment.get("faction"),
            "stance": comment.get("stance"),
            "introduced_step": comment.get("introduced_step"),
        }
        for comment in comments
    ]


# 2026/08/24 第三次联调问题修复，修改功能：使用紧凑输入并限制趋势分析的输出规模。
def build_global_trend_prompt(event_context, initial_comments, incremental_comments):
    """构造初始评论与当前轮增量评论的全局趋势分析提示词。"""
    allowed_comment_ids = [
        comment.get("comment_id").strip()
        for comment in initial_comments + incremental_comments
        if isinstance(comment.get("comment_id"), str)
        and comment.get("comment_id").strip()
    ]
    output_format = {
        "trend_direction": "improving | stable | worsening",
        "reason": "不超过100字的一句话说明",
        "evidence_comment_ids": ["最多5个支持结论的评论编号"],
    }
    return f"""
你是社会舆情趋势分析器。请比较初始评论与当前轮新增评论，判断本轮讨论趋势。

【事件和当前官方声明】
{json.dumps(event_context, ensure_ascii=False)}

【初始评论】
{json.dumps(simplify_comments(initial_comments), ensure_ascii=False)}

【当前轮增量评论】
{json.dumps(simplify_comments(incremental_comments), ensure_ascii=False)}

【允许引用的评论编号】
{json.dumps(allowed_comment_ids, ensure_ascii=False)}

判断标准：
1. 负面、质疑和激进表达减少，趋向中性、理性或接受，判断为 improving。
2. 情绪和立场没有明显变化，判断为 stable。
3. 负面、质疑、批评、激进或对立表达增加，判断为 worsening。
4. 只能依据提供的评论进行判断，不要计算或编造精确比例。
5. reason 必须为一句话且不超过 {GLOBAL_TREND_REASON_LIMIT} 字。
6. evidence_comment_ids 只能逐字复制“允许引用的评论编号”中的值，最多返回 {GLOBAL_TREND_EVIDENCE_LIMIT} 个；没有可靠证据时返回空数组。

只返回一个紧凑JSON对象，不要换行或补充其他字段：
{json.dumps(output_format, ensure_ascii=False)}
""".strip()


# 2026/08/24 第三次联调问题修复，修改功能：规范化过长说明并限制有效证据编号数量。
# 2026/10/08 历史复现趋势证据容错，修改功能：非法证据编号降级为可审计告警，不再中断整轮实验。
def validate_global_trend(result, valid_comment_ids):
    """检查并规范化LLM返回的全局趋势结果。"""
    if not isinstance(result, dict):
        raise ValueError("全局趋势分析结果必须是JSON对象。")
    if result.get("trend_direction") not in TREND_DIRECTIONS:
        raise ValueError("trend_direction 必须是 improving、stable 或 worsening。")

    reason = str(result.get("reason", "")).strip()
    if not reason:
        raise ValueError("全局趋势分析结果缺少reason。")

    normalized_valid_ids = {
        item.strip()
        for item in valid_comment_ids
        if isinstance(item, str) and item.strip()
    }
    raw_evidence_ids = result.get("evidence_comment_ids")
    validation_issues = []
    invalid_ids = []
    valid_evidence_ids = []

    # evidence_comment_ids 只用于解释趋势结论，不参与负面率、官方态度或
    # 传播指标计算。模型偶发返回越界编号时保留核心趋势，并记录过滤结果，
    # 避免一个辅助证据字段使已经完成的 Agent 决策和传播计算全部作废。
    if not isinstance(raw_evidence_ids, list):
        validation_issues.append("evidence_comment_ids_not_array")
        raw_evidence_ids = []

    for item in raw_evidence_ids:
        if not isinstance(item, str):
            validation_issues.append("non_string_evidence_id")
            invalid_ids.append(str(item))
            continue
        normalized_id = item.strip()
        if normalized_id not in normalized_valid_ids:
            invalid_ids.append(normalized_id)
            continue
        valid_evidence_ids.append(normalized_id)

    unique_evidence_ids = list(dict.fromkeys(valid_evidence_ids))[
        :GLOBAL_TREND_EVIDENCE_LIMIT
    ]
    unique_invalid_ids = list(dict.fromkeys(invalid_ids))[
        :GLOBAL_TREND_EVIDENCE_LIMIT
    ]
    if unique_invalid_ids:
        validation_issues.append("invalid_evidence_comment_ids_filtered")

    return {
        "trend_direction": result["trend_direction"],
        "reason": reason[:GLOBAL_TREND_REASON_LIMIT],
        "evidence_comment_ids": unique_evidence_ids,
        "evidence_validation": {
            "status": "filtered" if validation_issues else "valid",
            "issues": list(dict.fromkeys(validation_issues)),
            "invalid_ids": unique_invalid_ids,
        },
    }


# 2026/08/24 第三次联调问题修复，修改功能：为受控趋势JSON预留足够的输出空间。
def analyze_global_trend(event_context, initial_comments, incremental_comments):
    """调用LLM分析初始评论和当前轮增量评论之间的变化趋势。"""
    if not incremental_comments:
        return {
            "trend_direction": "stable",
            "reason": "当前只有初始评论，作为后续趋势比较的基线。",
            "evidence_comment_ids": [],
            "evidence_validation": {
                "status": "valid",
                "issues": [],
                "invalid_ids": [],
            },
        }

    prompt = build_global_trend_prompt(
        event_context,
        initial_comments,
        incremental_comments,
    )
    result = call_deepseek_json(
        prompt=prompt,
        system_prompt="你只能返回符合要求的合法JSON对象。",
        temperature=0,
        max_tokens=GLOBAL_TREND_MAX_TOKENS,
        # 2026/09/04 Demo性能基线，新增功能：标记全局趋势分析请求类型。
        request_type="global_trend",
    )
    valid_comment_ids = {
        comment.get("comment_id")
        for comment in initial_comments + incremental_comments
    }
    return validate_global_trend(result, valid_comment_ids)


def calculate_negative_emotion_rate(agent_decisions):
    """计算成功决策Agent中的负面情绪数量和比例。"""
    agent_count = len(agent_decisions)
    negative_count = sum(
        1
        for record in agent_decisions
        if record["decision"].get("current_emotion") == "negative"
    )
    negative_rate = negative_count / agent_count if agent_count else 0.0
    return {
        "agent_count": agent_count,
        "negative_count": negative_count,
        "negative_rate": round(negative_rate, 6),
    }


# 2026/08/25 第五次联调问题修复，新增功能：保留三种情绪的完整分布以诊断负面率变化。
def calculate_emotion_distribution(agent_decisions):
    """计算成功决策Agent的正面、中性和负面情绪分布。"""
    agent_count = len(agent_decisions)
    distribution = {}
    for emotion in EMOTIONS:
        count = sum(
            1
            for record in agent_decisions
            if record["decision"].get("current_emotion") == emotion
        )
        distribution[emotion] = {
            "count": count,
            "rate": round(count / agent_count, 6) if agent_count else 0.0,
        }
    return {
        "agent_count": agent_count,
        "distribution": distribution,
    }


# 2026/10/12，历史趋势复现观测口径修正，新增功能：单独统计 Agent
# 实际发表的评论，不再用内部情绪或生成候选评论冒充公众可观测表达。
def calculate_expression_distribution(agent_decisions):
    """统计 Agent 本轮实际表达的评论情绪和明确分母。

    ``current_emotion`` 是 Agent 的内部状态；真实采集数据则来自已经发表的
    评论。二者必须分别统计。表达情绪以最终选中评论的 ``emotion`` 为准，
    分布分母只包含具有合法三分类标签的实际表达，同时保留沉默和未分类数量。
    """

    agent_count = len(agent_decisions)
    expressions = []
    for record in agent_decisions:
        decision = record.get("decision", {})
        selected_comment = decision.get("selected_comment")
        if decision.get("will_comment") is True and isinstance(
            selected_comment, dict
        ):
            expressions.append(selected_comment)

    counts = {
        emotion: sum(
            1 for comment in expressions if comment.get("emotion") == emotion
        )
        for emotion in EMOTIONS
    }
    classified_count = sum(counts.values())
    expression_count = len(expressions)
    distribution = {
        emotion: {
            "count": counts[emotion],
            "rate": (
                round(counts[emotion] / classified_count, 6)
                if classified_count
                else None
            ),
        }
        for emotion in EMOTIONS
    }
    return {
        "agent_count": agent_count,
        "expression_count": expression_count,
        "silent_agent_count": agent_count - expression_count,
        "participation_rate": (
            round(expression_count / agent_count, 6) if agent_count else 0.0
        ),
        "classified_expression_count": classified_count,
        "unclassified_expression_count": expression_count - classified_count,
        "distribution": distribution,
    }


# 2026/10/16，新增功能：单独统计沉默、原创和转发，并记录
# 原创文本的去重率。该指标不改变内部情绪的全Agent分母，也不用
# 发言人数反推情绪结论。
def calculate_action_distribution(agent_decisions):
    """返回Agent行为分布和可观测表达的基础多样性。"""

    decisions = [record.get("decision", {}) for record in agent_decisions]
    action_types = []
    original_texts = []
    for decision in decisions:
        action_type = decision.get("action_type")
        if action_type not in {"silent", "original", "reshare"}:
            action_type = "original" if decision.get("will_comment") else "silent"
        action_types.append(action_type)
        if action_type == "original":
            selected_comment = decision.get("selected_comment", {})
            text = str(selected_comment.get("text", "")).strip()
            if text:
                original_texts.append(text)

    agent_count = len(decisions)
    distribution = {}
    for action_type in ("silent", "original", "reshare"):
        count = action_types.count(action_type)
        distribution[action_type] = {
            "count": count,
            "rate": round(count / agent_count, 6) if agent_count else 0.0,
        }
    unique_original_count = len(set(original_texts))
    return {
        "agent_count": agent_count,
        "distribution": distribution,
        "original_expression_count": len(original_texts),
        "unique_original_expression_count": unique_original_count,
        "original_expression_uniqueness_rate": (
            round(unique_original_count / len(original_texts), 6)
            if original_texts
            else None
        ),
    }


# 2026/08/25 第五次联调问题修复，修改功能：无声明时将官方态度指标标为不适用。
def calculate_attitude_distribution(agent_decisions, statement_status=None):
    """仅使用存在官方声明时的适用Agent计算官方态度分布。"""
    agent_count = len(agent_decisions)
    statement_applicable = (
        statement_status != "none"
        if statement_status is not None
        else any(
            record["decision"].get("official_attitude") != "not_applicable"
            for record in agent_decisions
        )
    )
    applicable_decisions = agent_decisions if statement_applicable else []
    applicable_agent_count = sum(
        1
        for record in applicable_decisions
        if record["decision"].get("official_attitude") in OFFICIAL_ATTITUDES
    )
    distribution = {}
    for attitude in OFFICIAL_ATTITUDES:
        count = sum(
            1
            for record in applicable_decisions
            if record["decision"].get("official_attitude") == attitude
        )
        rate = (
            round(count / applicable_agent_count, 6)
            if applicable_agent_count
            else None
        )
        distribution[attitude] = {
            "count": count,
            "rate": rate,
        }

    return {
        "agent_count": agent_count,
        "applicable_agent_count": applicable_agent_count,
        "not_applicable_count": agent_count - applicable_agent_count,
        "distribution": distribution,
    }


# 2026/10/14，新增功能：把群体趋同作为可观测诊断，而不是实验熔断条件。
def calculate_attitude_diagnostics(agent_decisions, statement_status=None):
    """诊断官方态度多样性、同步转向和两个内部判断维度。"""

    statement_applicable = (
        statement_status != "none"
        if statement_status is not None
        else any(
            record.get("decision", {}).get("official_attitude")
            != "not_applicable"
            for record in agent_decisions
        )
    )
    decisions = [
        record.get("decision", {})
        for record in agent_decisions
        if statement_applicable
        and record.get("decision", {}).get("official_attitude")
        in OFFICIAL_ATTITUDES
    ]
    count = len(decisions)

    attitude_counts = {
        attitude: sum(
            decision.get("official_attitude") == attitude
            for decision in decisions
        )
        for attitude in OFFICIAL_ATTITUDES
    }
    nonzero_rates = [value / count for value in attitude_counts.values() if value]
    entropy = -sum(rate * math.log(rate) for rate in nonzero_rates)
    normalized_entropy = entropy / math.log(len(OFFICIAL_ATTITUDES)) if count else None
    largest_group_count = max(attitude_counts.values(), default=0)

    transition_reasons = [
        decision.get("official_attitude_resolution", {}).get(
            "transition_reason"
        )
        for decision in decisions
    ]
    changed_count = sum(
        reason in {"changed_after_threshold", "moved_one_level_only"}
        for reason in transition_reasons
    )

    def dimension_distribution(field, values):
        return {
            value: {
                "count": sum(decision.get(field) == value for decision in decisions),
                "rate": (
                    round(
                        sum(decision.get(field) == value for decision in decisions)
                        / count,
                        6,
                    )
                    if count
                    else None
                ),
            }
            for value in values
        }

    return {
        "applicable_agent_count": count,
        "largest_attitude_group_count": largest_group_count,
        "largest_attitude_group_rate": (
            round(largest_group_count / count, 6) if count else None
        ),
        "normalized_attitude_entropy": (
            round(normalized_entropy, 6)
            if normalized_entropy is not None
            else None
        ),
        "changed_agent_count": changed_count,
        "synchronized_transition_rate": (
            round(changed_count / count, 6) if count else None
        ),
        "claim_position_distribution": dimension_distribution(
            "claim_position",
            ("accepted", "unresolved", "challenged"),
        ),
        "process_evaluation_distribution": dimension_distribution(
            "process_evaluation",
            ("satisfied", "partial", "dissatisfied"),
        ),
        "diagnostic_only": True,
    }


# 2026/10/17，新增功能：聚合个人视图中的有效邻居曝光诊断。
def calculate_neighbor_exposure_diagnostics(agent_decisions):
    """统计邻居曝光目标的实际填充率、轮龄和根表达去重情况。"""

    target_total = 0
    visible_total = 0
    full_target_count = 0
    zero_exposure_count = 0
    root_total = 0
    age_distribution = {}
    applicable_count = 0
    for record in agent_decisions:
        target = record.get("neighbor_target_count")
        visible = record.get("neighbor_visible_count")
        if (
            isinstance(target, bool)
            or not isinstance(target, int)
            or target <= 0
            or isinstance(visible, bool)
            or not isinstance(visible, int)
        ):
            continue
        applicable_count += 1
        target_total += target
        visible_total += max(0, visible)
        full_target_count += visible >= target
        zero_exposure_count += visible == 0
        root_count = record.get("unique_neighbor_root_count", 0)
        if isinstance(root_count, int) and not isinstance(root_count, bool):
            root_total += max(0, root_count)
        for age, count in record.get(
            "neighbor_expression_age_distribution", {}
        ).items():
            if isinstance(count, int) and not isinstance(count, bool):
                age_distribution[str(age)] = (
                    age_distribution.get(str(age), 0) + max(0, count)
                )

    return {
        "applicable_agent_count": applicable_count,
        "target_exposure_count": target_total,
        "effective_exposure_count": visible_total,
        "effective_neighbor_exposure_rate": (
            round(visible_total / target_total, 6)
            if target_total
            else None
        ),
        "full_target_agent_rate": (
            round(full_target_count / applicable_count, 6)
            if applicable_count
            else None
        ),
        "zero_exposure_agent_rate": (
            round(zero_exposure_count / applicable_count, 6)
            if applicable_count
            else None
        ),
        "average_unique_root_count": (
            round(root_total / applicable_count, 6)
            if applicable_count
            else None
        ),
        "expression_age_distribution": age_distribution,
        "diagnostic_only": True,
    }


# 2026/10/18，新增功能：汇总Persona状态门槛、方向性证据效用及
# 邻居/公共证据限流效果。
# 2026/10/19，修改功能：增加证据生命周期的新增、延续和消费数量，
# 用于区分“没有新证据”与“权威证据仍在有限吸收期”。
def calculate_strategy_state_diagnostics(agent_decisions):
    """统计策略状态变化来源，不把诊断值作为新的群体控制条件。"""

    applicable = []
    for record in agent_decisions:
        decision = record.get("decision", {})
        if isinstance(decision.get("strategy_state_guard"), dict):
            applicable.append(decision)
    if not applicable:
        return {
            "applicable_agent_count": 0,
            "diagnostic_only": True,
        }

    peer_signals = []
    peer_thresholds = []
    emotion_changed_count = 0
    attitude_changed_count = 0
    peer_allowed_count = 0
    peer_held_count = 0
    neighbor_visible_total = 0
    neighbor_state_total = 0
    public_visible_total = 0
    public_state_total = 0
    exogenous_state_total = 0
    endogenous_state_total = 0
    effective_non_peer_total = 0
    held_non_peer_total = 0
    directional_group_total = 0
    lifecycle_new_total = 0
    lifecycle_restored_total = 0
    lifecycle_consumed_total = 0
    assimilation_active_total = 0
    assimilation_new_total = 0
    assimilation_restored_total = 0
    assimilation_expired_total = 0
    assimilation_consumed_total = 0
    assimilation_fractions = []
    attitude_memory_active_total = 0
    attitude_memory_new_total = 0
    attitude_memory_restored_total = 0
    utility_margins = []
    switch_margins = []
    directional_support_totals = {
        "positive": 0.0,
        "neutral": 0.0,
        "negative": 0.0,
    }
    transition_basis_counts = {}
    transition_reason_counts = {}
    attitude_reason_counts = {}
    for decision in applicable:
        transition = decision.get("state_transition_diagnostics", {})
        evidence = decision.get("state_evidence_diagnostics", {})
        signal = transition.get("peer_signal_strength")
        threshold = transition.get("peer_change_threshold")
        if isinstance(signal, (int, float)) and not isinstance(signal, bool):
            peer_signals.append(float(signal))
        if isinstance(threshold, (int, float)) and not isinstance(
            threshold,
            bool,
        ):
            peer_thresholds.append(float(threshold))
        emotion_changed_count += transition.get("emotion_changed") is True
        attitude_changed_count += (
            transition.get("official_attitude_changed") is True
        )
        basis = str(transition.get("state_change_basis", "unknown"))
        transition_basis_counts[basis] = transition_basis_counts.get(
            basis,
            0,
        ) + 1
        # 新版方向性整合器直接保存邻居信号是否满足个体门槛；保留
        # 旧basis兼容历史实验记录和离线可视化。
        peer_eligible = transition.get("peer_influence_eligible")
        if peer_eligible is True or (
            basis == "peer_signal_passed_persona_threshold"
        ):
            peer_allowed_count += 1
        elif (
            int(transition.get("independent_neighbor_root_count", 0) or 0)
            > 0
            or basis == "peer_signal_below_persona_threshold"
        ):
            peer_held_count += 1
        transition_reason = str(
            transition.get("transition_reason", "unknown")
        )
        transition_reason_counts[transition_reason] = (
            transition_reason_counts.get(transition_reason, 0) + 1
        )
        reason = str(
            transition.get("official_transition_reason", "unknown")
        )
        attitude_reason_counts[reason] = attitude_reason_counts.get(
            reason,
            0,
        ) + 1
        neighbor_visible_total += int(
            evidence.get("neighbor_visible_comment_count", 0) or 0
        )
        neighbor_state_total += int(
            evidence.get("neighbor_state_evidence_count", 0) or 0
        )
        public_visible_total += int(
            evidence.get("public_visible_comment_count", 0) or 0
        )
        public_state_total += int(
            evidence.get("public_state_evidence_count", 0) or 0
        )
        exogenous_state_total += int(
            evidence.get("exogenous_state_evidence_count", 0) or 0
        )
        endogenous_state_total += int(
            evidence.get("endogenous_state_evidence_count", 0) or 0
        )
        effective_non_peer_total += int(
            transition.get("effective_non_peer_evidence_count", 0) or 0
        )
        held_non_peer_total += int(
            transition.get("held_non_peer_evidence_count", 0) or 0
        )
        directional_group_total += int(
            transition.get("directional_evidence_group_count", 0) or 0
        )
        lifecycle = transition.get("evidence_lifecycle", {})
        if isinstance(lifecycle, dict):
            lifecycle_new_total += int(
                lifecycle.get("new_group_count", 0) or 0
            )
            lifecycle_restored_total += int(
                lifecycle.get("restored_group_count", 0) or 0
            )
            lifecycle_consumed_total += int(
                lifecycle.get("consumed_group_count", 0) or 0
            )
        assimilation = transition.get("evidence_assimilation", {})
        if isinstance(assimilation, dict):
            assimilation_active_total += int(
                assimilation.get("active_group_count", 0) or 0
            )
            assimilation_new_total += int(
                assimilation.get("new_group_count", 0) or 0
            )
            assimilation_restored_total += int(
                assimilation.get("restored_group_count", 0) or 0
            )
            assimilation_expired_total += int(
                assimilation.get("expired_group_count", 0) or 0
            )
            assimilation_consumed_total += int(
                assimilation.get("consumed_group_count", 0) or 0
            )
            absorbed_fraction = assimilation.get(
                "average_absorbed_fraction"
            )
            if isinstance(absorbed_fraction, (int, float)) and not isinstance(
                absorbed_fraction,
                bool,
            ):
                assimilation_fractions.append(float(absorbed_fraction))
        attitude_lifecycle = transition.get("attitude_lifecycle", {})
        if isinstance(attitude_lifecycle, dict):
            attitude_memory_active_total += int(
                attitude_lifecycle.get("active_count", 0) or 0
            )
            attitude_memory_new_total += int(
                attitude_lifecycle.get("new_count", 0) or 0
            )
            attitude_memory_restored_total += int(
                attitude_lifecycle.get("restored_count", 0) or 0
            )
        utility_margin = transition.get("utility_margin")
        if isinstance(utility_margin, (int, float)) and not isinstance(
            utility_margin,
            bool,
        ):
            utility_margins.append(float(utility_margin))
        switch_margin = transition.get("required_switch_margin")
        if isinstance(switch_margin, (int, float)) and not isinstance(
            switch_margin,
            bool,
        ):
            switch_margins.append(float(switch_margin))
        directional_support = transition.get(
            "aggregated_directional_support",
            {},
        )
        if isinstance(directional_support, dict):
            for emotion in directional_support_totals:
                value = directional_support.get(emotion)
                if isinstance(value, (int, float)) and not isinstance(
                    value,
                    bool,
                ):
                    directional_support_totals[emotion] += float(value)

    count = len(applicable)
    return {
        "applicable_agent_count": count,
        "emotion_changed_count": emotion_changed_count,
        "emotion_changed_rate": round(emotion_changed_count / count, 6),
        "official_attitude_changed_count": attitude_changed_count,
        "official_attitude_changed_rate": round(
            attitude_changed_count / count,
            6,
        ),
        "peer_transition_allowed_count": peer_allowed_count,
        "peer_transition_held_count": peer_held_count,
        "average_peer_signal_strength": (
            round(sum(peer_signals) / len(peer_signals), 6)
            if peer_signals
            else None
        ),
        "average_peer_change_threshold": (
            round(sum(peer_thresholds) / len(peer_thresholds), 6)
            if peer_thresholds
            else None
        ),
        "neighbor_visible_comment_count": neighbor_visible_total,
        "neighbor_state_evidence_count": neighbor_state_total,
        "neighbor_state_evidence_retention_rate": (
            round(neighbor_state_total / neighbor_visible_total, 6)
            if neighbor_visible_total
            else None
        ),
        "public_visible_comment_count": public_visible_total,
        "public_state_evidence_count": public_state_total,
        "public_state_evidence_retention_rate": (
            round(public_state_total / public_visible_total, 6)
            if public_visible_total
            else None
        ),
        # 2026/10/19，新增功能：分开审计外部语境与Agent内生表达，避免把
        # 两类信息混成一个“评论池数量”后误判方案效果来源。
        "exogenous_state_evidence_count": exogenous_state_total,
        "endogenous_state_evidence_count": endogenous_state_total,
        "effective_non_peer_evidence_count": effective_non_peer_total,
        "held_non_peer_evidence_count": held_non_peer_total,
        "directional_evidence_group_count": directional_group_total,
        "average_directional_evidence_group_count": round(
            directional_group_total / count,
            6,
        ),
        "lifecycle_new_evidence_group_count": lifecycle_new_total,
        "lifecycle_restored_evidence_group_count": (
            lifecycle_restored_total
        ),
        "lifecycle_consumed_evidence_group_count": (
            lifecycle_consumed_total
        ),
        # 2026/10/20，新增功能：渐进吸收诊断只用于解释不同Persona的
        # 延迟变化，不参与群体配额、进场判断或结果改写。
        "assimilation_active_evidence_group_count": (
            assimilation_active_total
        ),
        "assimilation_new_evidence_group_count": assimilation_new_total,
        "assimilation_restored_evidence_group_count": (
            assimilation_restored_total
        ),
        "assimilation_expired_evidence_group_count": (
            assimilation_expired_total
        ),
        "assimilation_consumed_evidence_group_count": (
            assimilation_consumed_total
        ),
        "average_authoritative_absorbed_fraction": (
            round(
                sum(assimilation_fractions) / len(assimilation_fractions),
                6,
            )
            if assimilation_fractions
            else None
        ),
        "attitude_memory_active_evidence_count": (
            attitude_memory_active_total
        ),
        "attitude_memory_new_evidence_count": attitude_memory_new_total,
        "attitude_memory_restored_evidence_count": (
            attitude_memory_restored_total
        ),
        "average_directional_support": {
            emotion: round(total / count, 6)
            for emotion, total in directional_support_totals.items()
        },
        "average_utility_margin": (
            round(sum(utility_margins) / len(utility_margins), 6)
            if utility_margins
            else None
        ),
        "average_required_switch_margin": (
            round(sum(switch_margins) / len(switch_margins), 6)
            if switch_margins
            else None
        ),
        "transition_basis_counts": transition_basis_counts,
        "transition_reason_counts": transition_reason_counts,
        "official_transition_reason_counts": attitude_reason_counts,
        "diagnostic_only": True,
    }


# 2026/08/25 第五次联调问题修复，修改功能：保存完整情绪分布并按声明状态计算官方态度。
def calculate_round_metrics(
    event_context,
    agent_decisions,
    global_trend,
    propagation_metrics=None,
):
    """组合舆情状态和传播指标，生成一个时间步的指标记录。"""
    successful_decisions = filter_successful_decisions(agent_decisions)
    return {
        "event_id": event_context["event_id"],
        "step": event_context["current_state"]["step"],
        "global_trend": global_trend,
        "agent_negative_emotion": calculate_negative_emotion_rate(
            successful_decisions
        ),
        "agent_emotion_distribution": calculate_emotion_distribution(
            successful_decisions
        ),
        "agent_expression_distribution": calculate_expression_distribution(
            successful_decisions
        ),
        "agent_action_distribution": calculate_action_distribution(
            successful_decisions
        ),
        "official_attitude_distribution": calculate_attitude_distribution(
            successful_decisions,
            event_context.get("current_state", {}).get(
                "official_statement_status",
                "none",
            ),
        ),
        "official_attitude_diagnostics": calculate_attitude_diagnostics(
            successful_decisions,
            event_context.get("current_state", {}).get(
                "official_statement_status",
                "none",
            ),
        ),
        "neighbor_exposure_diagnostics": (
            calculate_neighbor_exposure_diagnostics(successful_decisions)
        ),
        "strategy_state_diagnostics": (
            calculate_strategy_state_diagnostics(successful_decisions)
        ),
        # 2026/9/5，社交网络传播第二阶段A，新增功能：在单轮指标中保存传播覆盖和深度。
        "propagation_metrics": propagation_metrics
        or calculate_propagation_metrics([], len(successful_decisions)),
    }


def save_round_metrics(round_metrics, output_file=METRICS_HISTORY_FILE):
    """将本轮指标追加保存到metrics_history.jsonl。"""
    event_id = round_metrics.get("event_id")
    step = round_metrics.get("step")
    duplicate = any(
        record.get("event_id") == event_id and record.get("step") == step
        for record in read_jsonl(output_file)
    )
    if duplicate:
        raise ValueError(f"事件 {event_id} 的第 {step} 轮指标已经存在。")
    append_jsonl(output_file, round_metrics)


def run_round_metrics():
    """读取当前轮数据，计算三项Demo指标并保存。"""
    ensure_runtime_directories()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    event_id = event_context["event_id"]
    current_step = event_context["current_state"]["step"]
    agent_decisions = load_round_decisions(
        event_id,
        current_step,
        DECISION_HISTORY_FILE,
    )
    if not agent_decisions:
        raise ValueError("当前时间步没有成功的Agent决策，请先运行批量决策。")

    comment_pool = load_comment_pool(COMMENT_POOL_FILE)
    if comment_pool.get("event_id") != event_id:
        raise ValueError("初始评论池与当前事件的event_id不一致。")
    initial_comments = comment_pool["comments"]
    # 2026/08/24 第三次联调问题修复，修改功能：趋势分析只读取当前轮增量评论，避免输入随轮次累积膨胀。
    incremental_comments = load_incremental_comments(
        event_id,
        current_step,
        INCREMENTAL_COMMENT_FILE,
    )
    current_incremental_comments = [
        comment
        for comment in incremental_comments
        if comment.get("introduced_step") == current_step
    ]
    global_trend = analyze_global_trend(
        event_context,
        initial_comments,
        current_incremental_comments,
    )
    propagation_events = load_propagation_events(
        PROPAGATION_HISTORY_FILE,
        event_id,
        current_step,
    )
    propagation_metrics = calculate_propagation_metrics(
        propagation_events,
        len(agent_decisions),
    )
    round_metrics = calculate_round_metrics(
        event_context,
        agent_decisions,
        global_trend,
        propagation_metrics,
    )
    save_round_metrics(round_metrics, METRICS_HISTORY_FILE)

    print(f"事件 {event_id} 第 {current_step} 轮指标统计完成。")
    print(f"输出文件：{METRICS_HISTORY_FILE}")
    print(json.dumps(round_metrics, ensure_ascii=False, indent=2))
    return round_metrics


# 2026/08/27 舆情指标计算扩充，新增功能：整理每个Agent的逐轮情绪历史。
def build_agent_emotion_timeline(agent_state_history):
    """将Agent状态记录整理为按Agent和时间步排序的情绪序列。"""
    if not isinstance(agent_state_history, list):
        raise ValueError("agent_state_history 必须是列表。")

    timeline_by_agent = {}
    seen_records = set()
    for record in agent_state_history:
        if not isinstance(record, dict):
            raise ValueError("Agent状态历史中的每条记录必须是对象。")
        agent_id = record.get("agent_id")
        step = record.get("step")
        state = record.get("state")
        emotion = state.get("current_emotion") if isinstance(state, dict) else None
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("Agent状态记录缺少有效agent_id。")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("Agent状态记录缺少有效step。")
        if emotion not in EMOTIONS:
            raise ValueError("Agent状态记录缺少有效current_emotion。")

        record_key = (agent_id, step)
        if record_key in seen_records:
            raise ValueError(f"Agent {agent_id} 第 {step} 轮状态重复。")
        seen_records.add(record_key)
        timeline_by_agent.setdefault(agent_id, []).append(
            {"step": step, "emotion": emotion}
        )

    for timeline in timeline_by_agent.values():
        timeline.sort(key=lambda item: item["step"])
    return timeline_by_agent


# 2026/08/27 舆情指标计算扩充，新增功能：提取并校验逐轮负面率序列。
def extract_negative_rate_series(metrics_history):
    """兼容场景轮次结果和原始指标记录，返回按时间步排序的负面率。"""
    if not isinstance(metrics_history, list):
        raise ValueError("metrics_history 必须是列表。")

    rate_series = []
    seen_steps = set()
    for record in metrics_history:
        if not isinstance(record, dict):
            raise ValueError("指标历史中的每条记录必须是对象。")
        step = record.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("指标记录缺少有效step。")
        if step in seen_steps:
            raise ValueError(f"第 {step} 轮指标重复。")

        policy_metrics = record.get("policy_metrics")
        if isinstance(policy_metrics, dict):
            negative_rate = policy_metrics.get("negative_rate")
        else:
            emotion_metrics = record.get("agent_negative_emotion")
            negative_rate = (
                emotion_metrics.get("negative_rate")
                if isinstance(emotion_metrics, dict)
                else None
            )
        if (
            isinstance(negative_rate, bool)
            or not isinstance(negative_rate, (int, float))
            or not 0 <= negative_rate <= 1
        ):
            raise ValueError(f"第 {step} 轮缺少有效negative_rate。")

        seen_steps.add(step)
        rate_series.append(
            {"step": step, "negative_rate": float(negative_rate)}
        )

    rate_series.sort(key=lambda item: item["step"])
    return rate_series


def _find_recovery_and_rebound_agents(timeline_by_agent, statement_step):
    """返回进场前负面、进场后恢复和恢复后反弹的Agent集合。"""
    baseline_step = statement_step - 1
    baseline_negative_agents = set()
    recovered_agents = set()
    rebound_agents = set()

    for agent_id, timeline in timeline_by_agent.items():
        baseline_emotion = next(
            (
                item["emotion"]
                for item in timeline
                if item["step"] == baseline_step
            ),
            None,
        )
        if baseline_emotion != "negative":
            continue
        baseline_negative_agents.add(agent_id)

        recovered = False
        for item in timeline:
            if item["step"] < statement_step:
                continue
            if not recovered and item["emotion"] != "negative":
                recovered = True
                recovered_agents.add(agent_id)
            elif recovered and item["emotion"] == "negative":
                rebound_agents.add(agent_id)
                break

    return baseline_negative_agents, recovered_agents, rebound_agents


# 2026/08/27 舆情指标计算扩充，修改功能：计算进场前负面Agent在声明后的恢复比例。
def calculate_emotion_recovery_rate(agent_state_history, statement_step):
    """计算进场前为负面、进场后至少一次转为非负面的Agent比例。"""
    if isinstance(statement_step, bool) or not isinstance(statement_step, int):
        raise ValueError("statement_step 必须是整数。")
    if statement_step < 2:
        raise ValueError("statement_step 必须大于等于2。")

    timeline_by_agent = build_agent_emotion_timeline(agent_state_history)
    baseline_agents, recovered_agents, _ = _find_recovery_and_rebound_agents(
        timeline_by_agent,
        statement_step,
    )
    baseline_count = len(baseline_agents)
    recovery_rate = (
        round(len(recovered_agents) / baseline_count, 6)
        if baseline_count
        else None
    )
    return {
        "baseline_step": statement_step - 1,
        "baseline_negative_agent_count": baseline_count,
        "recovered_agent_count": len(recovered_agents),
        "emotion_recovery_rate": recovery_rate,
    }


# 2026/08/27 舆情指标计算扩充，修改功能：计算负面率首次改善后的连续持续轮数。
def calculate_effect_duration(metrics_history, statement_step):
    """计算声明后负面率首次低于进场前基线的连续时间步。"""
    if isinstance(statement_step, bool) or not isinstance(statement_step, int):
        raise ValueError("statement_step 必须是整数。")
    if statement_step < 2:
        raise ValueError("statement_step 必须大于等于2。")

    rate_series = extract_negative_rate_series(metrics_history)
    baseline_step = statement_step - 1
    baseline_record = next(
        (item for item in rate_series if item["step"] == baseline_step),
        None,
    )
    if baseline_record is None:
        raise ValueError(f"找不到进场前第 {baseline_step} 轮负面率。")

    baseline_rate = baseline_record["negative_rate"]
    post_records = [
        item for item in rate_series if item["step"] >= statement_step
    ]
    start_index = next(
        (
            index
            for index, item in enumerate(post_records)
            if item["negative_rate"] < baseline_rate
        ),
        None,
    )
    if start_index is None:
        return {
            "effect_baseline_negative_rate": round(baseline_rate, 6),
            "effect_start_step": None,
            "effect_end_step": None,
            "effect_duration": 0,
        }

    effect_records = [post_records[start_index]]
    for item in post_records[start_index + 1 :]:
        previous_step = effect_records[-1]["step"]
        if (
            item["step"] != previous_step + 1
            or item["negative_rate"] >= baseline_rate
        ):
            break
        effect_records.append(item)
    return {
        "effect_baseline_negative_rate": round(baseline_rate, 6),
        "effect_start_step": effect_records[0]["step"],
        "effect_end_step": effect_records[-1]["step"],
        "effect_duration": len(effect_records),
    }


# 2026/08/27 舆情指标计算扩充，修改功能：计算恢复Agent后续再次转负面的比例。
def calculate_rebound_rate(agent_state_history, statement_step):
    """计算进场后已经恢复、随后再次变为负面的Agent比例。"""
    if isinstance(statement_step, bool) or not isinstance(statement_step, int):
        raise ValueError("statement_step 必须是整数。")
    if statement_step < 2:
        raise ValueError("statement_step 必须大于等于2。")

    timeline_by_agent = build_agent_emotion_timeline(agent_state_history)
    _, recovered_agents, rebound_agents = _find_recovery_and_rebound_agents(
        timeline_by_agent,
        statement_step,
    )
    recovered_count = len(recovered_agents)
    rebound_rate = (
        round(len(rebound_agents) / recovered_count, 6)
        if recovered_count
        else None
    )
    return {
        "rebound_agent_count": len(rebound_agents),
        "rebound_rate": rebound_rate,
    }


# 2026/08/27 舆情指标计算扩充，修改功能：计算负面率峰值、峰值轮次和累计负面量。
def calculate_negative_peak_and_area(metrics_history):
    """计算逐轮负面率的最高值、对应时间步和简单累计值。"""
    rate_series = extract_negative_rate_series(metrics_history)
    if not rate_series:
        raise ValueError("指标历史不能为空。")

    peak_rate = max(item["negative_rate"] for item in rate_series)
    return {
        "negative_peak_rate": round(peak_rate, 6),
        "negative_peak_steps": [
            item["step"]
            for item in rate_series
            if item["negative_rate"] == peak_rate
        ],
        "negative_area": round(
            sum(item["negative_rate"] for item in rate_series),
            6,
        ),
        "observed_step_count": len(rate_series),
    }


# 2026/08/27 舆情指标计算扩充，修改功能：计算回应场景相对不回应场景的负面指标改善值。
def calculate_control_net_effect(treatment_metrics, control_metrics):
    """使用不回应指标减去回应指标，正数表示回应场景有所改善。"""
    if not isinstance(treatment_metrics, dict) or not isinstance(
        control_metrics,
        dict,
    ):
        raise ValueError("回应场景和对照场景指标必须是对象。")

    metric_names = (
        "final_negative_rate",
        "negative_peak_rate",
        "negative_area",
    )
    values = {}
    for metric_name in metric_names:
        treatment_value = treatment_metrics.get(metric_name)
        control_value = control_metrics.get(metric_name)
        if (
            isinstance(treatment_value, bool)
            or not isinstance(treatment_value, (int, float))
            or isinstance(control_value, bool)
            or not isinstance(control_value, (int, float))
        ):
            raise ValueError(f"缺少有效的{metric_name}。")
        values[metric_name] = round(control_value - treatment_value, 6)

    return {
        "final_negative_rate_reduction": values["final_negative_rate"],
        "peak_negative_rate_reduction": values["negative_peak_rate"],
        "negative_area_reduction": values["negative_area"],
    }


def calculate_run_stability(experiment_runs):
    """预留：计算不同随机种子重复运行结果的稳定性。"""
    raise NotImplementedError("多次运行稳定性将在后期实现。")


if __name__ == "__main__":
    run_round_metrics()
