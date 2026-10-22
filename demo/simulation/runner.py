"""组织单轮和多轮社会舆情模拟。

本模块只负责按照顺序调用已有功能，不重新实现评论生成、Agent决策或指标计算。
官方声明及其类型由人工输入或后续实验模块提供，本模块不进行预测。
"""

import argparse
import json
import time

from agents.state_store import AgentStateStore
from agents.batch_decision import run_batch_decision
from application.runtime_config import load_project_runtime_config
from simulation.event_context import load_event_context
from comments.incremental_generator import (
    load_incremental_history,
    run_incremental_generation,
)
from infrastructure.json_storage import append_jsonl_many, load_json, read_jsonl
from infrastructure.llm_service import (
    get_llm_performance_stats,
    reset_llm_performance_stats,
)
from evaluation.metrics import run_round_metrics
from agents.persona_repository import load_personas
from domain.contracts import SimulationContext
from simulation.state_manager import validate_simulation_state


# 2026/09/04 Demo性能基线，新增功能：为父进程提供稳定的单轮结果解析标记。
SIMULATION_STEP_RESULT_PREFIX = "SIMULATION_STEP_RESULT="


# 2026/08/22 联调可靠性收尾：按Agent去重读取指定时间步已经保存的成功决策。
def load_successful_decisions(
    event_id,
    step,
    history_file=None,
):
    """读取指定事件和时间步的成功决策，并按Agent编号去重。"""
    if history_file is None:
        history_file = load_project_runtime_config().paths.decision_history_file
    decisions_by_agent = {}
    for record in read_jsonl(history_file):
        if record.get("event_id") != event_id or record.get("step") != step:
            continue
        if record.get("status") != "success" or not record.get("agent_id"):
            continue
        decisions_by_agent[record["agent_id"]] = record

    return [decisions_by_agent[key] for key in sorted(decisions_by_agent)]


# 2026/08/22 联调可靠性收尾：使用预期Agent数量判断本轮决策是否完整。
def has_complete_decisions(
    event_id,
    step,
    expected_agent_count,
    history_file=None,
):
    """判断指定时间步是否已经保存全部Agent的成功决策。"""
    decisions = load_successful_decisions(event_id, step, history_file)
    return len(decisions) == expected_agent_count


# 2026/08/22 联调可靠性收尾：恢复完整决策对应的缺失Agent状态，避免中断后留下半轮数据。
def restore_missing_agent_states(
    decisions,
    state_file=None,
):
    """根据完整决策补写缺失的Agent状态，已经存在的状态不会重复写入。"""
    if state_file is None:
        state_file = load_project_runtime_config().paths.agent_state_file
    existing_keys = {
        (record.get("event_id"), record.get("step"), record.get("agent_id"))
        for record in read_jsonl(state_file)
    }
    state_store = AgentStateStore(state_file)
    missing_records = []

    for result in decisions:
        key = (result.get("event_id"), result.get("step"), result.get("agent_id"))
        if key in existing_keys:
            continue
        missing_records.append(
            state_store.build_state_record(
                result["event_id"],
                result["step"],
                result["agent_id"],
                result["decision"],
            )
        )

    if missing_records:
        append_jsonl_many(state_file, missing_records)
        print(f"已补写 {len(missing_records)} 条缺失的Agent状态。")
    return missing_records


def has_round_metrics(event_id, step, history_file=None):
    """判断指定事件和时间步是否已经保存舆情指标。"""
    if history_file is None:
        history_file = load_project_runtime_config().paths.metrics_history_file
    return any(
        record.get("event_id") == event_id and record.get("step") == step
        for record in read_jsonl(history_file)
        if not record.get("is_example")
    )


def find_incremental_record(
    event_id,
    step,
    history_file=None,
):
    """查找当前时间步已经生成的增量评论批次。"""
    if history_file is None:
        history_file = load_project_runtime_config().paths.incremental_comment_file
    for record in load_incremental_history(history_file):
        if record.get("event_id") == event_id and record.get("step") == step:
            return record
    return None


def validate_step_order(
    event_id,
    step,
    expected_agent_count,
    runtime_config=None,
):
    """检查当前时间步是否可以开始，并返回可复用的完整决策。"""
    runtime_config = runtime_config or load_project_runtime_config()
    paths = runtime_config.paths
    if has_round_metrics(event_id, step, paths.metrics_history_file):
        raise ValueError(f"事件 {event_id} 的第 {step} 轮已经完成指标统计。")

    saved_decisions = load_successful_decisions(
        event_id,
        step,
        paths.decision_history_file,
    )
    if saved_decisions and len(saved_decisions) != expected_agent_count:
        raise ValueError(
            f"事件 {event_id} 的第 {step} 轮存在不完整决策："
            f"需要 {expected_agent_count} 个，实际 {len(saved_decisions)} 个。"
        )

    previous_step_incomplete = step > 1 and (
        not has_complete_decisions(
            event_id,
            step - 1,
            expected_agent_count,
            paths.decision_history_file,
        )
        or not has_round_metrics(
            event_id,
            step - 1,
            paths.metrics_history_file,
        )
    )
    if previous_step_incomplete:
        raise ValueError(
            f"事件 {event_id} 的第 {step - 1} 轮尚未完成，"
            f"不能直接运行第 {step} 轮。"
        )
    return saved_decisions


