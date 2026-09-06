"""按照真实时间线运行单一历史舆情场景。"""

from pathlib import Path

from runtime_paths import DEMO_DIR  # noqa: F401

from simulation.event_state_updater import append_event_state_record
from experiment_runner import (
    calculate_scenario_propagation_summary,
    load_round_result,
    prepare_scenario_state,
    run_simulation_step,
    summarize_comment_quality,
)
from infrastructure.json_storage import load_json, save_json
from timeline_service import (
    get_official_state_for_step,
    get_step_period,
    load_official_response_timeline,
)


# 2026/09/02 历史趋势复现，新增功能：在固定轮次更新官方信息并连续运行同一场景。
def run_historical_replay(
    experiment_id,
    experiment_dir,
    event_file,
    comment_pool_file,
    timeline_file,
):
    """运行固定历史路线，输出每轮指标、通告记录和数据质量。"""
    experiment_dir = Path(experiment_dir)
    event_file = Path(event_file)
    comment_pool_file = Path(comment_pool_file)
    timeline_file = Path(timeline_file)
    _validate_input_files(
        experiment_dir,
        event_file,
        comment_pool_file,
        timeline_file,
    )

    event_input = load_json(event_file)
    event_id = event_input.get("event_id")
    timeline = load_official_response_timeline(timeline_file, event_id)
    scenario_dir, state_dir = prepare_scenario_state(
        experiment_dir,
        "historical_replay",
        event_id,
    )
    state_file = state_dir / "event_state_history.json"
    rounds = []
    quality_records = []
    official_update_records = []

    for step in range(1, timeline["total_steps"] + 1):
        official_state = get_official_state_for_step(timeline, step)
        if step > 1:
            append_event_state_record(
                event_input=event_input,
                official_statement=official_state["official_statement"],
                official_statement_status=official_state[
                    "official_statement_status"
                ],
                state_file=state_file,
            )

        if official_state["is_update_step"]:
            official_update_records.append(
                _build_official_update_record(timeline, step)
            )

        run_simulation_step(state_dir, event_file, comment_pool_file)
        round_result, comment_quality = load_round_result(
            state_dir,
            event_id,
            step,
        )
        round_result.update(get_step_period(timeline, step))
        round_result["official_statement_timing"] = {
            "introduced_step": official_state["introduced_step"],
            "is_new": official_state["is_update_step"],
        }
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
    save_json(scenario_dir / "historical_replay_result.json", result)
    save_json(experiment_dir / "historical_replay_result.json", result)
    return result


def _validate_input_files(
    experiment_dir,
    event_file,
    comment_pool_file,
    timeline_file,
):
    """在创建状态目录前检查历史批次输入是否完整。"""
    if not experiment_dir.is_dir():
        raise FileNotFoundError(f"实验目录不存在：{experiment_dir}")
    for label, path in (
        ("事件快照", event_file),
        ("评论池快照", comment_pool_file),
        ("官方信息时间线", timeline_file),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label}不存在：{path}")


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
