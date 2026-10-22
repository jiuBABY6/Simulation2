"""单个 Agent 的受约束 LLM 决策入口。

业务规则、文件存储和网络请求分别由独立模块负责，本文件只负责串联单个 Agent 的流程。
"""

import argparse
import json

from agents.state_store import AgentStateStore
from comments.repository import load_comments
from application.runtime_config import load_project_runtime_config
from agents.decision_engine import (
    build_allowed_choices,
    build_decision_prompt,
    build_final_decision,
    build_generated_expression_comment,
    select_best_candidate,
    validate_cognition_decision,
)
from simulation.event_context import load_event_context
from infrastructure.json_storage import load_json, save_json
from infrastructure.llm_service import call_deepseek_json
from agents.persona_repository import load_first_persona
from agents.historical_participation import (
    apply_historical_participation_policy,
)
from agents.strategy_behavior import apply_strategy_participation_policy
from agents.strategy_expression import (
    MAX_EXPRESSION_LENGTH,
    TARGET_EXPRESSION_LENGTH,
    build_strategy_expression_prompt,
    normalize_overlong_strategy_expression,
    validate_strategy_expression,
)
from agents.state_evidence import build_state_evidence_view
from domain.contracts import (
    AgentDecisionInput,
    AgentDecisionResult,
    SimulationContext,
)
from simulation.options import (
    uses_agent_generated_expression,
    uses_evidence_based_emotions,
    uses_strategy_participation_gate,
)


HISTORICAL_DECISION_TEMPERATURE = 0.1
STRATEGY_EXPRESSION_RETRY_COUNT = 2


# 2026/08/21 新增功能：只根据个人可见评论生成Agent认知决策。
def decide_agent_cognition(
    persona,
    event_context,
    policy,
    visible_comments,
    previous_state,
    history_summary,
    correction_feedback=None,
):
    """调用LLM形成认知说明；历史官方态度由个体规则预先裁决。"""
    choices = build_allowed_choices(
        event_context,
        policy,
        visible_comments,
        persona,
        previous_state,
        # 2026/10/17，修改功能：回应方案只在本次请求中判断状态；
        # 历史复现继续使用包含其既有证据协议的完整决策契约。
        state_only=(
            uses_strategy_participation_gate(event_context)
            and not uses_evidence_based_emotions(event_context)
        ),
    )
    prompt = build_decision_prompt(
        event_context,
        choices,
        visible_comments,
        previous_state,
        history_summary,
    )
    if correction_feedback:
        # 2026/10/16，新增功能：业务校验失败后的下一次请求携带
        # 精确纠错原因。仅传递短文本，不改变原始决策上下文和证据边界。
        prompt = (
            f"{prompt}\n\n【上一次输出的纠错要求】\n"
            f"{str(correction_feedback).strip()[:300]}\n"
            "请修正该问题后重新返回完整JSON，不要重复上一次的无效表达。"
        )
    evidence_based = uses_evidence_based_emotions(event_context)
    cognition_decision = call_deepseek_json(
        prompt,
        "你必须严格遵守允许选项，只返回一个合法 JSON 对象。",
        # 2026/10/14，修改功能：历史复现用于机制评测，需要降低相同输入
        # 下的随机漂移；回应方案对照保留 0.3，允许个体表达差异。
        temperature=HISTORICAL_DECISION_TEMPERATURE if evidence_based else 0.3,
        max_tokens=1500,
        # 2026/09/04 Demo性能基线，新增功能：标记Agent认知决策请求类型。
        request_type="agent_decision",
    )
    return validate_cognition_decision(cognition_decision, choices)


