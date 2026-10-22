"""策略对照实验的证据作用通道路由。

2026/10/20，新增功能：评论的情绪标签只描述其公开表达方式，不能直接
决定它改变哪一种内部状态。本模块根据 ``reaction_target``、证据角色和
信息来源，把证据分别路由到事件情绪、官方态度与公开参与三个通道。

模块只返回确定性的通道权重，不读取文件、不调用 LLM，也不设置任何
群体目标。历史复现继续使用自己的证据规则，不依赖本模块。
"""

from __future__ import annotations


# 目标权重描述“该话题与哪个状态有关”，不描述证据真伪或最终结论。
# 对官方过程的批评主要进入官方态度；公共讨论热度主要进入参与通道。
TARGET_CHANNEL_WEIGHTS = {
    "event_harm": (1.00, 0.05, 0.55),
    "victim_support": (0.70, 0.20, 0.80),
    "event_outcome": (1.00, 0.65, 0.55),
    "identity_confirmation": (0.45, 0.80, 0.35),
    "forensic_result": (0.80, 0.80, 0.45),
    # 已核实事实既会影响对官方可信度的判断，也可能真实改变公众对
    # 事件后果的感受，因此保留较高的事件情绪通道；与仅描述调查过程
    # 的通告区分，后者仍主要进入官方态度通道。
    "fact_clarification": (0.85, 0.85, 0.40),
    "official_claim": (0.10, 1.00, 0.45),
    "official_response": (0.15, 1.00, 0.45),
    "investigation_process": (0.12, 1.00, 0.50),
    "accountability": (0.25, 1.00, 0.65),
    "process_accountability": (0.20, 1.00, 0.60),
    "public_discourse": (0.00, 0.10, 1.00),
    "social_action": (0.35, 0.10, 1.00),
}


def _bounded(value, default=0.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0.0, min(1.0, float(value)))


def _target(item):
    """返回显式证据目标；旧记录缺少目标时保留原有事件情绪语义。"""

    value = str(
        item.get("reaction_target")
        or item.get("evidence_target")
        or ""
    ).strip()
    if value:
        return value
    # 兼容早期评论和离线测试：旧数据没有语义目标时，不能在升级后
    # 静默变成完全无效证据。新运行会由统一语义契约显式补齐目标。
    if item.get("evidence_type") == "simulated_comment":
        return "event_harm"
    return "official_response"


def route_evidence_impact(item):
    """返回证据对三个状态通道的有界权重和审计原因。"""

    target = _target(item)
    raw = TARGET_CHANNEL_WEIGHTS.get(target, (0.10, 0.20, 0.50))
    event_weight, attitude_weight, participation_weight = raw
    role = str(item.get("evidence_role", "opinion")).strip()
    source = str(item.get("information_source_type", "public")).strip()

    # 针对官方过程的提问不能等价为对原始事件的负面情绪；它仍然可以
    # 强烈影响 question/wait，并提高公开讨论意愿。
    if role in {"question", "contradict"} and target in {
        "official_claim",
        "official_response",
        "investigation_process",
        "accountability",
        "process_accountability",
    }:
        event_weight *= 0.35
        attitude_weight = min(1.0, attitude_weight * 1.05)
        participation_weight = min(1.0, participation_weight * 1.10)

    # 普通公众观点不能因为自称“澄清”就取得与官方或客观事实相同的
    # 事件情绪作用；事实强度仍由上游 evidence_policy 独立控制。
    if source in {"public", "agent"} and role == "clarify":
        event_weight *= 0.75

    return {
        "target": target,
        "event_emotion": round(_bounded(event_weight), 6),
        "official_attitude": round(_bounded(attitude_weight), 6),
        "participation": round(_bounded(participation_weight), 6),
        "routing_reason": f"target:{target};role:{role or 'opinion'}",
    }


def route_emotion_support(item, support):
    """只保留真正能够影响事件情绪的方向性支持。"""

    routing = route_evidence_impact(item)
    weight = routing["event_emotion"]
    normalized = {
        emotion: round(_bounded(value) * weight, 6)
        for emotion, value in support.items()
    }
    return normalized, routing
