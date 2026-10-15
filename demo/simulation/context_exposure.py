"""为单个 Agent 构造可复现的历史公众语境曝光。

已核实事实属于公共广播；公众讨论和建设性证据属于个体信息曝光。
本模块只负责拆分与抽样，不负责 Agent 决策或文件读写。
"""

from __future__ import annotations

import copy
import hashlib


PERSONAL_CONTEXT_GROUPS = {
    "public_discourse": ("context_id", "public_discourse_reach_rate"),
    "positive_evidence": ("evidence_id", "positive_evidence_reach_rate"),
}


def _is_exposed(event_id, step, agent_id, evidence_id, reach_rate):
    """使用稳定哈希完成伯努利抽样，重跑同一批次得到相同曝光。"""

    if reach_rate <= 0:
        return False
    if reach_rate >= 1:
        return True
    seed = f"{event_id}:{step}:{agent_id}:{evidence_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    ratio = int.from_bytes(digest[:8], "big") / float(2**64)
    return ratio < reach_rate


def personalize_event_context(event_context, agent_id):
    """返回不共享内部引用的 Agent 事件视图和实际语境证据编号。"""

    personalized = copy.deepcopy(event_context)
    state = personalized.get("current_state", {})
    public_context = state.get("public_context")
    if not isinstance(public_context, dict):
        return personalized, []

    options = personalized.get("simulation_options", {})
    exposure = options.get("context_exposure", {})
    event_id = personalized.get("event_id", "")
    step = state.get("step")
    visible_ids = []
    personal_context = {}

    # 2026/10/12，个体语境曝光：同一轮客观事实仍广播给所有 Agent，
    # 只有争议讨论与建设性证据按事件、轮次和 Agent 稳定抽样。
    for group_name, (id_field, rate_field) in PERSONAL_CONTEXT_GROUPS.items():
        rate = float(exposure.get(rate_field, 1.0))
        selected = []
        for item in public_context.get(group_name, []):
            if not isinstance(item, dict):
                continue
            evidence_id = str(item.get(id_field, "")).strip()
            if not evidence_id:
                continue
            if _is_exposed(event_id, step, agent_id, evidence_id, rate):
                selected.append(copy.deepcopy(item))
                visible_ids.append(evidence_id)
        personal_context[group_name] = selected

    shared_context = copy.deepcopy(public_context)
    shared_context.pop("public_discourse", None)
    shared_context.pop("positive_evidence", None)
    state["public_context"] = shared_context
    state["individual_public_context"] = personal_context
    return personalized, visible_ids
