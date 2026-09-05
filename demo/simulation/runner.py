"""组织单轮和多轮社会舆情模拟。

本模块只负责按照顺序调用已有功能，不重新实现评论生成、Agent决策或指标计算。
官方声明及其类型由人工输入或后续实验模块提供，本模块不进行预测。
"""

import argparse
import json
import time

from agents.state_store import AgentStateStore
from agents.batch_decision import run_batch_decision
from simulation.event_context import load_event_context
from simulation.event_state_updater import append_event_state_record
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
from project_config import (
    AGENT_STATE_FILE,
    DECISION_HISTORY_FILE,
    EVENT_FILE,
    EVENT_STATE_FILE,
    INCREMENTAL_COMMENT_COUNT,
    INCREMENTAL_COMMENT_FILE,
    MAX_AGENT_COUNT,
    MAX_WORKERS,
    METRICS_HISTORY_FILE,
    STATE_DIR,
)
from simulation.state_manager import validate_simulation_state


# 2026/09/04 Demo性能基线，新增功能：为父进程提供稳定的单轮结果解析标记。
SIMULATION_STEP_RESULT_PREFIX = "SIMULATION_STEP_RESULT="


# 2026/08/22 联调可靠性收尾：按Agent去重读取指定时间步已经保存的成功决策。
def load_successful_decisions(
    event_id,
    step,
    history_file=DECISION_HISTORY_FILE,
):
    """读取指定事件和时间步的成功决策，并按Agent编号去重。"""
    decisions_by_agent = {}
    for record in read_jsonl(history_file):
        if record.get("event_id") != event_id or record.get("step") != step:
            continue
        if record.get("status") != "success" or not record.get("agent_id"):
            continue
        decisions_by_agent[record["agent_id"]] = record

    return [decisions_by_agent[key] for key in sorted(decisions_by_agent)]


def has_successful_decision(event_id, step, history_file=DECISION_HISTORY_FILE):
    """兼容原有调用：判断指定时间步是否至少存在一个成功决策。"""
    return bool(load_successful_decisions(event_id, step, history_file))


# 2026/08/22 联调可靠性收尾：使用预期Agent数量判断本轮决策是否完整。
def has_complete_decisions(
    event_id,
    step,
    expected_agent_count,
    history_file=DECISION_HISTORY_FILE,
):
    """判断指定时间步是否已经保存全部Agent的成功决策。"""
    decisions = load_successful_decisions(event_id, step, history_file)
    return len(decisions) == expected_agent_count


# 2026/08/22 联调可靠性收尾：恢复完整决策对应的缺失Agent状态，避免中断后留下半轮数据。
def restore_missing_agent_states(
    decisions,
    state_file=AGENT_STATE_FILE,
):
    """根据完整决策补写缺失的Agent状态，已经存在的状态不会重复写入。"""
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


def has_round_metrics(event_id, step, history_file=METRICS_HISTORY_FILE):
    """判断指定事件和时间步是否已经保存舆情指标。"""
    return any(
        record.get("event_id") == event_id and record.get("step") == step
        for record in read_jsonl(history_file)
        if not record.get("is_example")
    )


def find_incremental_record(
    event_id,
    step,
    history_file=INCREMENTAL_COMMENT_FILE,
):
    """查找当前时间步已经生成的增量评论批次。"""
    for record in load_incremental_history(history_file):
        if record.get("event_id") == event_id and record.get("step") == step:
            return record
    return None


def validate_step_order(event_id, step, expected_agent_count):
    """检查当前时间步是否可以开始，并返回可复用的完整决策。"""
    if has_round_metrics(event_id, step):
        raise ValueError(f"事件 {event_id} 的第 {step} 轮已经完成指标统计。")

    saved_decisions = load_successful_decisions(event_id, step)
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
        )
        or not has_round_metrics(event_id, step - 1)
    )
    if previous_step_incomplete:
        raise ValueError(
            f"事件 {event_id} 的第 {step - 1} 轮尚未完成，"
            f"不能直接运行第 {step} 轮。"
        )
    return saved_decisions


