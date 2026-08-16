"""批量运行多个 Agent 的受约束 LLM 决策。"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent_state_store import AgentStateStore
from comment_pool_generator import load_or_generate_comment_pool
from decision_engine import (
    attach_selected_comment,
    build_allowed_choices,
    build_decision_prompt,
    validate_decision,
)
from event_context import load_event_context
from json_storage import append_jsonl_many, load_json
from llm_service import call_deepseek_json
from persona_repository import load_personas
from project_config import (
    DECISION_HISTORY_FILE,
    EVENT_FILE,
    EVENT_STATE_FILE,
    COMMENT_POOL_FILE,
    MAX_AGENT_COUNT,
    MAX_WORKERS,
    PERSONA_DIR,
    POLICY_FILE,
    RETRY_COUNT,
    ensure_runtime_directories,
)


def decide_one_agent_with_retry(persona, event_context, policy, candidates, state_store):
    """完成一个 Agent 的决策，失败后按指数间隔重试。"""
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

    last_error = "未知错误"
    for attempt in range(RETRY_COUNT + 1):
        try:
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
        except Exception as error:
            last_error = str(error)
            if attempt < RETRY_COUNT:
                time.sleep(2 ** attempt)

    return {
        "event_id": event_id,
        "step": step,
        "agent_id": agent_id,
        "decision_method": "constrained_llm",
        "status": "failed",
        "error": last_error,
    }


def run_batch_decision(
    max_count=MAX_AGENT_COUNT,
    max_workers=MAX_WORKERS,
    regenerate_comment_pool=False,
):
    """读取多个 Persona，并发完成当前事件时间步的决策。"""
    ensure_runtime_directories()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    policy = load_json(POLICY_FILE)
    candidates = load_or_generate_comment_pool(
        event_context,
        force_regenerate=regenerate_comment_pool,
    )
    personas = load_personas(max_count=max_count)
    if not personas:
        raise RuntimeError(f"没有找到 Persona 文件：{PERSONA_DIR}")

    state_store = AgentStateStore()
    results = []
    print(
        f"事件 {event_context['event_id']}，时间步 {event_context['current_state']['step']}，"
        f"Agent 数量 {len(personas)}，并发数 {max_workers}"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                decide_one_agent_with_retry,
                persona,
                event_context,
                policy,
                candidates,
                state_store,
            ): persona["agent_id"]
            for persona in personas
        }
        for completed_count, future in enumerate(as_completed(future_map), start=1):
            result = future.result()
            results.append(result)
            print(
                f"已完成 {completed_count}/{len(personas)}："
                f"{result['agent_id']}，状态：{result['status']}"
            )

    results.sort(key=lambda item: item["agent_id"])
    append_jsonl_many(DECISION_HISTORY_FILE, results)
    state_records = state_store.save_decision_states(results)
    print(f"批量决策完成，成功 {len(state_records)} 条，失败 {len(results) - len(state_records)} 条。")
    print(f"评论池：{COMMENT_POOL_FILE}")
    print(f"决策记录：{DECISION_HISTORY_FILE}")
    print(f"Agent 状态记录：{state_store.state_file}")
    return results


def main():
    """提供批量决策的命令行入口。"""
    parser = argparse.ArgumentParser(description="批量运行 Agent 决策")
    parser.add_argument("--max-agents", type=int, default=MAX_AGENT_COUNT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--regenerate-comments", action="store_true", help="重新生成评论池")
    args = parser.parse_args()
    run_batch_decision(args.max_agents, args.workers, args.regenerate_comments)


if __name__ == "__main__":
    main()
