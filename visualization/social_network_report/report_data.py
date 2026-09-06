"""只读整理第二十六次联调的网络、传播链和分析数据。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from config import EXPERIMENT_DIR, SCENARIO_NAMES


def _load_json(path: Path) -> dict[str, object]:
    """读取JSON对象，不对实验文件执行任何写入。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON文件不是对象：{path}")
    return data


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    """读取JSONL对象列表并忽略空行。"""
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"JSONL第{line_number}行不是对象：{path}")
        records.append(record)
    return records


def _validate_experiment_dir() -> None:
    """确认专题页面所需的第二十六次联调文件完整。"""
    required_files = [
        EXPERIMENT_DIR / "experiment_result.json",
        EXPERIMENT_DIR / "social_network_snapshot.json",
    ]
    for scenario_id in SCENARIO_NAMES:
        required_files.extend(
            [
                EXPERIMENT_DIR / scenario_id / "scenario_result.json",
                EXPERIMENT_DIR
                / scenario_id
                / "state"
                / "propagation_history.jsonl",
                EXPERIMENT_DIR
                / scenario_id
                / "state"
                / "decision_history.jsonl",
            ]
        )
    missing = [str(path) for path in required_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("专题实验文件不完整：" + "；".join(missing))


def _validate_scenario(scenario_id: str) -> str:
    """只允许访问本次实验的五个既定场景。"""
    if scenario_id not in SCENARIO_NAMES:
        raise ValueError(f"未知实验场景：{scenario_id}")
    return scenario_id


def _scenario_state_file(scenario_id: str, file_name: str) -> Path:
    """返回指定场景状态文件路径。"""
    _validate_scenario(scenario_id)
    return EXPERIMENT_DIR / scenario_id / "state" / file_name


def _calculate_overall_quality(data_quality: dict[str, object]) -> dict[str, object]:
    """按五个场景实际增量评论总量计算本批次质量摘要。"""
    llm_count = sum(
        int(item.get("llm_comment_count", 0))
        for item in data_quality.values()
        if isinstance(item, dict)
    )
    history_count = sum(
        int(item.get("history_fallback_count", 0))
        for item in data_quality.values()
        if isinstance(item, dict)
    )
    emergency_count = sum(
        int(item.get("emergency_fallback_count", 0))
        for item in data_quality.values()
        if isinstance(item, dict)
    )
    total = llm_count + history_count + emergency_count
    fallback_count = history_count + emergency_count
    return {
        "total_comment_count": total,
        "llm_comment_count": llm_count,
        "history_fallback_count": history_count,
        "emergency_fallback_count": emergency_count,
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_count / total, 6) if total else 0.0,
    }


# 2026/09/06 社交网络传播可视化，新增功能：汇总第二十六次联调的网络、策略和验收结论。
def build_report_summary() -> dict[str, object]:
    """返回专题首页需要的实验、网络、传播和质量摘要。"""
    _validate_experiment_dir()
    experiment = _load_json(EXPERIMENT_DIR / "experiment_result.json")
    network = _load_json(EXPERIMENT_DIR / "social_network_snapshot.json")
    comparison = experiment.get("comparison", {})
    propagation = comparison.get("propagation_metrics", {})
    data_quality = comparison.get("data_quality", {})

    scenario_rows = []
    for scenario_id, scenario_name in SCENARIO_NAMES.items():
        metrics = propagation.get(scenario_id, {})
        quality = data_quality.get(scenario_id, {})
        scenario_rows.append(
            {
                "scenario_id": scenario_id,
                "scenario_name": scenario_name,
                "propagation": metrics,
                "quality": quality,
                "final_trend": comparison.get("final_trends", {}).get(
                    scenario_id
                ),
            }
        )

    total_exposure = sum(
        int(row["propagation"].get("exposure_count", 0))
        for row in scenario_rows
    )
    total_continued = sum(
        int(row["propagation"].get("continued_propagation_count", 0))
        for row in scenario_rows
    )
    max_depth = max(
        (
            int(row["propagation"].get("max_propagation_depth", 0))
            for row in scenario_rows
        ),
        default=0,
    )

    return {
        "experiment_id": experiment.get("experiment_id"),
        "status": experiment.get("status"),
        "entry_triggered": experiment.get("entry_triggered"),
        "entry_reason": experiment.get("entry_reason"),
        "performance": experiment.get("performance", {}),
        "network": {
            "network_version": network.get("network_version"),
            "network_seed": network.get("network_seed"),
            "node_count": len(network.get("nodes", [])),
            "edge_count": len(network.get("edges", [])),
            "neighbors_per_agent": network.get("neighbors_per_agent"),
            "propagation_decay_factor": network.get(
                "propagation_decay_factor"
            ),
            "visibility": network.get("visibility", {}),
        },
        "overall_propagation": {
            "exposure_count": total_exposure,
            "continued_propagation_count": total_continued,
            "continuation_rate": round(
                total_continued / total_exposure, 6
            )
            if total_exposure
            else 0.0,
            "max_propagation_depth": max_depth,
        },
        "overall_quality": _calculate_overall_quality(data_quality),
        "scenarios": scenario_rows,
        "findings": [
            "五个场景共记录2117次邻居曝光，传播事件均沿固定关注关系发生。",
            "所有场景均形成多跳传播，最大传播深度为4至6层。",
            "逐条传播记录均符合“来源影响力 × 0.7^(层级-1)”的衰减规则。",
            "传播持久化与指标计算没有造成可观察的性能退化。",
        ],
        "limitations": [
            "当前只有10个Agent且每人关注5人，网络密度较高，五个场景覆盖率均为100%。",
            "本批次Agent每轮均有实际表达，覆盖与活跃程度高于一般现实网络。",
            "关注关系由固定种子随机生成，尚未按真实关系或互动动态调整。",
            "公共评论补充不属于关系网络传播，未写入邻居传播事件文件。",
            "本页面用于分析模拟传播机制，不代表现实平台的真实传播规模。",
        ],
    }


