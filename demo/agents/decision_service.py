"""单个 Agent 的受约束 LLM 决策入口。

业务规则、文件存储和网络请求分别由独立模块负责，本文件只负责串联单个 Agent 的流程。
"""

import argparse
import json

from agents.state_store import AgentStateStore
from comments.repository import load_comments
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
from project_config import (
    COMMENT_POOL_FILE,
    COMMENT_SELECTION_SEED,
    COMMENT_SELECTION_TOP_K,
    EVENT_FILE,
    EVENT_STATE_FILE,
    POLICY_FILE,
    SINGLE_LLM_RESULT_FILE,
)
from simulation.options import uses_evidence_based_emotions


HISTORICAL_DECISION_TEMPERATURE = 0.1


# 2026/08/21 新增功能：只根据个人可见评论生成Agent认知决策。
def decide_agent_cognition(
    persona,
    event_context,
    policy,
    visible_comments,
    previous_state,
    history_summary,
):
    """调用LLM形成认知说明；历史官方态度由个体规则预先裁决。"""
    choices = build_allowed_choices(
        event_context,
        policy,
        visible_comments,
        persona,
        previous_state,
    )
    prompt = build_decision_prompt(
        event_context,
        choices,
        visible_comments,
        previous_state,
        history_summary,
    )
    evidence_based = uses_evidence_based_emotions(event_context)
    cognition_decision = call_deepseek_json(
        prompt,
        "你必须严格遵守允许选项，只返回一个合法 JSON 对象。",
        # 2026/10/14，修改功能：历史复现用于机制评测，需要降低相同输入
        # 下的随机漂移；五策略继续保留原有 0.3，不改变既有实验行为。
        temperature=HISTORICAL_DECISION_TEMPERATURE if evidence_based else 0.3,
        max_tokens=1500,
        # 2026/09/04 Demo性能基线，新增功能：标记Agent认知决策请求类型。
        request_type="agent_decision",
    )
    return validate_cognition_decision(cognition_decision, choices)


def decide_one_agent(
    persona,
    event_context,
    policy,
    visible_comments,
    state_store,
):
    """形成Agent认知；历史复现原创表达，五策略沿用候选评论选择。"""
    event_id = event_context["event_id"]
    step = event_context["current_state"]["step"]
    agent_id = persona["agent_id"]
    previous_state = state_store.get_latest_state(agent_id, event_id, step)
    history_summary = state_store.build_history_summary(agent_id, event_id, step)

    cognition_decision = decide_agent_cognition(
        persona,
        event_context,
        policy,
        visible_comments,
        previous_state,
        history_summary,
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

    selected_comment = None
    scored_candidates = []
    no_fresh_candidate = False
    if cognition_decision["will_comment"]:
        if uses_evidence_based_emotions(event_context):
            # 2026/10/12，历史复现原创表达：复用认知决策的同一次LLM
            # 调用，不额外增加请求；评论池只提供个人舆情环境。
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
        else:
            selected_comment, scored_candidates = _select_legacy_comment(
                cognition_decision,
                visible_comments,
                event_context,
                persona,
                history_summary,
            )
        if selected_comment is None:
            # 五策略没有新候选时结束评论行为；历史原创表达在此前已校验，
            # 不会进入这个兼容分支。
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
    if uses_evidence_based_emotions(event_context):
        decision["selection_source"] = (
            "agent_original_expression"
            if decision["will_comment"]
            else "agent_silence"
        )
    elif no_fresh_candidate:
        decision["selection_source"] = "no_fresh_candidate"
    return {
        "event_id": event_id,
        "step": step,
        "agent_id": agent_id,
        "decision_method": (
            "rule_attitude_constrained_llm"
            if uses_evidence_based_emotions(event_context)
            else "constrained_llm"
        ),
        "status": "success",
        "decision": decision,
    }


def _select_legacy_comment(
    cognition_decision,
    visible_comments,
    event_context,
    persona,
    history_summary,
):
    """保留五策略原有候选评论选择，避免历史机制影响策略实验。"""

    # 2026/08/25 第八次联调问题修复：从个人历史提取已发表评论，
    # 避免五策略路径在本轮重复选择。
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
        COMMENT_SELECTION_TOP_K,
        COMMENT_SELECTION_SEED,
        excluded_comment_ids,
        excluded_comment_texts,
    )


def run_single_agent(persona=None):
    """执行单个 Agent 决策，并保存结果和动态状态。"""
    persona = persona or load_first_persona()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    policy = load_json(POLICY_FILE)
    comments = load_comments(COMMENT_POOL_FILE)
    state_store = AgentStateStore()

    result = decide_one_agent(
        persona,
        event_context,
        policy,
        comments,
        state_store,
    )
    state_store.save_decision_states([result])
    save_json(SINGLE_LLM_RESULT_FILE, result)
    print("单个 Agent 决策完成。")
    print(f"结果文件：{SINGLE_LLM_RESULT_FILE}")
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
