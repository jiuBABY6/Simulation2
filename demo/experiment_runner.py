"""运行并比较三种官方回应方案与一组不回应基线。

本模块只负责编排实验。三种可配置回应方案与不回应基线使用相同的动态进场规则
和独立状态目录，具体评论生成、Agent 决策和指标统计继续由
simulation/runner.py 完成。
"""

import time
from pathlib import Path

from application.round_results import (
    calculate_scenario_propagation_summary as _calculate_propagation_summary,
    extract_policy_metrics as _extract_policy_metrics,
    load_round_result as _load_round_result,
    load_step_comment_quality as _load_step_comment_quality,
    load_step_metrics as _load_step_metrics,
    summarize_comment_quality as _summarize_comment_quality,
)
from application.error_summary import (
    summarize_scenario_error as _summarize_scenario_error,
)
from application.runtime_config import DEFAULT_SIMULATION_RUNTIME
from application.scenario_state import (
    prepare_scenario_state as _prepare_scenario_state,
)
from application.step_executor import (
    SimulationStepRequest,
    SubprocessSimulationStepExecutor,
    parse_simulation_step_result as _parse_simulation_step_result,
)
from simulation.event_state_updater import append_event_state_record
from agents.persona_repository import load_personas
from infrastructure.json_storage import (
    load_json,
    read_jsonl,
    save_json,
)
from infrastructure.llm_service import merge_llm_performance_stats
from evaluation.metrics import (
    calculate_control_net_effect,
    calculate_effect_duration,
    calculate_emotion_recovery_rate,
    calculate_negative_peak_and_area,
    calculate_rebound_rate,
)
from project_config import (
    DEMO_DIR,
    OFFICIAL_RESPONSE_FILE,
    SOCIAL_NETWORK_CONFIG_FILE,
)
from simulation.social_network import build_fixed_social_network
from simulation.options import get_simulation_options
from simulation.counterfactual_controls import (
    CounterfactualIsolationError,
    audit_cross_scenario_controls,
    audit_scenario_isolation,
    build_scenario_input_sha256,
    build_shared_input_manifest,
    build_state_snapshot_manifest,
    objective_state_fields,
)


# 回应方案对照与历史复现共用的单轮参数集中在 application/runtime_config.py。
MAX_STEPS = 10
MAX_AGENTS = DEFAULT_SIMULATION_RUNTIME.max_agents
MAX_WORKERS = DEFAULT_SIMULATION_RUNTIME.max_workers
# 2026/10/19，修改功能：回应方案对照减少每轮外生LLM评论；历史复现
# 仍读取共享运行配置中的 incremental_comment_count=20。两条路径通过
# 显式配置字段分离，避免修改全局常量时意外改变历史实验。
INCREMENTAL_COMMENT_COUNT = (
    DEFAULT_SIMULATION_RUNTIME.strategy_incremental_comment_count
)
RANDOM_SEED = DEFAULT_SIMULATION_RUNTIME.random_seed
# 2026/08/25 第八次联调问题修复，修改功能：提高评论生成多样性，减少确定性重复文本。
COMMENT_TEMPERATURE = DEFAULT_SIMULATION_RUNTIME.comment_temperature

# 官方回应的触发阈值。
NEGATIVE_RATE_THRESHOLD = 0.5

# 2026/08/23 内容策略对照，修改功能：内容场景共用一个已有的动态进场规则。
ENTRY_STRATEGIES = (
    "negative_threshold",
    "global_worsening",
    "combined_policy",
)
# 2026/10/16，修改功能：实验固定比较三个用户自定义回应方案，
# 但不限定方案名称和内容类型。不回应基线由系统单独补充。
RESPONSE_PLAN_COUNT = 3
OFFICIAL_STATEMENT_STATUSES = (
    "clear",
    "incomplete",
    "conflict",
)
OFFICIAL_EVIDENCE_DIMENSIONS = {
    "verified_fact",
    "completed_action",
    "accountability",
    "empathy",
    "unresolved_process",
    "rumor_control",
}
# 2026/08/23 内容策略对照，新增功能：保留不发布官方声明的独立实验基线。
NO_RESPONSE_SCENARIO = {
    "strategy_id": "no_response",
    "strategy_name": "不回应",
    "official_statement": "",
    "official_statement_status": "none",
}