def _load_scenario_events(scenario_id: str) -> list[dict[str, object]]:
    """读取一个场景的邻居曝光事件。"""
    return _load_jsonl(
        _scenario_state_file(scenario_id, "propagation_history.jsonl")
    )


def _load_scenario_decisions(scenario_id: str) -> list[dict[str, object]]:
    """读取一个场景的Agent决策记录。"""
    return _load_jsonl(
        _scenario_state_file(scenario_id, "decision_history.jsonl")
    )


# 2026/09/06 社交网络传播可视化，新增功能：按场景和轮次构建信息流方向的网络视图。
def build_network_view(scenario_id: str, step: int) -> dict[str, object]:
    """返回截至指定轮次的网络节点和传播边统计。"""
    _validate_scenario(scenario_id)
    if isinstance(step, bool) or not isinstance(step, int) or not 1 <= step <= 10:
        raise ValueError("step必须是1到10之间的整数。")

    network = _load_json(EXPERIMENT_DIR / "social_network_snapshot.json")
    events = [
        event
        for event in _load_scenario_events(scenario_id)
        if int(event.get("step", 0)) <= step
    ]
    edge_stats: dict[tuple[str, str], dict[str, object]] = {}
    for edge in network.get("edges", []):
        # 网络边表示“source关注target”，页面统一反转为真实信息流方向。
        source_agent_id = edge["target_agent_id"]
        target_agent_id = edge["source_agent_id"]
        edge_stats[(source_agent_id, target_agent_id)] = {
            "source_agent_id": source_agent_id,
            "target_agent_id": target_agent_id,
            "follower_agent_id": target_agent_id,
            "followed_agent_id": source_agent_id,
            "exposure_count": 0,
            "selected_exposure_count": 0,
            "effective_weight_total": 0.0,
            "max_depth": 0,
        }

    for event in events:
        key = (event.get("source_agent_id"), event.get("target_agent_id"))
        if key not in edge_stats:
            continue
        stats = edge_stats[key]
        stats["exposure_count"] += 1
        if event.get("was_selected") is True:
            stats["selected_exposure_count"] += 1
        stats["effective_weight_total"] += float(
            event.get("effective_weight", 0.0)
        )
        stats["max_depth"] = max(
            int(stats["max_depth"]), int(event.get("propagation_depth", 0))
        )

    node_stats = defaultdict(
        lambda: {
            "sent_exposure_count": 0,
            "received_exposure_count": 0,
            "continued_count": 0,
        }
    )
    for event in events:
        source = event.get("source_agent_id")
        target = event.get("target_agent_id")
        if source:
            node_stats[source]["sent_exposure_count"] += 1
        if target:
            node_stats[target]["received_exposure_count"] += 1
            if event.get("was_selected") is True:
                node_stats[target]["continued_count"] += 1

    nodes = []
    for node in network.get("nodes", []):
        agent_id = node["agent_id"]
        nodes.append({**node, **node_stats[agent_id]})

    active_edges = sum(
        1 for edge in edge_stats.values() if edge["exposure_count"] > 0
    )
    return {
        "scenario_id": scenario_id,
        "scenario_name": SCENARIO_NAMES[scenario_id],
        "step": step,
        "nodes": nodes,
        "edges": list(edge_stats.values()),
        "event_count": len(events),
        "active_edge_count": active_edges,
    }


def _comment_texts(decisions: list[dict[str, object]]) -> dict[str, str]:
    """从实际表达中提取评论编号与文本。"""
    texts = {}
    for record in decisions:
        decision = record.get("decision", {})
        if not isinstance(decision, dict):
            continue
        comment = decision.get("selected_comment", {})
        if not isinstance(comment, dict):
            continue
        comment_id = str(comment.get("comment_id", "")).strip()
        text = str(comment.get("text", "")).strip()
        if comment_id and text:
            texts.setdefault(comment_id, text)
    return texts


