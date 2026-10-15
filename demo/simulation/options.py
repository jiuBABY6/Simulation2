"""仿真事件级可选行为配置。

本模块只负责配置校验和默认值，不读取文件，也不区分具体事件。
未显式配置的事件保持现有策略约束，避免历史复现增强影响五策略实验。
"""

from __future__ import annotations

from project_config import INCREMENTAL_COMMENT_COUNT, VISIBLE_COMMENT_COUNT


EMOTION_CHOICE_POLICY_CONSTRAINED = "policy_constrained"
EMOTION_CHOICE_EVIDENCE_BASED_ALL = "evidence_based_all"
VALID_EMOTION_CHOICE_MODES = {
    EMOTION_CHOICE_POLICY_CONSTRAINED,
    EMOTION_CHOICE_EVIDENCE_BASED_ALL,
}
DEFAULT_ACTIVE_OPINION_WINDOW = 2
MAX_INCREMENTAL_COMMENT_COUNT = 200
DEFAULT_HISTORICAL_NEIGHBORS_PER_AGENT = 5
DEFAULT_HISTORICAL_NEIGHBOR_COMMENT_COUNT = 4
DEFAULT_HISTORICAL_PUBLIC_COMMENT_COUNT = 11
DEFAULT_PUBLIC_DISCOURSE_REACH_RATE = 0.65
DEFAULT_POSITIVE_EVIDENCE_REACH_RATE = 0.50


# 2026/10/9，新增功能：集中校验事件级仿真开关，未配置事件继续使用原有行为。
def normalize_simulation_options(event_input: dict | None) -> dict:
    """返回稳定的事件级配置，拒绝会造成运行歧义的非法值。"""

    payload = event_input if isinstance(event_input, dict) else {}
    raw_options = payload.get("simulation_options", {})
    if raw_options is None:
        raw_options = {}
    if not isinstance(raw_options, dict):
        raise ValueError("simulation_options 必须是 JSON 对象。")

    emotion_choice_mode = str(
        raw_options.get(
            "emotion_choice_mode",
            EMOTION_CHOICE_POLICY_CONSTRAINED,
        )
    ).strip()
    if emotion_choice_mode not in VALID_EMOTION_CHOICE_MODES:
        raise ValueError(
            "simulation_options.emotion_choice_mode 只能是 "
            "policy_constrained 或 evidence_based_all。"
        )

    incremental_comment_count = raw_options.get(
        "incremental_comment_count",
        INCREMENTAL_COMMENT_COUNT,
    )
    if (
        isinstance(incremental_comment_count, bool)
        or not isinstance(incremental_comment_count, int)
        or not 1 <= incremental_comment_count <= MAX_INCREMENTAL_COMMENT_COUNT
    ):
        raise ValueError(
            "simulation_options.incremental_comment_count 必须是 "
            f"1 到 {MAX_INCREMENTAL_COMMENT_COUNT} 的整数。"
        )

    active_opinion_window = raw_options.get(
        "active_opinion_window",
        DEFAULT_ACTIVE_OPINION_WINDOW,
    )
    if (
        isinstance(active_opinion_window, bool)
        or not isinstance(active_opinion_window, int)
        or active_opinion_window < 1
    ):
        raise ValueError(
            "simulation_options.active_opinion_window 必须是正整数。"
        )

    # 2026/10/12，历史复现传播减速：使用较稀疏的固定关系和4条邻居
    # 表达，避免两轮内形成近乎全网覆盖；五策略仍使用全局网络配置。
    network = None
    visibility = None
    context_exposure = None
    if emotion_choice_mode == EMOTION_CHOICE_EVIDENCE_BASED_ALL:
        raw_network = raw_options.get("network", {})
        if raw_network is None:
            raw_network = {}
        if not isinstance(raw_network, dict):
            raise ValueError("simulation_options.network 必须是 JSON 对象。")
        neighbors_per_agent = raw_network.get(
            "neighbors_per_agent",
            DEFAULT_HISTORICAL_NEIGHBORS_PER_AGENT,
        )
        if (
            isinstance(neighbors_per_agent, bool)
            or not isinstance(neighbors_per_agent, int)
            or neighbors_per_agent < 0
        ):
            raise ValueError(
                "simulation_options.network.neighbors_per_agent "
                "必须是非负整数。"
            )
        network = {"neighbors_per_agent": neighbors_per_agent}

        raw_visibility = raw_options.get("visibility", {})
        if raw_visibility is None:
            raw_visibility = {}
        if not isinstance(raw_visibility, dict):
            raise ValueError("simulation_options.visibility 必须是 JSON 对象。")
        neighbor_count = raw_visibility.get(
            "neighbor_comment_count",
            DEFAULT_HISTORICAL_NEIGHBOR_COMMENT_COUNT,
        )
        public_count = raw_visibility.get(
            "public_comment_count",
            DEFAULT_HISTORICAL_PUBLIC_COMMENT_COUNT,
        )
        for field_name, value in (
            ("neighbor_comment_count", neighbor_count),
            ("public_comment_count", public_count),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"simulation_options.visibility.{field_name} 必须是非负整数。"
                )
        visibility = {
            "neighbor_comment_count": neighbor_count,
            "public_comment_count": public_count,
        }
        if neighbor_count + public_count != VISIBLE_COMMENT_COUNT:
            raise ValueError(
                "simulation_options.visibility中的邻居评论数与公共评论数之和"
                f"必须等于{VISIBLE_COMMENT_COUNT}。"
            )
        # 当前传播模型每名邻居每轮最多提供一条上一轮表达。若目标邻居
        # 评论数大于关注人数，该配置在拓扑上永远无法实现，应在运行前
        # 明确拒绝，而不是长期静默地用公共评论补足。
        if neighbor_count > neighbors_per_agent:
            raise ValueError(
                "simulation_options.visibility.neighbor_comment_count "
                "不能大于 simulation_options.network.neighbors_per_agent。"
            )

        raw_exposure = raw_options.get("context_exposure", {})
        if raw_exposure is None:
            raw_exposure = {}
        if not isinstance(raw_exposure, dict):
            raise ValueError(
                "simulation_options.context_exposure 必须是 JSON 对象。"
            )
        context_exposure = {
            "public_discourse_reach_rate": raw_exposure.get(
                "public_discourse_reach_rate",
                DEFAULT_PUBLIC_DISCOURSE_REACH_RATE,
            ),
            "positive_evidence_reach_rate": raw_exposure.get(
                "positive_evidence_reach_rate",
                DEFAULT_POSITIVE_EVIDENCE_REACH_RATE,
            ),
        }
        for field_name, value in context_exposure.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= value <= 1
            ):
                raise ValueError(
                    "simulation_options.context_exposure."
                    f"{field_name} 必须是 0 到 1 之间的数值。"
                )
            context_exposure[field_name] = float(value)

    options = {
        "emotion_choice_mode": emotion_choice_mode,
        "incremental_comment_count": incremental_comment_count,
        "active_opinion_window": active_opinion_window,
    }
    if visibility is not None:
        options["network"] = network
        options["visibility"] = visibility
        options["context_exposure"] = context_exposure
    return options


def uses_evidence_based_emotions(event_context: dict | None) -> bool:
    """判断当前事件是否显式启用基于证据的三分类情绪选择。"""

    if not isinstance(event_context, dict):
        return False
    options = event_context.get("simulation_options")
    if not isinstance(options, dict):
        options = normalize_simulation_options(event_context)
    return (
        options.get("emotion_choice_mode")
        == EMOTION_CHOICE_EVIDENCE_BASED_ALL
    )
