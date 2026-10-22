"""按照真实时间线运行单一历史舆情场景。"""

from pathlib import Path

if __package__:
    from .runtime_paths import DEMO_DIR  # noqa: F401
    from .public_context import (
        get_public_context_for_step,
        load_public_context_timeline,
    )
    from .run_manifest import save_historical_run_manifest
    from .timeline_service import (
        get_official_state_for_step,
        get_step_period,
        load_official_response_timeline,
    )
else:  # pragma: no cover - 保留直接脚本启动方式
    from runtime_paths import DEMO_DIR  # noqa: F401
    from public_context import (
        get_public_context_for_step,
        load_public_context_timeline,
    )
    from run_manifest import save_historical_run_manifest
    from timeline_service import (
        get_official_state_for_step,
        get_step_period,
        load_official_response_timeline,
    )

from application.round_results import (
    calculate_scenario_propagation_summary,
    load_round_result,
    summarize_comment_quality,
)
from application.runtime_config import DEFAULT_SIMULATION_RUNTIME
from application.scenario_state import prepare_scenario_state
from application.step_executor import (
    SimulationStepRequest,
    SubprocessSimulationStepExecutor,
)
from infrastructure.json_storage import load_json, save_json
from simulation.event_state_updater import append_event_state_record
from simulation.options import normalize_simulation_options


# 历史复现只负责历史时间线编排；单轮执行协议由共享应用层提供。
_STEP_EXECUTOR = SubprocessSimulationStepExecutor()


def _run_simulation_step(
    state_dir,
    event_file,
    comment_pool_file,
    incremental_comment_count,
):
    """使用与五策略实验一致的参数执行一轮，避免依赖其顶层脚本。"""

    return _STEP_EXECUTOR.run(
        SimulationStepRequest(
            state_dir=Path(state_dir),
            event_file=Path(event_file),
            comment_pool_file=Path(comment_pool_file),
            social_network_file=None,
            incremental_comment_count=incremental_comment_count,
            max_agents=DEFAULT_SIMULATION_RUNTIME.max_agents,
            max_workers=DEFAULT_SIMULATION_RUNTIME.max_workers,
            random_seed=DEFAULT_SIMULATION_RUNTIME.random_seed,
            comment_temperature=(
                DEFAULT_SIMULATION_RUNTIME.comment_temperature
            ),
            demo_dir=DEMO_DIR,
        )
    )