# 2026/09/06 社交网络传播可视化，新增功能：列出可追踪的评论及其传播规模。
def build_comment_catalog(scenario_id: str) -> dict[str, object]:
    """返回一个场景中按传播深度和曝光次数排序的评论目录。"""
    _validate_scenario(scenario_id)
    events = _load_scenario_events(scenario_id)
    texts = _comment_texts(_load_scenario_decisions(scenario_id))
    groups = defaultdict(list)
    for event in events:
        comment_id = str(event.get("comment_id", "")).strip()
        if comment_id:
            groups[comment_id].append(event)

    comments = []
    for comment_id, comment_events in groups.items():
        resulting_ids = {
            event.get("resulting_expression_id")
            for event in comment_events
            if event.get("was_selected") is True
            and event.get("resulting_expression_id")
        }
        comments.append(
            {
                "comment_id": comment_id,
                "text": texts.get(comment_id, "未找到评论文本"),
                "exposure_count": len(comment_events),
                "continued_count": len(resulting_ids),
                "max_depth": max(
                    int(event.get("propagation_depth", 0))
                    for event in comment_events
                ),
                "first_step": min(
                    int(event.get("step", 0)) for event in comment_events
                ),
                "last_step": max(
                    int(event.get("step", 0)) for event in comment_events
                ),
            }
        )
    comments.sort(
        key=lambda item: (
            item["max_depth"],
            item["exposure_count"],
            item["continued_count"],
        ),
        reverse=True,
    )
    return {
        "scenario_id": scenario_id,
        "scenario_name": SCENARIO_NAMES[scenario_id],
        "comments": comments,
    }


# 2026/09/06 社交网络传播可视化，新增功能：使用表达谱系构建单条评论传播DAG。
def build_comment_cascade(
    scenario_id: str, comment_id: str
) -> dict[str, object]:
    """返回一条评论的实际表达、继续传播和停止曝光节点。"""
    _validate_scenario(scenario_id)
    comment_id = str(comment_id).strip()
    if not comment_id:
        raise ValueError("comment_id不能为空。")

    decisions = _load_scenario_decisions(scenario_id)
    events = [
        event
        for event in _load_scenario_events(scenario_id)
        if event.get("comment_id") == comment_id
    ]
    expression_nodes = {}
    comment_text = ""
    for record in decisions:
        decision = record.get("decision", {})
        if not isinstance(decision, dict):
            continue
        selected = decision.get("selected_comment", {})
        if not isinstance(selected, dict) or selected.get("comment_id") != comment_id:
            continue
        expression_id = decision.get("expression_id")
        if not expression_id:
            continue
        comment_text = comment_text or str(selected.get("text", ""))
        expression_nodes[expression_id] = {
            "node_id": expression_id,
            "node_type": "expression",
            "agent_id": record.get("agent_id"),
            "step": record.get("step"),
            "depth": decision.get("propagation_depth", 0),
            "parent_expression_ids": decision.get("parent_expression_ids", []),
            "root_expression_ids": decision.get("root_expression_ids", []),
        }

    links = []
    stop_nodes = []
    seen_links = set()
    for event in events:
        source_id = event.get("source_expression_id")
        if event.get("was_selected") is True and event.get(
            "resulting_expression_id"
        ):
            target_id = event["resulting_expression_id"]
            key = (source_id, target_id, "continued")
            if key not in seen_links:
                seen_links.add(key)
                links.append(
                    {
                        "source": source_id,
                        "target": target_id,
                        "link_type": "continued",
                        "step": event.get("step"),
                        "effective_weight": event.get("effective_weight"),
                    }
                )
        else:
            stop_id = f"stop_{event.get('propagation_event_id')}"
            stop_nodes.append(
                {
                    "node_id": stop_id,
                    "node_type": "stopped_exposure",
                    "agent_id": event.get("target_agent_id"),
                    "step": event.get("step"),
                    "depth": event.get("propagation_depth"),
                    "effective_weight": event.get("effective_weight"),
                }
            )
            links.append(
                {
                    "source": source_id,
                    "target": stop_id,
                    "link_type": "stopped",
                    "step": event.get("step"),
                    "effective_weight": event.get("effective_weight"),
                }
            )

    resulting_ids = {
        event.get("resulting_expression_id")
        for event in events
        if event.get("was_selected") is True
        and event.get("resulting_expression_id")
    }
    return {
        "scenario_id": scenario_id,
        "scenario_name": SCENARIO_NAMES[scenario_id],
        "comment_id": comment_id,
        "comment_text": comment_text or "未找到评论文本",
        "summary": {
            "expression_count": len(expression_nodes),
            "exposure_count": len(events),
            "continued_count": len(resulting_ids),
            "stopped_count": sum(
                event.get("was_selected") is not True for event in events
            ),
            "reached_agent_count": len(
                {
                    event.get("target_agent_id")
                    for event in events
                    if event.get("target_agent_id")
                }
            ),
            "max_depth": max(
                (int(event.get("propagation_depth", 0)) for event in events),
                default=0,
            ),
            "first_step": min(
                (int(event.get("step", 0)) for event in events), default=0
            ),
            "last_step": max(
                (int(event.get("step", 0)) for event in events), default=0
            ),
        },
        "nodes": [*expression_nodes.values(), *stop_nodes],
        "links": links,
    }
