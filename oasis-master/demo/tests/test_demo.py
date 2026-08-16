from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from weibo_demo.comment_mapping import KeywordCommentMapper
from weibo_demo.config import load_scenario
from weibo_demo.engine import SimulationEngine
from weibo_demo.llm import LLMCallBudgetExceeded, LLMCallGate
from weibo_demo.models import TimingPolicy
from weibo_demo.storage import InMemoryEventStore

DEMO_ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = DEMO_ROOT / "config" / "scenario.json"


class ConfigurationTests(unittest.TestCase):
    def test_scenario_has_ten_unique_groups(self) -> None:
        scenario = load_scenario(SCENARIO_PATH)
        self.assertEqual(10, len(scenario.groups))
        self.assertEqual(
            10,
            len({group.group_id for group in scenario.groups}),
        )

    def test_comment_mapper_has_safe_fallback(self) -> None:
        scenario = load_scenario(SCENARIO_PATH)
        mapper = KeywordCommentMapper(scenario.groups)
        self.assertEqual(
            "fact_checkers",
            mapper.classify("请给出证据和原始来源"),
        )
        self.assertEqual(
            "low_engagement",
            mapper.classify("路过看一下"),
        )


class SimulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_gate_enforces_budget(self) -> None:
        gate = LLMCallGate(max_concurrency=1, call_budget=1)

        async def operation() -> str:
            return "ok"

        self.assertEqual("ok", await gate.call(operation))
        with self.assertRaises(LLMCallBudgetExceeded):
            await gate.call(operation)

    async def test_same_seed_is_deterministic(self) -> None:
        scenario = load_scenario(SCENARIO_PATH).with_runtime_overrides(
            steps=5,
            timing_policy=TimingPolicy.NO_RESPONSE,
        )
        first = await SimulationEngine(
            scenario,
            InMemoryEventStore(),
        ).run()
        second = await SimulationEngine(
            scenario,
            InMemoryEventStore(),
        ).run()
        self.assertEqual(
            [item.to_dict() for item in first.metrics],
            [item.to_dict() for item in second.metrics],
        )

    async def test_risk_policy_can_intervene(self) -> None:
        scenario = load_scenario(SCENARIO_PATH)
        scenario = replace(
            scenario,
            steps=3,
            official=replace(
                scenario.official,
                timing_policy=TimingPolicy.RISK_THRESHOLD,
                min_step=0,
                risk_threshold=0.0,
            ),
        )
        result = await SimulationEngine(
            scenario,
            InMemoryEventStore(),
        ).run()
        self.assertIsNotNone(result.intervention)
        self.assertEqual(0, result.intervention.step)

    async def test_reset_recreates_initial_state(self) -> None:
        scenario = load_scenario(SCENARIO_PATH).with_runtime_overrides(steps=2)
        store = InMemoryEventStore()
        engine = SimulationEngine(scenario, store)
        first = await engine.run()
        engine.reset()
        second = await engine.run()
        self.assertEqual(
            [item.to_dict() for item in first.metrics],
            [item.to_dict() for item in second.metrics],
        )
        self.assertNotEqual(first.run_id, second.run_id)


if __name__ == "__main__":
    unittest.main()