# 2026/08/22 系统重置与状态初始化 修改功能：每轮开始前严格检查当前状态目录。
def run_one_simulation_step(
    max_agents=None,
    max_workers=None,
    incremental_comment_count=None,
    runtime_config=None,
):
    """执行当前最新时间步的增量评论、Agent决策和指标统计。

    参数：
        max_agents：本轮最多参与决策的Agent数量。
        max_workers：批量Agent决策的最大并发线程数。
        incremental_comment_count：第2轮以后每轮生成的增量评论数量。

    返回：
        当前时间步的执行结果摘要。
    """
    runtime_config = runtime_config or load_project_runtime_config()
    paths = runtime_config.paths
    settings = runtime_config.simulation
    max_agents = settings.max_agents if max_agents is None else max_agents
    max_workers = settings.max_workers if max_workers is None else max_workers
    incremental_comment_count = (
        settings.incremental_comment_count
        if incremental_comment_count is None
        else incremental_comment_count
    )
    # 2026/09/04 Demo性能基线，新增功能：单独统计本轮评论生成、Agent决策、指标计算和LLM调用。
    reset_llm_performance_stats()
    step_start_time = time.perf_counter()
    event_input = load_json(paths.event_file)
    validate_simulation_state(paths.state_dir, event_input.get("event_id"))
    event_context = SimulationContext.from_mapping(
        load_event_context(paths.event_file, paths.event_state_file)
    )
    event_id = event_context.event_id
    step = event_context.step
    expected_agent_count = len(
        load_personas(paths.persona_dir, max_count=max_agents)
    )
    if expected_agent_count == 0:
        raise RuntimeError("没有可用于本轮决策的Persona。")

    # 2026/08/22 联调可靠性收尾：完整决策已经存在时复用结果，只补做尚未完成的指标统计。
    saved_decisions = validate_step_order(
        event_id,
        step,
        expected_agent_count,
        runtime_config,
    )

    incremental_record = None
    incremental_generated = False
    incremental_start_time = time.perf_counter()
    if step > 1:
        incremental_record = find_incremental_record(
            event_id,
            step,
            paths.incremental_comment_file,
        )
        if incremental_record is None:
            incremental_record = run_incremental_generation(
                incremental_comment_count
            )
            incremental_generated = True
    incremental_duration = time.perf_counter() - incremental_start_time

    agent_start_time = time.perf_counter()
    decisions_reused = bool(saved_decisions)
    if decisions_reused:
        decisions = saved_decisions
        print(
            f"事件 {event_id} 第 {step} 轮已有完整Agent决策，"
            "跳过重复决策并继续计算指标。"
        )
    else:
        decisions = run_batch_decision(
            max_count=max_agents,
            max_workers=max_workers,
            simulation_context=event_context,
            runtime_config=runtime_config,
        )

    # 联调修改：任一Agent失败时停止本轮，避免使用不完整数据计算指标 2026/08/21 19：06
    failed_decisions = [
        result for result in decisions if result.get("status") != "success"
    ]
    if failed_decisions:
        failed_details = [
            {
                "agent_id": result.get("agent_id"),
                "error": result.get("error", "未知错误"),
            }
            for result in failed_decisions
        ]
        raise RuntimeError(
            f"本轮有 {len(failed_decisions)} 个Agent决策失败："
            f"{failed_details}"
        )

    restore_missing_agent_states(decisions, paths.agent_state_file)
    success_count = len(decisions)
    agent_duration = time.perf_counter() - agent_start_time

    metrics_start_time = time.perf_counter()
    metrics = run_round_metrics()
    metrics_duration = time.perf_counter() - metrics_start_time

    return {
        "event_id": event_id,
        "step": step,
        "incremental_comment_count": (
            incremental_record.get("comment_count", 0)
            if incremental_record
            else 0
        ),
        "incremental_generated": incremental_generated,
        "incremental_generation_mode": (
            incremental_record.get("generation_mode", "llm_incremental")
            if incremental_record
            else "initial_pool"
        ),
        "agent_decision_count": len(decisions),
        "decisions_reused": decisions_reused,
        "success_count": success_count,
        "failed_count": len(decisions) - success_count,
        "metrics": metrics,
        "performance": {
            "total_duration_seconds": round(
                time.perf_counter() - step_start_time,
                3,
            ),
            "stage_duration_seconds": {
                "incremental_comment_generation": round(
                    incremental_duration,
                    3,
                ),
                "agent_decision": round(agent_duration, 3),
                "metrics": round(metrics_duration, 3),
            },
            "llm_requests": get_llm_performance_stats(),
        },
    }


def main():
    """提供执行当前最新时间步的命令行入口。"""
    runtime_config = load_project_runtime_config()
    parser = argparse.ArgumentParser(description="运行当前时间步的完整社会模拟")
    parser.add_argument(
        "--max-agents",
        type=int,
        default=runtime_config.simulation.max_agents,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=runtime_config.simulation.max_workers,
    )
    parser.add_argument(
        "--incremental-comments",
        type=int,
        default=runtime_config.simulation.incremental_comment_count,
    )
    args = parser.parse_args()

    result = run_one_simulation_step(
        max_agents=args.max_agents,
        max_workers=args.workers,
        incremental_comment_count=args.incremental_comments,
        runtime_config=runtime_config,
    )
    print("当前时间步模拟完成。")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 2026/09/04 Demo性能基线，新增功能：输出紧凑标记供实验父进程读取性能数据。
    performance_result = {
        "step": result["step"],
        "performance": result["performance"],
    }
    performance_json = json.dumps(
        performance_result,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    print(f"{SIMULATION_STEP_RESULT_PREFIX}{performance_json}")


if __name__ == "__main__":
    main()
