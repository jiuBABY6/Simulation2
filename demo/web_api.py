"""Public web-facing API facade for Simulation2.

This module groups the web input functions (event, announcement content,
strategy selection) and the step-wise session control functions under one
importable API surface. It does not add an HTTP server and does not implement
simulation algorithms.
"""

from __future__ import annotations

from experiment_runner import (
    CUSTOM_CONTENT_STRATEGY_ID,
    is_custom_statement_ready,
    list_triggerable_strategies,
    resolve_entry_timing,
    resolve_official_response_options,
)
from web_control import resolve_announcement_timeline
from project_config import EVENT_FILE, OFFICIAL_RESPONSE_FILE
from simulation.event_context import resolve_event_input
from web_control import (
    add_web_announcement,
    continue_web_experiment,
    create_web_experiment,
    get_web_experiment_status,
    list_web_experiments,
    pause_web_experiment,
    restart_web_experiment,
    resume_web_experiment,
    rollback_web_experiment,
    run_all_web_experiment,
    start_web_experiment,
    step_web_experiment,
)


def get_event_web_default():
    """返回默认事件输入（来自 event_example.json）。"""
    return resolve_event_input(default_event_file=EVENT_FILE, event_input=None)


def apply_event_web_input(web_event_input=None):
    """合并默认事件与 web 输入并校验。"""
    return resolve_event_input(
        default_event_file=EVENT_FILE,
        event_input=web_event_input,
    )


def get_official_content_web_default():
    """返回默认官方公告策略（来自 official_response_options.json）。"""
    event_id = get_event_web_default()["event_id"]
    return resolve_official_response_options(
        event_id=event_id,
        default_response_file=OFFICIAL_RESPONSE_FILE,
        content_input=None,
    )


def prepare_web_inputs(
    web_event_input=None,
    official_content_input=None,
    entry_timing_input=None,
    announcement_timeline_input=None,
):
    """合并事件与公告 web 输入，返回一次实验所需的标准输入。"""
    event_input = apply_event_web_input(web_event_input)
    official_options = resolve_official_response_options(
        event_id=event_input["event_id"],
        default_response_file=OFFICIAL_RESPONSE_FILE,
        content_input=official_content_input,
    )
    return {
        "event_input": event_input,
        "official_response_options": official_options,
        "event_id": event_input["event_id"],
        "strategies": list_triggerable_strategies(official_options),
        "entry_timing": resolve_entry_timing(entry_timing_input),
        "announcement_timeline": resolve_announcement_timeline(
            announcement_timeline_input
        ),
    }


def apply_entry_timing_input(entry_timing_input=None):
    """校验并规范化自定义进场时机输入。"""
    return resolve_entry_timing(entry_timing_input)


def list_strategy_web_options(web_event_input=None, official_content_input=None):
    """返回 web 页面可选择的策略及 readiness 状态。"""
    return prepare_web_inputs(
        web_event_input=web_event_input,
        official_content_input=official_content_input,
    )["strategies"]


def apply_strategy_web_input(
    selected_strategy_id,
    web_event_input=None,
    official_content_input=None,
):
    """校验并返回单个策略的 web 输入。"""
    payload = prepare_web_inputs(
        web_event_input=web_event_input,
        official_content_input=official_content_input,
    )
    available = {
        item["strategy_id"]: item
        for item in payload["strategies"]
    }
    if selected_strategy_id not in available:
        raise ValueError(f"不支持的策略编号：{selected_strategy_id}")
    selected = available[selected_strategy_id]
    if (
        selected_strategy_id == CUSTOM_CONTENT_STRATEGY_ID
        and not selected.get("ready")
    ):
        raise ValueError(
            "custom 策略公告为空，请先填写 official_statement 与状态。"
        )
    return {
        "strategy_id": selected_strategy_id,
        "strategy_name": selected["strategy_name"],
        "custom": selected.get("custom", False),
        "ready": selected.get("ready", True),
    }


__all__ = [
    "add_web_announcement",
    "get_event_web_default",
    "apply_event_web_input",
    "get_official_content_web_default",
    "prepare_web_inputs",
    "apply_entry_timing_input",
    "list_strategy_web_options",
    "apply_strategy_web_input",
    "create_web_experiment",
    "start_web_experiment",
    "step_web_experiment",
    "continue_web_experiment",
    "pause_web_experiment",
    "resume_web_experiment",
    "rollback_web_experiment",
    "restart_web_experiment",
    "run_all_web_experiment",
    "get_web_experiment_status",
    "list_web_experiments",
]
