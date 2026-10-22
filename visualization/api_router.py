"""统一可视化的只读 API 路由。

HTTP 传输与业务查询在此分离：处理器只负责收发字节，本模块只负责参数
校验和调用历史、策略、共享网络三层服务。
"""

from __future__ import annotations

from typing import Any

from visualization.historical.real_trend_repository import list_real_trends
from visualization.historical.service import (
    build_comparison as build_historical_comparison,
    load_dashboard as load_historical_dashboard,
    load_reference_for_request,
)
from visualization.shared.experiment_catalog import list_experiments
from visualization.shared.network.service import (
    build_comment_cascade,
    build_comment_catalog,
    build_network_view,
    build_report_summary,
)
from visualization.strategy.service import (
    load_dashboard as load_strategy_dashboard,
)


API_PATHS = frozenset(
    {
        "/api/catalog",
        "/api/historical/real-trends",
        "/api/historical/real-trend",
        "/api/historical/dashboard",
        "/api/historical/comparison",
        "/api/strategy/dashboard",
        "/api/network/report",
        "/api/network/view",
        "/api/network/comments",
        "/api/network/cascade",
    }
)


def _first(query: dict[str, list[str]], name: str) -> str:
    values = query.get(name, [""])
    return values[0] if values else ""


def _required(query: dict[str, list[str]], name: str) -> str:
    value = _first(query, name).strip()
    if not value:
        raise ValueError(f"缺少 {name}")
    return value


def dispatch_api(path: str, query: dict[str, list[str]]) -> Any:
    """执行一个已注册的 GET API，并返回可 JSON 序列化的数据。"""

    if path not in API_PATHS:
        raise LookupError(f"未注册的 API：{path}")
    if path == "/api/catalog":
        return {"experiments": list_experiments(mode=_first(query, "mode") or None)}
    if path == "/api/historical/real-trends":
        return {"real_trends": list_real_trends()}
    if path == "/api/historical/real-trend":
        return load_reference_for_request(
            experiment_id=_first(query, "experiment_id"),
            event_id=_first(query, "event_id"),
        )

    experiment_id = _required(query, "experiment_id")
    if path == "/api/historical/dashboard":
        return load_historical_dashboard(experiment_id)
    if path == "/api/historical/comparison":
        return build_historical_comparison(experiment_id)
    if path == "/api/strategy/dashboard":
        return load_strategy_dashboard(experiment_id)
    if path == "/api/network/report":
        return build_report_summary(experiment_id)

    scenario_id = _first(query, "scenario") or None
    if path == "/api/network/view":
        raw_step = _first(query, "step")
        step = int(raw_step) if raw_step else None
        return build_network_view(experiment_id, scenario_id, step)
    if path == "/api/network/comments":
        return build_comment_catalog(experiment_id, scenario_id)
    return build_comment_cascade(
        experiment_id,
        scenario_id,
        _first(query, "comment_id"),
    )