# 2026/10/17，新增功能：状态和行为确定后再单独生成原创表达。
def generate_strategy_expression(
    persona,
    event_context,
    state_decision,
    visible_comments,
    history_summary,
    correction_feedback=None,
):
    """生成并校验策略实验的原创文本，不改写既定状态或动作。"""

    local_feedback = correction_feedback
    last_expression = None
    last_error = None
    evidence_catalog = None
    for attempt in range(STRATEGY_EXPRESSION_RETRY_COUNT + 1):
        prompt, evidence_catalog = build_strategy_expression_prompt(
            persona,
            event_context,
            state_decision,
            visible_comments,
            history_summary,
            correction_feedback=local_feedback,
        )
        last_expression = call_deepseek_json(
            prompt,
            "你只生成一条合法的Agent原创表达，并严格返回JSON对象。",
            temperature=0.5,
            max_tokens=700,
            request_type="agent_expression",
        )
        try:
            return validate_strategy_expression(
                last_expression,
                evidence_catalog,
            )
        except ValueError as error:
            last_error = error
            if attempt < STRATEGY_EXPRESSION_RETRY_COUNT:
                raw_text = (
                    last_expression.get("text", "")
                    if isinstance(last_expression, dict)
                    else ""
                )
                length_detail = (
                    f"当前正文长度为{len(str(raw_text).strip())}个字符；"
                    if raw_text
                    else ""
                )
                # 2026/10/17，新增功能：表达错误只在表达阶段纠正，
                # 不重新判断内部状态、发言资格或动作。
                local_feedback = (
                    f"{error} {length_detail}请保留核心观点并压缩到"
                    f"{TARGET_EXPRESSION_LENGTH}个字符以内，硬上限为"
                    f"{MAX_EXPRESSION_LENGTH}个字符。"
                )

    # 模型连续忽略长度约束时，仅对超长正文执行确定性句末裁剪。
    # 情绪、立场、证据编号等任何其他错误仍保持失败，不使用默认值掩盖。
    normalized_expression = normalize_overlong_strategy_expression(
        last_expression
    )
    try:
        return validate_strategy_expression(
            normalized_expression,
            evidence_catalog or [],
        )
    except ValueError:
        raise last_error


def decide_one_agent(
    persona,
    event_context,
    policy,
    visible_comments,
    state_store,
    runtime_config=None,
):
    """兼容旧调用签名，把已有参数转换为显式决策契约。"""

    decision_input = build_agent_decision_input(
        persona,
        event_context,
        policy,
        visible_comments,
        state_store,
    )
    return decide_agent(
        decision_input,
        runtime_config=runtime_config,
    ).to_record()


def build_agent_decision_input(
    persona,
    event_context,
    policy,
    visible_comments,
    state_store,
):
    """在状态存储边界组装单个 Agent 的完整决策输入。"""

    context = SimulationContext.from_mapping(event_context)
    agent_id = persona["agent_id"]
    previous_state = state_store.get_latest_state(
        agent_id,
        context.event_id,
        context.step,
    )
    history_summary = state_store.build_history_summary(
        agent_id,
        context.event_id,
        context.step,
    )
    return AgentDecisionInput(
        persona=persona,
        context=context,
        policy=policy,
        visible_comments=visible_comments,
        previous_state=previous_state,
        history_summary=history_summary,
    )


