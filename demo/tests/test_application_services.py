from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from application.round_results import (
    extract_policy_metrics,
    load_round_result,
)
from application.step_executor import (
    SIMULATION_STEP_RESULT_PREFIX,
    SimulationStepRequest,
    SubprocessSimulationStepExecutor,
    parse_simulation_step_result,
)
from domain.contracts import (
    AgentDecisionInput,
    AgentDecisionResult,
    SimulationContext,
)
from historical_replay import replay_runner


class ApplicationServiceTests(unittest.TestCase):
    def test_historical_replay_has_state_update_dependency(self) -> None:
        """历史复现进入第2轮前必须能追加事件状态。"""

        self.assertTrue(callable(replay_runner.append_event_state_record))

    def test_decision_contract_preserves_legacy_record_shape(self) -> None:
        context = SimulationContext(
            {"event_id": "event_test", "current_state": {"step": 2}}
        )
        decision_input = AgentDecisionInput(
            persona={"agent_id": "agent_001"},
            context=context,
            policy={},
            visible_comments=[],
            previous_state={},
            history_summary={},
        )
        self.assertEqual(decision_input.agent_id, "agent_001")
        result = AgentDecisionResult(
            event_id=context.event_id,
            step=context.step,
            agent_id=decision_input.agent_id,
            decision_method="constrained_llm",
            status="success",
            decision={"will_comment": False},
        )
        self.assertEqual(
            result.to_record(),
            {
                "event_id": "event_test",
                "step": 2,
                "agent_id": "agent_001",
                "decision_method": "constrained_llm",
                "status": "success",
                "decision": {"will_comment": False},
            },
        )

    def test_simulation_context_rejects_invalid_step(self) -> None:
        with self.assertRaises(ValueError):
            SimulationContext(
                {"event_id": "event_test", "current_state": {"step": 0}}
            )

    def test_parses_last_structured_subprocess_result(self) -> None:
        output = "\n".join(
            [
                "普通日志",
                f'{SIMULATION_STEP_RESULT_PREFIX}{json.dumps({"step": 1})}',
                f'{SIMULATION_STEP_RESULT_PREFIX}{json.dumps({"step": 2})}',
            ]
        )
        self.assertEqual(parse_simulation_step_result(output), {"step": 2})

    @patch("application.step_executor.subprocess.Popen")
    def test_keyboard_interrupt_terminates_child_process(
        self,
        mocked_popen,
    ) -> None:
        """Ctrl+C中断父进程时必须主动回收当前仿真子进程。"""

        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
        mocked_popen.return_value = process
        request = SimulationStepRequest(
            state_dir=Path("state"),
            event_file=Path("event.json"),
            comment_pool_file=Path("comments.json"),
            social_network_file=None,
            incremental_comment_count=10,
            max_agents=30,
            max_workers=4,
            random_seed=2026,
            comment_temperature=0.3,
            demo_dir=Path("demo"),
        )

        with self.assertRaises(KeyboardInterrupt):
            SubprocessSimulationStepExecutor().run(request)

        process.terminate.assert_called_once_with()
        self.assertEqual(process.communicate.call_count, 2)

    def test_policy_metric_basis_keeps_internal_and_expression_separate(self) -> None:
        metrics = {
            "agent_negative_emotion": {
                "negative_rate": 0.75,
                "negative_count": 3,
                "agent_count": 4,
            },
            "agent_expression_distribution": {
                "expression_count": 2,
                "classified_expression_count": 2,
                "silent_agent_count": 2,
                "distribution": {
                    "negative": {"count": 1, "rate": 0.5},
                },
            },
            "official_attitude_distribution": {
                "applicable_agent_count": 4,
                "distribution": {
                    "question": {"rate": 0.25},
                    "accept": {"rate": 0.5},
                },
            },
            "global_trend": {"trend_direction": "stable"},
        }
        internal = extract_policy_metrics(metrics, "agent_internal")
        expression = extract_policy_metrics(metrics, "agent_expression")
        self.assertEqual(internal["negative_rate"], 0.75)
        self.assertEqual(expression["negative_rate"], 0.5)
        self.assertEqual(expression["negative_denominator"], 2)

    def test_round_reader_preserves_existing_result_shape(self) -> None:
        metrics = {
            "event_id": "event_test",
            "step": 1,
            "agent_negative_emotion": {
                "negative_rate": 1.0,
                "negative_count": 1,
                "agent_count": 1,
            },
            "agent_expression_distribution": {
                "expression_count": 1,
                "classified_expression_count": 1,
                "silent_agent_count": 0,
            },
            "official_attitude_distribution": {
                "applicable_agent_count": 0,
                "distribution": {
                    "question": {"rate": 0.0},
                    "accept": {"rate": 0.0},
                },
            },
            "global_trend": {"trend_direction": "stable"},
            "propagation_metrics": {"coverage_rate": 0.2},
        }
        with patch(
            "application.round_results.read_jsonl",
            return_value=[metrics],
        ):
            result, quality = load_round_result(
                Path("state"), "event_test", 1
            )
        self.assertIsNone(quality)
        self.assertEqual(result["step"], 1)
        self.assertEqual(result["propagation_metrics"]["coverage_rate"], 0.2)


if __name__ == "__main__":
    unittest.main()

