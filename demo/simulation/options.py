"""仿真事件级可选行为配置。

本模块只负责配置校验和默认值，不读取文件，也不区分具体事件。
不同行为能力使用独立开关，避免再用“是否为历史复现”一个条件
同时控制情绪、发言、动作和记忆。
"""

from __future__ import annotations

from project_config import (
    INCREMENTAL_COMMENT_COUNT,
    STRATEGY_INCREMENTAL_COMMENT_COUNT,
    VISIBLE_COMMENT_COUNT,
)


EMOTION_CHOICE_POLICY_CONSTRAINED = "policy_constrained"
EMOTION_CHOICE_EVIDENCE_BASED_ALL = "evidence_based_all"
VALID_EMOTION_CHOICE_MODES = {
    EMOTION_CHOICE_POLICY_CONSTRAINED,
    EMOTION_CHOICE_EVIDENCE_BASED_ALL,
}
DEFAULT_ACTIVE_OPINION_WINDOW = 2
DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS = 3
DEFAULT_STRATEGY_EXPRESSION_TIME_DECAY = 0.72
MAX_INCREMENTAL_COMMENT_COUNT = 200
DEFAULT_HISTORICAL_NEIGHBORS_PER_AGENT = 5
DEFAULT_HISTORICAL_NEIGHBOR_COMMENT_COUNT = 4
DEFAULT_HISTORICAL_PUBLIC_COMMENT_COUNT = 11
DEFAULT_PUBLIC_DISCOURSE_REACH_RATE = 0.65
DEFAULT_POSITIVE_EVIDENCE_REACH_RATE = 0.50

# 2026/10/16，新增功能：将 Agent 的发言、动作、表达和记忆模式拆成
# 独立配置。策略对照默认启用受控的自主行为；历史复现保留已
# 验证的证据发言门控，两条路径不再互相借用隐式默认值。
PARTICIPATION_PERSONA_STATE_GATE = "persona_state_gate"
PARTICIPATION_HISTORICAL_EVIDENCE_GATE = "historical_evidence_gate"
ACTION_SILENT_ORIGINAL_RESHARE = "silent_original_reshare"
ACTION_SILENT_ORIGINAL = "silent_original"
EXPRESSION_AGENT_GENERATED = "agent_generated"
MEMORY_BOUNDED_EVENT = "bounded_event"
EXPOSURE_NETWORK_PERSONALIZED = "network_personalized"

VALID_PARTICIPATION_MODES = {
    PARTICIPATION_PERSONA_STATE_GATE,
    PARTICIPATION_HISTORICAL_EVIDENCE_GATE,
}
VALID_ACTION_MODES = {
    ACTION_SILENT_ORIGINAL_RESHARE,
    ACTION_SILENT_ORIGINAL,
}
VALID_EXPRESSION_MODES = {EXPRESSION_AGENT_GENERATED}
VALID_MEMORY_MODES = {MEMORY_BOUNDED_EVENT}
VALID_EXPOSURE_MODES = {EXPOSURE_NETWORK_PERSONALIZED}

