"""回应方案中官方态度证据的独立跨轮生命周期。

2026/10/19，新增功能：官方态度不再复用情绪证据的“消费后失效”规则。
事实支持、过程回应和未解决关切按声明目标分别保存；旧证据只构成当前
认知背景，只有本轮新增且未处理过的证据才能触发态度变化。

本模块不判断最终态度、不读取文件、不调用LLM。它只维护有限记忆并把
当前证据与仍有效的历史证据组合，供 ``official_attitude`` 统一裁决。
"""

from __future__ import annotations

from copy import deepcopy


MAX_ATTITUDE_MEMORY_ITEMS = 48
AUTHORITATIVE_RETENTION_ROUNDS = 8
SOCIAL_RETENTION_ROUNDS = 2
AUTHORITATIVE_DECAY = 0.92
SOCIAL_DECAY = 0.55

ATTITUDE_TARGETS = {
    "official_claim",
    "official_response",
    "investigation_process",
    "accountability",
    "process_accountability",
    "fact_clarification",
    "event_outcome",
    "identity_confirmation",
    "forensic_result",
}

AUTHORITATIVE_SOURCE_TYPES = {"official", "event", "media", "expert", "witness"}


def _safe_step(value):
    return value if isinstance(value, int) and value >= 1 else None


def _memory_from_state(previous_state):
    if not isinstance(previous_state, dict):
        return {}
    raw = previous_state.get("strategy_attitude_memory", {})
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): deepcopy(value)
        for key, value in raw.items()
        if key and isinstance(value, dict)
    }


def _attitude_key(item):
    evidence_id = str(item.get("evidence_id", "")).strip()
    group_id = str(
        item.get("claim_id")
        or item.get("evidence_group_id", evidence_id)
    ).strip()
    target = str(item.get("reaction_target") or item.get("evidence_target") or "")
    # 2026/10/19，修改功能：同一主张、同一判断目标只保留最新阶段。
    # ``question -> clarify`` 是问题被回应的生命周期变化，不是两条应永久
    # 并存的证据；否则旧关切会在已经澄清后继续重复推高质疑信号。
    return "|".join((group_id or evidence_id, target))


def _is_relevant(item):
    target = str(item.get("reaction_target") or item.get("evidence_target") or "")
    role = str(item.get("evidence_role", "opinion"))
    if target not in ATTITUDE_TARGETS:
        return False
    # 公众个人意见可以影响关注和情绪，但不能单独建立事实接受。
    source_type = str(item.get("information_source_type", "public"))
    if role in {"support", "clarify"} and source_type not in AUTHORITATIVE_SOURCE_TYPES:
        return False
    return role in {"support", "clarify", "contradict", "question"}


def _memory_snapshot(item, current_step):
    evidence_id = str(item.get("evidence_id", "")).strip()
    impact = item.get("personal_impact", {})
    return {
        "memory_key": _attitude_key(item),
        "evidence_id": evidence_id,
        "evidence_group_id": str(item.get("evidence_group_id", evidence_id)),
        "evidence_type": item.get("evidence_type"),
        "content": str(item.get("content", "")),
        "reaction_target": item.get("reaction_target") or item.get("evidence_target"),
        "evidence_target": item.get("reaction_target") or item.get("evidence_target"),
        "evidence_role": item.get("evidence_role", "opinion"),
        "information_source_type": item.get("information_source_type", "public"),
        "information_origin": item.get("information_origin", "exogenous"),
        "evidence_strength": item.get("evidence_strength", "weak"),
        "unresolved_concern": bool(item.get("unresolved_concern", False)),
        "first_seen_step": current_step,
        "last_seen_step": current_step,
        "personal_impact": {
            "official_attitude_score": float(
                impact.get("official_attitude_score", 0.0) or 0.0
            )
        },
    }


def _restore_item(entry, current_step):
    first_seen = _safe_step(entry.get("first_seen_step")) or current_step
    age = max(0, current_step - first_seen)
    source_type = str(entry.get("information_source_type", "public"))
    authoritative = source_type in AUTHORITATIVE_SOURCE_TYPES
    retention = (
        AUTHORITATIVE_RETENTION_ROUNDS
        if authoritative
        else SOCIAL_RETENTION_ROUNDS
    )
    if age > retention:
        return None
    decay = AUTHORITATIVE_DECAY if authoritative else SOCIAL_DECAY
    restored = deepcopy(entry)
    base_score = float(
        restored.get("personal_impact", {}).get(
            "official_attitude_score", 0.0
        )
        or 0.0
    )
    restored["personal_impact"] = {
        "official_attitude_score": round(base_score * (decay ** age), 6)
    }
    restored["is_new_this_step"] = False
    restored["restored_from_attitude_memory"] = True
    restored["attitude_memory_age"] = age
    return restored


def prepare_attitude_evidence(previous_state, current_step, appraised_evidence):
    """组合本轮新增证据与仍有效的态度记忆，并返回下一轮记忆。"""

    step = _safe_step(current_step)
    if step is None:
        return {
            "evidence_items": [],
            "memory": {},
            "diagnostics": {"active_count": 0, "new_count": 0, "restored_count": 0},
        }

    memory = _memory_from_state(previous_state)
    current_items = []
    current_keys = set()
    for item in appraised_evidence or []:
        if not isinstance(item, dict) or not _is_relevant(item):
            continue
        key = _attitude_key(item)
        if not key:
            continue
        current_keys.add(key)
        if item.get("is_new_this_step") is True:
            snapshot = _memory_snapshot(item, step)
            old = memory.get(key)
            if isinstance(old, dict):
                snapshot["first_seen_step"] = (
                    _safe_step(old.get("first_seen_step")) or step
                )
            memory[key] = snapshot
            current_items.append(dict(item))
        elif key not in memory:
            # 升级前的旧状态可能没有态度记忆；可把持续声明作为背景写入，
            # 但绝不把它标成新证据触发变化。
            memory[key] = _memory_snapshot(item, step)

    restored = []
    retained = {}
    for key, entry in memory.items():
        item = _restore_item(entry, step)
        if item is None:
            continue
        retained[key] = entry
        if key not in current_keys or not any(
            _attitude_key(current) == key for current in current_items
        ):
            restored.append(item)

    ordered = sorted(
        retained.items(),
        key=lambda pair: (
            _safe_step(pair[1].get("last_seen_step")) or 0,
            pair[0],
        ),
        reverse=True,
    )[:MAX_ATTITUDE_MEMORY_ITEMS]
    memory = dict(ordered)
    return {
        "evidence_items": [*current_items, *restored],
        "memory": memory,
        "diagnostics": {
            "active_count": len(current_items) + len(restored),
            "new_count": len(current_items),
            "restored_count": len(restored),
            "memory_count": len(memory),
        },
    }