def decide_agent(
    decision_input,
    runtime_config=None,
    correction_feedback=None,
):
    """根据显式输入形成决策，不读取配置、事件或状态文件。

    2026/10/15，重构功能：Agent 决策核心只依赖调用方传入的 Persona、
    仿真上下文、可见评论和历史状态。文件读取留在应用边界，便于独立测试，
    同时通过 ``AgentDecisionResult.to_record`` 保持原有 JSON 输出格式。
    """

    if not isinstance(decision_input, AgentDecisionInput):
        raise TypeError("decision_input 必须是 AgentDecisionInput。")
    runtime_config = runtime_config or load_project_runtime_config()
    event_context = decision_input.context.to_mapping()
    persona = decision_input.persona
    policy = decision_input.policy
    visible_comments = decision_input.visible_comments
    previous_state = decision_input.previous_state
    history_summary = decision_input.history_summary
    event_id = decision_input.context.event_id
    step = decision_input.context.step
    agent_id = decision_input.agent_id

    # 2026/10/18，新增功能：状态证据消融只改变认知请求的评论输入。
    # 行为门控、转发候选和原创表达仍使用完整个人可见评论，从而严格
    # 区分“评论不可见”和“评论可见但不能直接改变内部状态”。
    state_evidence_view = build_state_evidence_view(
        visible_comments,
        event_context,
        persona,
    )
    state_evidence_comments = state_evidence_view["comments"]
    cognition_decision = decide_agent_cognition(
        persona,
        event_context,
        policy,
        state_evidence_comments,
        previous_state,
        history_summary,
        correction_feedback=correction_feedback,
    )
    if uses_evidence_based_emotions(event_context):
        # 2026/10/12，历史复现发言决策：内部状态先独立形成，再根据
        # 新证据、状态变化、表达重复和连续发言疲劳判断是否公开表达。
        # 该后置门控不改写情绪或官方态度，也不进入五策略路径。
        cognition_decision = apply_historical_participation_policy(
            cognition_decision,
            persona,
            event_context,
            visible_comments,
            previous_state,
            history_summary,
        )
        # 历史复现的旧决策契约没有action_type，在应用边界补齐，
        # 不改变其原有“原创或沉默”行为。
        cognition_decision["action_type"] = (
            "original" if cognition_decision.get("will_comment") else "silent"
        )
    elif uses_strategy_participation_gate(event_context):
        # 2026/10/17，修改功能：策略对照中先形成内部状态，再由
        # 本地门控独立决定是否发言及原创/转发动作；整个过程不读取
        # LLM的发言意愿，也不改写情绪和官方态度。
        cognition_decision = apply_strategy_participation_policy(
            cognition_decision,
            persona,
            event_context,
            visible_comments,
            previous_state,
            history_summary,
        )

    selected_comment = None
    scored_candidates = []
    no_fresh_candidate = False
    if cognition_decision["will_comment"]:
        action_type = cognition_decision.get("action_type")
        if (
            uses_agent_generated_expression(event_context)
            and action_type == "original"
        ):
            if (
                uses_strategy_participation_gate(event_context)
                and not uses_evidence_based_emotions(event_context)
            ):
                # 2026/10/17，新增功能：原创文本是状态和动作之后的
                # 独立生成阶段；表达情绪始终开放三分类。
                cognition_decision["expression"] = (
                    generate_strategy_expression(
                        persona,
                        event_context,
                        cognition_decision,
                        visible_comments,
                        history_summary,
                        correction_feedback=correction_feedback,
                    )
                )
            selected_comment = build_generated_expression_comment(
                cognition_decision,
                event_context,
                persona,
            )
            scored_candidates = [
                {
                    "comment_id": selected_comment["comment_id"],
                    "score": 1.0,
                }
            ]
        elif action_type == "reshare":
            reshare_comment_id = cognition_decision.get(
                "reshare_comment_id"
            )
            selected_comment = next(
                (
                    dict(comment)
                    for comment in visible_comments
                    if comment.get("comment_id") == reshare_comment_id
                ),
                None,
            )
            if selected_comment is None:
                raise ValueError("转发的评论不在个人可见范围内。")
            # 2026/10/19，新增功能：被转发内容可以来自外部，但“Agent
            # 决定再次传播”属于内生行为。保留原来源供追溯，同时让下一轮
            # 正确区分外部输入与Agent网络反馈。
            selected_comment["reshared_from_provenance"] = (
                selected_comment.get("provenance_type")
                or selected_comment.get("source_type")
            )
            selected_comment["provenance_type"] = "agent_reshare"
            selected_comment["information_origin"] = "endogenous"
            selected_comment["information_source_type"] = "agent"
            scored_candidates = [
                {"comment_id": reshare_comment_id, "score": 1.0}
            ]
        else:
            selected_comment, scored_candidates = _select_legacy_comment(
                cognition_decision,
                visible_comments,
                event_context,
                persona,
                history_summary,
                runtime_config.decision.comment_selection_top_k,
                runtime_config.decision.comment_selection_seed,
            )
        if selected_comment is None:
            # 仅旧版候选选择模式可进入该兼容分支；新版原创
            # 或转发在此前已经完成严格校验。
            cognition_decision = dict(cognition_decision)
            cognition_decision["will_comment"] = False
            cognition_decision["comment_faction"] = None
            reason = dict(cognition_decision.get("decision_reason", {}))
            reason["comment"] = "本轮没有尚未发表过的合适评论，因此不重复发表评论。"
            cognition_decision["decision_reason"] = reason
            no_fresh_candidate = True

    if (
        selected_comment is not None
        and not uses_evidence_based_emotions(event_context)
        and cognition_decision.get("action_type") != "original"
        and selected_comment.get("comment_id") not in {
            comment.get("comment_id") for comment in visible_comments
        }
    ):
        raise ValueError("Agent最终表达不在个人可见评论范围内。")

    decision = build_final_decision(
        cognition_decision,
        selected_comment,
        scored_candidates,
        len(visible_comments),
    )
    # 2026/10/18，新增功能：记录“实际看见”和“允许改变状态”的边界。
    # 完整可见列表仍供行为与表达使用，以下字段仅用于机制诊断。
    decision["state_evidence_diagnostics"] = dict(
        state_evidence_view["diagnostics"]
    )
    decision["state_evidence_comment_count"] = (
        state_evidence_view["diagnostics"]["state_evidence_comment_count"]
    )
    decision["state_evidence_excluded_count"] = (
        state_evidence_view["diagnostics"]["state_evidence_excluded_count"]
    )
    if uses_evidence_based_emotions(event_context):
        decision["selection_source"] = (
            "agent_original_expression"
            if decision["will_comment"]
            else "agent_silence"
        )
    elif uses_strategy_participation_gate(event_context):
        action_type = decision.get("action_type", "silent")
        decision["selection_source"] = {
            "original": "agent_original_expression",
            "reshare": "agent_visible_reshare",
            "silent": "agent_silence",
        }[action_type]
    elif no_fresh_candidate:
        decision["selection_source"] = "no_fresh_candidate"
    return AgentDecisionResult(
        event_id=event_id,
        step=step,
        agent_id=agent_id,
        decision_method=(
            "rule_attitude_constrained_llm"
            if uses_evidence_based_emotions(event_context)
            # 2026/10/17，恢复功能：回应方案的状态决策恢复为
            # 2026/10/15实验采用的受约束LLM机制。沉默、原创、转发
            # 仍由独立行为层处理，不改变状态决策方法的审计名称。
            else "constrained_llm"
        ),
        status="success",
        decision=decision,
    )


