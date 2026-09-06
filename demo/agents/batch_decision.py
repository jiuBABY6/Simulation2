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
from infrastructure.json_storage import (
    append_jsonl_many,
    load_json,
    read_jsonl,
    save_json,
)
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
    PROPAGATION_HISTORY_FILE,
    RETRY_COUNT,
    SOCIAL_NETWORK_CONFIG_FILE,
    SOCIAL_NETWORK_FILE,
    VISIBLE_COMMENT_COUNT,
    ensure_runtime_directories,
)
from simulation.propagation import (
    build_agent_blackboard_view,
    build_public_blackboard,
    extract_previous_agent_expressions,
)
from simulation.social_network import (
    build_fixed_social_network,
    validate_social_network,
)
from simulation.propagation_tracking import (
    attach_expression_lineage,
    build_propagation_events,
    save_step_propagation_events,
)


def load_or_create_social_network(personas):
    """读取固定网络快照；独立入口缺少快照时按固定种子创建一次。"""
    agent_ids = [persona["agent_id"] for persona in personas]
    if SOCIAL_NETWORK_FILE.is_file():
        return validate_social_network(
            load_json(SOCIAL_NETWORK_FILE),
            agent_ids,
        )

    # 2026/9/5，社交网络传播，新增功能：为非五策略入口建立可复现网络快照。
    config = load_json(SOCIAL_NETWORK_CONFIG_FILE)
    social_network = build_fixed_social_network(personas, config)
    save_json(SOCIAL_NETWORK_FILE, social_network)
    return social_network


def load_visibility_config(social_network):
    """从本批次网络快照读取并校验两类评论的可见数量。"""
    config = social_network.get("visibility", {})
    neighbor_count = config.get("neighbor_comment_count", 0)
    public_count = config.get("public_comment_count", VISIBLE_COMMENT_COUNT)
    for field_name, value in (
        ("neighbor_comment_count", neighbor_count),
        ("public_comment_count", public_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} 必须是非负整数。")
    if neighbor_count + public_count != VISIBLE_COMMENT_COUNT:
        raise ValueError(
            "邻居评论数量与公共评论数量之和必须等于VISIBLE_COMMENT_COUNT。"
        )
    return neighbor_count, public_count


# 2026/9/5，社交网络传播，修改功能：按照固定关系网络为每个Agent构建不同的个人可见范围。
def build_agent_views(
    personas,
    public_blackboard,
    social_network,
    agent_expressions,
):
    """为本轮所有 Agent 生成可复现的个人黑板视图。

    参数：
        personas：参与本轮决策的 Persona 列表。
        public_blackboard：当前时间步的公共黑板。

    返回：
        以 agent_id 为键、个人黑板视图为值的字典。
    """
    neighbor_count, public_count = load_visibility_config(social_network)
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
            social_network=social_network,
            agent_expressions=agent_expressions,
            neighbor_comment_count=neighbor_count,
            public_comment_count=public_count,
        )

    return agent_views


def decide_one_agent_with_retry(
    persona,
    event_context,
    policy,
    agent_view,
    state_store,
):
    """使用个人可见评论形成认知并选择表达，失败时有限重试。

    参数：
        persona：当前 Agent 的人物画像。
        event_context：事件固定信息和当前官方声明。
        policy：全局决策规则和分位数配置。
        agent_view：当前 Agent 本轮的个人黑板视图。
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
    neighbor_visible_count = agent_view["neighbor_visible_count"]
    public_visible_count = agent_view["public_visible_count"]

    last_error = "未知错误"
    for attempt in range(RETRY_COUNT + 1):
        try:
            result = decide_one_agent(
                persona,
                event_context,
                policy,
                visible_comments,
                state_store,
            )
            result["visible_comment_ids"] = visible_comment_ids
            # 2026/08/25 第六次联调问题修复，新增功能：保存两层评论的实际可见数量便于联调核对。
            result["current_step_visible_count"] = current_step_visible_count
            result["historical_visible_count"] = historical_visible_count
            # 2026/9/5，社交网络传播，新增功能：保存邻居传播与公共补充的实际可见数量。
            result["neighbor_visible_count"] = neighbor_visible_count
            result["public_visible_count"] = public_visible_count
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
        "neighbor_visible_count": neighbor_visible_count,
        "public_visible_count": public_visible_count,
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
    social_network = load_or_create_social_network(personas)
    previous_expressions = extract_previous_agent_expressions(
        read_jsonl(DECISION_HISTORY_FILE),
        event_context["event_id"],
        event_context["current_state"]["step"],
    )
    agent_views = build_agent_views(
        personas,
        public_blackboard,
        social_network,
        previous_expressions,
    )
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

    # 2026/9/5，社交网络传播第二阶段A，新增功能：为成功表达补充谱系并生成本轮邻居曝光记录。
    results = [attach_expression_lineage(result) for result in results]
    propagation_events = build_propagation_events(agent_views, results)

    # 2026/9/5，社交网络传播第二阶段A，修改功能：先防重保存传播事件，避免传播写入失败后留下孤立决策。
    propagation_count = save_step_propagation_events(
        PROPAGATION_HISTORY_FILE,
        propagation_events,
        event_context["event_id"],
        event_context["current_state"]["step"],
    )
    # 2026/08/22 联调可靠性收尾：只有全部Agent成功后才统一保存正式结果。
    append_jsonl_many(DECISION_HISTORY_FILE, results)
    state_records = state_store.save_decision_states(results)

    print(f"批量决策完成，成功 {len(state_records)} 条，失败 0 条。")
    print(f"全局评论池：{COMMENT_POOL_FILE}")
    print(f"决策记录：{DECISION_HISTORY_FILE}")
    print(
        f"传播记录：{PROPAGATION_HISTORY_FILE}，"
        f"本轮邻居曝光 {propagation_count} 次"
    )
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
