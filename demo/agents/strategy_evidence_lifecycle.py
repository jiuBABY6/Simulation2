"""回应方案状态证据的个体生命周期管理。

2026/10/19，新增功能：官方或客观证据不再只在投入当轮有效，也不会
在后续每轮被当作全新证据重复施加。每个 Agent 通过上一轮动态状态
保存有限的证据记忆；未推动状态变化的权威证据最多保留两轮递减影响，
一旦实际推动情绪变化，就标记为已消费并停止继续推动。

本模块只处理调用方传入的普通字典，不读写文件、不调用 LLM，也不理解
具体公告文本。语义判断仍由 ``strategy_evidence_integrator`` 负责。
"""

from __future__ import annotations

from copy import deepcopy


MAX_EVIDENCE_MEMORY_GROUPS = 48


def _safe_step(value):
    return value if isinstance(value, int) and value >= 1 else None


def _memory_from_state(previous_state):
    """读取并复制合法记忆，避免决策过程修改调用方状态。"""

    if not isinstance(previous_state, dict):
        return {}
    raw = previous_state.get("strategy_evidence_memory", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(group_id): deepcopy(entry)
        for group_id, entry in raw.items()
        if group_id and isinstance(entry, dict)
    }


def update_evidence_memory(
    previous_state,
    current_step,
    new_groups,
    consumed_group_ids=(),
):
    """生成下一轮状态要保存的有限证据记忆。

    只长期保存权威证据和已经实际推动过状态变化的传播根。这样既能
    阻止同一根重复推动，也不会把每轮所有公共评论永久写入状态文件。
    """

    step = _safe_step(current_step)
    memory = _memory_from_state(previous_state)
    consumed = {
        str(group_id) for group_id in consumed_group_ids if group_id
    }

    for group in new_groups:
        group_id = str(group.get("evidence_group_id", "")).strip()
        if not group_id:
            continue
        source_kinds = set(group.get("source_kinds", []))
        authoritative = "authoritative" in source_kinds
        if not authoritative and group_id not in consumed:
            continue
        old = memory.get(group_id, {})
        memory[group_id] = {
            "evidence_group_id": group_id,
            "evidence_ids": list(group.get("evidence_ids", [])),
            "source_kind": (
                "authoritative" if authoritative else "social"
            ),
            "source_kinds": sorted(source_kinds),
            "first_seen_step": (
                _safe_step(old.get("first_seen_step")) or step
            ),
            "last_seen_step": step,
            "directional_support": dict(
                group.get("base_directional_support")
                or group.get("directional_support", {})
            ),
            "supporting_id_by_emotion": dict(
                group.get("supporting_id_by_emotion", {})
            ),
            "positive_eligible": bool(
                group.get("positive_eligible", False)
            ),
            "semantic_dimensions": list(
                group.get("semantic_dimensions", [])
            ),
            "emotion_consumed": (
                old.get("emotion_consumed") is True
                or group_id in consumed
            ),
        }

    for group_id in consumed:
        if group_id in memory:
            memory[group_id]["emotion_consumed"] = True
            memory[group_id]["last_seen_step"] = step

    # 过期且未消费的证据没有继续保留的意义；已消费根短期保留用于防止
    # 重复传播，整体再按最近时间裁剪，控制 JSONL 状态体积。
    retained = []
    for group_id, entry in memory.items():
        first_seen = _safe_step(entry.get("first_seen_step"))
        last_seen = _safe_step(entry.get("last_seen_step")) or first_seen
        age = step - first_seen if step is not None and first_seen else 0
        consumed_age = step - last_seen if step is not None and last_seen else 0
        if entry.get("emotion_consumed") is True:
            if consumed_age <= 6:
                retained.append((group_id, entry))
        elif entry.get("source_kind") == "authoritative" and age <= 2:
            retained.append((group_id, entry))

    retained.sort(
        key=lambda pair: (
            _safe_step(pair[1].get("last_seen_step")) or 0,
            pair[0],
        ),
        reverse=True,
    )
    return dict(retained[:MAX_EVIDENCE_MEMORY_GROUPS])

