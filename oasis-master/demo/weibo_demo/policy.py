from __future__ import annotations

from .config import OfficialConfig
from .models import MetricSnapshot, Statement, StatementType, TimingPolicy


STATEMENT_EFFECTS: dict[StatementType, tuple[float, float, float]] = {
    StatementType.FACT_BRIEFING: (0.25, 0.10, 0.08),
    StatementType.EMPATHY_REASSURANCE: (0.05, 0.30, 0.12),
    StatementType.RUMOR_CLARIFICATION: (0.45, 0.08, 0.05),
    StatementType.PROGRESS_UPDATE: (0.12, 0.18, 0.10),
}


class OfficialPolicyAgent:
    """基于聚合态势决定是否进场；声明内容目前使用可审计模板。"""

    agent_id = "official_policy"

    def __init__(self, config: OfficialConfig) -> None:
        self.config = config
        self.intervention: Statement | None = None

    def reset(self) -> None:
        self.intervention = None

    def _should_intervene(
        self,
        step: int,
        history: list[MetricSnapshot],
    ) -> bool:
        if self.intervention is not None or not history:
            return False

        policy = self.config.timing_policy
        current = history[-1]
        if policy is TimingPolicy.NO_RESPONSE:
            return False
        if policy is TimingPolicy.IMMEDIATE:
            return step >= 1
        if step < self.config.min_step:
            return False
        if policy is TimingPolicy.EARLY_THRESHOLD:
            recent_growth = [item.growth_rate for item in history[-2:]]
            return (
                current.intensity >= self.config.intensity_threshold
                and len(recent_growth) == 2
                and all(value > 0 for value in recent_growth)
            )
        if policy is TimingPolicy.RISK_THRESHOLD:
            return current.risk_score >= self.config.risk_threshold
        if policy is TimingPolicy.AFTER_PEAK and len(history) >= 2:
            return (
                history[-2].growth_rate > 0
                and history[-1].growth_rate <= 0
            )
        return False

    async def decide(
        self,
        step: int,
        history: list[MetricSnapshot],
    ) -> Statement | None:
        if not self._should_intervene(step, history):
            return None

        statement_type = self.config.statement_type
        rumor_reduction, negative_reduction, trust_gain = STATEMENT_EFFECTS[
            statement_type
        ]
        self.intervention = Statement(
            statement_type=statement_type,
            content=self.config.templates[statement_type],
            step=step,
            rumor_reduction=rumor_reduction,
            negative_reduction=negative_reduction,
            trust_gain=trust_gain,
        )
        return self.intervention
