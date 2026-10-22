"""策略机制消融开关的回归测试。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.state_evidence import (  # noqa: E402
    build_state_evidence_view,
    select_state_evidence_comments,
)
from ablation_runner import (  # noqa: E402
    _build_comparison_matrix,
    _build_variant_event,
)
from comments.incremental_generator import (  # noqa: E402
    run_frozen_incremental_generation,
    validate_incremental_record,
)
from simulation.options import (  # noqa: E402
    freezes_incremental_public_comments,
    normalize_simulation_options,
    uses_neighbor_feedback,
)


class AblationOptionTests(unittest.TestCase):
    def test_defaults_preserve_full_feedback(self):
        options = normalize_simulation_options({})

        self.assertEqual(
            options["ablation"]["incremental_public_comment_mode"],
            "llm_incremental",
        )
        self.assertEqual(
            options["ablation"]["state_comment_evidence_mode"],
            "all_visible",
        )
        self.assertTrue(options["ablation"]["neighbor_feedback_enabled"])
        self.assertIsNone(options["ablation"]["fixed_response_step"])

    def test_explicit_ablation_options_are_normalized(self):
        context = {
            "simulation_options": {
                "ablation": {
                    "incremental_public_comment_mode": (
                        "frozen_after_initial"
                    ),
                    "state_comment_evidence_mode": (
                        "exclude_llm_incremental"
                    ),
                    "neighbor_feedback_enabled": False,
                    "fixed_response_step": 2,
                }
            }
        }
        options = normalize_simulation_options(context)
        normalized_context = {"simulation_options": options}

        self.assertTrue(
            freezes_incremental_public_comments(normalized_context)
        )
        self.assertFalse(uses_neighbor_feedback(normalized_context))

    def test_invalid_ablation_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "llm_incremental"):
            normalize_simulation_options(
                {
                    "simulation_options": {
                        "ablation": {
                            "incremental_public_comment_mode": "unknown"
                        }
                    }
                }
            )

    def test_variant_event_does_not_modify_source_event(self):
        source = {
            "event_id": "event_test",
            "event_content": "test content",
        }

        variant = _build_variant_event(
            source,
            "frozen_public",
            fixed_response_step=3,
        )

        self.assertNotIn("simulation_options", source)
        self.assertEqual(
            variant["simulation_options"]["ablation"][
                "incremental_public_comment_mode"
            ],
            "frozen_after_initial",
        )
        self.assertEqual(
            variant["simulation_options"]["ablation"][
                "fixed_response_step"
            ],
            3,
        )


class StateEvidenceAblationTests(unittest.TestCase):
    def test_only_external_incremental_comments_are_excluded(self):
        event = {
            "simulation_options": normalize_simulation_options(
                {
                    "simulation_options": {
                        "ablation": {
                            "state_comment_evidence_mode": (
                                "exclude_llm_incremental"
                            )
                        }
                    }
                }
            )
        }
        comments = [
            {
                "comment_id": "initial",
                "introduced_step": 1,
                "generation_trigger": "initial_event",
            },
            {
                "comment_id": "external",
                "introduced_step": 2,
                "generation_trigger": "ongoing_discussion",
            },
            {
                "comment_id": "agent",
                "introduced_step": 2,
                "generation_trigger": "agent_decision",
                "source_type": "neighbor_propagation",
            },
        ]

        selected = select_state_evidence_comments(comments, event)

        self.assertEqual(
            [item["comment_id"] for item in selected],
            ["initial", "agent"],
        )

    def test_default_mode_keeps_all_visible_comments(self):
        comments = [{"comment_id": "external", "introduced_step": 2}]
        selected = select_state_evidence_comments(
            comments,
            {"simulation_options": normalize_simulation_options({})},
        )
        self.assertEqual(selected, comments)

    def test_malformed_step_is_not_misclassified_as_initial(self):
        event = {
            "simulation_options": normalize_simulation_options(
                {
                    "simulation_options": {
                        "ablation": {
                            "state_comment_evidence_mode": (
                                "exclude_llm_incremental"
                            )
                        }
                    }
                }
            )
        }
        selected = select_state_evidence_comments(
            [{"comment_id": "bad", "introduced_step": "bad"}],
            event,
        )
        self.assertEqual(selected, [])

    def test_strategy_state_view_limits_recent_unique_neighbor_roots(self):
        event = {
            "simulation_options": normalize_simulation_options({}),
        }
        comments = [
            {
                "comment_id": "public",
                "source_type": "llm_generated",
                "introduced_step": 2,
            },
            {
                "comment_id": "n1",
                "source_type": "neighbor_propagation",
                "expression_age": 1,
                "root_expression_ids": ["root-1"],
                "propagation_weight": 0.9,
            },
            {
                "comment_id": "n1-duplicate",
                "source_type": "neighbor_propagation",
                "expression_age": 1,
                "root_expression_ids": ["root-1"],
                "propagation_weight": 0.8,
            },
            {
                "comment_id": "n2",
                "source_type": "neighbor_propagation",
                "expression_age": 1,
                "root_expression_ids": ["root-2"],
                "propagation_weight": 0.7,
            },
            {
                "comment_id": "old",
                "source_type": "neighbor_propagation",
                "expression_age": 2,
                "root_expression_ids": ["root-3"],
                "propagation_weight": 1.0,
            },
        ]

        view = build_state_evidence_view(comments, event)

        # 2026/10/19，传播窗口与认知窗口统一为最近 3 轮，因此第 2 轮的
        # 邻居表达不再被状态判断提前丢弃。
        self.assertEqual(
            [item["comment_id"] for item in view["comments"]],
            ["public", "n1", "n2", "old"],
        )
        diagnostics = view["diagnostics"]
        self.assertEqual(diagnostics["neighbor_state_evidence_count"], 3)
        self.assertEqual(diagnostics["neighbor_duplicate_root_count"], 1)
        self.assertEqual(diagnostics["neighbor_excluded_by_age_count"], 0)

    def test_strategy_state_view_limits_public_comments_by_persona(self):
        event = {
            "event_labels": {"topic": "社会事件"},
            "current_state": {"step": 2},
            "simulation_options": normalize_simulation_options({}),
        }
        persona = {
            "topic_preference": {"社会事件": 1.0},
            "information_orientation": {
                "fact_rate": 0.9,
                "opinion_rate": 0.05,
                "questioning_rate": 0.05,
            },
        }
        comments = [
            {
                "comment_id": f"public-{index}",
                "source_type": "llm_generated",
                "introduced_step": 2,
                "topic": "社会事件",
                "orientation": "fact" if index < 3 else "opinion",
            }
            for index in range(8)
        ]

        view = build_state_evidence_view(comments, event, persona)

        self.assertEqual(len(view["comments"]), 5)
        self.assertTrue(
            {"public-0", "public-1", "public-2"}.issubset(
                {item["comment_id"] for item in view["comments"]}
            )
        )
        self.assertEqual(
            view["diagnostics"]["public_excluded_by_limit_count"],
            3,
        )


class FrozenIncrementalRecordTests(unittest.TestCase):
    def test_frozen_round_writes_one_valid_empty_record(self):
        context = {
            "event_id": "event_test",
            "current_state": {"step": 2},
        }
        with (
            patch(
                "comments.incremental_generator.load_event_context",
                return_value=context,
            ),
            patch(
                "comments.incremental_generator.load_incremental_history",
                side_effect=[
                    [],
                    [{"event_id": "event_test", "step": 2}],
                ],
            ),
            patch(
                "comments.incremental_generator.append_incremental_record"
            ) as append_record,
            patch(
                "comments.incremental_generator.ensure_runtime_directories"
            ),
        ):
            record = run_frozen_incremental_generation()
            with self.assertRaisesRegex(ValueError, "已经存在"):
                run_frozen_incremental_generation()

        validate_incremental_record(record)
        append_record.assert_called_once()
        self.assertEqual(record["comment_count"], 0)
        self.assertEqual(record["comments"], [])
        self.assertEqual(
            record["generation_mode"],
            "disabled_by_ablation",
        )


class AblationComparisonTests(unittest.TestCase):
    def test_matrix_uses_saved_round_metrics(self):
        variants = [
            {
                "variant": "full_feedback",
                "strategy_results": [
                    {
                        "status": "success",
                        "strategy": "response_plan_1",
                        "strategy_name": "方案一",
                        "rounds": [
                            {
                                "step": 2,
                                "policy_metrics": {"negative_rate": 0.6},
                                "agent_expression_distribution": {
                                    "participation_rate": 0.5,
                                    "distribution": {
                                        "negative": {"rate": 0.4}
                                    },
                                },
                                "neighbor_exposure_diagnostics": {
                                    "effective_neighbor_exposure_rate": 0.3
                                },
                                "strategy_state_diagnostics": {
                                    "neighbor_state_evidence_retention_rate": 0.5,
                                    "public_state_evidence_retention_rate": 0.45,
                                    "effective_non_peer_evidence_count": 2,
                                },
                                "comment_generation": {
                                    "generation_mode": "llm_incremental"
                                },
                            }
                        ],
                    }
                ],
            }
        ]

        matrix = _build_comparison_matrix(variants)

        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix[0]["rounds"][0]["internal_negative_rate"], 0.6)
        self.assertEqual(
            matrix[0]["rounds"][0]["effective_neighbor_exposure_rate"],
            0.3,
        )
        self.assertEqual(
            matrix[0]["rounds"][0][
                "public_state_evidence_retention_rate"
            ],
            0.45,
        )
        self.assertEqual(
            matrix[0]["rounds"][0][
                "effective_non_peer_evidence_count"
            ],
            2,
        )


if __name__ == "__main__":
    unittest.main()
