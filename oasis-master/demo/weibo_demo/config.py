from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .models import GroupProfile, StatementType, TimingPolicy


@dataclass(frozen=True)
class OfficialConfig:
    timing_policy: TimingPolicy
    statement_type: StatementType
    min_step: int
    intensity_threshold: float
    risk_threshold: float
    templates: dict[StatementType, str]


@dataclass(frozen=True)
class MetricConfig:
    post_weight: float
    repost_weight: float
    like_weight: float
    comment_weight: float
    intensity_denominator_ratio: float


@dataclass(frozen=True)
class SeedMetrics:
    intensity: float
    negative_ratio: float
    rumor_ratio: float
    authority_coverage: float


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    title: str
    description: str
    steps: int
    step_minutes: int
    seed: int
    expected_group_count: int
    groups: tuple[GroupProfile, ...]
    official: OfficialConfig
    metrics: MetricConfig
    seed_metrics: SeedMetrics

    def validate(self) -> None:
        if len(self.groups) != self.expected_group_count:
            raise ValueError(
                f"场景要求 {self.expected_group_count} 个群体 Agent，"
                f"实际配置 {len(self.groups)} 个。"
            )
        group_ids = [group.group_id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("群体 Agent 的 group_id 必须唯一。")
        if self.steps <= 0 or self.step_minutes <= 0:
            raise ValueError("steps 和 step_minutes 必须为正数。")
        for group in self.groups:
            if group.population_size <= 0:
                raise ValueError(f"{group.group_id} 的 population_size 必须为正数。")
            rates = (
                group.activity_rate,
                group.like_rate,
                group.repost_rate,
                group.comment_rate,
                group.event_sensitivity,
                group.official_sensitivity,
                group.baseline_attention,
                group.baseline_negative_ratio,
                group.baseline_rumor_belief,
                group.trust_official,
            )
            if any(rate < 0 or rate > 1 for rate in rates):
                raise ValueError(f"{group.group_id} 存在不在 [0, 1] 的参数。")

    def with_runtime_overrides(
        self,
        *,
        steps: int | None = None,
        seed: int | None = None,
        timing_policy: TimingPolicy | None = None,
        statement_type: StatementType | None = None,
    ) -> "ScenarioConfig":
        official = replace(
            self.official,
            timing_policy=timing_policy or self.official.timing_policy,
            statement_type=statement_type or self.official.statement_type,
        )
        updated = replace(
            self,
            steps=steps if steps is not None else self.steps,
            seed=seed if seed is not None else self.seed,
            official=official,
        )
        updated.validate()
        return updated


def _group_from_dict(data: dict[str, Any]) -> GroupProfile:
    return GroupProfile(
        group_id=str(data["group_id"]),
        name=str(data["name"]),
        description=str(data["description"]),
        population_size=int(data["population_size"]),
        activity_rate=float(data["activity_rate"]),
        like_rate=float(data["like_rate"]),
        repost_rate=float(data["repost_rate"]),
        comment_rate=float(data["comment_rate"]),
        event_sensitivity=float(data["event_sensitivity"]),
        official_sensitivity=float(data["official_sensitivity"]),
        baseline_attention=float(data["baseline_attention"]),
        baseline_negative_ratio=float(data["baseline_negative_ratio"]),
        baseline_rumor_belief=float(data["baseline_rumor_belief"]),
        trust_official=float(data["trust_official"]),
        keywords=tuple(str(item) for item in data.get("keywords", [])),
        data_source=str(data.get("data_source", "assumed")),
    )


def load_scenario(path: str | Path) -> ScenarioConfig:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    official_data = data["official"]
    official = OfficialConfig(
        timing_policy=TimingPolicy(official_data["timing_policy"]),
        statement_type=StatementType(official_data["statement_type"]),
        min_step=int(official_data["min_step"]),
        intensity_threshold=float(official_data["intensity_threshold"]),
        risk_threshold=float(official_data["risk_threshold"]),
        templates={
            StatementType(key): str(value)
            for key, value in official_data["templates"].items()
        },
    )
    metric_data = data["metrics"]
    seed_data = data["seed_metrics"]
    scenario = ScenarioConfig(
        scenario_id=str(data["scenario_id"]),
        title=str(data["title"]),
        description=str(data["description"]),
        steps=int(data["steps"]),
        step_minutes=int(data["step_minutes"]),
        seed=int(data["seed"]),
        expected_group_count=int(data.get("expected_group_count", 10)),
        groups=tuple(_group_from_dict(item) for item in data["groups"]),
        official=official,
        metrics=MetricConfig(
            post_weight=float(metric_data["post_weight"]),
            repost_weight=float(metric_data["repost_weight"]),
            like_weight=float(metric_data["like_weight"]),
            comment_weight=float(metric_data["comment_weight"]),
            intensity_denominator_ratio=float(
                metric_data["intensity_denominator_ratio"]
            ),
        ),
        seed_metrics=SeedMetrics(
            intensity=float(seed_data["intensity"]),
            negative_ratio=float(seed_data["negative_ratio"]),
            rumor_ratio=float(seed_data["rumor_ratio"]),
            authority_coverage=float(seed_data["authority_coverage"]),
        ),
    )
    scenario.validate()
    return scenario
