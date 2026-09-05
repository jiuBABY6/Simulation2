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
    select_best_candidate,
    validate_cognition_decision,
)
from simulation.event_context import load_event_context
from infrastructure.json_storage import load_json, save_json
from infrastructure.llm_service import call_deepseek_json
from agents.persona_repository import load_first_persona
from project_config import (
    COMMENT_POOL_FILE,
    COMMENT_SELECTION_SEED,
    COMMENT_SELECTION_TOP_K,
    EVENT_FILE,
    EVENT_STATE_FILE,
    POLICY_FILE,
    SINGLE_LLM_RESULT_FILE,
)


# 2026/08/21 新增功能：只根据个人可见评论生成Agent认知决策。
def decide_agent_cognition(
    persona,
    event_context,
    policy,
    visible_comments,
    previous_state,
    history_summary,
):
    """调用LLM决定情绪、官方态度、评论意愿和评论派系。"""
    choices = build_allowed_choices(
        event_context,
        policy,
        visible_comments,
        persona,
    )
    prompt = build_decision_prompt(
        event_context,
        choices,
        visible_comments,
        previous_state,
        history_summary,
    )
    cognition_decision = call_deepseek_json(
        prompt,
        "你必须严格遵守允许选项，只返回一个合法 JSON 对象。",
        temperature=0,
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
    global_comments,
    state_store,
):
    """先形成Agent认知，再从当前全局候选评论中选择最终表达。"""
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

    selected_comment = None
    scored_candidates = []
    no_fresh_candidate = False
    if cognition_decision["will_comment"]:
        # 2026/08/25 第八次联调问题修复，新增功能：从个人历史提取已发表评论，避免本轮重复选择。
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
        # 2026/08/25 第五次联调问题修复，修改功能：让最终评论优先匹配本轮官方态度。
        # 2026/08/25 第六次联调问题修复，修改功能：从评分最高的三条评论中进行可复现选择。
        selected_comment, scored_candidates = select_best_candidate(
            global_comments,
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
        if selected_comment is None:
            # 2026/08/25 第八次联调问题修复，修改功能：没有新候选时结束评论行为，不回退到个人旧评论。
            cognition_decision = dict(cognition_decision)
            cognition_decision["will_comment"] = False
            cognition_decision["comment_faction"] = None
            reason = dict(cognition_decision.get("decision_reason", {}))
            reason["comment"] = "本轮没有尚未发表过的合适评论，因此不重复发表评论。"
            cognition_decision["decision_reason"] = reason
            no_fresh_candidate = True

    decision = build_final_decision(
        cognition_decision,
        selected_comment,
        scored_candidates,
        len(global_comments),
    )
    if no_fresh_candidate:
        decision["selection_source"] = "no_fresh_candidate"
    return {
        "event_id": event_id,
        "step": step,
        "agent_id": agent_id,
        "decision_method": "constrained_llm",
        "status": "success",
        "decision": decision,
    }


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