def _select_legacy_comment(
    cognition_decision,
    visible_comments,
    event_context,
    persona,
    history_summary,
    selection_top_k,
    selection_seed,
):
    """保留旧批次/显式兼容配置的候选评论选择。"""

    # 2026/08/25 第八次联调问题修复：从个人历史提取已发表评论，
    # 避免兼容路径在本轮重复选择。
    own_comment_history = history_summary.get("own_comment_history", [])
    excluded_comment_ids = {
        item.get("comment_id")
        for item in own_comment_history
        if isinstance(item, dict) and item.get("comment_id")
    }
    excluded_comment_texts = {
        item.get("text")
        for item in own_comment_history
        if isinstance(item, dict) and item.get("text")
    }
    return select_best_candidate(
        visible_comments,
        event_context,
        persona,
        cognition_decision["current_emotion"],
        cognition_decision["comment_faction"],
        cognition_decision["official_attitude"],
        selection_top_k,
        selection_seed,
        excluded_comment_ids,
        excluded_comment_texts,
    )


def run_single_agent(persona=None, runtime_config=None):
    """执行单个 Agent 决策，并保存结果和动态状态。"""
    runtime_config = runtime_config or load_project_runtime_config()
    paths = runtime_config.paths
    persona = persona or load_first_persona(paths.persona_dir)
    event_context = load_event_context(paths.event_file, paths.event_state_file)
    policy = load_json(paths.policy_file)
    comments = load_comments(paths.comment_pool_file)
    state_store = AgentStateStore(paths.agent_state_file)

    result = decide_one_agent(
        persona,
        event_context,
        policy,
        comments,
        state_store,
        runtime_config,
    )
    state_store.save_decision_states([result])
    save_json(paths.single_llm_result_file, result)
    print("单个 Agent 决策完成。")
    print(f"结果文件：{paths.single_llm_result_file}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    """提供单个 Agent 决策的命令行入口。"""
    parser = argparse.ArgumentParser(description="运行单个 Agent 的受约束 LLM 决策")
    parser.add_argument("--agent-file", default="", help="可选的 Persona JSON 文件路径")
    args = parser.parse_args()
    persona = load_json(args.agent_file) if args.agent_file else None
    run_single_agent(persona)


if __name__ == "__main__":
    main()
