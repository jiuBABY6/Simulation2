"""Step-wise web control API for Simulation2.

The controller drives the existing single-step simulation runner one round at
a time and keeps a small control file plus rollback checkpoints inside the
experiment directory. It is designed for a future web/backend layer and does
not reimplement comment generation, agent decisions, or metric formulas.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from comments.pool_generator import generate_comment_pool
from experiment_runner import (
    CUSTOM_CONTENT_STRATEGY_ID,
    MAX_STEPS,
    NO_RESPONSE_SCENARIO,
    calculate_strategy_effect_metrics,
    evaluate_response_entry,
    extract_policy_metrics,
    is_custom_statement_ready,
    load_round_result,
    prepare_scenario_state,
    resolve_entry_timing,
    resolve_official_response_options,
    run_experiment,
    run_simulation_step,
    summarize_comment_quality,
    summarize_step_performance,
)
from infrastructure.json_storage import load_json, read_jsonl, save_json
from project_config import (
    COMMENT_POOL_SIZE,
    COMMENT_PROFILE_FILE,
    EVENT_FILE,
    OFFICIAL_RESPONSE_FILE,
)
from simulation.batch_manager import prepare_simulation_batch
from simulation.event_context import resolve_event_input
from simulation.event_state_updater import append_event_state_record


CONTROL_FILE_NAME = "web_control.json"
CHECKPOINT_DIR_NAME = ".web_checkpoints"
ALL_STRATEGIES_ID = "__all__"
_LOCK = threading.RLock()


def resolve_announcement_timeline(announcement_timeline_input=None):
    """规范化任意轮次公告时间线。"""
    if announcement_timeline_input is None:
        return []
    if isinstance(announcement_timeline_input, dict) and isinstance(
        announcement_timeline_input.get("events"), list
    ):
        announcement_timeline_input = announcement_timeline_input["events"]
    if not isinstance(announcement_timeline_input, list):
        raise ValueError("announcement_timeline_input 必须是公告事件列表。")

    allowed_statuses = {"clear", "incomplete", "conflict", "none"}
    normalized = []
    seen_rounds = set()
    for index, item in enumerate(announcement_timeline_input, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个公告事件必须是 JSON 对象。")
        round_no = item.get("round")
        statement = str(item.get("official_statement", "")).strip()
        status = item.get("official_statement_status")
        if (
            isinstance(round_no, bool)
            or not isinstance(round_no, int)
            or not 2 <= round_no <= MAX_STEPS
        ):
            raise ValueError(
                f"公告轮次必须是 2 到 {MAX_STEPS} 之间的整数。"
            )
        if round_no in seen_rounds:
            raise ValueError(f"同一轮次不能发布多条公告：{round_no}")
        if not statement:
            raise ValueError(f"第 {round_no} 轮公告内容不能为空。")
        if status not in allowed_statuses or status == "none":
            raise ValueError(
                f"第 {round_no} 轮公告状态必须是 clear、incomplete 或 conflict。"
            )
        seen_rounds.add(round_no)
        normalized.append(
            {
                "round": round_no,
                "official_statement": statement,
                "official_statement_status": status,
            }
        )
    normalized.sort(key=lambda event: event["round"])
    return normalized


def _experiment_dir(experiment_id: str) -> Path:
    from project_config import EXPERIMENT_DIR

    if (
        not experiment_id
        or Path(experiment_id).name != experiment_id
        or experiment_id in {".", ".."}
    ):
        raise ValueError("实验编号不合法")
    candidate = (EXPERIMENT_DIR / experiment_id).resolve()
    if EXPERIMENT_DIR.resolve() not in candidate.parents:
        raise ValueError("实验编号不合法")
    return candidate


def _control_file(experiment_dir: Path) -> Path:
    return experiment_dir / CONTROL_FILE_NAME


def _load_control(experiment_dir: Path) -> dict:
    control = load_json(_control_file(experiment_dir))
    if not isinstance(control, dict):
        raise ValueError(f"控制文件损坏：{_control_file(experiment_dir)}")
    return control


def _save_control(experiment_dir: Path, control: dict) -> None:
    save_json(_control_file(experiment_dir), control)


def _assert_inside_experiment(experiment_dir: Path, path: Path) -> Path:
    resolved = path.resolve()
    root = experiment_dir.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"路径超出实验目录：{resolved}")
    return resolved


def _checkpoint_dir(experiment_dir: Path) -> Path:
    return experiment_dir / CHECKPOINT_DIR_NAME


def _snapshot_state_dir(experiment_dir: Path, state_dir: Path, sequence: int) -> Path:
    state_dir = _assert_inside_experiment(experiment_dir, state_dir)
    if not state_dir.is_dir():
        raise FileNotFoundError(f"待快照状态目录不存在：{state_dir}")
    target = _checkpoint_dir(experiment_dir) / f"{sequence:04d}"
    if target.exists():
        # 失败重试或暂停后继续时可能复用同一序号，重建该步开始前的快照。
        target = _assert_inside_experiment(experiment_dir, target)
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(state_dir, target)
    return target


def _prune_checkpoints(experiment_dir: Path, keep_sequence: int) -> None:
    """删除回滚后不再需要的检查点，避免后续同序号快照冲突。"""
    checkpoint_root = _checkpoint_dir(experiment_dir)
    if not checkpoint_root.is_dir():
        return
    for path in checkpoint_root.iterdir():
        if not path.is_dir() or not path.name.isdigit():
            continue
        sequence = int(path.name)
        if sequence <= keep_sequence:
            continue
        path = _assert_inside_experiment(experiment_dir, path)
        shutil.rmtree(path)


def _remove_scenario_dir(experiment_dir: Path, strategy_id: str) -> None:
    scenario_dir = _assert_inside_experiment(
        experiment_dir, experiment_dir / strategy_id
    )
    if scenario_dir.is_dir():
        shutil.rmtree(scenario_dir)


def _remove_experiment_file(experiment_dir: Path, file_path: Path) -> None:
    file_path = _assert_inside_experiment(experiment_dir, file_path)
    if file_path.is_file():
        file_path.unlink()


def _replace_event_state(
    state_dir: Path,
    event_id: str,
    round_no: int,
    official_statement: str,
    official_statement_status: str,
) -> None:
    """替换指定轮次的事件状态，用于暂停时补发/修改公告。"""
    state_file = state_dir / "event_state_history.json"
    records = load_json(state_file)
    if not isinstance(records, list):
        raise ValueError("event_state_history.json 不是状态数组。")
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("event_id") == event_id
            and record.get("step") == round_no
        ):
            record["official_statement"] = official_statement.strip()
            record["official_statement_status"] = official_statement_status
            save_json(state_file, records)
            return
    raise ValueError(f"状态目录中不存在第 {round_no} 轮事件状态。")


def _selected_strategy(official_options: dict, strategy_id: str) -> dict:
    if strategy_id == NO_RESPONSE_SCENARIO["strategy_id"]:
        return dict(NO_RESPONSE_SCENARIO)
    for item in official_options.get("content_strategies", []):
        if item["strategy_id"] == strategy_id:
            return dict(item)
    raise ValueError(f"不支持的策略编号：{strategy_id}")


def _history_rounds(control: dict) -> list:
    return [
        item["round"]
        for item in control.get("history", [])
        if isinstance(item.get("round"), dict)
    ]


def _history_quality(control: dict) -> list:
    return [
        item["comment_quality"]
        for item in control.get("history", [])
        if isinstance(item.get("comment_quality"), dict)
    ]


def _active_response(strategy: dict) -> dict:
    if strategy.get("strategy_id") == NO_RESPONSE_SCENARIO["strategy_id"]:
        return {
            "official_statement": "",
            "official_statement_status": "none",
        }
    return {
        "official_statement": strategy.get("official_statement", ""),
        "official_statement_status": strategy.get(
            "official_statement_status",
            "none",
        ),
    }


def _timeline_event_at(control: dict, round_no: int):
    for event in control.get("announcement_timeline", []) or []:
        if event.get("round") == round_no:
            return event
    return None


def _timeline_latest_at(control: dict, round_no: int):
    latest = None
    for event in control.get("announcement_timeline", []) or []:
        if event.get("round") <= round_no:
            latest = event
    return latest


def _no_statement():
    return {
        "official_statement": "",
        "official_statement_status": "none",
    }


def _active_for_round(control: dict, strategy: dict, round_no: int) -> dict:
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        event = _timeline_event_at(control, round_no)
        if event:
            return {
                "official_statement": event.get("official_statement", ""),
                "official_statement_status": event.get(
                    "official_statement_status",
                    "none",
                ),
            }
        latest = _timeline_latest_at(control, round_no)
        if latest:
            return {
                "official_statement": latest.get(
                    "official_statement",
                    "",
                ),
                "official_statement_status": latest.get(
                    "official_statement_status",
                    "none",
                ),
            }
        return _no_statement()

    timing = control.get("entry_timing") or {}
    if timing.get("mode") == "fixed_round":
        if round_no >= timing.get("round", MAX_STEPS + 1):
            return _active_response(strategy)
        return _no_statement()
    return _active_response(strategy)


def _baseline_entry_decision(control: dict, round_result: dict) -> dict:
    policy_metrics = round_result.get("policy_metrics", {})
    entry_decision = evaluate_response_entry(
        control["entry_strategy"],
        policy_metrics,
        response_count=0,
        round_results=_history_rounds(control),
        stagnation_rounds=control.get("stagnation_rounds", 0),
        improvement_tolerance=control.get(
            "negative_rate_improvement_tolerance",
            0.05,
        ),
    )
    return entry_decision


def _begin_scenario(experiment_dir: Path, control: dict, event_input: dict) -> None:
    event_id = event_input["event_id"]
    strategy_id = control["selected_strategy_id"]
    strategy = _selected_strategy(
        load_json(experiment_dir / "official_response_options.json"),
        strategy_id,
    )
    if (
        strategy_id == CUSTOM_CONTENT_STRATEGY_ID
        and not is_custom_statement_ready(strategy)
    ):
        control["status"] = "not_run"
        control["phase"] = "completed"
        control["not_run_reason"] = "custom_statement_empty"
        return

    _, scenario_state_dir = prepare_scenario_state(
        experiment_dir,
        strategy_id,
        event_id,
        baseline_state_dir=Path(control["baseline_state_dir"]),
    )
    append_event_state_record(
        event_input=event_input,
        official_statement=_active_response(strategy)["official_statement"],
        official_statement_status=_active_response(strategy)[
            "official_statement_status"
        ],
        state_file=scenario_state_dir / "event_state_history.json",
    )
    control["scenario_state_dir"] = str(scenario_state_dir)
    control["strategy"] = strategy
    control["phase"] = "scenario"
    control["current_step"] = control["response_step"]


def _start_direct_scenario(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> None:
    """固定轮次/时间线模式：不跑基线，直接从第 1 轮运行所选策略。"""
    event_id = event_input["event_id"]
    strategy_id = control["selected_strategy_id"]
    strategy = _selected_strategy(
        load_json(experiment_dir / "official_response_options.json"),
        strategy_id,
    )
    if (
        strategy_id == CUSTOM_CONTENT_STRATEGY_ID
        and not is_custom_statement_ready(strategy)
    ):
        control["status"] = "not_run"
        control["phase"] = "completed"
        control["not_run_reason"] = "custom_statement_empty"
        return

    _, scenario_state_dir = prepare_scenario_state(
        experiment_dir,
        strategy_id,
        event_id,
    )
    control["scenario_state_dir"] = str(scenario_state_dir)
    control["strategy"] = strategy
    control["phase"] = "scenario"
    control["current_step"] = 1
    control["baseline_completed_step"] = 0
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        control["response_step"] = timeline[0]["round"]
        control["entry_reason"] = "announcement_timeline"
    else:
        timing = control.get("entry_timing") or {}
        control["response_step"] = timing.get("round")
        control["entry_reason"] = "custom_entry_round"


def _finalize_scenario(experiment_dir: Path, control: dict) -> None:
    strategy = control["strategy"]
    strategy_id = strategy["strategy_id"]
    scenario_dir = experiment_dir / strategy_id
    state_dir = Path(control["scenario_state_dir"])
    response_step = control.get("response_step")
    rounds = _history_rounds(control)
    effect_metrics = calculate_strategy_effect_metrics(
        rounds,
        state_dir,
        response_step,
    )
    step_results = [
        item.get("performance")
        for item in control.get("history", [])
        if item.get("phase") == "scenario"
        and isinstance(item.get("performance"), dict)
    ]
    performance = summarize_step_performance(step_results)
    performance["duration_seconds"] = round(
        time.time() - control.get("started_at", time.time()),
        3,
    )
    official_responses = []
    timeline = control.get("announcement_timeline", []) or []
    if timeline:
        for event in timeline:
            official_responses.append(
                {
                    "step": event["round"],
                    "strategy_id": strategy_id,
                    "strategy_name": strategy.get("strategy_name"),
                    "official_statement": event.get(
                        "official_statement",
                        "",
                    ),
                    "official_statement_status": event.get(
                        "official_statement_status",
                        "clear",
                    ),
                }
            )
    elif strategy_id != NO_RESPONSE_SCENARIO["strategy_id"]:
        official_responses.append(
            {
                "step": response_step,
                "strategy_id": strategy_id,
                "strategy_name": strategy.get("strategy_name"),
                **_active_response(strategy),
            }
        )
    result = {
        "strategy": strategy_id,
        "strategy_name": strategy.get("strategy_name"),
        "entry_strategy": control["entry_strategy"],
        "status": "success",
        "entry_triggered": True,
        "entry_reason": control.get("entry_reason"),
        "entry_timing": control.get("entry_timing"),
        "announcement_timeline": control.get(
            "announcement_timeline",
            [],
        ),
        "comparison_eligible": True,
        "official_responses": official_responses,
        "rounds": rounds,
        "final_metrics": rounds[-1].get("policy_metrics", {}),
        "effect_metrics": effect_metrics,
        "comment_quality": summarize_comment_quality(
            _history_quality(control)
        ),
        "shared_baseline_completed_step": control.get(
            "baseline_completed_step"
        ),
        "state_dir": str(state_dir),
        "performance": performance,
    }
    scenario_dir.mkdir(parents=True, exist_ok=True)
    save_json(scenario_dir / "scenario_result.json", result)
    control["scenario_result"] = result
    control["status"] = "completed"
    control["phase"] = "completed"


def _append_history(
    control: dict,
    sequence: int,
    checkpoint_path: Path,
    phase: str,
    step: int,
    round_result: dict,
    step_performance: dict | None,
    comment_quality: dict | None,
) -> None:
    state_dir = (
        control["baseline_state_dir"]
        if phase == "baseline"
        else control["scenario_state_dir"]
    )
    control.setdefault("history", []).append(
        {
            "sequence": sequence,
            "phase": phase,
            "step": step,
            "checkpoint": str(checkpoint_path),
            "checkpoint_state_dir": str(state_dir),
            "round": round_result,
            "performance": step_performance,
            "comment_quality": comment_quality,
        }
    )
    control["last_completed_step"] = step


def _advance_baseline(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> dict:
    state_dir = Path(control["baseline_state_dir"])
    sequence = control.get("sequence", 0) + 1
    step = control["current_step"]
    checkpoint = _snapshot_state_dir(experiment_dir, state_dir, sequence)
    step_result = run_simulation_step(
        state_dir,
        Path(control["event_file"]),
        Path(control["comment_pool_file"]),
    )
    round_result, comment_quality = load_round_result(
        state_dir,
        event_input["event_id"],
        step,
    )
    _append_history(
        control,
        sequence,
        checkpoint,
        "baseline",
        step,
        round_result,
        step_result,
        comment_quality,
    )
    control["sequence"] = sequence
    control["paused"] = True

    if step >= MAX_STEPS:
        control["status"] = "completed_no_entry"
        control["phase"] = "completed"
        return control

    entry_timing = control.get("entry_timing") or {}
    if entry_timing.get("mode") == "fixed_round":
        if entry_timing.get("round") == step + 1:
            entry_decision = {
                "should_enter": True,
                "entry_reason": "custom_entry_round",
                "stagnant_round_count": 0,
            }
        else:
            entry_decision = {
                "should_enter": False,
                "entry_reason": None,
                "stagnant_round_count": 0,
            }
    else:
        entry_decision = _baseline_entry_decision(control, round_result)
    control["stagnant_round_count"] = entry_decision.get(
        "stagnant_round_count",
        0,
    )
    if entry_decision["should_enter"]:
        control["response_step"] = step + 1
        control["entry_reason"] = entry_decision["entry_reason"]
        control["baseline_completed_step"] = step
        control["status"] = "running"
        _begin_scenario(experiment_dir, control, event_input)
        return control

    append_event_state_record(
        event_input=event_input,
        official_statement="",
        official_statement_status="none",
        state_file=state_dir / "event_state_history.json",
    )
    control["current_step"] = step + 1
    control["status"] = "running"
    return control


def _advance_scenario(
    experiment_dir: Path,
    control: dict,
    event_input: dict,
) -> dict:
    state_dir = Path(control["scenario_state_dir"])
    sequence = control.get("sequence", 0) + 1
    step = control["current_step"]
    checkpoint = _snapshot_state_dir(experiment_dir, state_dir, sequence)
    step_result = run_simulation_step(
        state_dir,
        Path(control["event_file"]),
        Path(control["comment_pool_file"]),
    )
    round_result, comment_quality = load_round_result(
        state_dir,
        event_input["event_id"],
        step,
    )
    _append_history(
        control,
        sequence,
        checkpoint,
        "scenario",
        step,
        round_result,
        step_result,
        comment_quality,
    )
    control["sequence"] = sequence
    control["paused"] = True
    if step >= MAX_STEPS:
        _finalize_scenario(experiment_dir, control)
        return control
    active = _active_for_round(
        control,
        control["strategy"],
        step + 1,
    )
    append_event_state_record(
        event_input=event_input,
        official_statement=active["official_statement"],
        official_statement_status=active["official_statement_status"],
        state_file=state_dir / "event_state_history.json",
    )
    control["current_step"] = step + 1
    control["status"] = "running"
    return control


def _restore_checkpoint(experiment_dir: Path, checkpoint_path: Path, state_dir: Path) -> None:
    checkpoint = _assert_inside_experiment(experiment_dir, checkpoint_path)
    state_dir = _assert_inside_experiment(experiment_dir, state_dir)
    if not checkpoint.is_dir():
        raise FileNotFoundError(f"检查点不存在：{checkpoint}")
    if state_dir.is_dir():
        shutil.rmtree(state_dir)
    state_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(checkpoint, state_dir)


def _build_control(
    batch_context: dict,
    event_input: dict,
    official_options: dict,
    selected_strategy_id: str,
    mode: str = "single",
    entry_timing: dict | None = None,
    announcement_timeline: list | None = None,
) -> dict:
    resolved_timing = entry_timing or {"mode": "dynamic", "round": None}
    return {
        "experiment_id": batch_context["experiment_id"],
        "event_id": event_input["event_id"],
        "selected_strategy_id": selected_strategy_id,
        "mode": mode,
        "strategy_queue": [],
        "entry_timing": resolved_timing,
        "announcement_timeline": announcement_timeline or [],
        "status": "created",
        "phase": "created",
        "paused": True,
        "entry_strategy": official_options["entry_strategy"],
        "stagnation_rounds": official_options["stagnation_rounds"],
        "negative_rate_improvement_tolerance": official_options[
            "negative_rate_improvement_tolerance"
        ],
        "event_file": str(batch_context["event_file"]),
        "comment_pool_file": str(batch_context["comment_pool_file"]),
        "official_response_file": str(
            batch_context["official_response_file"]
        ),
        "current_step": 1,
        "sequence": 0,
        "history": [],
        "checkpoints": [],
        "created_at": time.time(),
    }


def create_web_experiment(
    web_event_input=None,
    official_content_input=None,
    selected_strategy_id="fact_report",
    entry_timing_input=None,
    announcement_timeline_input=None,
    experiment_id=None,
):
    """创建可供 web 逐步控制的实验会话。"""
    event_input = resolve_event_input(
        default_event_file=EVENT_FILE,
        event_input=web_event_input,
    )
    official_options = resolve_official_response_options(
        event_id=event_input["event_id"],
        default_response_file=OFFICIAL_RESPONSE_FILE,
        content_input=official_content_input,
    )
    mode = (
        "all"
        if selected_strategy_id == ALL_STRATEGIES_ID
        else "single"
    )
    if mode == "single":
        _selected_strategy(official_options, selected_strategy_id)
    entry_timing = resolve_entry_timing(entry_timing_input)
    announcement_timeline = resolve_announcement_timeline(
        announcement_timeline_input
    )
    if mode == "all" and announcement_timeline:
        raise ValueError("全部策略模式暂不支持公告时间线。")
    batch_context = prepare_simulation_batch(
        event_input,
        experiment_id=experiment_id,
        official_response_options=official_options,
    )
    experiment_dir = Path(batch_context["experiment_dir"])
    control = _build_control(
        batch_context,
        event_input,
        official_options,
        selected_strategy_id,
        mode=mode,
        entry_timing=entry_timing,
        announcement_timeline=announcement_timeline,
    )
    _save_control(experiment_dir, control)
    return get_web_experiment_status(control["experiment_id"])


def start_web_experiment(experiment_id):
    """准备初始评论池并初始化共享基线，准备逐轮运行。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    if control.get("phase") != "created":
        raise ValueError("实验会话已初始化，不能重复启动。")
    event_input = load_json(control["event_file"])
    comment_pool_file = Path(control["comment_pool_file"])
    if not comment_pool_file.is_file():
        print("正在为新实验会话生成初始评论池……")
        comment_pool = generate_comment_pool(
            event_input=event_input,
            profile_file=COMMENT_PROFILE_FILE,
            comment_count=COMMENT_POOL_SIZE,
        )
        save_json(comment_pool_file, comment_pool)
    if control.get("mode") == "all":
        control["phase"] = "ready"
        control["status"] = "ready"
        control["paused"] = False
        control["started_at"] = time.time()
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)
    timing = control.get("entry_timing") or {}
    timeline = control.get("announcement_timeline", []) or []
    if timing.get("mode") == "fixed_round" or timeline:
        _start_direct_scenario(experiment_dir, control, event_input)
        if control.get("status") == "not_run":
            _save_control(experiment_dir, control)
            return get_web_experiment_status(experiment_id)
        control["status"] = "running"
        control["paused"] = False
        control["started_at"] = time.time()
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)
    _, baseline_state_dir = prepare_scenario_state(
        experiment_dir,
        "_shared_baseline",
        event_input["event_id"],
    )
    control["baseline_state_dir"] = str(baseline_state_dir)
    control["phase"] = "baseline"
    control["current_step"] = 1
    control["status"] = "running"
    control["paused"] = False
    control["started_at"] = time.time()
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def run_all_web_experiment(experiment_id):
    """按不回应与内置内容策略顺序完整运行一个五策略批次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    if control.get("mode") != "all":
        raise ValueError("run 动作只适用于全部策略依次运行模式。")
    if control.get("phase") not in {"created", "ready", "completed"}:
        raise ValueError(f"当前会话状态不允许运行全部策略：{control.get('phase')}")

    event_input = load_json(control["event_file"])
    comment_pool_file = Path(control["comment_pool_file"])
    if not comment_pool_file.is_file():
        print("正在为全部策略模式生成初始评论池……")
        comment_pool = generate_comment_pool(
            event_input=event_input,
            profile_file=COMMENT_PROFILE_FILE,
            comment_count=COMMENT_POOL_SIZE,
        )
        save_json(comment_pool_file, comment_pool)

    control["status"] = "running"
    control["phase"] = "all_running"
    control["paused"] = False
    _save_control(experiment_dir, control)

    result = run_experiment(
        experiment_id=control["experiment_id"],
        experiment_dir=experiment_dir,
        event_file=control["event_file"],
        comment_pool_file=control["comment_pool_file"],
        official_response_file=control["official_response_file"],
    )
    control["status"] = result.get("status", "completed")
    control["phase"] = "completed"
    control["paused"] = False
    control["current_step"] = MAX_STEPS
    control["strategy_count"] = len(result.get("strategy_results", []))
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def step_web_experiment(experiment_id):
    """继续并执行一个时间步，执行后自动暂停在下一个轮次边界。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        if control.get("paused"):
            return get_web_experiment_status(experiment_id)
        if control.get("phase") not in {"baseline", "scenario"}:
            raise ValueError(
                f"当前会话状态不允许推进：{control.get('phase')}"
            )
        event_input = load_json(control["event_file"])
        if control["phase"] == "baseline":
            _advance_baseline(experiment_dir, control, event_input)
        else:
            _advance_scenario(experiment_dir, control, event_input)
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def continue_web_experiment(experiment_id):
    """清空暂停标记并执行一个时间步。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = False
    _save_control(experiment_dir, control)
    return step_web_experiment(experiment_id)


def pause_web_experiment(experiment_id):
    """暂停当前会话；下一次推进前不会自动执行新轮次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = True
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def resume_web_experiment(experiment_id):
    """仅清除暂停标记，不自动执行新轮次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    control["paused"] = False
    _save_control(experiment_dir, control)
    return get_web_experiment_status(experiment_id)


def rollback_web_experiment(experiment_id, steps=1):
    """回滚到最近完成步之前的检查点。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        history = control.get("history", [])
        if not history:
            return get_web_experiment_status(experiment_id)
        steps = max(1, int(steps))
        if steps > len(history):
            steps = len(history)
        target_index = len(history) - steps
        target_item = history[target_index]
        checkpoint = Path(target_item["checkpoint"])
        if control.get("phase") == "scenario" and target_item["phase"] == "baseline":
            _remove_scenario_dir(
                experiment_dir,
                control["selected_strategy_id"],
            )
        _restore_checkpoint(
            experiment_dir,
            checkpoint,
            Path(target_item["checkpoint_state_dir"]),
        )
        control["history"] = history[:target_index]
        control["sequence"] = target_index
        _prune_checkpoints(experiment_dir, target_index)
        control["phase"] = target_item["phase"]
        control["current_step"] = target_item["step"]
        control["paused"] = True
        if target_item["phase"] == "baseline":
            control["baseline_state_dir"] = str(
                Path(target_item["checkpoint_state_dir"])
            )
        else:
            control["scenario_state_dir"] = str(
                Path(target_item["checkpoint_state_dir"])
            )
        if target_item["phase"] == "baseline":
            control.pop("response_step", None)
            control.pop("scenario_state_dir", None)
            control.pop("strategy", None)
        control["status"] = "running"
        _remove_experiment_file(
            experiment_dir,
            experiment_dir
            / control["selected_strategy_id"]
            / "scenario_result.json",
        )
        _remove_experiment_file(
            experiment_dir,
            experiment_dir / "experiment_result.json",
        )
        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def restart_web_experiment(experiment_id):
    """基于同一输入创建一个不可覆盖的新实验批次。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    event_input = load_json(control["event_file"])
    official_options = load_json(control["official_response_file"])
    new_batch = prepare_simulation_batch(
        event_input,
        official_response_options=official_options,
    )
    old_pool = Path(control["comment_pool_file"])
    if old_pool.is_file():
        shutil.copy2(old_pool, new_batch["comment_pool_file"])
    new_dir = Path(new_batch["experiment_dir"])
    new_control = _build_control(
        new_batch,
        event_input,
        official_options,
        control["selected_strategy_id"],
        mode=control.get("mode", "single"),
        entry_timing=control.get("entry_timing"),
        announcement_timeline=control.get("announcement_timeline", []),
    )
    _save_control(new_dir, new_control)
    return get_web_experiment_status(new_batch["experiment_id"])


def _active_state_dir(control: dict) -> Path:
    value = control.get("scenario_state_dir") or control.get(
        "baseline_state_dir"
    )
    return Path(value) if value else None


def _comment_distribution(comments):
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for comment in comments:
        emotion = comment.get("emotion")
        if emotion in counts:
            counts[emotion] += 1
    classified = sum(counts.values())
    return {
        "comment_count": len(comments),
        "classified_count": classified,
        "distribution": {
            label: {
                "count": count,
                "rate": round(count / classified, 4) if classified else None,
            }
            for label, count in counts.items()
        },
    }


def _load_agent_snapshot(state_dir: Path | None, event_id: str, step):
    if state_dir is None or step is None:
        return []
    records = {}
    for row in read_jsonl(state_dir / "agent_state_history.jsonl"):
        if row.get("event_id") != event_id or row.get("step") != step:
            continue
        agent_id = row.get("agent_id")
        if agent_id:
            records[agent_id] = row
    agents = []
    for agent_id in sorted(records):
        row = records[agent_id]
        state = row.get("state", {}) or {}
        last_comment = state.get("last_comment") or {}
        agents.append(
            {
                "agent_id": agent_id,
                "current_emotion": state.get("current_emotion"),
                "official_attitude": state.get("official_attitude"),
                "will_comment": state.get("will_comment"),
                "last_action": state.get("last_action"),
                "last_comment_faction": state.get("last_comment_faction"),
                "last_comment": last_comment.get("text", ""),
                "comment_emotion": last_comment.get("emotion"),
                "comment_orientation": last_comment.get("orientation"),
            }
        )
    return agents


def add_web_announcement(
    experiment_id,
    round_no,
    official_statement,
    official_statement_status="clear",
):
    """在暂停状态下向指定轮次追加或替换一条公告。"""
    with _LOCK:
        experiment_dir = _experiment_dir(experiment_id)
        control = _load_control(experiment_dir)
        if not control.get("paused"):
            raise ValueError("只能在暂停状态下添加公告。")
        if control.get("phase") not in {"baseline", "scenario"}:
            raise ValueError("当前会话阶段不允许添加公告。")

        event = resolve_announcement_timeline(
            [
                {
                    "round": round_no,
                    "official_statement": official_statement,
                    "official_statement_status": official_statement_status,
                }
            ]
        )[0]
        current_step = int(control.get("current_step", 1))
        if event["round"] < current_step:
            raise ValueError("不能修改已经运行完成的轮次。")
        if control.get("selected_strategy_id") == NO_RESPONSE_SCENARIO[
            "strategy_id"
        ]:
            raise ValueError("不回应策略不能添加公告。")

        timeline = list(control.get("announcement_timeline", []) or [])
        timeline = [
            item
            for item in timeline
            if item.get("round") != event["round"]
        ]
        timeline.append(event)
        timeline.sort(key=lambda item: item["round"])
        control["announcement_timeline"] = timeline

        if control.get("phase") == "scenario":
            if event["round"] == current_step:
                _replace_event_state(
                    Path(control["scenario_state_dir"]),
                    control["event_id"],
                    current_step,
                    event["official_statement"],
                    event["official_statement_status"],
                )
        else:
            if event["round"] == current_step:
                event_input = load_json(control["event_file"])
                strategy_id = control["selected_strategy_id"]
                strategy = _selected_strategy(
                    load_json(experiment_dir / "official_response_options.json"),
                    strategy_id,
                )
                _, scenario_state_dir = prepare_scenario_state(
                    experiment_dir,
                    strategy_id,
                    event_input["event_id"],
                    baseline_state_dir=Path(control["baseline_state_dir"]),
                )
                _replace_event_state(
                    scenario_state_dir,
                    event_input["event_id"],
                    current_step,
                    event["official_statement"],
                    event["official_statement_status"],
                )
                control["scenario_state_dir"] = str(scenario_state_dir)
                control["strategy"] = strategy
                control["phase"] = "scenario"
                control["response_step"] = current_step
                control["entry_reason"] = "manual_announcement"
                control["status"] = "running"
            else:
                control["entry_timing"] = {
                    "mode": "fixed_round",
                    "round": event["round"],
                }

        _save_control(experiment_dir, control)
        return get_web_experiment_status(experiment_id)


def _build_round_snapshot(experiment_dir: Path, control: dict) -> dict:
    """读取已完成轮次指标与当前评论池，返回 web 实时展示快照。"""
    event_id = control.get("event_id")
    initial_comments = []
    comment_pool_file = Path(control["comment_pool_file"])
    if comment_pool_file.is_file():
        pool = load_json(comment_pool_file) or {}
        initial_comments = pool.get("comments", []) or []

    state_dir = _active_state_dir(control)
    metrics_history = []
    comment_rows = []
    if state_dir is not None and state_dir.is_dir():
        for row in read_jsonl(state_dir / "metrics_history.jsonl"):
            if isinstance(row, dict) and row.get("event_id") == event_id:
                metrics_history.append(row)
        for row in read_jsonl(
            state_dir / "incremental_comment_history.jsonl"
        ):
            if isinstance(row, dict) and row.get("event_id") == event_id:
                comment_rows.append(row)

    metrics_history.sort(key=lambda item: item.get("step", 0))
    comment_rows.sort(key=lambda item: item.get("step", 0))
    simplified_metrics = []
    for row in metrics_history:
        try:
            policy = extract_policy_metrics(row)
        except Exception:
            policy = {}
        simplified_metrics.append(
            {
                "step": row.get("step"),
                "policy_metrics": policy,
                "global_trend": row.get("global_trend", {}).get(
                    "trend_direction"
                ),
                "global_trend_reason": row.get("global_trend", {}).get(
                    "reason",
                    "",
                ),
                "agent_emotion_distribution": row.get(
                    "agent_emotion_distribution",
                    {},
                ),
                "official_attitude_distribution": row.get(
                    "official_attitude_distribution",
                    {},
                ),
            }
        )

    incremental_by_step = {
        row.get("step"): row for row in comment_rows
    }
    comment_history = []
    all_steps = sorted(
        {
            item.get("step")
            for item in simplified_metrics
            if item.get("step") is not None
        }
        | {row.get("step") for row in comment_rows if row.get("step") is not None}
    )
    if all_steps and all_steps[0] == 1:
        distribution = _comment_distribution(initial_comments)
        comment_history.append(
            {
                "step": 1,
                "source": "initial_pool",
                **distribution,
                "quality_status": "normal",
            }
        )
    for step in all_steps:
        if step == 1:
            continue
        record = incremental_by_step.get(step)
        comments = record.get("comments", []) if isinstance(record, dict) else []
        comment_history.append(
            {
                "step": step,
                "source": "incremental",
                **_comment_distribution(comments),
                "quality_status": (
                    record.get("quality_status", "normal")
                    if isinstance(record, dict)
                    else "unknown"
                ),
                "fallback_count": (
                    record.get("fallback_count", 0)
                    if isinstance(record, dict)
                    else 0
                ),
                "llm_comment_count": (
                    record.get("llm_comment_count", 0)
                    if isinstance(record, dict)
                    else 0
                ),
            }
        )

    latest_step = max(all_steps) if all_steps else None
    latest_comments = []
    if latest_step == 1:
        latest_comments = initial_comments
    elif latest_step in incremental_by_step:
        latest_comments = (
            incremental_by_step[latest_step].get("comments", []) or []
        )
    comments_by_step = {}
    for step in all_steps:
        if step == 1:
            step_comments = initial_comments
        else:
            record = incremental_by_step.get(step)
            step_comments = (
                record.get("comments", [])
                if isinstance(record, dict)
                else []
            )
        comments_by_step[str(step)] = [
            {
                "comment_id": item.get("comment_id"),
                "text": item.get("text", ""),
                "emotion": item.get("emotion"),
                "faction": item.get("faction"),
                "orientation": item.get("orientation"),
                "stance": item.get("stance"),
            }
            for item in step_comments
        ][:80]
    visible_comments = comments_by_step.get(str(latest_step), []) if latest_step else []
    return {
        "latest_step": latest_step,
        "initial_comment_count": len(initial_comments),
        "comment_pool": _comment_distribution(initial_comments),
        "agents": _load_agent_snapshot(state_dir, event_id, latest_step),
        "metrics_history": simplified_metrics,
        "comment_history": comment_history,
        "comments_by_step": comments_by_step,
        "latest_comments": visible_comments,
    }


def get_web_experiment_status(experiment_id):
    """返回 web 展示所需的会话状态。"""
    experiment_dir = _experiment_dir(experiment_id)
    control = _load_control(experiment_dir)
    scenario_result = None
    experiment_result = None
    if control.get("mode") == "all":
        result_file = experiment_dir / "experiment_result.json"
        if result_file.is_file():
            experiment_result = load_json(result_file)
    else:
        result_file = (
            experiment_dir
            / control.get("selected_strategy_id", "")
            / "scenario_result.json"
        )
        if result_file.is_file():
            scenario_result = load_json(result_file)
    snapshot = _build_round_snapshot(experiment_dir, control)
    return {
        "experiment_id": control["experiment_id"],
        "event_id": control.get("event_id"),
        "selected_strategy_id": control.get("selected_strategy_id"),
        "mode": control.get("mode"),
        "strategy_count": control.get("strategy_count"),
        "status": control.get("status"),
        "phase": control.get("phase"),
        "paused": control.get("paused"),
        "current_step": control.get("current_step"),
        "response_step": control.get("response_step"),
        "entry_reason": control.get("entry_reason"),
        "entry_timing": control.get("entry_timing"),
        "announcement_timeline": control.get(
            "announcement_timeline",
            [],
        ),
        "not_run_reason": control.get("not_run_reason"),
        "completed_step_count": len(control.get("history", [])),
        "max_steps": MAX_STEPS,
        "scenario_result_ready": scenario_result is not None,
        "scenario_result": scenario_result,
        "experiment_result_ready": experiment_result is not None,
        "experiment_result": experiment_result,
        "snapshot": snapshot,
    }


def list_web_experiments():
    """列出带 web 控制文件的实验会话。"""
    from project_config import EXPERIMENT_DIR

    sessions = []
    if not EXPERIMENT_DIR.is_dir():
        return sessions
    for experiment_dir in sorted(EXPERIMENT_DIR.iterdir()):
        if not experiment_dir.is_dir():
            continue
        if not _control_file(experiment_dir).is_file():
            continue
        try:
            sessions.append(get_web_experiment_status(experiment_dir.name))
        except Exception:
            continue
    return sessions


if __name__ == "__main__":
    print("Web control API module loaded.")
