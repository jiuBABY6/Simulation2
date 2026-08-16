from __future__ import annotations

import asyncio
import hashlib
import random
import uuid

from .agents import GroupAgent
from .config import ScenarioConfig
from .models import (
    ActionBatch,
    DomainEvent,
    LifecyclePhase,
    MetricSnapshot,
    Observation,
    SimulationResult,
    clamp,
)
from .policy import OfficialPolicyAgent
from .storage import EventStore, InMemoryEventStore


def _stable_rng(seed: int, step: int, agent_id: str) -> random.Random:
    material = f"{seed}:{step}:{agent_id}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _lifecycle(intensity: float, growth_rate: float) -> LifecyclePhase:
    if intensity < 0.15:
        return LifecyclePhase.LATENT
    if growth_rate > 0.08:
        return LifecyclePhase.RISING
    if growth_rate < -0.08:
        return LifecyclePhase.DECLINING
    return LifecyclePhase.PEAK


class SimulationEngine:
    """离散时间、并行决策、稳定排序提交的群体 Agent 仿真引擎。"""

    def __init__(
        self,
        scenario: ScenarioConfig,
        event_store: EventStore | None = None,
    ) -> None:
        self.scenario = scenario
        self.event_store = event_store or InMemoryEventStore()
        self._has_run = False
        self._initialize_runtime()

    def _initialize_runtime(self) -> None:
        self.run_id = (
            f"{self.scenario.scenario_id}-{self.scenario.seed}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        self.groups = [GroupAgent(profile) for profile in self.scenario.groups]
        self.official = OfficialPolicyAgent(self.scenario.official)
        self._event_sequence = 0
        seed_metrics = self.scenario.seed_metrics
        seed_risk = clamp(
            0.35 * seed_metrics.intensity
            + 0.20 * seed_metrics.rumor_ratio
            + 0.10 * seed_metrics.negative_ratio
        )
        self.metrics: list[MetricSnapshot] = [
            MetricSnapshot(
                step=-1,
                intensity=seed_metrics.intensity,
                growth_rate=0.0,
                negative_ratio=seed_metrics.negative_ratio,
                rumor_ratio=seed_metrics.rumor_ratio,
                authority_coverage=seed_metrics.authority_coverage,
                cross_group_ratio=0.0,
                active_population=0,
                lifecycle=LifecyclePhase.LATENT,
                risk_score=seed_risk,
            )
        ]

    def reset(self) -> None:
        """丢弃本次动态状态，保留不可变场景配置。"""
        self.event_store.clear()
        self._has_run = False
        self._initialize_runtime()

    def _emit(
        self,
        *,
        step: int,
        event_type: str,
        actor_id: str,
        payload: dict,
    ) -> None:
        event = DomainEvent(
            run_id=self.run_id,
            step=step,
            event_type=event_type,
            actor_id=actor_id,
            payload=payload,
            sequence=self._event_sequence,
        )
        self._event_sequence += 1
        self.event_store.append(event)

    def _calculate_metrics(
        self,
        step: int,
        batches: list[ActionBatch],
        has_statement: bool,
    ) -> MetricSnapshot:
        total_population = sum(item.population_size for item in batches)
        total_active = sum(item.active for item in batches)
        likes = sum(item.likes for item in batches)
        reposts = sum(item.reposts for item in batches)
        comments = sum(item.comments for item in batches)
        negative_comments = sum(item.negative_comments for item in batches)
        rumor_reposts = sum(item.rumor_reposts for item in batches)
        active_groups = sum(
            1
            for item in batches
            if item.population_size > 0
            and item.active / item.population_size >= 0.02
        )

        weights = self.scenario.metrics
        weighted_volume = (
            (1 if has_statement else 0) * weights.post_weight
            + reposts * weights.repost_weight
            + likes * weights.like_weight
            + comments * weights.comment_weight
        )
        denominator = max(
            1.0,
            total_population * weights.intensity_denominator_ratio,
        )
        intensity = clamp(weighted_volume / denominator)

        if comments > 0:
            negative_ratio = clamp(negative_comments / comments)
        else:
            negative_ratio = clamp(
                sum(
                    group.state.negative_ratio * group.profile.population_size
                    for group in self.groups
                )
                / max(1, total_population)
            )
        if reposts > 0:
            rumor_ratio = clamp(rumor_reposts / reposts)
        else:
            rumor_ratio = clamp(
                sum(
                    group.state.rumor_belief * group.profile.population_size
                    for group in self.groups
                )
                / max(1, total_population)
            )
        authority_coverage = clamp(
            sum(
                group.state.authority_coverage * group.profile.population_size
                for group in self.groups
            )
            / max(1, total_population)
        )
        cross_group_ratio = active_groups / max(1, len(batches))
        previous_intensity = self.metrics[-1].intensity
        growth_rate = max(
            -1.0,
            min(
                1.0,
                (intensity - previous_intensity)
                / (previous_intensity + 0.05),
            ),
        )
        risk_score = clamp(
            0.35 * intensity
            + 0.25 * clamp(max(growth_rate, 0.0))
            + 0.20 * rumor_ratio
            + 0.10 * negative_ratio
            + 0.10 * cross_group_ratio
        )
        return MetricSnapshot(
            step=step,
            intensity=intensity,
            growth_rate=growth_rate,
            negative_ratio=negative_ratio,
            rumor_ratio=rumor_ratio,
            authority_coverage=authority_coverage,
            cross_group_ratio=cross_group_ratio,
            active_population=total_active,
            lifecycle=_lifecycle(intensity, growth_rate),
            risk_score=risk_score,
        )

    async def step(self, step: int) -> MetricSnapshot:
        statement = await self.official.decide(step, self.metrics)
        if statement is not None:
            self._emit(
                step=step,
                event_type="official_intervention",
                actor_id=self.official.agent_id,
                payload=statement.to_dict(),
            )

        observation = Observation(metrics=self.metrics[-1], statement=statement)
        tasks = [
            group.decide(
                observation=observation,
                step=step,
                rng=_stable_rng(self.scenario.seed, step, group.profile.group_id),
            )
            for group in self.groups
        ]
        # 10 个群体可并行决策；每个群体使用独立 RNG，避免调度顺序影响结果。
        batches = sorted(
            await asyncio.gather(*tasks),
            key=lambda item: item.agent_id,
        )

        # 平台作为单逻辑写入器，按稳定顺序提交事件。
        for batch in batches:
            self._emit(
                step=step,
                event_type="group_action_batch",
                actor_id=batch.agent_id,
                payload=batch.to_dict(),
            )
        for group in sorted(self.groups, key=lambda item: item.profile.group_id):
            self._emit(
                step=step,
                event_type="group_state_snapshot",
                actor_id=group.profile.group_id,
                payload=group.state.to_dict(),
            )

        snapshot = self._calculate_metrics(
            step=step,
            batches=batches,
            has_statement=statement is not None,
        )
        self.metrics.append(snapshot)
        self._emit(
            step=step,
            event_type="metric_snapshot",
            actor_id="simulation_engine",
            payload=snapshot.to_dict(),
        )
        return snapshot

    async def run(self) -> SimulationResult:
        if self._has_run:
            raise RuntimeError("同一运行实例只能执行一次；请先调用 reset()。")
        self._has_run = True
        self._emit(
            step=-1,
            event_type="run_started",
            actor_id="simulation_engine",
            payload={
                "scenario_id": self.scenario.scenario_id,
                "seed": self.scenario.seed,
                "group_count": len(self.groups),
                "timing_policy": self.scenario.official.timing_policy.value,
                "statement_type": self.scenario.official.statement_type.value,
            },
        )
        for step in range(self.scenario.steps):
            await self.step(step)

        result = SimulationResult(
            run_id=self.run_id,
            scenario_id=self.scenario.scenario_id,
            seed=self.scenario.seed,
            timing_policy=self.scenario.official.timing_policy,
            statement_type=self.scenario.official.statement_type,
            metrics=self.metrics[1:],
            intervention=self.official.intervention,
        )
        self._emit(
            step=self.scenario.steps,
            event_type="run_completed",
            actor_id="simulation_engine",
            payload=result.summary(),
        )
        return result
