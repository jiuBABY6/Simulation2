"""运行并比较四种官方内容策略。

本模块只负责编排实验。四种内容策略使用相同的动态进场规则和独立状态目录，
具体评论生成、Agent 决策和指标统计继续由 simulation/runner.py 完成。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from simulation.event_state_updater import append_event_state_record
from infrastructure.json_storage import load_json, read_jsonl, save_json
from infrastructure.llm_service import merge_llm_performance_stats
from evaluation.metrics import (
    calculate_control_net_effect,
    calculate_effect_duration,
    calculate_emotion_recovery_rate,
    calculate_negative_peak_and_area,
    calculate_rebound_rate,
)
from project_config import DEMO_DIR, OFFICIAL_RESPONSE_FILE
from simulation.state_manager import (
    initialize_simulation_state,
    initialize_state_from_snapshot,
)


# 修改下面这些参数即可调整 Demo 实验规模。
# MAX_STEPS = 5
# MAX_AGENTS = 30
# MAX_WORKERS = 5
# INCREMENTAL_COMMENT_COUNT = 20
MAX_STEPS = 10
MAX_AGENTS = 10
MAX_WORKERS = 5
INCREMENTAL_COMMENT_COUNT = 20
RANDOM_SEED = 2026
# 2026/08/25 第八次联调问题修复，修改功能：提高评论生成多样性，减少确定性重复文本。
COMMENT_TEMPERATURE = 0.5

# 2026/09/04 Demo性能基线，新增功能：识别单轮子进程返回的结构化性能结果。
SIMULATION_STEP_RESULT_PREFIX = "SIMULATION_STEP_RESULT="

# 官方回应的触发阈值。
NEGATIVE_RATE_THRESHOLD = 0.5

# 2026/08/23 内容策略对照，修改功能：内容场景共用一个已有的动态进场规则。
ENTRY_STRATEGIES = (
    "negative_threshold",
    "global_worsening",
    "combined_policy",
)
# 2026/08/23 内容策略对照，新增功能：明确当前 Demo 必须提供的四种人工内容策略。
CONTENT_STRATEGY_IDS = (
    "fact_report",
    "empathy",
    "rumor_clarification",
    "handling_progress",
)
OFFICIAL_STATEMENT_STATUSES = (
    "clear",
    "incomplete",
    "conflict",
)
# 2026/08/23 内容策略对照，新增功能：保留不发布官方声明的独立实验基线。
NO_RESPONSE_SCENARIO = {
    "strategy_id": "no_response",
    "strategy_name": "不回应",
    "official_statement": "",
    "official_statement_status": "none",
}


def parse_simulation_step_result(output):
    """从子进程标准输出中提取最后一个带标记的单轮结果。"""
    for line in reversed(str(output).splitlines()):
        if not line.startswith(SIMULATION_STEP_RESULT_PREFIX):
            continue
        payload = line[len(SIMULATION_STEP_RESULT_PREFIX):]
        try:
            result = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("单轮子进程返回的性能结果不是合法JSON。") from error
        if not isinstance(result, dict):
            raise ValueError("单轮子进程返回的结果必须是JSON对象。")
        return result
    raise ValueError("单轮子进程没有返回带标记的结构化结果。")


def summarize_step_performance(step_results):
    """汇总一组实际执行时间步的阶段耗时和LLM请求。"""
    stage_totals = {
        "incremental_comment_generation": 0.0,
        "agent_decision": 0.0,
        "metrics": 0.0,
    }
    llm_stats = []
    normalized_steps = []

    for item in step_results:
        if not isinstance(item, dict):
            continue
        performance = item.get("performance", {})
        if not isinstance(performance, dict):
            continue
        normalized_steps.append(
            {
                "step": item.get("step"),
                **performance,
            }
        )
        stage_duration = performance.get("stage_duration_seconds", {})
        if isinstance(stage_duration, dict):
            for stage_name in stage_totals:
                value = stage_duration.get(stage_name, 0)
                if isinstance(value, (int, float)) and not isinstance(
                    value,
                    bool,
                ):
                    stage_totals[stage_name] += value
        llm_stats.append(performance.get("llm_requests"))

    return {
        "executed_step_count": len(normalized_steps),
        "stage_duration_seconds": {
            key: round(value, 3)
            for key, value in stage_totals.items()
        },
        "llm_requests": merge_llm_performance_stats(*llm_stats),
        "steps": normalized_steps,
    }


def build_experiment_performance(
    shared_baseline,
    strategy_results,
    experiment_duration,
    baseline_duration,
):
    """汇总共享基线和各策略的性能统计，不重复计算复制的基线轮次。"""
    performance_items = []
    baseline_performance = (
        shared_baseline.get("performance", {})
        if isinstance(shared_baseline, dict)
        else {}
    )
    if baseline_performance:
        performance_items.append(baseline_performance)

    strategy_duration = {}
    for result in strategy_results:
        strategy_id = result.get("strategy")
        performance = result.get("performance", {})
        if not strategy_id or not isinstance(performance, dict):
            continue
        strategy_duration[strategy_id] = performance.get(
            "duration_seconds",
            0.0,
        )
        performance_items.append(performance)

    stage_totals = {
        "incremental_comment_generation": 0.0,
        "agent_decision": 0.0,
        "metrics": 0.0,
    }
    for performance in performance_items:
        stages = performance.get("stage_duration_seconds", {})
        if not isinstance(stages, dict):
            continue
        for stage_name in stage_totals:
            value = stages.get(stage_name, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stage_totals[stage_name] += value

    return {
        "experiment_duration_seconds": round(experiment_duration, 3),
        "shared_baseline_duration_seconds": round(baseline_duration, 3),
        "strategy_duration_seconds": strategy_duration,
        "stage_duration_seconds": {
            key: round(value, 3)
            for key, value in stage_totals.items()
        },
        "llm_requests": merge_llm_performance_stats(
            *(item.get("llm_requests") for item in performance_items)
        ),
    }


# 2026/08/23 内容策略对照，新增功能：严格校验人工维护的官方内容策略输入。
# 2026/08/27 第十二次联调修复，修改功能：校验连续未改善动态进场配置。
def validate_official_response_options(options, event_id):
    """校验事件编号、动态进场规则和内容策略字段。"""
    if not isinstance(options, dict):
        raise ValueError("官方内容策略文件必须是 JSON 对象。")
    if options.get("event_id") != event_id:
        raise ValueError("官方内容策略与当前事件的 event_id 不一致。")

    entry_strategy = options.get("entry_strategy")
    if entry_strategy not in ENTRY_STRATEGIES:
        raise ValueError(
            f"entry_strategy 必须是以下之一：{ENTRY_STRATEGIES}"
        )

    stagnation_rounds = options.get("stagnation_rounds", 0)
    if (
        isinstance(stagnation_rounds, bool)
        or not isinstance(stagnation_rounds, int)
        or stagnation_rounds < 0
    ):
        raise ValueError("stagnation_rounds 必须是非负整数。")
    improvement_tolerance = options.get(
        "negative_rate_improvement_tolerance",
        0.05,
    )
    if (
        isinstance(improvement_tolerance, bool)
        or not isinstance(improvement_tolerance, (int, float))
        or not 0 <= improvement_tolerance <= 1
    ):
        raise ValueError(
            "negative_rate_improvement_tolerance 必须是0到1之间的数值。"
        )

    raw_strategies = options.get("content_strategies")
    if not isinstance(raw_strategies, list) or not raw_strategies:
        raise ValueError("content_strategies 必须是非空数组。")

    strategies = []
    strategy_ids = set()
    for index, item in enumerate(raw_strategies, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个内容策略必须是 JSON 对象。")

        strategy_id = str(item.get("strategy_id", "")).strip()
        strategy_name = str(item.get("strategy_name", "")).strip()
        statement = str(item.get("official_statement", "")).strip()
        statement_status = item.get("official_statement_status")
        if (
            not strategy_id
            or Path(strategy_id).name != strategy_id
            or strategy_id in {".", ".."}
        ):
            raise ValueError(f"第 {index} 个内容策略的 strategy_id 不合法。")
        if strategy_id in strategy_ids:
            raise ValueError(f"发现重复的内容策略编号：{strategy_id}")
        if not strategy_name:
            raise ValueError(f"内容策略 {strategy_id} 缺少 strategy_name。")
        if not statement:
            raise ValueError(f"内容策略 {strategy_id} 的官方声明不能为空。")
        if statement_status not in OFFICIAL_STATEMENT_STATUSES:
            raise ValueError(
                f"内容策略 {strategy_id} 的 official_statement_status 不合法。"
            )

        strategy_ids.add(strategy_id)
        strategies.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "official_statement": statement,
                "official_statement_status": statement_status,
            }
        )

    expected_ids = set(CONTENT_STRATEGY_IDS)
    if strategy_ids != expected_ids:
        missing_ids = sorted(expected_ids - strategy_ids)
        extra_ids = sorted(strategy_ids - expected_ids)
        raise ValueError(
            "内容策略必须完整包含当前四种策略："
            f"缺少 {missing_ids}，多余 {extra_ids}。"
        )

    return {
        "event_id": event_id,
        "entry_strategy": entry_strategy,
        "stagnation_rounds": stagnation_rounds,
        "negative_rate_improvement_tolerance": float(
            improvement_tolerance
        ),
        "content_strategies": strategies,
    }


# 2026/08/23 内容策略对照，新增功能：从外部 JSON 读取当前事件的人工官方声明。
def load_official_response_options(response_file, event_id):
    """读取并返回经过严格校验的官方内容策略。"""
    response_path = Path(response_file)
    if not response_path.is_file():
        raise FileNotFoundError(f"官方内容策略文件不存在：{response_path}")
    return validate_official_response_options(
        load_json(response_path),
        event_id,
    )


# 2026/08/25 第五次联调问题修复，修改功能：保留无声明场景的空官方态度指标。
def extract_policy_metrics(round_metrics):
    """提取官方回应策略需要使用的指标，并保留不适用的空值。"""
    try:
        attitude_summary = round_metrics["official_attitude_distribution"]
        attitude = attitude_summary["distribution"]
        return {
            "negative_rate": round_metrics["agent_negative_emotion"]["negative_rate"],
            "question_rate": attitude["question"]["rate"],
            "accept_rate": attitude["accept"]["rate"],
            "official_attitude_applicable_count": attitude_summary.get(
                "applicable_agent_count",
                attitude_summary.get("agent_count", 0),
            ),
            "global_trend": round_metrics["global_trend"]["trend_direction"],
        }
    except (KeyError, TypeError) as error:
        raise ValueError("指标结果缺少实验策略所需字段。") from error


# 2026/08/27 第十二次联调修复，新增功能：计算第1轮基线之后连续没有明显改善的轮数。
def count_consecutive_stagnant_rounds(
    round_results,
    improvement_tolerance,
):
    """从最近一轮向前统计趋势稳定且负面率未明显下降的连续轮数。"""
    if not isinstance(round_results, list):
        raise ValueError("round_results 必须是列表。")
    if (
        isinstance(improvement_tolerance, bool)
        or not isinstance(improvement_tolerance, (int, float))
        or not 0 <= improvement_tolerance <= 1
    ):
        raise ValueError("improvement_tolerance 必须是0到1之间的数值。")

    stagnant_rounds = 0
    for index in range(len(round_results) - 1, 0, -1):
        current_metrics = round_results[index].get("policy_metrics", {})
        previous_metrics = round_results[index - 1].get(
            "policy_metrics",
            {},
        )
        current_rate = current_metrics.get("negative_rate")
        previous_rate = previous_metrics.get("negative_rate")
        if (
            current_metrics.get("global_trend") != "stable"
            or not isinstance(current_rate, (int, float))
            or isinstance(current_rate, bool)
            or not isinstance(previous_rate, (int, float))
            or isinstance(previous_rate, bool)
        ):
            break

        negative_rate_improvement = previous_rate - current_rate
        if negative_rate_improvement > improvement_tolerance:
            break
        stagnant_rounds += 1
    return stagnant_rounds


# 2026/08/27 第十二次联调修复，新增功能：统一返回是否进场、触发原因和停滞轮数。
def evaluate_response_entry(
    entry_strategy,
    policy_metrics,
    response_count,
    round_results=None,
    stagnation_rounds=0,
    improvement_tolerance=0.05,
):
    """按照阈值、趋势和连续未改善规则判断下一轮是否进场。"""
    if entry_strategy == "no_response":
        return {
            "should_enter": False,
            "entry_reason": None,
            "stagnant_round_count": 0,
        }
    if entry_strategy not in ENTRY_STRATEGIES:
        raise ValueError(f"不支持的动态进场规则：{entry_strategy}")
    if response_count >= 1:
        return {
            "should_enter": False,
            "entry_reason": None,
            "stagnant_round_count": 0,
        }

    negative_high = policy_metrics["negative_rate"] >= NEGATIVE_RATE_THRESHOLD
    trend_worsening = policy_metrics["global_trend"] == "worsening"
    if entry_strategy in {"negative_threshold", "combined_policy"} and negative_high:
        return {
            "should_enter": True,
            "entry_reason": "negative_threshold",
            "stagnant_round_count": 0,
        }
    if entry_strategy in {"global_worsening", "combined_policy"} and trend_worsening:
        return {
            "should_enter": True,
            "entry_reason": "global_worsening",
            "stagnant_round_count": 0,
        }

    stagnant_round_count = 0
    if entry_strategy == "combined_policy" and stagnation_rounds > 0:
        stagnant_round_count = count_consecutive_stagnant_rounds(
            round_results or [],
            improvement_tolerance,
        )
        if stagnant_round_count >= stagnation_rounds:
            return {
                "should_enter": True,
                "entry_reason": "stagnation",
                "stagnant_round_count": stagnant_round_count,
            }
    return {
        "should_enter": False,
        "entry_reason": None,
        "stagnant_round_count": stagnant_round_count,
    }


# 2026/08/23 内容策略对照，修改功能：所有内容场景最多发布一次官方声明。
# 2026/08/27 第十二次联调修复，修改功能：保留旧布尔调用并复用统一进场判断。
def should_publish_response(entry_strategy, policy_metrics, response_count):
    """根据统一动态进场规则判断下一轮是否首次发布官方声明。"""
    decision = evaluate_response_entry(
        entry_strategy,
        policy_metrics,
        response_count,
    )
    return decision["should_enter"]


# 2026/08/22 系统重置与状态初始化 修改功能：使用统一状态管理器创建策略状态目录。
# 2026/08/25 第八次联调问题修复，修改功能：场景可从统一的进场前状态快照开始运行。
def prepare_scenario_state(
    experiment_dir,
    strategy_name,
    event_id,
    baseline_state_dir=None,
):
    """为一个实验策略创建初始状态，必要时复用共享基线快照。"""
    scenario_dir = Path(experiment_dir) / strategy_name
    state_dir = scenario_dir / "state"
    if scenario_dir.exists():
        raise FileExistsError(f"实验策略目录已经存在：{scenario_dir}")

    if baseline_state_dir is None:
        initialize_simulation_state(
            state_dir=state_dir,
            event_input={"event_id": event_id},
        )
    else:
        initialize_state_from_snapshot(
            source_state_dir=baseline_state_dir,
            state_dir=state_dir,
            event_id=event_id,
        )
    return scenario_dir, state_dir


# 2026/08/22 系统重置与状态初始化，修改功能：向仿真子进程传递本批次独立输入路径。
def run_simulation_step(state_dir, event_file, comment_pool_file):
    """使用指定状态、事件和评论池运行一个时间步并返回性能结果。"""
    environment = os.environ.copy()
    environment["SIMULATION_STATE_DIR"] = str(Path(state_dir).resolve())
    environment["SIMULATION_EVENT_FILE"] = str(Path(event_file).resolve())
    environment["SIMULATION_COMMENT_POOL_FILE"] = str(
        Path(comment_pool_file).resolve()
    )
    environment["SIMULATION_RANDOM_SEED"] = str(RANDOM_SEED)
    environment["SIMULATION_COMMENT_TEMPERATURE"] = str(COMMENT_TEMPERATURE)
    # 2026/08/22 联调可靠性收尾：统一子进程输出编码，避免中文错误信息出现乱码。
    environment["PYTHONIOENCODING"] = "utf-8"

    # 2026/09/05 代码结构重构，修改功能：以包模块方式启动迁移后的仿真运行器。
    command = [
        sys.executable,
        "-m",
        "simulation.runner",
        "--max-agents",
        str(MAX_AGENTS),
        "--workers",
        str(MAX_WORKERS),
        "--incremental-comments",
        str(INCREMENTAL_COMMENT_COUNT),
    ]
    process = subprocess.run(
        command,
        cwd=str(DEMO_DIR),
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        # 2026/08/24 增量评论稳定补齐，修改功能：失败时同时保留评论过滤日志和异常栈。
        output_parts = []
        if process.stdout.strip():
            output_parts.append(f"标准输出：\n{process.stdout.strip()}")
        if process.stderr.strip():
            output_parts.append(f"异常输出：\n{process.stderr.strip()}")
        message = "\n\n".join(output_parts) or "子进程未返回错误信息。"
        raise RuntimeError(f"场景时间步运行失败：{message}")

    # 2026/09/04 Demo性能基线，修改功能：解析子进程结果供基线、场景和实验三级汇总。
    return parse_simulation_step_result(process.stdout)


# 2026/08/26 第九次联调问题修复，新增功能：提取适合控制台显示的简短场景错误。
def summarize_scenario_error(error, max_length=160):
    """返回单行错误摘要，完整异常仍由实验结果文件保存。"""
    message = str(error)
    if "HTTP 402" in message or "Insufficient Balance" in message:
        return "DeepSeek HTTP 402：余额不足（Insufficient Balance）"

    lines = [line.strip() for line in message.splitlines() if line.strip()]
    summary = lines[-1] if lines else error.__class__.__name__
    if len(summary) > max_length:
        return f"{summary[:max_length]}……"
    return summary


def load_step_metrics(metrics_file, event_id, step):
    """读取指定事件和时间步的正式指标记录。"""
    matches = [
        record
        for record in read_jsonl(metrics_file)
        if record.get("event_id") == event_id
        and record.get("step") == step
        and not record.get("is_example")
    ]
    if not matches:
        raise ValueError(f"找不到事件 {event_id} 第 {step} 轮的指标。")
    return matches[-1]


# 2026/08/24 增量评论稳定补齐，新增功能：读取指定轮次的评论来源统计和数据质量状态。
# 2026/09/04 增量评论生成架构优化，修改功能：向场景结果传递首轮请求、统一补齐和生成波次统计。
# 2026/09/04 评论质量与耗时平衡，修改功能：传递质量目标和自适应救援请求统计。
def load_step_comment_quality(incremental_file, event_id, step):
    """从增量评论历史中提取场景结果需要的质量摘要。"""
    matches = [
        record
        for record in read_jsonl(incremental_file)
        if record.get("event_id") == event_id and record.get("step") == step
    ]
    if not matches:
        raise ValueError(f"找不到事件 {event_id} 第 {step} 轮的增量评论。")
    record = matches[-1]
    fallback_count = record.get("fallback_count", 0)
    history_fallback_count = record.get(
        "history_fallback_count",
        fallback_count,
    )
    emergency_fallback_count = record.get("emergency_fallback_count", 0)
    return {
        "step": step,
        "quality_status": record.get("quality_status", "normal"),
        "comment_count": record.get("comment_count", 0),
        "llm_comment_count": record.get(
            "llm_comment_count",
            record.get("comment_count", 0) - fallback_count,
        ),
        "history_fallback_count": history_fallback_count,
        "emergency_fallback_count": emergency_fallback_count,
        "fallback_count": fallback_count,
        "generation_attempts": record.get("generation_attempts", 0),
        "initial_request_count": record.get("initial_request_count", 0),
        "refill_request_count": record.get("refill_request_count", 0),
        "rescue_request_count": record.get("rescue_request_count", 0),
        "generation_wave_count": record.get("generation_wave_count", 0),
        "quality_target_count": record.get("quality_target_count", 0),
        "model_returned_comment_count": record.get(
            "model_returned_comment_count",
            0,
        ),
        "rejection_counts": record.get("rejection_counts", {}),
        "validation_errors": record.get("validation_errors", []),
    }


# 2026/08/24 增量评论稳定补齐，新增功能：汇总一个实验场景全部轮次的评论数据质量。
# 2026/09/04 增量评论生成架构优化，修改功能：汇总业务层评论请求数，便于和性能基线直接比较。
# 2026/09/04 评论质量与耗时平衡，修改功能：汇总自适应救援请求数量。
def summarize_comment_quality(quality_records):
    """汇总兜底数量，并按 emergency、degraded、normal 的优先级定级。"""
    statuses = {record["quality_status"] for record in quality_records}
    if "emergency" in statuses:
        quality_status = "emergency"
    elif "degraded" in statuses:
        quality_status = "degraded"
    else:
        quality_status = "normal"
    return {
        "quality_status": quality_status,
        "llm_comment_count": sum(
            record["llm_comment_count"] for record in quality_records
        ),
        "history_fallback_count": sum(
            record["history_fallback_count"] for record in quality_records
        ),
        "emergency_fallback_count": sum(
            record["emergency_fallback_count"] for record in quality_records
        ),
        "fallback_count": sum(
            record["fallback_count"] for record in quality_records
        ),
        "generation_attempts": sum(
            record.get("generation_attempts", 0)
            for record in quality_records
        ),
        "initial_request_count": sum(
            record.get("initial_request_count", 0)
            for record in quality_records
        ),
        "refill_request_count": sum(
            record.get("refill_request_count", 0)
            for record in quality_records
        ),
        "rescue_request_count": sum(
            record.get("rescue_request_count", 0)
            for record in quality_records
        ),
        "warning_steps": [
            record["step"]
            for record in quality_records
            if record["quality_status"] != "normal"
        ],
    }


# 2026/08/25 第八次联调问题修复，新增功能：统一读取共享基线和独立场景的单轮结果。
def load_round_result(state_dir, event_id, step):
    """读取一个时间步的策略指标，并在增量轮次附加评论质量。"""
    metrics_file = Path(state_dir) / "metrics_history.jsonl"
    incremental_file = Path(state_dir) / "incremental_comment_history.jsonl"
    round_metrics = load_step_metrics(metrics_file, event_id, step)
    round_result = {
        "step": step,
        "policy_metrics": extract_policy_metrics(round_metrics),
    }
    comment_quality = None
    if step > 1:
        comment_quality = load_step_comment_quality(
            incremental_file,
            event_id,
            step,
        )
        round_result["comment_generation"] = comment_quality
    return round_result, comment_quality


# 2026/08/27 舆情指标计算扩充，新增功能：汇总单个场景的恢复、反弹和负面过程指标。
def calculate_strategy_effect_metrics(rounds, state_dir, response_step):
    """根据场景轮次和Agent状态历史计算单批次过程指标。"""
    peak_metrics = calculate_negative_peak_and_area(rounds)
    final_negative_rate = rounds[-1]["policy_metrics"]["negative_rate"]
    effect_metrics = {
        "analysis_start_step": response_step,
        "final_negative_rate": final_negative_rate,
        **peak_metrics,
        "control_net_effect": None,
    }
    if response_step is None:
        effect_metrics.update(
            {
                "baseline_step": None,
                "baseline_negative_agent_count": None,
                "recovered_agent_count": None,
                "emotion_recovery_rate": None,
                "effect_baseline_negative_rate": None,
                "effect_start_step": None,
                "effect_end_step": None,
                "effect_duration": None,
                "rebound_agent_count": None,
                "rebound_rate": None,
            }
        )
        return effect_metrics

    agent_state_history = read_jsonl(
        Path(state_dir) / "agent_state_history.jsonl"
    )
    recovery_metrics = calculate_emotion_recovery_rate(
        agent_state_history,
        response_step,
    )
    duration_metrics = calculate_effect_duration(rounds, response_step)
    rebound_metrics = calculate_rebound_rate(
        agent_state_history,
        response_step,
    )
    effect_metrics.update(recovery_metrics)
    effect_metrics.update(duration_metrics)
    effect_metrics.update(rebound_metrics)
    return effect_metrics


# 2026/08/27 舆情指标计算扩充，新增功能：为回应场景附加相对不回应场景的净效果。
def attach_control_net_effect_metrics(strategy_results, experiment_dir):
    """找到成功的不回应场景，并将净效果写回各成功回应场景。"""
    control_result = next(
        (
            result
            for result in strategy_results
            if result.get("strategy") == "no_response"
            and result.get("status") == "success"
            and isinstance(result.get("effect_metrics"), dict)
        ),
        None,
    )
    if control_result is None:
        return

    control_metrics = control_result["effect_metrics"]
    for result in strategy_results:
        effect_metrics = result.get("effect_metrics")
        if (
            result.get("status") != "success"
            or not isinstance(effect_metrics, dict)
        ):
            continue
        if result.get("strategy") != "no_response":
            effect_metrics["control_net_effect"] = (
                calculate_control_net_effect(
                    effect_metrics,
                    control_metrics,
                )
            )
        scenario_file = (
            Path(experiment_dir)
            / result["strategy"]
            / "scenario_result.json"
        )
        save_json(scenario_file, result)


# 2026/08/25 第八次联调问题修复，新增功能：所有策略共用官方动态进场前的真实舆情路径。
# 2026/08/27 第十二次联调修复，修改功能：共享基线支持连续未改善进场并记录触发原因。
def run_shared_pre_entry_baseline(
    entry_strategy,
    event_input,
    experiment_dir,
    event_file,
    comment_pool_file,
    stagnation_rounds=0,
    improvement_tolerance=0.05,
):
    """在无声明状态下运行到首次触发进场，并返回可复制的状态快照。"""
    # 2026/09/04 Demo性能基线，新增功能：记录共享基线墙钟耗时和每个实际执行时间步的性能。
    baseline_start_time = time.perf_counter()
    _, state_dir = prepare_scenario_state(
        experiment_dir,
        "_shared_baseline",
        event_input["event_id"],
    )
    state_file = state_dir / "event_state_history.json"
    rounds = []
    quality_records = []
    response_step = None
    entry_reason = None
    stagnant_round_count = 0
    step_results = []

    for step in range(1, MAX_STEPS + 1):
        step_result = run_simulation_step(
            state_dir,
            event_file,
            comment_pool_file,
        )
        step_results.append(step_result)
        round_result, comment_quality = load_round_result(
            state_dir,
            event_input["event_id"],
            step,
        )
        rounds.append(round_result)
        if comment_quality is not None:
            quality_records.append(comment_quality)

        if step == MAX_STEPS:
            break
        entry_decision = evaluate_response_entry(
            entry_strategy,
            round_result["policy_metrics"],
            response_count=0,
            round_results=rounds,
            stagnation_rounds=stagnation_rounds,
            improvement_tolerance=improvement_tolerance,
        )
        stagnant_round_count = entry_decision["stagnant_round_count"]
        if entry_decision["should_enter"]:
            response_step = step + 1
            entry_reason = entry_decision["entry_reason"]
            break

        append_event_state_record(
            event_input=event_input,
            official_statement="",
            official_statement_status="none",
            state_file=state_file,
        )

    performance = summarize_step_performance(step_results)
    performance["duration_seconds"] = round(
        time.perf_counter() - baseline_start_time,
        3,
    )
    return {
        "state_dir": state_dir,
        "rounds": rounds,
        "quality_records": quality_records,
        "completed_step": rounds[-1]["step"],
        "response_step": response_step,
        "entry_triggered": response_step is not None,
        "entry_reason": entry_reason,
        "stagnant_round_count": stagnant_round_count,
        "performance": performance,
    }


# 2026/08/23 内容策略对照，修改功能：每个场景使用相同进场规则和一种人工内容策略。
# 2026/08/25 第八次联调问题修复，修改功能：各场景从同一份进场前快照继续独立演化。
# 2026/08/27 第十二次联调修复，修改功能：未触发进场的回应场景标记为not_run。
def run_one_content_strategy(
    content_strategy,
    entry_strategy,
    event_input,
    experiment_dir,
    event_file,
    comment_pool_file,
    shared_baseline,
):
    """复制共享基线，并从动态进场后的第一轮继续运行内容策略。"""
    # 2026/09/04 Demo性能基线，新增功能：记录单个策略自身执行的墙钟耗时和分轮性能。
    strategy_start_time = time.perf_counter()
    strategy_id = content_strategy["strategy_id"]
    scenario_dir, state_dir = prepare_scenario_state(
        experiment_dir,
        strategy_id,
        event_input["event_id"],
        shared_baseline["state_dir"],
    )
    state_file = state_dir / "event_state_history.json"
    is_response_scenario = entry_strategy != "no_response"
    active_response = (
        {
            "official_statement": content_strategy["official_statement"],
            "official_statement_status": content_strategy[
                "official_statement_status"
            ],
        }
        if is_response_scenario
        else {
            "official_statement": "",
            "official_statement_status": "none",
        }
    )
    response_records = []
    rounds = list(shared_baseline["rounds"])
    quality_records = list(shared_baseline["quality_records"])
    response_step = shared_baseline["response_step"]
    entry_triggered = shared_baseline["entry_triggered"]
    entry_reason = shared_baseline["entry_reason"]
    step_results = []

    if is_response_scenario and not entry_triggered:
        performance = summarize_step_performance(step_results)
        performance["duration_seconds"] = round(
            time.perf_counter() - strategy_start_time,
            3,
        )
        result = {
            "strategy": strategy_id,
            "strategy_name": content_strategy["strategy_name"],
            "entry_strategy": entry_strategy,
            "status": "not_run",
            "reason": "official_response_not_triggered",
            "entry_triggered": False,
            "entry_reason": None,
            "comparison_eligible": False,
            "official_responses": [],
            "rounds": rounds,
            "final_metrics": rounds[-1]["policy_metrics"],
            "comment_quality": summarize_comment_quality(quality_records),
            "shared_baseline_completed_step": shared_baseline[
                "completed_step"
            ],
            "state_dir": str(state_dir),
            "performance": performance,
        }
        save_json(scenario_dir / "scenario_result.json", result)
        return result

    if response_step is not None:
        if is_response_scenario:
            response_records.append(
                {
                    "step": response_step,
                    "strategy_id": strategy_id,
                    "strategy_name": content_strategy["strategy_name"],
                    **active_response,
                }
            )

        append_event_state_record(
            event_input=event_input,
            official_statement=active_response["official_statement"],
            official_statement_status=active_response[
                "official_statement_status"
            ],
            state_file=state_file,
        )

    for step in range(response_step or (MAX_STEPS + 1), MAX_STEPS + 1):
        step_result = run_simulation_step(
            state_dir,
            event_file,
            comment_pool_file,
        )
        step_results.append(step_result)
        round_result, comment_quality = load_round_result(
            state_dir,
            event_input["event_id"],
            step,
        )
        if comment_quality is not None:
            quality_records.append(comment_quality)
        rounds.append(round_result)

        if step == MAX_STEPS:
            break

        # 2026/08/25 第八次联调问题修复，修改功能：分叉后持续沿用各场景自己的声明状态。
        append_event_state_record(
            event_input=event_input,
            official_statement=active_response["official_statement"],
            official_statement_status=active_response[
                "official_statement_status"
            ],
            state_file=state_file,
        )

    # 2026/08/27 舆情指标计算扩充，新增功能：场景完成后计算完整10轮的过程指标。
    effect_metrics = calculate_strategy_effect_metrics(
        rounds,
        state_dir,
        response_step,
    )
    performance = summarize_step_performance(step_results)
    performance["duration_seconds"] = round(
        time.perf_counter() - strategy_start_time,
        3,
    )
    result = {
        "strategy": strategy_id,
        "strategy_name": content_strategy["strategy_name"],
        "entry_strategy": entry_strategy,
        "status": "success",
        "entry_triggered": entry_triggered,
        "entry_reason": entry_reason,
        "comparison_eligible": entry_triggered,
        "official_responses": response_records,
        "rounds": rounds,
        "final_metrics": rounds[-1]["policy_metrics"],
        "effect_metrics": effect_metrics,
        "comment_quality": summarize_comment_quality(quality_records),
        "shared_baseline_completed_step": shared_baseline["completed_step"],
        "state_dir": str(state_dir),
        "performance": performance,
    }
    save_json(scenario_dir / "scenario_result.json", result)
    return result


# 2026/08/25 第五次联调问题修复，修改功能：跳过不适用指标并如实返回全部并列策略。
def compare_strategy_results(strategy_results):
    """比较策略最终指标，并明确返回唯一最佳、并列或不适用结果。"""
    successful = [
        result
        for result in strategy_results
        if result.get("status") == "success"
        and result.get("comparison_eligible", True)
        and isinstance(result.get("final_metrics"), dict)
    ]
    if not successful:
        return {}

    def find_best(value_reader, highest=False):
        eligible = []
        for result in successful:
            value = value_reader(result)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                eligible.append((result, value))
        if not eligible:
            return None

        values = [value for _, value in eligible]
        best_value = max(values) if highest else min(values)
        best_results = [
            result
            for result, value in eligible
            if value == best_value
        ]
        is_tie = len(best_results) > 1
        return {
            "strategy": None if is_tie else best_results[0]["strategy"],
            "strategy_name": (
                None if is_tie else best_results[0].get("strategy_name")
            ),
            "strategies": [
                {
                    "strategy": result["strategy"],
                    "strategy_name": result.get("strategy_name"),
                }
                for result in best_results
            ],
            "value": best_value,
            "is_tie": is_tie,
        }

    def read_effect_metric(result, metric_name):
        """读取场景过程指标中的一个数值。"""
        return result.get("effect_metrics", {}).get(metric_name)

    def read_control_metric(result, metric_name):
        """读取场景相对不回应基线的一个净效果数值。"""
        control_metrics = result.get("effect_metrics", {}).get(
            "control_net_effect"
        )
        if not isinstance(control_metrics, dict):
            return None
        return control_metrics.get(metric_name)

    # 2026/08/27 舆情指标计算扩充，修改功能：同时比较最终指标和单批次过程指标。
    comparison = {
        "lowest_negative_rate": find_best(
            lambda result: result["final_metrics"].get("negative_rate")
        ),
        "lowest_question_rate": find_best(
            lambda result: result["final_metrics"].get("question_rate")
        ),
        "highest_accept_rate": find_best(
            lambda result: result["final_metrics"].get("accept_rate"),
            highest=True,
        ),
        "lowest_negative_peak_rate": find_best(
            lambda result: read_effect_metric(result, "negative_peak_rate")
        ),
        "lowest_negative_area": find_best(
            lambda result: read_effect_metric(result, "negative_area")
        ),
        "highest_emotion_recovery_rate": find_best(
            lambda result: read_effect_metric(
                result,
                "emotion_recovery_rate",
            ),
            highest=True,
        ),
        "longest_effect_duration": find_best(
            lambda result: read_effect_metric(result, "effect_duration"),
            highest=True,
        ),
        "lowest_rebound_rate": find_best(
            lambda result: read_effect_metric(result, "rebound_rate")
        ),
        "highest_negative_area_reduction": find_best(
            lambda result: read_control_metric(
                result,
                "negative_area_reduction",
            ),
            highest=True,
        ),
        "final_trends": {
            result["strategy"]: result["final_metrics"]["global_trend"]
            for result in successful
        },
    }
    # 2026/08/24 增量评论稳定补齐，修改功能：对照结果显式附带各场景质量，避免忽略大量兜底。
    comparison["data_quality"] = {
        result["strategy"]: result.get(
            "comment_quality",
            {"quality_status": "unknown"},
        )
        for result in successful
    }
    comparison["quality_warning_strategies"] = [
        result["strategy"]
        for result in successful
        if result.get("comment_quality", {}).get("quality_status")
        not in {None, "normal"}
    ]
    return comparison


# 2026/08/23 内容策略对照，修改功能：读取批次声明快照并汇总全部内容策略场景。
def run_experiment(
    experiment_id,
    experiment_dir,
    event_file,
    comment_pool_file,
    official_response_file=OFFICIAL_RESPONSE_FILE,
):
    """使用当前批次的独立输入运行官方内容策略对照实验。"""
    # 2026/09/04 Demo性能基线，新增功能：记录实验编排、共享基线和各策略的墙钟耗时。
    experiment_start_time = time.perf_counter()
    experiment_dir = Path(experiment_dir)
    event_file = Path(event_file)
    comment_pool_file = Path(comment_pool_file)
    official_response_file = Path(official_response_file)
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"实验目录不存在：{experiment_dir}")
    if not event_file.is_file():
        raise FileNotFoundError(f"事件快照不存在：{event_file}")
    if not comment_pool_file.is_file():
        raise FileNotFoundError(f"本批次评论池不存在：{comment_pool_file}")
    if not official_response_file.is_file():
        raise FileNotFoundError(
            f"本批次官方内容策略不存在：{official_response_file}"
        )

    event_input = load_json(event_file)
    response_options = load_official_response_options(
        official_response_file,
        event_input["event_id"],
    )
    entry_strategy = response_options["entry_strategy"]

    # 2026/08/23 内容策略对照，修改功能：先运行不回应基线，再运行四个官方内容场景。
    scenarios = [(NO_RESPONSE_SCENARIO, "no_response")]
    scenarios.extend(
        (content_strategy, entry_strategy)
        for content_strategy in response_options["content_strategies"]
    )

    # 2026/08/25 第八次联调问题修复，新增功能：只运行一次官方进场前基线供全部场景复制。
    shared_baseline = None
    baseline_error = None
    print("正在运行官方进场前共享基线……")
    baseline_start_time = time.perf_counter()
    try:
        shared_baseline = run_shared_pre_entry_baseline(
            entry_strategy,
            event_input,
            experiment_dir,
            event_file,
            comment_pool_file,
            stagnation_rounds=response_options["stagnation_rounds"],
            improvement_tolerance=response_options[
                "negative_rate_improvement_tolerance"
            ],
        )
        if shared_baseline["entry_triggered"]:
            print(
                f"官方动态进场将在第 {shared_baseline['response_step']} 轮触发，"
                f"原因：{shared_baseline['entry_reason']}。"
            )
        else:
            print(
                "共享基线运行结束后仍未触发官方进场，"
                "回应策略将标记为未运行。"
            )
    except Exception as error:
        baseline_error = f"共享基线运行失败：{error}"
    baseline_duration = time.perf_counter() - baseline_start_time
    if shared_baseline is not None:
        baseline_duration = shared_baseline.get("performance", {}).get(
            "duration_seconds",
            baseline_duration,
        )

    strategy_results = []
    for content_strategy, scenario_entry_strategy in scenarios:
        strategy_id = content_strategy["strategy_id"]
        print(
            f"正在运行实验场景：{strategy_id} "
            f"({content_strategy['strategy_name']})"
        )
        strategy_start_time = time.perf_counter()
        try:
            if baseline_error:
                raise RuntimeError(baseline_error)
            result = run_one_content_strategy(
                content_strategy,
                scenario_entry_strategy,
                event_input,
                experiment_dir,
                event_file,
                comment_pool_file,
                shared_baseline,
            )
            if result.get("status") == "not_run":
                print(
                    f"实验场景 {strategy_id} 未运行："
                    "官方动态进场条件未触发。"
                )
        except Exception as error:
            # 2026/08/26 第九次联调问题修复，新增功能：场景失败时在控制台输出单行错误摘要。
            print(f"实验场景 {strategy_id} 失败：{summarize_scenario_error(error)}")
            result = {
                "strategy": strategy_id,
                "strategy_name": content_strategy["strategy_name"],
                "entry_strategy": scenario_entry_strategy,
                "status": "failed",
                "error": str(error),
                "performance": {
                    **summarize_step_performance([]),
                    "duration_seconds": round(
                        time.perf_counter() - strategy_start_time,
                        3,
                    ),
                },
            }
            # 2026/08/22 系统重置与状态初始化，新增功能：失败策略也保存统一的场景结果文件。
            scenario_dir = experiment_dir / strategy_id
            scenario_dir.mkdir(parents=True, exist_ok=True)
            save_json(scenario_dir / "scenario_result.json", result)
        strategy_results.append(result)

    # 2026/08/27 舆情指标计算扩充，新增功能：场景全部完成后计算相对不回应基线的净效果。
    attach_control_net_effect_metrics(strategy_results, experiment_dir)

    success_count = sum(
        result.get("status") == "success" for result in strategy_results
    )
    # 2026/08/27 第十二次联调修复，新增功能：失败与未运行场景分别计数，避免把未进场误报为失败或成功。
    not_run_count = sum(
        result.get("status") == "not_run" for result in strategy_results
    )
    failed_count = sum(
        result.get("status") == "failed" for result in strategy_results
    )
    entry_triggered = bool(
        shared_baseline and shared_baseline.get("entry_triggered")
    )
    if failed_count:
        experiment_status = "partial_failed" if success_count else "failed"
    elif not_run_count:
        experiment_status = "completed_no_entry"
    elif success_count == len(strategy_results):
        experiment_status = "completed"
    else:
        experiment_status = "failed"

    if baseline_error or (entry_triggered and failed_count == len(strategy_results)):
        comparison_status = "failed"
    elif not entry_triggered:
        comparison_status = "not_evaluable"
    elif failed_count:
        comparison_status = "partial"
    else:
        comparison_status = "completed"

    # 2026/08/27 第十二次联调修复，修改功能：只有真实触发进场后才计算内容策略对照结果。
    comparison = (
        compare_strategy_results(strategy_results)
        if entry_triggered
        else {}
    )
    performance = build_experiment_performance(
        shared_baseline=shared_baseline,
        strategy_results=strategy_results,
        experiment_duration=time.perf_counter() - experiment_start_time,
        baseline_duration=baseline_duration,
    )

    experiment_result = {
        "experiment_id": experiment_id,
        "event_id": event_input["event_id"],
        "entry_strategy": entry_strategy,
        "status": experiment_status,
        "strategy_count": len(strategy_results),
        "success_count": success_count,
        "not_run_count": not_run_count,
        "failed_count": failed_count,
        "entry_triggered": entry_triggered,
        "entry_reason": (
            shared_baseline.get("entry_reason")
            if shared_baseline is not None
            else None
        ),
        "comparison_status": comparison_status,
        "strategy_results": strategy_results,
        "comparison": comparison,
        "performance": performance,
    }
    if shared_baseline is not None:
        experiment_result["shared_baseline"] = {
            "completed_step": shared_baseline["completed_step"],
            "response_step": shared_baseline["response_step"],
            "entry_triggered": shared_baseline["entry_triggered"],
            "entry_reason": shared_baseline["entry_reason"],
            "stagnant_round_count": shared_baseline[
                "stagnant_round_count"
            ],
            "state_dir": str(shared_baseline["state_dir"]),
            "performance": shared_baseline["performance"],
        }
    result_file = experiment_dir / "experiment_result.json"
    save_json(result_file, experiment_result)
    print(f"实验完成，结果保存在：{result_file}")
    return experiment_result


if __name__ == "__main__":
    print("请运行 python demo/main.py 启动完整模拟实验。")
