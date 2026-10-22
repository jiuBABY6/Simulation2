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

from agents.decision_service import (
    build_agent_decision_input,
    decide_agent,
)
from agents.state_store import AgentStateStore
from application.runtime_config import load_project_runtime_config
from comments.repository import load_all_comments
from simulation.event_context import load_event_context
from simulation.context_exposure import personalize_event_context
from infrastructure.json_storage import (
    append_jsonl_many,
    load_json,
    read_jsonl,
    save_json,
)
from agents.persona_repository import load_personas
from domain.contracts import AgentDecisionResult, SimulationContext
from simulation.propagation import (
    RECENT_EXPRESSION_WINDOW_ROUNDS,
    build_agent_blackboard_view,
    build_public_blackboard,
    extract_recent_agent_expressions,
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
from simulation.options import (
    get_simulation_options,
    uses_evidence_based_emotions,
    uses_neighbor_feedback,
)


def load_or_create_social_network(
    personas,
    event_context=None,
    runtime_config=None,
):
    """读取固定网络快照；独立入口缺少快照时按固定种子创建一次。"""
    runtime_config = runtime_config or load_project_runtime_config()
    paths = runtime_config.paths
    agent_ids = [persona["agent_id"] for persona in personas]
    if paths.social_network_file.is_file():
        return validate_social_network(
            load_json(paths.social_network_file),
            agent_ids,
        )

    # 2026/9/5，社交网络传播，新增功能：为非五策略入口建立可复现网络快照。
    config = load_json(paths.social_network_config_file)
    options = (event_context or {}).get("simulation_options", {})
    network = options.get("network")
    visibility = options.get("visibility")
    if isinstance(network, dict):
        # 2026/10/12，历史复现网络拓扑隔离：只在事件显式启用历史
        # evidence_based_all 配置时覆盖关注人数；五策略仍读取全局配置。
        config = {**config, **network}
    if isinstance(visibility, dict):
        # 历史复现同时覆盖曝光目标；网络种子、影响力和衰减仍沿用全局值。
        config = {**config, **visibility}
    social_network = build_fixed_social_network(personas, config)
    save_json(paths.social_network_file, social_network)
    return social_network


def load_visibility_config(social_network, visible_comment_count):
    """从本批次网络快照读取并校验两类评论的可见数量。"""
    config = social_network.get("visibility", {})
    neighbor_count = config.get("neighbor_comment_count", 0)
    public_count = config.get("public_comment_count", visible_comment_count)
    for field_name, value in (
        ("neighbor_comment_count", neighbor_count),
        ("public_comment_count", public_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} 必须是非负整数。")
    if neighbor_count + public_count != visible_comment_count:
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
    event_context=None,
    runtime_config=None,
):
    """为本轮所有 Agent 生成可复现的个人黑板视图。

    参数：
        personas：参与本轮决策的 Persona 列表。
        public_blackboard：当前时间步的公共黑板。

    返回：
        以 agent_id 为键、个人黑板视图为值的字典。
    """
    runtime_config = runtime_config or load_project_runtime_config()
    settings = runtime_config.decision
    neighbor_count, public_count = load_visibility_config(
        social_network,
        settings.visible_comment_count,
    )
    if not uses_neighbor_feedback(event_context):
        # 2026/10/18，新增功能：网络消融只关闭邻居表达注入，固定网络
        # 快照本身仍保留，公共评论补足全部可见配额，便于和完整机制对照。
        neighbor_count = 0
        public_count = settings.visible_comment_count
    agent_views = {}
    # 2026/10/19，修改功能：策略实验和历史复现都按Persona温和调整
    # 公共评论曝光概率。这里仍保留探索基线，不会把低偏好内容完全过滤。
    personalize_public_comments = True
    for persona in personas:
        agent_id = persona.get("agent_id")
        if not agent_id:
            raise ValueError("Persona 缺少 agent_id。")
        if agent_id in agent_views:
            raise ValueError(f"发现重复的 agent_id：{agent_id}")

        agent_views[agent_id] = build_agent_blackboard_view(
            public_blackboard=public_blackboard,
            agent_id=agent_id,
            visible_count=settings.visible_comment_count,
            random_seed=settings.comment_visibility_seed,
            current_step_count=settings.current_step_visible_count,
            social_network=social_network,
            agent_expressions=agent_expressions,
            neighbor_comment_count=neighbor_count,
            public_comment_count=public_count,
            persona=persona if personalize_public_comments else None,
        )

    return agent_views


def decide_one_agent_with_retry(
    persona,
    event_context,
    policy,
    agent_view,
    state_store,
    runtime_config=None,
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
    runtime_config = runtime_config or load_project_runtime_config()
    context = SimulationContext.from_mapping(event_context)
    event_id = context.event_id
    step = context.step
    agent_id = persona["agent_id"]
    visible_comments = agent_view["visible_comments"]
    visible_comment_ids = agent_view["visible_comment_ids"]
    current_step_visible_count = agent_view["current_step_visible_count"]
    historical_visible_count = agent_view["historical_visible_count"]
    neighbor_visible_count = agent_view["neighbor_visible_count"]
    public_visible_count = agent_view["public_visible_count"]
    visible_neighbor_comment_ids = agent_view[
        "visible_neighbor_comment_ids"
    ]
    visible_public_comment_ids = agent_view["visible_public_comment_ids"]
    public_sampling_method = agent_view["public_sampling_method"]
    neighbor_target_count = agent_view["neighbor_target_count"]
    effective_neighbor_exposure_rate = agent_view[
        "effective_neighbor_exposure_rate"
    ]
    neighbor_expression_age_distribution = agent_view[
        "neighbor_expression_age_distribution"
    ]
    unique_neighbor_root_count = agent_view["unique_neighbor_root_count"]
    personalized_context, visible_context_evidence_ids = (
        personalize_event_context(event_context, agent_id)
    )
    historical_mode = uses_evidence_based_emotions(event_context)
    decision_input = build_agent_decision_input(
        persona,
        personalized_context,
        policy,
        visible_comments,
        state_store,
    )

    last_error = "未知错误"
    correction_feedback = None
    for attempt in range(runtime_config.decision.retry_count + 1):
        try:
            result = decide_agent(
                decision_input,
                runtime_config=runtime_config,
                correction_feedback=correction_feedback,
            ).to_record()
            result["visible_comment_ids"] = visible_comment_ids
            # 2026/08/25 第六次联调问题修复，新增功能：保存两层评论的实际可见数量便于联调核对。
            result["current_step_visible_count"] = current_step_visible_count
            result["historical_visible_count"] = historical_visible_count
            # 2026/9/5，社交网络传播，新增功能：保存邻居传播与公共补充的实际可见数量。
            result["neighbor_visible_count"] = neighbor_visible_count
            result["public_visible_count"] = public_visible_count
            result["neighbor_target_count"] = neighbor_target_count
            result["effective_neighbor_exposure_rate"] = (
                effective_neighbor_exposure_rate
            )
            result["neighbor_expression_age_distribution"] = dict(
                neighbor_expression_age_distribution
            )
            result["unique_neighbor_root_count"] = unique_neighbor_root_count
            if historical_mode:
                result["visible_neighbor_comment_ids"] = (
                    visible_neighbor_comment_ids
                )
                result["visible_public_comment_ids"] = (
                    visible_public_comment_ids
                )
                result["public_sampling_method"] = public_sampling_method
            result["visible_context_evidence_ids"] = (
                visible_context_evidence_ids
            )
            return result
        except Exception as error:
            last_error = str(error)
            # 2026/10/17，修改功能：整体验证失败时将精确原因传给
            # 下一次请求。原创表达自身优先使用局部重试，不会走到这里。
            correction_feedback = last_error
            if attempt < runtime_config.decision.retry_count:
                time.sleep(1)

    metadata = {
        "visible_comment_ids": visible_comment_ids,
        "current_step_visible_count": current_step_visible_count,
        "historical_visible_count": historical_visible_count,
        "neighbor_visible_count": neighbor_visible_count,
        "public_visible_count": public_visible_count,
        "neighbor_target_count": neighbor_target_count,
        "effective_neighbor_exposure_rate": effective_neighbor_exposure_rate,
        "neighbor_expression_age_distribution": dict(
            neighbor_expression_age_distribution
        ),
        "unique_neighbor_root_count": unique_neighbor_root_count,
        "visible_context_evidence_ids": visible_context_evidence_ids,
    }
    if historical_mode:
        metadata.update(
            {
                "visible_neighbor_comment_ids": visible_neighbor_comment_ids,
                "visible_public_comment_ids": visible_public_comment_ids,
                "public_sampling_method": public_sampling_method,
            }
        )
    return AgentDecisionResult(
        event_id=event_id,
        step=step,
        agent_id=agent_id,
        decision_method="constrained_llm",
        status="failed",
        error=last_error,
        metadata=metadata,
    ).to_record()


def run_batch_decision(
    max_count=None,
    max_workers=None,
    simulation_context=None,
    runtime_config=None,
):
    """并发完成当前时间步的多 Agent 决策并保存结果。

    参数：
        max_count：本轮最多参与决策的 Agent 数量。
        max_workers：同时执行的最大线程数量。

    返回：
        按 agent_id 排序的完整决策结果列表。
    """
    runtime_config = runtime_config or load_project_runtime_config()
    settings = runtime_config.decision
    paths = runtime_config.paths
    max_count = settings.max_agents if max_count is None else max_count
    max_workers = settings.max_workers if max_workers is None else max_workers
    if not isinstance(max_count, int) or max_count < 1:
        raise ValueError("max_count 必须是大于或等于 1 的整数。")
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers 必须是大于或等于 1 的整数。")

    runtime_config.ensure_runtime_directories()
    if simulation_context is None:
        event_context = load_event_context(
            paths.event_file,
            paths.event_state_file,
        )
    else:
        event_context = SimulationContext.from_mapping(
            simulation_context
        ).to_mapping()
    policy = load_json(paths.policy_file)
    global_comments = load_all_comments(
        event_id=event_context["event_id"],
        current_step=event_context["current_state"]["step"],
        comment_pool_file=paths.comment_pool_file,
    )
    personas = load_personas(paths.persona_dir, max_count=max_count)
    if not personas:
        raise RuntimeError(f"没有找到 Persona 文件：{paths.persona_dir}")

    public_blackboard = build_public_blackboard(event_context, global_comments)
    social_network = load_or_create_social_network(
        personas,
        event_context,
        runtime_config,
    )
    decision_history = read_jsonl(paths.decision_history_file)
    if uses_evidence_based_emotions(event_context):
        # 历史复现保持既有上一轮曝光口径，避免本次策略实验改动
        # 改写已经验收的条件化历史回放机制。
        previous_expressions = extract_previous_agent_expressions(
            decision_history,
            event_context["event_id"],
            event_context["current_state"]["step"],
        )
    else:
        # 2026/10/17，修改功能：三方案对照读取邻居最近3轮表达，
        # 后续由传播层按轮龄、时间衰减和根表达去重完成采样。
        expression_window_rounds = get_simulation_options(event_context).get(
            "expression_window_rounds",
            RECENT_EXPRESSION_WINDOW_ROUNDS,
        )
        previous_expressions = extract_recent_agent_expressions(
            decision_history,
            event_context["event_id"],
            event_context["current_state"]["step"],
            window_rounds=expression_window_rounds,
        )
    agent_views = build_agent_views(
        personas,
        public_blackboard,
        social_network,
        previous_expressions,
        event_context,
        runtime_config,
    )
    state_store = AgentStateStore(paths.agent_state_file)
    results = []
    worker_count = min(max_workers, len(personas))

    print(
        f"事件 {event_context['event_id']}，"
        f"时间步 {event_context['current_state']['step']}，"
        f"Agent 数量 {len(personas)}，并发数 {worker_count}，"
        f"每个 Agent 最多可见 {settings.visible_comment_count} 条评论"
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
                runtime_config,
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

    # 2026/10/12，历史原创表达传播谱系：原创文字虽然不是邻居评论的
    # 逐字转发，但只要证据明确引用个人可见的邻居表达，就继承其父节点、
    # 根节点和传播深度。五策略原有的直接评论选择仍保持兼容。
    results = [
        attach_expression_lineage(
            result,
            agent_views.get(result.get("agent_id"), {}),
        )
        for result in results
    ]
    propagation_events = build_propagation_events(agent_views, results)

    # 2026/9/5，社交网络传播第二阶段A，修改功能：先防重保存传播事件，避免传播写入失败后留下孤立决策。
    propagation_count = save_step_propagation_events(
        paths.propagation_history_file,
        propagation_events,
        event_context["event_id"],
        event_context["current_state"]["step"],
    )
    # 2026/08/22 联调可靠性收尾：只有全部Agent成功后才统一保存正式结果。
    append_jsonl_many(paths.decision_history_file, results)
    state_records = state_store.save_decision_states(results)

    print(f"批量决策完成，成功 {len(state_records)} 条，失败 0 条。")
    print(f"全局评论池：{paths.comment_pool_file}")
    print(f"决策记录：{paths.decision_history_file}")
    print(
        f"传播记录：{paths.propagation_history_file}，"
        f"本轮邻居曝光 {propagation_count} 次"
    )
    print(f"Agent 状态记录：{state_store.state_file}")
    return results


def main():
    """提供批量决策的命令行入口。"""
    runtime_config = load_project_runtime_config()
    parser = argparse.ArgumentParser(description="批量运行 Agent 决策")
    parser.add_argument(
        "--max-agents",
        type=int,
        default=runtime_config.decision.max_agents,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=runtime_config.decision.max_workers,
    )
    args = parser.parse_args()
    run_batch_decision(
        args.max_agents,
        args.workers,
        runtime_config=runtime_config,
    )


if __name__ == "__main__":
    main()
