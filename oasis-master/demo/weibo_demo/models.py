from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


class TimingPolicy(str, Enum):
    NO_RESPONSE = "S0"
    IMMEDIATE = "S1"
    EARLY_THRESHOLD = "S2"
    RISK_THRESHOLD = "S3"
    AFTER_PEAK = "S4"


class StatementType(str, Enum):
    FACT_BRIEFING = "A"
    EMPATHY_REASSURANCE = "B"
    RUMOR_CLARIFICATION = "C"
    PROGRESS_UPDATE = "D"


class LifecyclePhase(str, Enum):
    LATENT = "latent"
    RISING = "rising"
    PEAK = "peak"
    DECLINING = "declining"


@dataclass(frozen=True)
class GroupProfile:
    group_id: str
    name: str
    description: str
    population_size: int
    activity_rate: float
    like_rate: float
    repost_rate: float
    comment_rate: float
    event_sensitivity: float
    official_sensitivity: float
    baseline_attention: float
    baseline_negative_ratio: float
    baseline_rumor_belief: float
    trust_official: float
    keywords: tuple[str, ...] = ()
    data_source: str = "assumed"


@dataclass
class GroupState:
    attention: float
    negative_ratio: float
    rumor_belief: float
    trust_official: float
    authority_coverage: float = 0.0
    cumulative_exposures: int = 0
    last_active_step: int = -1

    @classmethod
    def from_profile(cls, profile: GroupProfile) -> "GroupState":
        return cls(
            attention=profile.baseline_attention,
            negative_ratio=profile.baseline_negative_ratio,
            rumor_belief=profile.baseline_rumor_belief,
            trust_official=profile.trust_official,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Statement:
    statement_type: StatementType
    content: str
    step: int
    rumor_reduction: float
    negative_reduction: float
    trust_gain: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["statement_type"] = self.statement_type.value
        return data


@dataclass(frozen=True)
class MetricSnapshot:
    step: int
    intensity: float
    growth_rate: float
    negative_ratio: float
    rumor_ratio: float
    authority_coverage: float
    cross_group_ratio: float
    active_population: int
    lifecycle: LifecyclePhase
    risk_score: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lifecycle"] = self.lifecycle.value
        return data


@dataclass(frozen=True)
class Observation:
    metrics: MetricSnapshot
    statement: Statement | None = None


@dataclass(frozen=True)
class ActionBatch:
    step: int
    agent_id: str
    population_size: int
    exposed: int
    active: int
    likes: int
    reposts: int
    comments: int
    do_nothing: int
    negative_comments: int
    rumor_reposts: int
    authority_reposts: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DomainEvent:
    run_id: str
    step: int
    event_type: str
    actor_id: str
    payload: dict[str, Any]
    sequence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationResult:
    run_id: str
    scenario_id: str
    seed: int
    timing_policy: TimingPolicy
    statement_type: StatementType
    metrics: list[MetricSnapshot] = field(default_factory=list)
    intervention: Statement | None = None

    def summary(self) -> dict[str, Any]:
        final = self.metrics[-1] if self.metrics else None
        peak = max(self.metrics, key=lambda item: item.intensity, default=None)
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "timing_policy": self.timing_policy.value,
            "statement_type": self.statement_type.value,
            "intervention_step": (
                self.intervention.step if self.intervention is not None else None
            ),
            "peak_intensity": peak.intensity if peak else None,
            "peak_step": peak.step if peak else None,
            "final_metrics": final.to_dict() if final else None,
        }