def parse_simulation_step_result(output):
    """兼容旧调用；实现已下沉到共享应用层。"""
    return _parse_simulation_step_result(output)


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
# 2026/10/16，修改功能：取消四种固定类型的编号约束，仅校验
# “三个唯一、完整、可执行的回应方案”，使新事件可直接替换方案。
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
    if (
        not isinstance(raw_strategies, list)
        or len(raw_strategies) != RESPONSE_PLAN_COUNT
    ):
        raise ValueError(
            "content_strategies 必须恰好包含 "
            f"{RESPONSE_PLAN_COUNT} 个回应方案。"
        )

    strategies = []
    strategy_ids = set()
    for index, item in enumerate(raw_strategies, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个内容策略必须是 JSON 对象。")

        strategy_id = str(item.get("strategy_id", "")).strip()
        strategy_name = str(item.get("strategy_name", "")).strip()
        statement = str(item.get("official_statement", "")).strip()
        statement_status = item.get("official_statement_status")
        raw_dimensions = item.get("evidence_dimensions", {})
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
        if not isinstance(raw_dimensions, dict):
            raise ValueError(
                f"内容策略 {strategy_id} 的 evidence_dimensions 必须是对象。"
            )
        unknown_dimensions = set(raw_dimensions) - OFFICIAL_EVIDENCE_DIMENSIONS
        if unknown_dimensions or any(
            not isinstance(value, bool) for value in raw_dimensions.values()
        ):
            raise ValueError(
                f"内容策略 {strategy_id} 的 evidence_dimensions 不合法："
                f"{sorted(unknown_dimensions)}"
            )

        strategy_ids.add(strategy_id)
        strategies.append(
            {
                "strategy_id": strategy_id,
                "strategy_name": strategy_name,
                "official_statement": statement,
                "official_statement_status": statement_status,
                "evidence_dimensions": {
                    key: bool(raw_dimensions.get(key, False))
                    for key in sorted(OFFICIAL_EVIDENCE_DIMENSIONS)
                },
            }
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
def extract_policy_metrics(round_metrics, negative_rate_basis="agent_internal"):
    """提取策略指标，并显式记录负面率的观测对象和分母。

    回应方案对照继续使用 ``agent_internal``，保持进场和方案比较语义；历史
    趋势复现显式传入 ``agent_expression``，用 Agent 实际发表的评论与真实
    评论比较。通过参数隔离两类实验，避免历史口径修正悄然改变回应方案对照。
    """
    return _extract_policy_metrics(round_metrics, negative_rate_basis)


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


# 2026/08/22 系统重置与状态初始化 修改功能：使用统一状态管理器创建策略状态目录。
# 2026/08/25 第八次联调问题修复，修改功能：场景可从统一的进场前状态快照开始运行。
def prepare_scenario_state(
    experiment_dir,
    strategy_name,
    event_id,
    baseline_state_dir=None,
    initial_state_context=None,
):
    """兼容旧调用；共享状态编排由应用层统一实现。"""
    return _prepare_scenario_state(
        experiment_dir,
        strategy_name,
        event_id,
        baseline_state_dir,
        initial_state_context,
    )


# 2026/9/5，社交网络传播，新增功能：实验开始前生成五个策略共同使用的固定网络快照。
def prepare_experiment_social_network(experiment_dir, max_agents=MAX_AGENTS):
    """生成并保存本实验唯一的社交网络快照。"""
    network_file = Path(experiment_dir) / "social_network_snapshot.json"
    if network_file.exists():
        raise FileExistsError(f"社交网络快照已经存在：{network_file}")
    personas = load_personas(max_count=max_agents)
    if not personas:
        raise RuntimeError("没有可用于构建社交网络的Persona。")
    network_config = load_json(SOCIAL_NETWORK_CONFIG_FILE)
    social_network = build_fixed_social_network(personas, network_config)
    save_json(network_file, social_network)
    return network_file


# 2026/08/22 系统重置与状态初始化，修改功能：向仿真子进程传递本批次独立输入路径。
def run_simulation_step(
    state_dir,
    event_file,
    comment_pool_file,
    social_network_file=None,
    incremental_comment_count=INCREMENTAL_COMMENT_COUNT,
):
    """兼容旧调用；由可替换的单轮执行器封装子进程协议。"""
    request = SimulationStepRequest(
        state_dir=Path(state_dir),
        event_file=Path(event_file),
        comment_pool_file=Path(comment_pool_file),
        social_network_file=(
            Path(social_network_file) if social_network_file is not None else None
        ),
        incremental_comment_count=incremental_comment_count,
        max_agents=MAX_AGENTS,
        max_workers=MAX_WORKERS,
        random_seed=RANDOM_SEED,
        comment_temperature=COMMENT_TEMPERATURE,
        demo_dir=DEMO_DIR,
    )
    return SubprocessSimulationStepExecutor().run(request)


# 2026/08/26 第九次联调问题修复，新增功能：提取适合控制台显示的简短场景错误。
def summarize_scenario_error(error, max_length=160):
    """兼容旧调用；控制台错误格式由共享应用层统一维护。"""
    return _summarize_scenario_error(error, max_length)


def load_step_metrics(metrics_file, event_id, step):
    """兼容旧调用；从共享结果读取器加载指标。"""
    return _load_step_metrics(metrics_file, event_id, step)


# 2026/08/24 增量评论稳定补齐，新增功能：读取指定轮次的评论来源统计和数据质量状态。
# 2026/09/04 增量评论生成架构优化，修改功能：向场景结果传递首轮请求、统一补齐和生成波次统计。
# 2026/09/04 评论质量与耗时平衡，修改功能：传递质量目标和自适应救援请求统计。
def load_step_comment_quality(incremental_file, event_id, step):
    """兼容旧调用；从共享结果读取器加载评论质量。"""
    return _load_step_comment_quality(incremental_file, event_id, step)


# 2026/08/24 增量评论稳定补齐，新增功能：汇总一个实验场景全部轮次的评论数据质量。
# 2026/09/04 增量评论生成架构优化，修改功能：汇总业务层评论请求数，便于和性能基线直接比较。
# 2026/09/04 评论质量与耗时平衡，修改功能：汇总自适应救援请求数量。
def summarize_comment_quality(quality_records):
    """兼容旧调用；评论质量汇总由共享结果服务完成。"""
    return _summarize_comment_quality(quality_records)


# 2026/08/25 第八次联调问题修复，新增功能：统一读取共享基线和独立场景的单轮结果。
def load_round_result(
    state_dir,
    event_id,
    step,
    negative_rate_basis="agent_internal",
):
    """兼容旧调用；共享结果服务保持返回结构不变。"""
    return _load_round_result(
        state_dir,
        event_id,
        step,
        negative_rate_basis=negative_rate_basis,
    )


# 2026/9/5，社交网络传播第二阶段A，新增功能：汇总一个场景的累计传播覆盖和深度。
def calculate_scenario_propagation_summary(state_dir, event_id):
    """兼容旧调用；传播汇总由共享结果服务完成。"""
    return _calculate_propagation_summary(state_dir, event_id)


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
    social_network_file=None,
    stagnation_rounds=0,
    improvement_tolerance=0.05,
    incremental_comment_count=INCREMENTAL_COMMENT_COUNT,
    shared_input_manifest=None,
):
    """在无声明状态下运行到首次触发进场，并返回可复制的状态快照。"""
    # 2026/09/04 Demo性能基线，新增功能：记录共享基线墙钟耗时和每个实际执行时间步的性能。
    baseline_start_time = time.perf_counter()
    shared_input_manifest = shared_input_manifest or {
        "shared_input_sha256": None,
        "objective_fact_timeline": [],
    }
    objective_timeline = shared_input_manifest.get(
        "objective_fact_timeline", []
    )
    initial_state_context = {
        **objective_state_fields(objective_timeline, 1),
        # 2026/10/20，新增功能：进场前状态明确属于共同基线；场景
        # 分叉后会换成各自scenario_id，但共同输入哈希保持不变。
        "scenario_id": "_shared_baseline",
    }
    if shared_input_manifest.get("shared_input_sha256"):
        initial_state_context["shared_input_sha256"] = (
            shared_input_manifest["shared_input_sha256"]
        )
    _, state_dir = prepare_scenario_state(
        experiment_dir,
        "_shared_baseline",
        event_input["event_id"],
        initial_state_context=initial_state_context,
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
            social_network_file,
            incremental_comment_count,
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
            **objective_state_fields(objective_timeline, step + 1),
            scenario_id="_shared_baseline",
            shared_input_sha256=shared_input_manifest.get(
                "shared_input_sha256"
            ),
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
    social_network_file=None,
    incremental_comment_count=INCREMENTAL_COMMENT_COUNT,
    shared_input_manifest=None,
    baseline_snapshot_manifest=None,
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
            "official_evidence_dimensions": content_strategy.get(
                "evidence_dimensions", {}
            ),
        }
        if is_response_scenario
        else {
            "official_statement": "",
            "official_statement_status": "none",
            "official_evidence_dimensions": {},
        }
    )
    # 2026/10/20，修改功能：每个方案从共同快照独立生成通告后的公众
    # 反应。共同输入只包含事件、初始评论、网络和客观事实时间线。
    shared_input_manifest = shared_input_manifest or build_shared_input_manifest(
        event_input,
        event_file,
        comment_pool_file,
        social_network_file,
    )
    baseline_snapshot_manifest = (
        baseline_snapshot_manifest
        or build_state_snapshot_manifest(shared_baseline["state_dir"])
    )
    shared_input_sha256 = shared_input_manifest["shared_input_sha256"]
    objective_timeline = shared_input_manifest.get(
        "objective_fact_timeline", []
    )
    scenario_input_sha256 = build_scenario_input_sha256(
        shared_input_sha256,
        strategy_id,
        active_response,
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
            "propagation_summary": calculate_scenario_propagation_summary(
                state_dir,
                event_input["event_id"],
            ),
            "shared_baseline_completed_step": shared_baseline[
                "completed_step"
            ],
            "state_dir": str(state_dir),
            "performance": performance,
            "counterfactual_controls": {
                "shared_input_sha256": shared_input_sha256,
                "pre_entry_snapshot_sha256": baseline_snapshot_manifest[
                    "snapshot_sha256"
                ],
                "scenario_input_sha256": scenario_input_sha256,
                "isolation_audit": {
                    "status": "not_applicable",
                    "checked_from_step": None,
                    "error_count": 0,
                    "errors": [],
                },
            },
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
            official_evidence_dimensions=active_response.get(
                "official_evidence_dimensions"
            ),
            **objective_state_fields(objective_timeline, response_step),
            scenario_id=strategy_id,
            shared_input_sha256=shared_input_sha256,
            state_file=state_file,
        )

    for step in range(response_step or (MAX_STEPS + 1), MAX_STEPS + 1):
        step_result = run_simulation_step(
            state_dir,
            event_file,
            comment_pool_file,
            social_network_file,
            incremental_comment_count,
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
            official_evidence_dimensions=active_response.get(
                "official_evidence_dimensions"
            ),
            **objective_state_fields(objective_timeline, step + 1),
            scenario_id=strategy_id,
            shared_input_sha256=shared_input_sha256,
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
    isolation_audit = audit_scenario_isolation(
        state_dir=state_dir,
        event_id=event_input["event_id"],
        scenario_id=strategy_id,
        response_step=response_step,
        shared_input_sha256=shared_input_sha256,
        objective_fact_timeline=objective_timeline,
        expected_response=active_response,
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
        "propagation_summary": calculate_scenario_propagation_summary(
            state_dir,
            event_input["event_id"],
        ),
        "shared_baseline_completed_step": shared_baseline["completed_step"],
        "state_dir": str(state_dir),
        "performance": performance,
        "counterfactual_controls": {
            "shared_input_sha256": shared_input_sha256,
            "pre_entry_snapshot_sha256": baseline_snapshot_manifest[
                "snapshot_sha256"
            ],
            "scenario_input_sha256": scenario_input_sha256,
            "isolation_audit": isolation_audit,
        },
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
    # 2026/9/5，社交网络传播第二阶段A，新增功能：并列展示各策略传播指标，不预设传播越广越好。
    comparison["propagation_metrics"] = {
        result["strategy"]: result.get("propagation_summary", {})
        for result in successful
    }
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
    incremental_comment_count = get_simulation_options(event_input)[
        "incremental_comment_count"
    ]
    response_options = load_official_response_options(
        official_response_file,
        event_input["event_id"],
    )
    entry_strategy = response_options["entry_strategy"]

    # 2026/9/5，社交网络传播，新增功能：先固化网络，再让共享基线和全部策略读取同一文件。
    social_network_file = prepare_experiment_social_network(experiment_dir)
    # 2026/10/20，新增功能：共同输入只包含不会被回应方案改变的内容。
    # SHA-256 在任何场景运行前生成，后续写入每个状态和评论批次供审计。
    shared_input_manifest = build_shared_input_manifest(
        event_input,
        event_file,
        comment_pool_file,
        social_network_file,
    )

    # 2026/10/16 回应方案对照：先运行不回应基线，再运行三个用户配置的回应方案。
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
            social_network_file,
            stagnation_rounds=response_options["stagnation_rounds"],
            improvement_tolerance=response_options[
                "negative_rate_improvement_tolerance"
            ],
            incremental_comment_count=incremental_comment_count,
            shared_input_manifest=shared_input_manifest,
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
    baseline_snapshot_manifest = (
        build_state_snapshot_manifest(shared_baseline["state_dir"])
        if shared_baseline is not None
        else None
    )
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
                social_network_file,
                incremental_comment_count,
                shared_input_manifest=shared_input_manifest,
                baseline_snapshot_manifest=baseline_snapshot_manifest,
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
            if isinstance(error, CounterfactualIsolationError):
                result["failure_type"] = "isolation_audit"
            # 2026/08/22 系统重置与状态初始化，新增功能：失败策略也保存统一的场景结果文件。
            scenario_dir = experiment_dir / strategy_id
            scenario_dir.mkdir(parents=True, exist_ok=True)
            save_json(scenario_dir / "scenario_result.json", result)
        strategy_results.append(result)

    # 2026/10/20，新增功能：各场景完成后统一验证状态目录、共同输入
    # 哈希和场景干预指纹，发现跨场景数据污染时实验不再标记为完成。
    cross_scenario_audit = None
    try:
        cross_scenario_audit = audit_cross_scenario_controls(strategy_results)
    except RuntimeError as error:
        cross_scenario_audit = {
            "status": "failed",
            "error": str(error),
        }

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
    isolation_failed = (
        cross_scenario_audit.get("status") == "failed"
        or any(
            result.get("failure_type") == "isolation_audit"
            for result in strategy_results
        )
    )
    if isolation_failed:
        experiment_status = "failed_isolation_audit"
    elif failed_count:
        experiment_status = "partial_failed" if success_count else "failed"
    elif not_run_count:
        experiment_status = "completed_no_entry"
    elif success_count == len(strategy_results):
        experiment_status = "completed"
    else:
        experiment_status = "failed"

    if isolation_failed:
        comparison_status = "failed"
    elif baseline_error or (
        entry_triggered and failed_count == len(strategy_results)
    ):
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
        "social_network_file": str(social_network_file),
        "comparison_status": comparison_status,
        "strategy_results": strategy_results,
        "comparison": comparison,
        "performance": performance,
        # 2026/10/19，新增功能：结果显式保存规范化后的运行选项，避免
        # 事件文件未填写默认值时无法还原实际增量评论数量。
        "simulation_options": get_simulation_options(event_input),
        # 2026/10/20，修改功能：共享的是客观输入，不再共享不回应
        # 场景生成的公众评论。公众反应和Agent表达在各方案内独立演化。
        "counterfactual_controls": {
            "version": shared_input_manifest["version"],
            "shared_input_sha256": shared_input_manifest[
                "shared_input_sha256"
            ],
            "components": shared_input_manifest["components"],
            "objective_fact_timeline_sha256": shared_input_manifest[
                "components"
            ]["objective_fact_timeline_sha256"],
            "objective_fact_steps": [
                item["step"]
                for item in shared_input_manifest[
                    "objective_fact_timeline"
                ]
            ],
            "pre_entry_snapshot_sha256": (
                baseline_snapshot_manifest["snapshot_sha256"]
                if baseline_snapshot_manifest is not None
                else None
            ),
            "public_reactions_shared": False,
            "scenario_reactions_independent": True,
            "cross_scenario_audit": cross_scenario_audit,
        },
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
