from __future__ import annotations

import asyncio
import random

from .models import (
    ActionBatch,
    GroupProfile,
    GroupState,
    Observation,
    clamp,
)


class GroupAgent:
    """使用聚合状态模拟一类相似受众，不维护无界自然语言记忆。"""

    def __init__(self, profile: GroupProfile) -> None:
        self.profile = profile
        self.state = GroupState.from_profile(profile)

    def reset(self) -> None:
        self.state = GroupState.from_profile(self.profile)

    def _apply_statement(self, observation: Observation, exposure_rate: float) -> None:
        statement = observation.statement
        if statement is None:
            return

        responsiveness = clamp(
            self.state.trust_official * self.profile.official_sensitivity
        )
        self.state.rumor_belief = clamp(
            self.state.rumor_belief
            * (1.0 - statement.rumor_reduction * responsiveness)
        )
        self.state.negative_ratio = clamp(
            self.state.negative_ratio
            * (1.0 - statement.negative_reduction * responsiveness)
        )
        self.state.trust_official = clamp(
            self.state.trust_official + statement.trust_gain * responsiveness
        )
        self.state.authority_coverage = clamp(
            self.state.authority_coverage
            + exposure_rate * (0.35 + 0.65 * responsiveness)
        )

    async def decide(
        self,
        observation: Observation,
        step: int,
        rng: random.Random,
    ) -> ActionBatch:
        # 让调用方可以统一使用 asyncio.gather；规则计算本身不占用 LLM 配额。
        await asyncio.sleep(0)

        metrics = observation.metrics
        pressure = clamp(
            0.45 * metrics.intensity
            + 0.20 * clamp(max(metrics.growth_rate, 0.0))
            + 0.35 * self.profile.event_sensitivity
        )
        self.state.attention = clamp(
            0.68 * self.state.attention + 0.32 * pressure
        )

        jitter = rng.uniform(0.92, 1.08)
        exposure_rate = clamp(
            (0.06 + 0.52 * self.state.attention + 0.22 * metrics.intensity)
            * jitter
        )
        self._apply_statement(observation, exposure_rate)

        exposed = min(
            self.profile.population_size,
            round(self.profile.population_size * exposure_rate),
        )
        activation_rate = clamp(
            self.profile.activity_rate
            * (0.42 + 0.58 * self.state.attention)
            * rng.uniform(0.94, 1.06)
        )
        active = min(exposed, round(exposed * activation_rate))

        emotional_boost = 0.75 + 0.45 * self.state.negative_ratio
        social_proof = 0.80 + 0.35 * metrics.intensity
        likes = round(active * clamp(self.profile.like_rate * social_proof))
        reposts = round(
            active
            * clamp(
                self.profile.repost_rate
                * emotional_boost
                * (1.0 - 0.30 * self.state.authority_coverage)
            )
        )
        comments = round(
            active
            * clamp(self.profile.comment_rate * emotional_boost)
        )
        negative_comments = round(comments * self.state.negative_ratio)
        rumor_reposts = round(
            reposts
            * self.state.rumor_belief
            * (1.0 - 0.45 * self.state.authority_coverage)
        )
        authority_reposts = (
            round(reposts * self.state.authority_coverage)
            if observation.statement is not None
            else 0
        )

        self.state.cumulative_exposures += exposed
        if active > 0:
            self.state.last_active_step = step
        # 没有新的官方信息时，权威信息覆盖会随时间轻微衰减。
        if observation.statement is None:
            self.state.authority_coverage = clamp(
                self.state.authority_coverage * 0.985
            )

        return ActionBatch(
            step=step,
            agent_id=self.profile.group_id,
            population_size=self.profile.population_size,
            exposed=exposed,
            active=active,
            likes=likes,
            reposts=reposts,
            comments=comments,
            do_nothing=max(0, exposed - active),
            negative_comments=negative_comments,
            rumor_reposts=rumor_reposts,
            authority_reposts=authority_reposts,
        )
