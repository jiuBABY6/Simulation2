"""读取和校验历史官方信息时间线。"""

from pathlib import Path

from runtime_paths import DEMO_DIR  # noqa: F401，导入时完成现有 Demo 模块路径初始化。

from infrastructure.json_storage import load_json


VALID_STATEMENT_STATUSES = {"clear", "incomplete", "conflict"}


# 2026/09/02 历史趋势复现，新增功能：校验固定轮次、阶段信息和官方声明时间线。
def validate_official_response_timeline(timeline, event_id):
    """校验历史时间线，并返回按轮次排序的精简配置。"""
    if not isinstance(timeline, dict):
        raise ValueError("官方信息时间线必须是 JSON 对象。")
    if timeline.get("event_id") != event_id:
        raise ValueError("官方信息时间线与当前事件的 event_id 不一致。")

    total_steps = timeline.get("total_steps")
    if (
        isinstance(total_steps, bool)
        or not isinstance(total_steps, int)
        or total_steps < 2
    ):
        raise ValueError("total_steps 必须是不小于2的整数。")

    step_periods = _validate_step_periods(
        timeline.get("step_periods", []),
        total_steps,
    )
    official_updates = _validate_official_updates(
        timeline.get("official_updates"),
        total_steps,
    )
    return {
        "event_id": event_id,
        "mode": "historical_replay",
        "total_steps": total_steps,
        "step_periods": step_periods,
        "official_updates": official_updates,
    }


def _validate_step_periods(raw_periods, total_steps):
    """校验每轮对应的现实时间段，便于结果与人工记录对齐。"""
    if not isinstance(raw_periods, list) or len(raw_periods) != total_steps:
        raise ValueError("step_periods 必须为每个时间步提供一条阶段记录。")

    periods = []
    seen_steps = set()
    for index, item in enumerate(raw_periods, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条阶段记录必须是 JSON 对象。")
        step = item.get("step")
        period = str(item.get("period", "")).strip()
        phase = str(item.get("phase", "")).strip()
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 1 <= step <= total_steps
        ):
            raise ValueError(f"第 {index} 条阶段记录的 step 不合法。")
        if step in seen_steps:
            raise ValueError(f"阶段记录存在重复时间步：{step}")
        if not period or not phase:
            raise ValueError(f"第 {index} 条阶段记录缺少 period 或 phase。")
        seen_steps.add(step)
        periods.append({"step": step, "period": period, "phase": phase})

    expected_steps = set(range(1, total_steps + 1))
    if seen_steps != expected_steps:
        raise ValueError("step_periods 必须连续覆盖全部时间步。")
    return sorted(periods, key=lambda item: item["step"])


def _validate_official_updates(raw_updates, total_steps):
    """校验官方信息只在指定轮次首次投入。"""
    if not isinstance(raw_updates, list) or not raw_updates:
        raise ValueError("official_updates 必须是非空数组。")

    updates = []
    seen_steps = set()
    for index, item in enumerate(raw_updates, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条官方信息必须是 JSON 对象。")

        step = item.get("step")
        statement = str(item.get("official_statement", "")).strip()
        status = item.get("official_statement_status")
        published_at = str(item.get("published_at", "")).strip()
        source_url = str(item.get("source_url", "")).strip()
        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or not 2 <= step <= total_steps
        ):
            raise ValueError(
                f"第 {index} 条官方信息的 step 必须在2到{total_steps}之间。"
            )
        if step in seen_steps:
            raise ValueError(f"官方信息存在重复投入轮次：{step}")
        if not statement:
            raise ValueError(f"第 {index} 条官方信息内容不能为空。")
        if status not in VALID_STATEMENT_STATUSES:
            raise ValueError(
                f"第 {index} 条官方信息状态必须属于 "
                f"{sorted(VALID_STATEMENT_STATUSES)}。"
            )
        if not published_at:
            raise ValueError(f"第 {index} 条官方信息缺少 published_at。")

        seen_steps.add(step)
        updates.append(
            {
                "step": step,
                "published_at": published_at,
                "official_statement": statement,
                "official_statement_status": status,
                "source_url": source_url,
            }
        )
    return sorted(updates, key=lambda item: item["step"])


# 2026/09/02 历史趋势复现，新增功能：从独立 JSON 文件读取固定官方信息时间线。
def load_official_response_timeline(timeline_file, event_id):
    """读取历史时间线，并执行严格校验。"""
    path = Path(timeline_file)
    if not path.is_file():
        raise FileNotFoundError(f"官方信息时间线不存在：{path}")
    return validate_official_response_timeline(load_json(path), event_id)


# 2026/09/02 历史趋势复现，新增功能：返回指定轮次应持续生效的最新官方信息。
def get_official_state_for_step(timeline, step):
    """返回本轮有效声明；没有官方信息时返回空声明状态。"""
    if not isinstance(step, int) or not 1 <= step <= timeline["total_steps"]:
        raise ValueError(f"时间步不合法：{step}")

    active_update = None
    for update in timeline["official_updates"]:
        if update["step"] > step:
            break
        active_update = update

    if active_update is None:
        return {
            "official_statement": "",
            "official_statement_status": "none",
            "introduced_step": None,
            "is_update_step": False,
        }
    return {
        "official_statement": active_update["official_statement"],
        "official_statement_status": active_update[
            "official_statement_status"
        ],
        "introduced_step": active_update["step"],
        "is_update_step": active_update["step"] == step,
    }


def get_step_period(timeline, step):
    """返回指定轮次对应的现实时间段和阶段名称。"""
    return next(
        item for item in timeline["step_periods"] if item["step"] == step
    )