# 2026/10/17，新增功能：消融实验使用独立、可审计的机制开关。
# 默认值必须完整复现当前正式实验；只有事件输入显式配置 ``ablation``
# 时才关闭某条反馈路径，避免实验代码通过注释或临时改常量污染主流程。
INCREMENTAL_PUBLIC_LLM = "llm_incremental"
INCREMENTAL_PUBLIC_FROZEN = "frozen_after_initial"
VALID_INCREMENTAL_PUBLIC_COMMENT_MODES = {
    INCREMENTAL_PUBLIC_LLM,
    INCREMENTAL_PUBLIC_FROZEN,
}
STATE_EVIDENCE_ALL_VISIBLE = "all_visible"
STATE_EVIDENCE_EXCLUDE_LLM_INCREMENTAL = "exclude_llm_incremental"
VALID_STATE_COMMENT_EVIDENCE_MODES = {
    STATE_EVIDENCE_ALL_VISIBLE,
    STATE_EVIDENCE_EXCLUDE_LLM_INCREMENTAL,
}
DEFAULT_ABLATION_OPTIONS = {
    "incremental_public_comment_mode": INCREMENTAL_PUBLIC_LLM,
    "state_comment_evidence_mode": STATE_EVIDENCE_ALL_VISIBLE,
    "neighbor_feedback_enabled": True,
    "fixed_response_step": None,
}


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

    current_state = payload.get("current_state", {})
    if not isinstance(current_state, dict):
        current_state = {}
    historical_mode = (
        emotion_choice_mode == EMOTION_CHOICE_EVIDENCE_BASED_ALL
        or current_state.get("simulation_mode") == "historical_replay"
    )

    # 2026/10/16，新增功能：回应方案对照默认启用
    # Persona/状态发言门控和“沉默、原创、转发”动作空间；历史
    # 复现继续使用原有的证据门控与原创表达，不改变其既有语义。
    behavior_defaults = {
        "participation_mode": (
            PARTICIPATION_HISTORICAL_EVIDENCE_GATE
            if historical_mode
            else PARTICIPATION_PERSONA_STATE_GATE
        ),
        "action_mode": (
            ACTION_SILENT_ORIGINAL
            if historical_mode
            else ACTION_SILENT_ORIGINAL_RESHARE
        ),
        "expression_mode": EXPRESSION_AGENT_GENERATED,
        "memory_mode": MEMORY_BOUNDED_EVENT,
        "exposure_mode": EXPOSURE_NETWORK_PERSONALIZED,
    }
    behavior_options = {}
    validators = {
        "participation_mode": VALID_PARTICIPATION_MODES,
        "action_mode": VALID_ACTION_MODES,
        "expression_mode": VALID_EXPRESSION_MODES,
        "memory_mode": VALID_MEMORY_MODES,
        "exposure_mode": VALID_EXPOSURE_MODES,
    }
    for field_name, allowed_values in validators.items():
        value = str(
            raw_options.get(field_name, behavior_defaults[field_name])
        ).strip()
        if value not in allowed_values:
            raise ValueError(
                f"simulation_options.{field_name} 必须是以下之一："
                f"{sorted(allowed_values)}"
            )
        behavior_options[field_name] = value

    raw_ablation = raw_options.get("ablation", {})
    if raw_ablation is None:
        raw_ablation = {}
    if not isinstance(raw_ablation, dict):
        raise ValueError("simulation_options.ablation 必须是 JSON 对象。")

    incremental_public_comment_mode = str(
        raw_ablation.get(
            "incremental_public_comment_mode",
            DEFAULT_ABLATION_OPTIONS["incremental_public_comment_mode"],
        )
    ).strip()
    if (
        incremental_public_comment_mode
        not in VALID_INCREMENTAL_PUBLIC_COMMENT_MODES
    ):
        raise ValueError(
            "simulation_options.ablation.incremental_public_comment_mode "
            "只能是 llm_incremental 或 frozen_after_initial。"
        )

    state_comment_evidence_mode = str(
        raw_ablation.get(
            "state_comment_evidence_mode",
            DEFAULT_ABLATION_OPTIONS["state_comment_evidence_mode"],
        )
    ).strip()
    if state_comment_evidence_mode not in VALID_STATE_COMMENT_EVIDENCE_MODES:
        raise ValueError(
            "simulation_options.ablation.state_comment_evidence_mode "
            "只能是 all_visible 或 exclude_llm_incremental。"
        )

    neighbor_feedback_enabled = raw_ablation.get(
        "neighbor_feedback_enabled",
        DEFAULT_ABLATION_OPTIONS["neighbor_feedback_enabled"],
    )
    if not isinstance(neighbor_feedback_enabled, bool):
        raise ValueError(
            "simulation_options.ablation.neighbor_feedback_enabled "
            "必须是布尔值。"
        )

    fixed_response_step = raw_ablation.get(
        "fixed_response_step",
        DEFAULT_ABLATION_OPTIONS["fixed_response_step"],
    )
    if fixed_response_step is not None and (
        isinstance(fixed_response_step, bool)
        or not isinstance(fixed_response_step, int)
        or fixed_response_step < 2
    ):
        raise ValueError(
            "simulation_options.ablation.fixed_response_step "
            "必须为空或大于等于2的整数。"
        )
    ablation_options = {
        "incremental_public_comment_mode": (
            incremental_public_comment_mode
        ),
        "state_comment_evidence_mode": state_comment_evidence_mode,
        "neighbor_feedback_enabled": neighbor_feedback_enabled,
        "fixed_response_step": fixed_response_step,
    }

    incremental_comment_count = raw_options.get(
        "incremental_comment_count",
        (
            INCREMENTAL_COMMENT_COUNT
            if historical_mode
            else STRATEGY_INCREMENTAL_COMMENT_COUNT
        ),
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

    expression_window_rounds = raw_options.get(
        "expression_window_rounds",
        DEFAULT_STRATEGY_EXPRESSION_WINDOW_ROUNDS,
    )
    if (
        isinstance(expression_window_rounds, bool)
        or not isinstance(expression_window_rounds, int)
        or expression_window_rounds < 1
    ):
        raise ValueError(
            "simulation_options.expression_window_rounds 必须是正整数。"
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
        "expression_window_rounds": expression_window_rounds,
        "ablation": ablation_options,
        **behavior_options,
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


def get_simulation_options(event_context: dict | None) -> dict:
    """返回已规范化选项，兼容旧批次中未保存新字段的上下文。"""

    if not isinstance(event_context, dict):
        return normalize_simulation_options({})
    options = event_context.get("simulation_options")
    if not isinstance(options, dict) or not {
        "participation_mode",
        "action_mode",
        "expression_mode",
        "memory_mode",
        "exposure_mode",
    }.issubset(options):
        return normalize_simulation_options(event_context)
    return options


def get_ablation_options(event_context: dict | None) -> dict:
    """返回完整消融配置；旧事件自动得到不改变行为的默认值。"""

    options = get_simulation_options(event_context)
    ablation = options.get("ablation")
    if not isinstance(ablation, dict):
        return dict(DEFAULT_ABLATION_OPTIONS)
    return {
        key: ablation.get(key, default)
        for key, default in DEFAULT_ABLATION_OPTIONS.items()
    }


def freezes_incremental_public_comments(event_context: dict | None) -> bool:
    """判断第2轮以后是否冻结外部LLM公共评论。"""

    return (
        get_ablation_options(event_context).get(
            "incremental_public_comment_mode"
        )
        == INCREMENTAL_PUBLIC_FROZEN
    )


def excludes_llm_incremental_from_state(event_context: dict | None) -> bool:
    """判断外部增量评论是否只作表达素材、不进入内部状态判断。"""

    return (
        get_ablation_options(event_context).get(
            "state_comment_evidence_mode"
        )
        == STATE_EVIDENCE_EXCLUDE_LLM_INCREMENTAL
    )


def uses_neighbor_feedback(event_context: dict | None) -> bool:
    """判断个人可见视图是否保留邻居Agent表达。"""

    return bool(
        get_ablation_options(event_context).get(
            "neighbor_feedback_enabled",
            True,
        )
    )


def uses_strategy_participation_gate(event_context: dict | None) -> bool:
    """判断是否启用策略实验的 Persona/状态发言门控。"""

    return (
        get_simulation_options(event_context).get("participation_mode")
        == PARTICIPATION_PERSONA_STATE_GATE
    )


def uses_agent_generated_expression(event_context: dict | None) -> bool:
    """判断发言时是否由 Agent 生成自己的文本。"""

    return (
        get_simulation_options(event_context).get("expression_mode")
        == EXPRESSION_AGENT_GENERATED
    )


def allows_reshare_action(event_context: dict | None) -> bool:
    """判断当前动作空间是否允许转发个人可见表达。"""

    return (
        get_simulation_options(event_context).get("action_mode")
        == ACTION_SILENT_ORIGINAL_RESHARE
    )
