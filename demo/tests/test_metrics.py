"""全局趋势指标校验的回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from evaluation.metrics import (  # noqa: E402
    GLOBAL_TREND_EVIDENCE_LIMIT,
    build_global_trend_prompt,
    calculate_attitude_diagnostics,
    calculate_expression_distribution,
    validate_global_trend,
)
from experiment_runner import extract_policy_metrics  # noqa: E402


class GlobalTrendValidationTests(unittest.TestCase):
    """证据编号异常只能降低证据质量，不能中断核心指标。"""

    def setUp(self):
        self.valid_ids = {"comment_001", "comment_002", "comment_003"}

    def _result(self, evidence_ids):
        return {
            "trend_direction": "stable",
            "reason": "评论情绪和立场没有明显变化。",
            "evidence_comment_ids": evidence_ids,
        }

    def test_valid_ids_remain_unchanged(self):
        validated = validate_global_trend(
            self._result(["comment_001", "comment_002"]),
            self.valid_ids,
        )

        self.assertEqual(
            validated["evidence_comment_ids"],
            ["comment_001", "comment_002"],
        )
        self.assertEqual(validated["evidence_validation"]["status"], "valid")
        self.assertEqual(validated["evidence_validation"]["issues"], [])

    def test_invalid_id_is_filtered_without_losing_valid_id(self):
        validated = validate_global_trend(
            self._result(["comment_001", "comment_081"]),
            self.valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], ["comment_001"])
        self.assertEqual(
            validated["evidence_validation"],
            {
                "status": "filtered",
                "issues": ["invalid_evidence_comment_ids_filtered"],
                "invalid_ids": ["comment_081"],
            },
        )

    def test_all_invalid_ids_produce_empty_evidence(self):
        validated = validate_global_trend(
            self._result(["comment_080", "comment_081"]),
            self.valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], [])
        self.assertEqual(validated["evidence_validation"]["status"], "filtered")

    def test_huxinyu_step_two_out_of_range_id_is_non_fatal(self):
        """回归覆盖实测第2轮允许001至080、模型返回081的故障。"""
        valid_ids = {f"comment_{index:03d}" for index in range(1, 81)}

        validated = validate_global_trend(
            self._result(["comment_061", "comment_081"]),
            valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], ["comment_061"])
        self.assertEqual(validated["evidence_validation"]["status"], "filtered")
        self.assertEqual(
            validated["evidence_validation"]["invalid_ids"],
            ["comment_081"],
        )

    def test_surrounding_whitespace_is_normalized(self):
        validated = validate_global_trend(
            self._result([" comment_001 "]),
            self.valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], ["comment_001"])
        self.assertEqual(validated["evidence_validation"]["status"], "valid")

    def test_non_array_evidence_is_non_fatal(self):
        validated = validate_global_trend(
            self._result("comment_001"),
            self.valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], [])
        self.assertEqual(
            validated["evidence_validation"]["issues"],
            ["evidence_comment_ids_not_array"],
        )

    def test_non_string_evidence_is_filtered(self):
        validated = validate_global_trend(
            self._result(["comment_001", 2]),
            self.valid_ids,
        )

        self.assertEqual(validated["evidence_comment_ids"], ["comment_001"])
        self.assertEqual(
            validated["evidence_validation"]["issues"],
            ["non_string_evidence_id", "invalid_evidence_comment_ids_filtered"],
        )
        self.assertEqual(validated["evidence_validation"]["invalid_ids"], ["2"])

    def test_duplicate_ids_are_deduplicated_and_limited(self):
        valid_ids = {f"comment_{index:03d}" for index in range(1, 10)}
        evidence_ids = ["comment_001", "comment_001"] + [
            f"comment_{index:03d}" for index in range(2, 10)
        ]

        validated = validate_global_trend(self._result(evidence_ids), valid_ids)

        self.assertEqual(
            validated["evidence_comment_ids"],
            [f"comment_{index:03d}" for index in range(1, 6)],
        )
        self.assertEqual(
            len(validated["evidence_comment_ids"]),
            GLOBAL_TREND_EVIDENCE_LIMIT,
        )

    def test_invalid_direction_remains_fatal(self):
        result = self._result([])
        result["trend_direction"] = "unknown"

        with self.assertRaisesRegex(ValueError, "trend_direction"):
            validate_global_trend(result, self.valid_ids)

    def test_blank_reason_remains_fatal(self):
        result = self._result([])
        result["reason"] = "  "

        with self.assertRaisesRegex(ValueError, "缺少reason"):
            validate_global_trend(result, self.valid_ids)

    def test_prompt_lists_allowed_comment_ids_explicitly(self):
        prompt = build_global_trend_prompt(
            {"event_id": "event_test"},
            [{"comment_id": "comment_001", "text": "初始评论"}],
            [{"comment_id": "comment_061", "text": "当前评论"}],
        )

        self.assertIn("【允许引用的评论编号】", prompt)
        self.assertIn('["comment_001", "comment_061"]', prompt)
        self.assertIn("只能逐字复制", prompt)


class AgentExpressionMetricTests(unittest.TestCase):
    """真实评论只能与 Agent 已经实际发表的表达比较。"""

    def test_expression_distribution_excludes_silent_agents(self):
        records = [
            {
                "decision": {
                    "current_emotion": "negative",
                    "will_comment": True,
                    "selected_comment": {"emotion": "neutral"},
                }
            },
            {
                "decision": {
                    "current_emotion": "negative",
                    "will_comment": True,
                    "selected_comment": {"emotion": "negative"},
                }
            },
            {
                "decision": {
                    "current_emotion": "negative",
                    "will_comment": False,
                    "selected_comment": None,
                }
            },
        ]

        result = calculate_expression_distribution(records)

        self.assertEqual(result["agent_count"], 3)
        self.assertEqual(result["expression_count"], 2)
        self.assertEqual(result["silent_agent_count"], 1)
        self.assertEqual(result["classified_expression_count"], 2)
        self.assertEqual(result["distribution"]["negative"]["rate"], 0.5)
        self.assertEqual(result["distribution"]["neutral"]["rate"], 0.5)

    def test_expression_distribution_reports_empty_denominator(self):
        result = calculate_expression_distribution(
            [{"decision": {"will_comment": False}}]
        )

        self.assertEqual(result["expression_count"], 0)
        self.assertIsNone(result["distribution"]["negative"]["rate"])

    def test_historical_basis_does_not_change_strategy_default(self):
        metrics = {
            "agent_negative_emotion": {
                "agent_count": 10,
                "negative_count": 8,
                "negative_rate": 0.8,
            },
            "agent_expression_distribution": {
                "expression_count": 4,
                "silent_agent_count": 6,
                "classified_expression_count": 4,
                "distribution": {
                    "negative": {"count": 1, "rate": 0.25}
                },
            },
            "official_attitude_distribution": {
                "applicable_agent_count": 10,
                "distribution": {
                    "question": {"rate": 0.2},
                    "accept": {"rate": 0.3},
                },
            },
            "global_trend": {"trend_direction": "stable"},
        }

        strategy = extract_policy_metrics(metrics)
        historical = extract_policy_metrics(
            metrics,
            negative_rate_basis="agent_expression",
        )

        self.assertEqual(strategy["negative_rate"], 0.8)
        self.assertEqual(strategy["negative_rate_basis"], "agent_internal")
        self.assertEqual(historical["negative_rate"], 0.25)
        self.assertEqual(historical["negative_denominator"], 4)


class AttitudeDiagnosticTests(unittest.TestCase):
    """群体趋同应被记录，但不能直接中断实验。"""

    def test_diagnostics_report_diversity_and_synchronized_change(self):
        records = [
            {
                "decision": {
                    "official_attitude": attitude,
                    "claim_position": claim,
                    "process_evaluation": process,
                    "official_attitude_resolution": {
                        "transition_reason": reason,
                    },
                }
            }
            for attitude, claim, process, reason in (
                ("accept", "accepted", "partial", "changed_after_threshold"),
                ("wait", "unresolved", "dissatisfied", "held_by_personal_threshold"),
                ("question", "challenged", "dissatisfied", "changed_after_threshold"),
            )
        ]

        result = calculate_attitude_diagnostics(records, "clear")

        self.assertAlmostEqual(result["largest_attitude_group_rate"], 1 / 3, places=6)
        self.assertEqual(result["normalized_attitude_entropy"], 1.0)
        self.assertEqual(result["changed_agent_count"], 2)
        self.assertEqual(result["synchronized_transition_rate"], 0.666667)
        self.assertTrue(result["diagnostic_only"])


if __name__ == "__main__":
    unittest.main()
