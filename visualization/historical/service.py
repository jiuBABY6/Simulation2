"""封装历史复现实验、真实趋势和探索性对照的只读服务。"""

from __future__ import annotations

from typing import Any

from visualization.historical.comparison_service import compare_negative_trends
from visualization.historical.real_trend_repository import (
    get_active_event_id,
    load_real_trend,
)
from visualization.historical.simulation_data_loader import load_experiment
from visualization.shared.experiment_catalog import describe_experiment


def resolve_requested_event_id(
    *, experiment_id: str | None = None, event_id: str | None = None
) -> str:
    """根据实验或显式事件编号确定真实趋势，拒绝交叉事件混用。"""

    normalized_event_id = str(event_id or "").strip()
    normalized_experiment_id = str(experiment_id or "").strip()
    if normalized_experiment_id:
        experiment_event_id = str(
            describe_experiment(normalized_experiment_id).get("event_id") or ""
        )
        if normalized_event_id and normalized_event_id != experiment_event_id:
            raise ValueError("experiment_id 与 event_id 不一致")
        normalized_event_id = experiment_event_id
    return normalized_event_id or get_active_event_id()


def load_reference_for_request(
    *, experiment_id: str | None = None, event_id: str | None = None
) -> dict[str, Any]:
    return load_real_trend(
        resolve_requested_event_id(
            experiment_id=experiment_id,
            event_id=event_id,
        )
    )


def load_dashboard(experiment_id: str) -> dict[str, Any]:
    return load_experiment(experiment_id)


def build_comparison(experiment_id: str) -> dict[str, Any]:
    simulation = load_experiment(experiment_id)
    reference = load_real_trend(str(simulation.get("event_id") or ""))
    # 2026/10/12，修改功能：一次返回四种口径，前端切换时不重复读取文件。
    comparisons = {
        basis: compare_negative_trends(simulation, reference, basis=basis)
        for basis in (
            "agent_expression",
            "current_round",
            "cumulative",
            "active_opinion",
        )
    }
    # 2026/10/12，历史复现观测口径修正：人工数据来自已发表评论，
    # 默认只与 Agent 的实际表达比较；其他评论池口径保留为诊断视图。
    default_basis = "agent_expression"
    return {
        **comparisons[default_basis],
        "default_basis": default_basis,
        "comparisons": comparisons,
    }
