"""批量运行多个 Agent 的受约束 LLM 决策。

本模块负责组织批量决策流程，不包含具体决策规则：
1. 构建当前时间步的公共黑板；
2. 为每个 Agent 生成个人可见评论；
3. 并发调用单 Agent 决策；
4. 保存完整决策和 Agent 动态状态。
"""

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.decision_service import decide_one_agent
from agents.state_store import AgentStateStore
from comments.repository import load_all_comments
from simulation.event_context import load_event_context
from infrastructure.json_storage import append_jsonl_many, load_json
from agents.persona_repository import load_personas
from project_config import (
    COMMENT_POOL_FILE,
    COMMENT_VISIBILITY_SEED,
    CURRENT_STEP_VISIBLE_COUNT,
    DECISION_HISTORY_FILE,
    EVENT_FILE,
    EVENT_STATE_FILE,
    MAX_AGENT_COUNT,
    MAX_WORKERS,
    PERSONA_DIR,
    POLICY_FILE,
    RETRY_COUNT,
    VISIBLE_COMMENT_COUNT,
    ensure_runtime_directories,
)
from simulation.propagation import build_agent_blackboard_view, build_public_blackboard


def build_agent_views(personas, public_blackboard):
    """为本轮所有 Agent 生成可复现的个人黑板视图。

    参数：
        personas：参与本轮决策的 Persona 列表。
        public_blackboard：当前时间步的公共黑板。

    返回：
        以 agent_id 为键、个人黑板视图为值的字典。
    """
    agent_views = {}
    for persona in personas:
        agent_id = persona.get("agent_id")
        if not agent_id:
            raise ValueError("Persona 缺少 agent_id。")
        if agent_id in agent_views:
            raise ValueError(f"发现重复的 agent_id：{agent_id}")

        agent_views[agent_id] = build_agent_blackboard_view(
            public_blackboard=public_blackboard,
            agent_id=agent_id,
            visible_count=VISIBLE_COMMENT_COUNT,
            random_seed=COMMENT_VISIBILITY_SEED,
            current_step_count=CURRENT_STEP_VISIBLE_COUNT,
        )

    return agent_views


def decide_one_agent_with_retry(
    persona,
    event_context,
    policy,
    agent_view,
    global_comments,
    state_store,
):
    """使用个人评论形成认知并从全局评论选择表达，失败时有限重试。

    参数：
        persona：当前 Agent 的人物画像。
        event_context：事件固定信息和当前官方声明。
        policy：全局决策规则和分位数配置。
        agent_view：当前 Agent 本轮的个人黑板视图。
        global_comments：当前时间步可以用于选择表达的全部候选评论。
        state_store：Agent 历史状态读取服务。

    返回：
        包含可见评论编号的完整决策结果或失败记录。
    """
    event_id = event_context["event_id"]
    step = event_context["current_state"]["step"]
    agent_id = persona["agent_id"]
    visible_comments = agent_view["visible_comments"]
    visible_comment_ids = agent_view["visible_comment_ids"]
    current_step_visible_count = agent_view["current_step_visible_count"]
    historical_visible_count = agent_view["historical_visible_count"]

    last_error = "未知错误"
    for attempt in range(RETRY_COUNT + 1):
        try:
            result = decide_one_agent(
                persona,
                event_context,
                policy,
                visible_comments,
                global_comments,
                state_store,
            )
            result["visible_comment_ids"] = visible_comment_ids
            # 2026/08/25 第六次联调问题修复，新增功能：保存两层评论的实际可见数量便于联调核对。
            result["current_step_visible_count"] = current_step_visible_count
            result["historical_visible_count"] = historical_visible_count
            return result
        except Exception as error:
            last_error = str(error)
            if attempt < RETRY_COUNT:
                time.sleep(1)

    return {
        "event_id": event_id,
        "step": step,
        "agent_id": agent_id,
        "visible_comment_ids": visible_comment_ids,
        "current_step_visible_count": current_step_visible_count,
        "historical_visible_count": historical_visible_count,
        "decision_method": "constrained_llm",
        "status": "failed",
        "error": last_error,
    }


def run_batch_decision(
    max_count=MAX_AGENT_COUNT,
    max_workers=MAX_WORKERS,
):
    """并发完成当前时间步的多 Agent 决策并保存结果。

    参数：
        max_count：本轮最多参与决策的 Agent 数量。
        max_workers：同时执行的最大线程数量。

    返回：
        按 agent_id 排序的完整决策结果列表。
    """
    if not isinstance(max_count, int) or max_count < 1:
        raise ValueError("max_count 必须是大于或等于 1 的整数。")
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers 必须是大于或等于 1 的整数。")

    ensure_runtime_directories()
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    policy = load_json(POLICY_FILE)
    global_comments = load_all_comments(
        event_id=event_context["event_id"],
        current_step=event_context["current_state"]["step"],
        comment_pool_file=COMMENT_POOL_FILE,
    )
    personas = load_personas(max_count=max_count)
    if not personas:
        raise RuntimeError(f"没有找到 Persona 文件：{PERSONA_DIR}")

    public_blackboard = build_public_blackboard(event_context, global_comments)
    agent_views = build_agent_views(personas, public_blackboard)
    state_store = AgentStateStore()
    results = []
    worker_count = min(max_workers, len(personas))

    print(
        f"事件 {event_context['event_id']}，"
        f"时间步 {event_context['current_state']['step']}，"
        f"Agent 数量 {len(personas)}，并发数 {worker_count}，"
        f"每个 Agent 最多可见 {VISIBLE_COMMENT_COUNT} 条评论"
    )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {}
        for persona in personas:
            agent_id = persona["agent_id"]
            future = executor.submit(
                decide_one_agent_with_retry,
                persona,
                event_context,
                policy,
                agent_views[agent_id],
                global_comments,
                state_store,
            )
            future_map[future] = agent_id

        for completed_count, future in enumerate(as_completed(future_map), start=1):
            result = future.result()
            results.append(result)
            print(
                f"已完成 {completed_count}/{len(personas)}："
                f"{result['agent_id']}，状态：{result['status']}"
            )

    results.sort(key=lambda item: item["agent_id"])

    # 2026/08/22 联调可靠性收尾：任一Agent失败时不写入本轮决策和状态，保证整轮可以重新运行。
    failed_results = [
        result for result in results if result.get("status") != "success"
    ]
    if failed_results:
        print(
            f"批量决策存在 {len(failed_results)} 个失败结果，"
            "本轮决策和Agent状态均未写入。"
        )
        return results

    # 2026/08/22 联调可靠性收尾：只有全部Agent成功后才统一保存正式结果。
    append_jsonl_many(DECISION_HISTORY_FILE, results)
    state_records = state_store.save_decision_states(results)

    print(f"批量决策完成，成功 {len(state_records)} 条，失败 0 条。")
    print(f"全局评论池：{COMMENT_POOL_FILE}")
    print(f"决策记录：{DECISION_HISTORY_FILE}")
    print(f"Agent 状态记录：{state_store.state_file}")
    return results


def main():
    """提供批量决策的命令行入口。"""
    parser = argparse.ArgumentParser(description="批量运行 Agent 决策")
    parser.add_argument("--max-agents", type=int, default=MAX_AGENT_COUNT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    run_batch_decision(args.max_agents, args.workers)


if __name__ == "__main__":
    main()
