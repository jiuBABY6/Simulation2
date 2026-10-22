"""回应方案权威证据的有限渐进吸收。

2026/10/20，新增功能：保持公开状态为 ``positive / neutral / negative``
离散值，但允许不同 Persona 在最多三轮内以不同速度处理同一份权威证据。
这解决一次性硬阈值造成的“当轮改变或永久冻结”，同时通过剩余潜力、
到期和消费标记阻止同一通告无限重复推动状态。

本模块只操作普通字典，不读取文件、不调用 LLM，也不决定最终情绪。
"""

from __future__ import annotations

from copy import deepcopy


ASSIMILATION_AGE_WEIGHTS = {0: 1.0, 1: 0.65, 2: 0.35}
MAX_ASSIMILATION_GROUPS = 48
CONSUMED_RETENTION_ROUNDS = 6


def _bounded(value, default=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _safe_step(value):
    return value if isinstance(value, int) and value >= 1 else None


def _memory_from_state(previous_state):
    if not isinstance(previous_state, dict):
        return {}
    raw = previous_state.get("strategy_evidence_assimilation", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(group_id): deepcopy(entry)
        for group_id, entry in raw.items()
        if group_id and isinstance(entry, dict)
    }


def _legacy_consumed_groups(previous_state):
    """读取旧生命周期消费标记，保证新机制兼容已有状态快照。"""

    raw = (
        previous_state.get("strategy_evidence_memory", {})
        if isinstance(previous_state, dict)
        else {}
    )
    if not isinstance(raw, dict):
        return set()
    return {
        str(group_id)
        for group_id, entry in raw.items()
        if isinstance(entry, dict) and entry.get("emotion_consumed") is True
    }


def persona_assimilation_rate(profile, group):
    """从稳定Persona画像推导本组证据的处理速度，不使用群体配额。"""

    profile = profile if isinstance(profile, dict) else {}
    orientation = profile.get("orientation", {})
    orientation = orientation if isinstance(orientation, dict) else {}
    fact = _bounded(orientation.get("fact"), 1 / 3)
    opinion = _bounded(orientation.get("opinion"), 1 / 3)
    questioning = _bounded(orientation.get("questioning"), 1 / 3)
    topic_interest = _bounded(profile.get("topic_interest"), 0.5)
    inertia = _bounded(profile.get("state_inertia"), 0.55)
    dimensions = set(group.get("semantic_dimensions", []))
    evidence_types = set(group.get("evidence_types", []))
    max_strength = str(group.get("max_evidence_strength", "background"))

    rate = (
        0.27
        + 0.26 * fact
        + 0.10 * opinion
        + 0.12 * topic_interest
        - 0.16 * inertia
        - 0.08 * questioning
    )
    if "completed_action" in dimensions or "verified_fact" in dimensions:
        rate += 0.08
    # 客观事实不是“官方说法的重复曝光”。强客观更新对高事实导向者
    # 可以在首轮被较快吸收，但仍保留Persona惯性和状态切换边际，避免
    # 退回“所有人看到同一事实就同步转向”的硬规则。
    if (
        evidence_types
        & {"objective_event", "historical_verified_update"}
        and max_strength == "strong"
    ):
        rate += 0.16
    if "unresolved_process" in dimensions:
        rate -= 0.04
    return round(max(0.20, min(0.72, rate)), 6)


def _new_entry(group, current_step):
    group_id = str(group.get("evidence_group_id", "")).strip()
    return {
        "evidence_group_id": group_id,
        "evidence_ids": list(group.get("evidence_ids", [])),
        "source_kinds": list(group.get("source_kinds", ["authoritative"])),
        "first_seen_step": current_step,
        "last_processed_step": None,
        "last_seen_step": current_step,
        "base_directional_support": dict(
            group.get("base_directional_support")
            or group.get("directional_support", {})
        ),
        "supporting_id_by_emotion": dict(
            group.get("supporting_id_by_emotion", {})
        ),
        "positive_eligible": bool(group.get("positive_eligible", False)),
        "semantic_dimensions": list(group.get("semantic_dimensions", [])),
        "evidence_types": list(group.get("evidence_types", [])),
        "max_evidence_strength": str(
            group.get("max_evidence_strength", "background")
        ),
        "absorbed_fraction": 0.0,
        "remaining_potential": 1.0,
        "emotion_consumed": False,
    }


def _effective_group(entry, age, rate, increment, restored):
    absorbed = _bounded(entry.get("absorbed_fraction"))
    base = entry.get("base_directional_support", {})
    return {
        "evidence_group_id": entry["evidence_group_id"],
        "evidence_ids": list(entry.get("evidence_ids", [])),
        "source_kinds": list(entry.get("source_kinds", ["authoritative"])),
        "directional_support": {
            emotion: round(_bounded(value) * absorbed, 6)
            for emotion, value in base.items()
        },
        "base_directional_support": dict(base),
        "supporting_id_by_emotion": dict(
            entry.get("supporting_id_by_emotion", {})
        ),
        "positive_eligible": bool(entry.get("positive_eligible", False)),
        "semantic_dimensions": list(entry.get("semantic_dimensions", [])),
        "evidence_types": list(entry.get("evidence_types", [])),
        "max_evidence_strength": str(
            entry.get("max_evidence_strength", "background")
        ),
        "lifecycle_state": "assimilating",
        "lifecycle_age": age,
        "assimilation_rate": rate,
        "absorbed_fraction": round(absorbed, 6),
        "remaining_potential": round(
            _bounded(entry.get("remaining_potential")),
            6,
        ),
        "absorbed_this_step": round(increment, 6),
        "restored_from_memory": restored,
    }


def prepare_assimilated_groups(
    previous_state,
    current_step,
    new_groups,
    profile,
):
    """返回本轮有效证据组、下一状态记忆与渐进吸收诊断。

    社会评论仍只在真实传播窗口内作用；只有官方或客观权威证据进入
    跨轮吸收。调用方在完成状态裁决后应调用 ``consume_groups``。
    """

    step = _safe_step(current_step)
    if step is None:
        # 离线旧调用缺少时间步时保持原行为，避免升级静默改变测试和工具。
        return {
            "groups": list(new_groups),
            "memory": _memory_from_state(previous_state),
            "diagnostics": {
                "active_group_count": 0,
                "new_group_count": 0,
                "restored_group_count": 0,
                "expired_group_count": 0,
                "average_absorbed_fraction": None,
            },
        }

    memory = _memory_from_state(previous_state)
    consumed = _legacy_consumed_groups(previous_state)
    social_groups = []
    incoming_authoritative = {}
    for group in new_groups:
        group_id = str(group.get("evidence_group_id", "")).strip()
        if not group_id or group_id in consumed:
            continue
        if "authoritative" not in set(group.get("source_kinds", [])):
            social_groups.append(group)
            continue
        incoming_authoritative[group_id] = group

    new_count = 0
    for group_id, group in incoming_authoritative.items():
        if group_id not in memory:
            memory[group_id] = _new_entry(group, step)
            new_count += 1
        else:
            # 同一权威事实重新出现在输入中只刷新可审计元数据，不重置
            # 已吸收比例或首次出现时间。
            entry = memory[group_id]
            entry["last_seen_step"] = step
            entry["evidence_ids"] = list(group.get("evidence_ids", []))
            entry["base_directional_support"] = dict(
                group.get("base_directional_support")
                or group.get("directional_support", {})
            )
            entry["supporting_id_by_emotion"] = dict(
                group.get("supporting_id_by_emotion", {})
            )
            entry["semantic_dimensions"] = list(
                group.get("semantic_dimensions", [])
            )
            entry["evidence_types"] = list(
                group.get("evidence_types", [])
            )
            entry["max_evidence_strength"] = str(
                group.get("max_evidence_strength", "background")
            )

    effective = list(social_groups)
    restored_count = 0
    expired_count = 0
    active_fractions = []
    for group_id, entry in list(memory.items()):
        if entry.get("emotion_consumed") is True:
            continue
        first_seen = _safe_step(entry.get("first_seen_step"))
        if first_seen is None:
            del memory[group_id]
            continue
        age = step - first_seen
        age_weight = ASSIMILATION_AGE_WEIGHTS.get(age)
        if age_weight is None:
            expired_count += 1
            del memory[group_id]
            continue
        if age > 0:
            restored_count += 1

        proxy_group = {
            "semantic_dimensions": entry.get("semantic_dimensions", []),
            "evidence_types": entry.get("evidence_types", []),
            "max_evidence_strength": entry.get(
                "max_evidence_strength",
                "background",
            ),
        }
        rate = persona_assimilation_rate(profile, proxy_group)
        increment = 0.0
        if entry.get("last_processed_step") != step:
            remaining = _bounded(entry.get("remaining_potential"), 1.0)
            increment = remaining * rate * age_weight
            absorbed = min(
                1.0,
                _bounded(entry.get("absorbed_fraction")) + increment,
            )
            entry["absorbed_fraction"] = round(absorbed, 6)
            entry["remaining_potential"] = round(1.0 - absorbed, 6)
            entry["last_processed_step"] = step
        active_fractions.append(_bounded(entry.get("absorbed_fraction")))
        effective.append(
            _effective_group(entry, age, rate, increment, age > 0)
        )

    return {
        "groups": effective,
        "memory": memory,
        "diagnostics": {
            "active_group_count": len(active_fractions),
            "new_group_count": new_count,
            "restored_group_count": restored_count,
            "expired_group_count": expired_count,
            "average_absorbed_fraction": (
                round(sum(active_fractions) / len(active_fractions), 6)
                if active_fractions
                else None
            ),
        },
    }


def consume_groups(memory, consumed_group_ids, current_step):
    """标记真正推动状态变化的证据组，并裁剪有界记忆。"""

    step = _safe_step(current_step)
    normalized = deepcopy(memory) if isinstance(memory, dict) else {}
    consumed = {str(value) for value in consumed_group_ids if value}
    for group_id in consumed:
        if group_id not in normalized:
            continue
        normalized[group_id]["emotion_consumed"] = True
        normalized[group_id]["consumed_step"] = step
        normalized[group_id]["remaining_potential"] = 0.0

    retained = []
    for group_id, entry in normalized.items():
        first_seen = _safe_step(entry.get("first_seen_step"))
        consumed_step = _safe_step(entry.get("consumed_step"))
        if entry.get("emotion_consumed") is True:
            if step is None or consumed_step is None or step - consumed_step <= CONSUMED_RETENTION_ROUNDS:
                retained.append((group_id, entry))
            continue
        if step is None or first_seen is None or step - first_seen <= 2:
            retained.append((group_id, entry))

    retained.sort(
        key=lambda pair: (
            _safe_step(pair[1].get("last_processed_step")) or 0,
            pair[0],
        ),
        reverse=True,
    )
    return dict(retained[:MAX_ASSIMILATION_GROUPS])