# 2026/08/22 系统重置与状态初始化 修改功能：每轮开始前严格检查当前状态目录。
def run_one_simulation_step(
    max_agents=MAX_AGENT_COUNT,
    max_workers=MAX_WORKERS,
    incremental_comment_count=INCREMENTAL_COMMENT_COUNT,
):
    """执行当前最新时间步的增量评论、Agent决策和指标统计。

    参数：
        max_agents：本轮最多参与决策的Agent数量。
        max_workers：批量Agent决策的最大并发线程数。
        incremental_comment_count：第2轮以后每轮生成的增量评论数量。

    返回：
        当前时间步的执行结果摘要。
    """
    # 2026/09/04 Demo性能基线，新增功能：单独统计本轮评论生成、Agent决策、指标计算和LLM调用。
    reset_llm_performance_stats()
    step_start_time = time.perf_counter()
    event_input = load_json(EVENT_FILE)
    validate_simulation_state(STATE_DIR, event_input.get("event_id"))
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    event_id = event_context["event_id"]
    step = event_context["current_state"]["step"]
    expected_agent_count = len(load_personas(max_count=max_agents))
    if expected_agent_count == 0:
        raise RuntimeError("没有可用于本轮决策的Persona。")

    # 2026/08/22 联调可靠性收尾：完整决策已经存在时复用结果，只补做尚未完成的指标统计。
    saved_decisions = validate_step_order(
        event_id,
        step,
        expected_agent_count,
    )

    incremental_record = None
    incremental_generated = False
    incremental_start_time = time.perf_counter()
    if step > 1:
        incremental_record = find_incremental_record(event_id, step)
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

    restore_missing_agent_states(decisions)
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


# 2026/08/22 系统重置与状态初始化 修改功能：跳过当前轮时单独检查状态，其余交由单轮入口检查。
def run_multi_round_simulation(
    future_event_states,
    run_current_step=True,
    max_agents=MAX_AGENT_COUNT,
    max_workers=MAX_WORKERS,
    incremental_comment_count=INCREMENTAL_COMMENT_COUNT,
):
    """运行当前时间步，并按照给定官方声明序列继续运行后续轮次。

    参数：
        future_event_states：后续轮次的官方声明列表。每项包含
            official_statement 和 official_statement_status。
        run_current_step：是否先运行event_state_history中的当前最新时间步。
        max_agents：每轮最多参与决策的Agent数量。
        max_workers：批量决策最大并发线程数。
        incremental_comment_count：每轮新增候选评论数量。

    返回：
        按时间步排列的模拟结果列表。
    """
    if not isinstance(future_event_states, list):
        raise ValueError("future_event_states 必须是列表。")

    event_input = load_json(EVENT_FILE)
    results = []

    if run_current_step:
        results.append(
            run_one_simulation_step(
                max_agents,
                max_workers,
                incremental_comment_count,
            )
        )
    else:
        validate_simulation_state(STATE_DIR, event_input.get("event_id"))
        current_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
        current_step = current_context["current_state"]["step"]
        expected_agent_count = len(load_personas(max_count=max_agents))
        current_step_complete = has_complete_decisions(
            current_context["event_id"],
            current_step,
            expected_agent_count,
        ) and has_round_metrics(current_context["event_id"], current_step)
        if not current_step_complete:
            raise ValueError("当前最新时间步尚未完成，不能直接追加下一轮状态。")

    for state_input in future_event_states:
        if not isinstance(state_input, dict):
            raise ValueError("每个后续事件状态都必须是字典。")
        append_event_state_record(
            event_input=event_input,
            official_statement=state_input.get("official_statement", ""),
            official_statement_status=state_input.get(
                "official_statement_status", "none"
            ),
            state_file=EVENT_STATE_FILE,
        )
        results.append(
            run_one_simulation_step(
                max_agents,
                max_workers,
                incremental_comment_count,
            )
        )

    return results


def main():
    """提供执行当前最新时间步的命令行入口。"""
    parser = argparse.ArgumentParser(description="运行当前时间步的完整社会模拟")
    parser.add_argument("--max-agents", type=int, default=MAX_AGENT_COUNT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument(
        "--incremental-comments",
        type=int,
        default=INCREMENTAL_COMMENT_COUNT,
    )
    args = parser.parse_args()

    result = run_one_simulation_step(
        max_agents=args.max_agents,
        max_workers=args.workers,
        incremental_comment_count=args.incremental_comments,
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