# 2026/09/02 历史趋势复现，新增功能：在固定轮次更新官方信息并连续运行同一场景。
def run_historical_replay(
    experiment_id,
    experiment_dir,
    event_file,
    comment_pool_file,
    timeline_file,
    public_context_file,
):
    """运行公众语境约束下的 LLM 历史回放，输出逐轮结果。"""
    experiment_dir = Path(experiment_dir)
    event_file = Path(event_file)
    comment_pool_file = Path(comment_pool_file)
    timeline_file = Path(timeline_file)
    public_context_file = Path(public_context_file)
    _validate_input_files(
        experiment_dir,
        event_file,
        comment_pool_file,
        timeline_file,
        public_context_file,
    )

    event_input = load_json(event_file)
    # 2026/10/8，新增功能：读取评论池中的校准元数据，只标记初始轮次，不向后续轮次注入真实趋势。
    comment_pool = load_json(comment_pool_file)
    initialization = comment_pool.get("initialization")
    if not isinstance(initialization, dict):
        raise ValueError("历史趋势复现必须包含第一轮人工初始化元数据。")
    calibrated_step = (
        initialization.get("calibrated_step")
        if isinstance(initialization, dict)
        else None
    )
    event_id = event_input.get("event_id")
    timeline = load_official_response_timeline(timeline_file, event_id)
    simulation_options = normalize_simulation_options(event_input)
    public_context_timeline = load_public_context_timeline(
        public_context_file,
        expected_event_id=event_id,
        expected_total_steps=timeline["total_steps"],
    )
    first_public_context = get_public_context_for_step(
        public_context_timeline, 1
    )
    scenario_dir, state_dir = prepare_scenario_state(
        experiment_dir,
        "historical_replay",
        event_id,
        initial_state_context=_build_state_context(
            first_public_context,
        ),
    )
    state_file = state_dir / "event_state_history.json"
    rounds = []
    quality_records = []
    official_update_records = []

    for step in range(1, timeline["total_steps"] + 1):
        official_state = get_official_state_for_step(timeline, step)
        public_context = get_public_context_for_step(
            public_context_timeline, step
        )
        if step > 1:
            append_event_state_record(
                event_input=event_input,
                official_statement=official_state["official_statement"],
                official_statement_status=official_state[
                    "official_statement_status"
                ],
                **_build_state_context(public_context),
                state_file=state_file,
            )

        if official_state["is_update_step"]:
            official_update_records.append(
                _build_official_update_record(timeline, step)
            )

        _run_simulation_step(
            state_dir,
            event_file,
            comment_pool_file,
            incremental_comment_count=simulation_options[
                "incremental_comment_count"
            ],
        )
        round_result, comment_quality = load_round_result(
            state_dir,
            event_id,
            step,
            # 2026/10/12，历史复现主观测口径修正：真实材料来自已发表
            # 评论，因此这里使用 Agent 实际表达，而不是内部情绪。
            negative_rate_basis="agent_expression",
        )
        round_result.update(get_step_period(timeline, step))
        round_result["official_statement_timing"] = {
            "introduced_step": official_state["introduced_step"],
            "is_new": official_state["is_update_step"],
        }
        round_result["is_calibration_point"] = step == calibrated_step
        round_result["public_context"] = public_context
        rounds.append(round_result)
        if comment_quality is not None:
            quality_records.append(comment_quality)

    result = {
        "experiment_id": experiment_id,
        "event_id": event_id,
        "mode": "historical_replay",
        "status": "completed",
        "step_count": len(rounds),
        "official_update_count": len(official_update_records),
        "official_updates": official_update_records,
        "initialization": initialization,
        "simulation_options": simulation_options,
        "public_context_enabled": True,
        "rounds": rounds,
        "final_metrics": rounds[-1]["policy_metrics"],
        "comment_quality": summarize_comment_quality(quality_records),
        # 2026/9/5，社交网络传播第二阶段A，新增功能：历史复现结果同步输出累计传播指标。
        "propagation_summary": calculate_scenario_propagation_summary(
            state_dir,
            event_id,
        ),
        "state_dir": str(state_dir),
    }
    # 2026/10/14，新增功能：记录本次实际使用的输入、代码、模型和 Persona
    # 指纹；API Key 不进入可重复性清单。
    run_manifest = save_historical_run_manifest(
        experiment_dir,
        state_dir,
        {
            "event_input": event_file,
            "comment_pool": comment_pool_file,
            "official_response_timeline": timeline_file,
            "public_context_timeline": public_context_file,
            "initial_opinion": experiment_dir / "initial_opinion.json",
        },
    )
    result["run_manifest"] = {
        "mechanism_version": run_manifest["mechanism_version"],
        "core_code_fingerprint": run_manifest["core_code_fingerprint"],
        "persona_set_fingerprint": run_manifest["persona_set_fingerprint"],
        "model": run_manifest["model"],
        "agent_decision_temperature": run_manifest[
            "agent_decision_temperature"
        ],
    }
    save_json(scenario_dir / "historical_replay_result.json", result)
    save_json(experiment_dir / "historical_replay_result.json", result)
    return result


def _validate_input_files(
    experiment_dir,
    event_file,
    comment_pool_file,
    timeline_file,
    public_context_file,
):
    """在创建状态目录前检查历史批次输入是否完整。"""
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"实验目录不存在：{experiment_dir}")
    for label, path in (
        ("事件快照", event_file),
        ("评论池快照", comment_pool_file),
        ("官方信息时间线", timeline_file),
        ("逐轮公众语境", public_context_file),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}不存在：{path}")


def _build_state_context(public_context):
    """把本轮历史公众语境和运行模式写入状态层。"""

    # 2026/10/10，修改功能：历史入口显式标记运行模式；逐轮公众语境
    # 只作为当轮可见信息，由 LLM 自主选择允许的离散状态。
    context = {
        "simulation_mode": "historical_replay",
        "public_context": public_context,
        "public_context_timing": {
            "step": public_context["step"],
            "period": public_context["period"],
            "phase": public_context["phase"],
        },
    }
    return context


def _build_official_update_record(timeline, step):
    """提取本轮首次投入的官方信息，写入复现结果。"""
    update = next(
        item for item in timeline["official_updates"] if item["step"] == step
    )
    return {
        "step": step,
        "published_at": update["published_at"],
        "official_statement": update["official_statement"],
        "official_statement_status": update[
            "official_statement_status"
        ],
        "source_url": update.get("source_url", ""),
    }
# 文件结束；保留显式标记以避免格式化工具追加多余空行。
