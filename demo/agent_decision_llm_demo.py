"""单个 Agent 的受约束 LLM 决策入口。

业务规则、文件存储和网络请求分别由独立模块负责，本文件只负责串联单个 Agent 的流程。
"""

import argparse
import json

from agent_state_store import AgentStateStore
from comment_pool_generator import load_or_generate_comment_pool
from decision_engine import (
    attach_selected_comment,
    build_allowed_choices,
    build_decision_prompt,
    validate_decision,
)
from event_context import load_event_context
from json_storage import load_json, save_json
from llm_service import call_deepseek_json
from persona_repository import load_first_persona
from project_config import (
    EVENT_FILE,
    EVENT_STATE_FILE,
    POLICY_FILE,
    SINGLE_LLM_RESULT_FILE,
)


def decide_one_agent(persona, event_context, policy, candidates, state_store):
    """读取 Agent 动态状态，调用 LLM 并校验本轮决策。"""
    event_id = event_context["event_id"]
    step = event_context["current_state"]["step"]
    agent_id = persona["agent_id"]
    previous_state = state_store.get_latest_state(agent_id, event_id, step)
    history_summary = state_store.build_history_summary(agent_id, event_id, step)
    choices = build_allowed_choices(event_context, policy, candidates, persona)
    prompt = build_decision_prompt(
        event_context,
        choices,
        candidates,
        previous_state,
        history_summary,
    )
    decision = call_deepseek_json(
        prompt,
        "你必须严格遵守允许选项，只返回一个合法 JSON 对象。",
        temperature=0,
        max_tokens=1500,
    )
    decision = validate_decision(decision, choices)
    decision = attach_selected_comment(decision, candidates)
    return {
        "event_id": event_id,
        "step": step,
        "agent_id": agent_id,
        "decision_method": "constrained_llm",
        "status": "success",
        "decision": decision,
    }


def run_single_agent(persona=None, regenerate_comment_pool=False):
    """执行单个 Agent 决策，并保存结果和动态状态。"""
    persona = persona or load_first_persona()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    policy = load_json(POLICY_FILE)
    candidates = load_or_generate_comment_pool(
        event_context,
        force_regenerate=regenerate_comment_pool,
    )
    state_store = AgentStateStore()

    result = decide_one_agent(persona, event_context, policy, candidates, state_store)
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
    parser.add_argument("--regenerate-comments", action="store_true", help="重新生成评论池")
    args = parser.parse_args()
    persona = load_json(args.agent_file) if args.agent_file else None
    run_single_agent(persona, args.regenerate_comments)


if __name__ == "__main__":
    main()
