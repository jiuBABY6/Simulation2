"""策略对照实验的共同输入固化与场景隔离检查。

2026/10/20，新增功能：对照实验只共享事件、初始评论、固定网络和
客观事实时间线，不再共享任何场景运行后生成的公众反应。模块使用稳定
SHA-256 指纹证明共同输入一致，并在场景结束后检查评论或状态是否误读了
其他场景的数据。

本模块不调用大模型、不决定 Agent 状态，也不修改实验结果；它只提供
确定性的输入规范化、指纹和审计能力。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from infrastructure.json_storage import read_jsonl
from simulation.event_state_updater import load_event_state_history
from simulation.state_manager import (
    EVENT_STATE_FILE_NAME,
    JSONL_STATE_FILE_NAMES,
)


CONTROL_VERSION = "counterfactual_inputs_v1"
# 2026/10/20，新增功能：直接复用状态管理模块声明的文件集合，避免
# 新增状态文件后反事实快照静默漏算。
STATE_SNAPSHOT_FILES = (
    EVENT_STATE_FILE_NAME,
    *JSONL_STATE_FILE_NAMES,
)


class CounterfactualIsolationError(RuntimeError):
    """表示共同输入或场景运行数据违反反事实隔离契约。"""


def stable_json_sha256(value) -> str:
    """返回与键顺序、缩进和中文转义无关的结构化数据哈希。"""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path) -> str:
    """流式计算文件哈希，避免把较大的评论池一次读入额外副本。"""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_objective_fact_timeline(event_input: dict) -> list[dict]:
    """规范化可选的逐轮客观事实，不接受公众情绪或方案评价。

    ``objective_event_timeline`` 可以直接是列表，也可以是包含 ``rounds``
    或 ``timeline`` 的对象。每项必须给出正整数 ``step``，事实正文放在
    ``objective_event_context``；为了便于人工配置，也允许直接提供
    ``events``，系统会包装为同名上下文。
    """

    if not isinstance(event_input, dict):
        raise ValueError("event_input 必须是 JSON 对象。")
    raw_timeline = event_input.get("objective_event_timeline", [])
    if isinstance(raw_timeline, dict):
        raw_timeline = raw_timeline.get(
            "rounds",
            raw_timeline.get("timeline", []),
        )
    if raw_timeline is None:
        raw_timeline = []
    if not isinstance(raw_timeline, list):
        raise ValueError("objective_event_timeline 必须是数组或包含rounds的对象。")

    normalized = []
    seen_steps = set()
    for index, item in enumerate(raw_timeline, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"objective_event_timeline 第 {index} 项必须是 JSON 对象。"
            )
        step = item.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError(
                f"objective_event_timeline 第 {index} 项缺少正整数step。"
            )
        if step in seen_steps:
            raise ValueError(f"objective_event_timeline 存在重复轮次：{step}。")
        seen_steps.add(step)

        context = item.get("objective_event_context")
        if context is None and "events" in item:
            context = {"events": item.get("events")}
        if not isinstance(context, dict):
            raise ValueError(
                f"objective_event_timeline 第 {step} 轮缺少"
                "objective_event_context对象。"
            )
        timing = item.get("objective_event_timing")
        if timing is None:
            timing = {
                key: item[key]
                for key in ("step", "period", "phase")
                if key in item
            }
        if timing is not None and not isinstance(timing, dict):
            raise ValueError(
                f"objective_event_timeline 第 {step} 轮的"
                "objective_event_timing必须是对象。"
            )
        record = {
            "step": step,
            "objective_event_context": context,
        }
        if timing:
            record["objective_event_timing"] = timing
        normalized.append(record)

    # 兼容已有首轮字段。显式时间线优先，避免同一轮出现两份事实。
    initial_context = event_input.get("objective_event_context")
    if isinstance(initial_context, dict) and 1 not in seen_steps:
        initial_record = {
            "step": 1,
            "objective_event_context": initial_context,
        }
        initial_timing = event_input.get("objective_event_timing")
        if isinstance(initial_timing, dict):
            initial_record["objective_event_timing"] = initial_timing
        normalized.append(initial_record)

    normalized.sort(key=lambda item: item["step"])
    return normalized


def objective_state_fields(timeline: list[dict], step: int) -> dict:
    """返回指定轮次应写入事件状态的客观事实字段。"""

    for record in timeline:
        if record.get("step") == step:
            result = {
                "objective_event_context": record["objective_event_context"],
            }
            if record.get("objective_event_timing") is not None:
                result["objective_event_timing"] = record[
                    "objective_event_timing"
                ]
            return result
    return {}


def build_shared_input_manifest(
    event_input,
    event_file,
    comment_pool_file,
    social_network_file,
) -> dict:
    """记录全部真正共享的输入，并生成单一共同输入指纹。"""

    timeline = normalize_objective_fact_timeline(event_input)
    components = {
        "event_input_sha256": file_sha256(event_file),
        "initial_comment_pool_sha256": file_sha256(comment_pool_file),
        "social_network_sha256": file_sha256(social_network_file),
        "objective_fact_timeline_sha256": stable_json_sha256(timeline),
    }
    return {
        "version": CONTROL_VERSION,
        "components": components,
        "shared_input_sha256": stable_json_sha256(components),
        "objective_fact_timeline": timeline,
    }


def build_state_snapshot_manifest(state_dir) -> dict:
    """为官方进场前快照生成文件级指纹，证明所有场景从同一点分叉。"""

    state_path = Path(state_dir)
    files = {}
    for file_name in STATE_SNAPSHOT_FILES:
        path = state_path / file_name
        if not path.is_file():
            raise FileNotFoundError(f"共享基线缺少状态文件：{path}")
        files[file_name] = file_sha256(path)
    return {
        "files": files,
        "snapshot_sha256": stable_json_sha256(files),
    }


def build_scenario_input_sha256(shared_input_sha256, scenario_id, response) -> str:
    """组合共同输入和本场景唯一干预，便于复现实验。"""

    evidence_dimensions = response.get(
        "official_evidence_dimensions",
        response.get("evidence_dimensions", {}),
    )
    return stable_json_sha256(
        {
            "shared_input_sha256": shared_input_sha256,
            "scenario_id": scenario_id,
            "official_statement": response.get("official_statement", ""),
            "official_statement_status": response.get(
                "official_statement_status", "none"
            ),
            # 2026/10/20，修改功能：人工声明的通告语义维度也是场景
            # 干预输入，必须进入指纹，不能只哈希正文和状态。
            "official_evidence_dimensions": (
                dict(evidence_dimensions)
                if isinstance(evidence_dimensions, dict)
                else {}
            ),
        }
    )


def audit_scenario_isolation(
    *,
    state_dir,
    event_id,
    scenario_id,
    response_step,
    shared_input_sha256,
    objective_fact_timeline,
    expected_response,
) -> dict:
    """检查通告投入后的状态、评论和共同事实是否发生跨场景污染。"""

    if not isinstance(response_step, int):
        return {
            "status": "not_applicable",
            "checked_from_step": None,
            "error_count": 0,
            "errors": [],
        }

    errors = []
    state_path = Path(state_dir)
    expected_statement = str(
        expected_response.get("official_statement", "")
    ).strip()
    expected_status = expected_response.get(
        "official_statement_status", "none"
    )
    expected_dimensions = expected_response.get(
        "official_evidence_dimensions",
        expected_response.get("evidence_dimensions", {}),
    )
    if not isinstance(expected_dimensions, dict):
        expected_dimensions = {}
    expected_facts = {
        item["step"]: objective_state_fields(objective_fact_timeline, item["step"])
        for item in objective_fact_timeline
    }

    state_records = load_event_state_history(
        state_path / "event_state_history.json",
        event_id,
    )
    for record in state_records:
        step = record.get("step")
        if not isinstance(step, int) or step < response_step:
            continue
        if record.get("scenario_id") != scenario_id:
            errors.append(f"第{step}轮事件状态scenario_id不属于当前场景。")
        if record.get("shared_input_sha256") != shared_input_sha256:
            errors.append(f"第{step}轮事件状态共同输入哈希不一致。")
        if str(record.get("official_statement", "")).strip() != expected_statement:
            errors.append(f"第{step}轮读取了非当前场景的官方声明。")
        if record.get("official_statement_status") != expected_status:
            errors.append(f"第{step}轮官方声明状态不属于当前场景。")
        if record.get("official_evidence_dimensions", {}) != expected_dimensions:
            errors.append(f"第{step}轮官方声明语义维度不属于当前场景。")

        fact_fields = expected_facts.get(step, {})
        for field in (
            "objective_event_context",
            "objective_event_timing",
        ):
            if record.get(field) != fact_fields.get(field):
                errors.append(f"第{step}轮共享客观事实字段{field}不一致。")

    incremental_records = [
        record
        for record in read_jsonl(
            state_path / "incremental_comment_history.jsonl"
        )
        if record.get("event_id") == event_id
        and isinstance(record.get("step"), int)
        and record["step"] >= response_step
    ]
    for record in incremental_records:
        step = record["step"]
        if record.get("scenario_id") != scenario_id:
            errors.append(f"第{step}轮公众反应记录来自其他场景。")
        if record.get("shared_input_sha256") != shared_input_sha256:
            errors.append(f"第{step}轮公众反应共同输入哈希不一致。")
        generation_mode = record.get("generation_mode")
        if record.get("shared_external_context") is True or generation_mode == (
            "shared_exogenous_context"
        ):
            errors.append(f"第{step}轮仍包含已禁止的共享公众评论。")
        if generation_mode not in {
            "scenario_reactive_public",
            "disabled_by_ablation",
        }:
            errors.append(
                f"第{step}轮公众反应没有使用场景独立生成模式。"
            )
        for comment in record.get("comments", []):
            if not isinstance(comment, dict):
                continue
            if comment.get("scenario_id") != scenario_id:
                errors.append(f"第{step}轮评论来自其他场景。")
                break
            if comment.get("shared_input_sha256") != shared_input_sha256:
                errors.append(f"第{step}轮评论共同输入哈希不一致。")
                break
            if comment.get("causal_origin") != "scenario_reactive_public":
                errors.append(f"第{step}轮评论缺少场景反应来源标记。")
                break

    result = {
        "status": "passed" if not errors else "failed",
        "checked_from_step": response_step,
        "event_state_count": len(
            [
                item
                for item in state_records
                if isinstance(item.get("step"), int)
                and item["step"] >= response_step
            ]
        ),
        "public_reaction_record_count": len(incremental_records),
        "public_reaction_sha256": stable_json_sha256(incremental_records),
        "error_count": len(errors),
        "errors": errors,
    }
    if errors:
        raise CounterfactualIsolationError(
            f"场景 {scenario_id} 跨场景污染检查失败：" + "；".join(errors)
        )
    return result


def audit_cross_scenario_controls(strategy_results: list[dict]) -> dict:
    """检查场景目录、共同输入指纹和场景输入指纹是否相互独立。"""

    successful = [
        item for item in strategy_results if item.get("status") == "success"
    ]
    errors = []
    failed_scenario_audits = [
        str(item.get("strategy", "unknown"))
        for item in strategy_results
        if item.get("failure_type") == "isolation_audit"
    ]
    if failed_scenario_audits:
        errors.append(
            "以下场景已被场景级污染检查拦截："
            + "、".join(failed_scenario_audits)
        )
    state_dirs = [
        str(Path(item.get("state_dir", "")).resolve())
        for item in successful
    ]
    if len(state_dirs) != len(set(state_dirs)):
        errors.append("两个或多个场景复用了同一个状态目录。")

    shared_hashes = {
        item.get("counterfactual_controls", {}).get("shared_input_sha256")
        for item in successful
    }
    if len(shared_hashes) > 1 or None in shared_hashes:
        errors.append("场景之间的共同输入哈希不一致或缺失。")

    scenario_hashes = [
        item.get("counterfactual_controls", {}).get("scenario_input_sha256")
        for item in successful
    ]
    if None in scenario_hashes or len(scenario_hashes) != len(set(scenario_hashes)):
        errors.append("场景输入指纹缺失或不同干预生成了相同指纹。")

    failed_audits = [
        item.get("strategy")
        for item in successful
        if item.get("counterfactual_controls", {})
        .get("isolation_audit", {})
        .get("status")
        not in {"passed", "not_applicable"}
    ]
    if failed_audits:
        errors.append("以下场景未通过隔离检查：" + "、".join(failed_audits))

    result = {
        "status": "passed" if not errors else "failed",
        "scenario_count": len(successful),
        "shared_input_sha256": (
            next(iter(shared_hashes)) if len(shared_hashes) == 1 else None
        ),
        "state_directories_are_distinct": len(state_dirs) == len(set(state_dirs)),
        "scenario_inputs_are_distinct": (
            None not in scenario_hashes
            and len(scenario_hashes) == len(set(scenario_hashes))
        ),
        "error_count": len(errors),
        "errors": errors,
    }
    if errors:
        raise CounterfactualIsolationError(
            "跨场景污染检查失败：" + "；".join(errors)
        )
    return result
