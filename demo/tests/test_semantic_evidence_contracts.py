"""2026/10/19 六项现实语义与传播约束的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.strategy_attitude_lifecycle import (  # noqa: E402
    prepare_attitude_evidence,
)
from comments.incremental_generator import build_incremental_prompt  # noqa: E402
from domain.comment_semantics import (  # noqa: E402
    normalize_comment_semantics,
    normalize_evidence_semantics,
)
from simulation.counterfactual_controls import (  # noqa: E402
    audit_cross_scenario_controls,
    audit_scenario_isolation,
    build_scenario_input_sha256,
    normalize_objective_fact_timeline,
)
from simulation.social_network import (  # noqa: E402
    get_normalized_influence_weight,
    validate_social_network,
)
from simulation.options import normalize_simulation_options  # noqa: E402


class CommentSemanticContractTests(unittest.TestCase):
    def test_legacy_neighbor_comment_keeps_provenance_but_becomes_endogenous(self):
        normalized = normalize_comment_semantics(
            {
                "comment_id": "c1",
                "source_type": "neighbor_propagation",
                "emotion_target": "official_response",
            }
        )

        self.assertEqual(normalized["source_type"], "neighbor_propagation")
        self.assertEqual(normalized["provenance_type"], "neighbor_propagation")
        self.assertEqual(normalized["information_source_type"], "agent")
        self.assertEqual(normalized["information_origin"], "endogenous")
        self.assertEqual(normalized["reaction_target"], "official_response")

    def test_public_support_does_not_become_authoritative_fact(self):
        normalized = normalize_evidence_semantics(
            {
                "evidence_id": "public-1",
                "evidence_type": "simulated_comment",
                "evidence_target": "official_claim",
                "evidence_role": "support",
                "source_type": "llm_generated",
            }
        )

        self.assertEqual(normalized["information_source_type"], "public")
        self.assertEqual(normalized["evidence_role"], "support")


class OfficialAttitudeLifecycleTests(unittest.TestCase):
    def test_authoritative_claim_survives_as_background_memory(self):
        evidence = {
            "evidence_id": "official-3",
            "evidence_group_id": "official-3",
            "evidence_type": "official_statement",
            "reaction_target": "official_claim",
            "evidence_target": "official_claim",
            "evidence_role": "clarify",
            "information_source_type": "official",
            "information_origin": "exogenous",
            "evidence_strength": "moderate",
            "is_new_this_step": True,
            "personal_impact": {"official_attitude_score": 0.7},
        }
        first = prepare_attitude_evidence({}, 3, [evidence])
        second = prepare_attitude_evidence(
            {"strategy_attitude_memory": first["memory"]},
            4,
            [],
        )

        self.assertEqual(first["diagnostics"]["new_count"], 1)
        self.assertEqual(second["diagnostics"]["restored_count"], 1)
        restored = second["evidence_items"][0]
        self.assertFalse(restored["is_new_this_step"])
        self.assertAlmostEqual(
            restored["personal_impact"]["official_attitude_score"],
            0.644,
        )

    def test_public_support_is_not_stored_as_official_fact(self):
        public_support = {
            "evidence_id": "public-support",
            "evidence_group_id": "public-support",
            "reaction_target": "official_claim",
            "evidence_target": "official_claim",
            "evidence_role": "support",
            "information_source_type": "public",
            "information_origin": "exogenous",
            "is_new_this_step": True,
            "personal_impact": {"official_attitude_score": 0.9},
        }

        result = prepare_attitude_evidence({}, 3, [public_support])

        self.assertEqual(result["evidence_items"], [])
        self.assertEqual(result["memory"], {})

    def test_new_clarification_replaces_old_concern_for_same_claim(self):
        concern = {
            "evidence_id": "concern-3",
            "evidence_group_id": "claim-3",
            "reaction_target": "official_claim",
            "evidence_target": "official_claim",
            "evidence_role": "question",
            "information_source_type": "official",
            "is_new_this_step": True,
            "unresolved_concern": True,
            "personal_impact": {"official_attitude_score": 0.6},
        }
        first = prepare_attitude_evidence({}, 3, [concern])
        clarification = {
            **concern,
            "evidence_id": "clarification-4",
            "evidence_role": "clarify",
            "unresolved_concern": False,
        }

        second = prepare_attitude_evidence(
            {"strategy_attitude_memory": first["memory"]},
            4,
            [clarification],
        )

        self.assertEqual(len(second["memory"]), 1)
        self.assertEqual(
            second["evidence_items"][0]["evidence_role"],
            "clarify",
        )


class NetworkNormalizationTests(unittest.TestCase):
    def test_raw_and_cognitive_weights_are_both_preserved(self):
        snapshot = validate_social_network(
            {
                "neighbors_per_agent": 1,
                "visibility": {
                    "neighbor_comment_count": 1,
                    "public_comment_count": 1,
                },
                "nodes": [
                    {"agent_id": "a", "influence_weight": 1.0},
                    {"agent_id": "b", "influence_weight": 1.6},
                    {"agent_id": "c", "influence_weight": 2.2},
                ],
                "edges": [
                    {"source_agent_id": "a", "target_agent_id": "b"},
                    {"source_agent_id": "b", "target_agent_id": "c"},
                    {"source_agent_id": "c", "target_agent_id": "a"},
                ],
            }
        )

        self.assertEqual(snapshot["nodes"][2]["influence_weight"], 2.2)
        self.assertEqual(get_normalized_influence_weight(snapshot, "a"), 0.0)
        self.assertEqual(get_normalized_influence_weight(snapshot, "b"), 0.5)
        self.assertEqual(get_normalized_influence_weight(snapshot, "c"), 1.0)


class CounterfactualIsolationTests(unittest.TestCase):
    def test_scenario_hash_includes_official_evidence_dimensions(self):
        shared_hash = "a" * 64
        common = {
            "official_statement": "通告正文相同",
            "official_statement_status": "incomplete",
        }

        first = build_scenario_input_sha256(
            shared_hash,
            "response_plan_1",
            {
                **common,
                "official_evidence_dimensions": {"empathy": True},
            },
        )
        second = build_scenario_input_sha256(
            shared_hash,
            "response_plan_1",
            {
                **common,
                "official_evidence_dimensions": {"empathy": False},
            },
        )

        self.assertNotEqual(first, second)

    def test_strategy_public_reaction_reads_statement_and_agent_discussion(self):
        event_context = {
            "event_id": "event-test",
            "event_content": "测试事件",
            "event_labels": {"topic": "社会事件"},
            "simulation_options": normalize_simulation_options({}),
            "current_state": {
                "step": 3,
                "official_statement": "SECRET_OFFICIAL_STATEMENT",
                "official_statement_status": "clear",
            },
        }

        prompt = build_incremental_prompt(
            event_context,
            [{"text": "SECRET_AGENT_DISCUSSION"}],
            [
                {
                    "profile_id": 1,
                    "profile_label": "测试公众",
                    "definition": "测试定义",
                }
            ],
            1,
            "scheduled",
            {"comment_count": 1},
            [],
            None,
        )

        self.assertIn("SECRET_OFFICIAL_STATEMENT", prompt)
        self.assertIn("SECRET_AGENT_DISCUSSION", prompt)
        self.assertIn("不得假装未看到已经公开的信息", prompt)

    def test_objective_fact_timeline_is_normalized_by_step(self):
        timeline = normalize_objective_fact_timeline(
            {
                "event_id": "event-test",
                "objective_event_timeline": {
                    "rounds": [
                        {
                            "step": 3,
                            "events": [{"text": "事实三"}],
                            "phase": "第三阶段",
                        },
                        {
                            "step": 2,
                            "objective_event_context": {
                                "events": [{"text": "事实二"}]
                            },
                        },
                    ]
                },
            }
        )

        self.assertEqual([item["step"] for item in timeline], [2, 3])
        self.assertEqual(
            timeline[1]["objective_event_timing"]["phase"],
            "第三阶段",
        )

    def test_scenario_isolation_accepts_independent_reactive_records(self):
        state_records = [
            {
                "event_id": "event-test",
                "step": 2,
                "official_statement": "本场景通告",
                "official_statement_status": "clear",
                "scenario_id": "response_plan_1",
                "shared_input_sha256": "a" * 64,
            },
        ]
        incremental_records = [
            {
                "event_id": "event-test",
                "step": 2,
                "scenario_id": "response_plan_1",
                "shared_input_sha256": "a" * 64,
                "generation_mode": "scenario_reactive_public",
                "comments": [
                    {
                        "comment_id": "c2",
                        "scenario_id": "response_plan_1",
                        "shared_input_sha256": "a" * 64,
                        "causal_origin": "scenario_reactive_public",
                    }
                ],
            },
        ]
        with patch(
            "simulation.counterfactual_controls.load_event_state_history",
            return_value=state_records,
        ), patch(
            "simulation.counterfactual_controls.read_jsonl",
            return_value=incremental_records,
        ):
            audit = audit_scenario_isolation(
                state_dir=Path("state"),
                event_id="event-test",
                scenario_id="response_plan_1",
                response_step=2,
                shared_input_sha256="a" * 64,
                objective_fact_timeline=[],
                expected_response={
                    "official_statement": "本场景通告",
                    "official_statement_status": "clear",
                },
            )

        self.assertEqual(audit["status"], "passed")
        self.assertEqual(audit["public_reaction_record_count"], 1)

    def test_scenario_isolation_rejects_legacy_shared_public_comments(self):
        with patch(
            "simulation.counterfactual_controls.load_event_state_history",
            return_value=[
                {
                    "event_id": "event-test",
                    "step": 2,
                    "official_statement": "",
                    "official_statement_status": "none",
                    "scenario_id": "no_response",
                    "shared_input_sha256": "a" * 64,
                }
            ],
        ), patch(
            "simulation.counterfactual_controls.read_jsonl",
            return_value=[
                {
                    "event_id": "event-test",
                    "step": 2,
                    "scenario_id": "no_response",
                    "shared_input_sha256": "a" * 64,
                    "generation_mode": "shared_exogenous_context",
                    "shared_external_context": True,
                    "comments": [
                        {"comment_id": "c2", "scenario_id": "no_response"}
                    ],
                }
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "共享公众评论"):
                audit_scenario_isolation(
                    state_dir=Path("state"),
                    event_id="event-test",
                    scenario_id="no_response",
                    response_step=2,
                    shared_input_sha256="a" * 64,
                    objective_fact_timeline=[],
                    expected_response={
                        "official_statement": "",
                        "official_statement_status": "none",
                    },
                )

    def test_cross_scenario_audit_requires_common_inputs_and_distinct_states(self):
        result = audit_cross_scenario_controls(
            [
                {
                    "strategy": "no_response",
                    "status": "success",
                    "state_dir": "state/no_response",
                    "counterfactual_controls": {
                        "shared_input_sha256": "a" * 64,
                        "scenario_input_sha256": "b" * 64,
                        "isolation_audit": {"status": "passed"},
                    },
                },
                {
                    "strategy": "response_plan_1",
                    "status": "success",
                    "state_dir": "state/response_plan_1",
                    "counterfactual_controls": {
                        "shared_input_sha256": "a" * 64,
                        "scenario_input_sha256": "c" * 64,
                        "isolation_audit": {"status": "passed"},
                    },
                },
            ]
        )

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["state_directories_are_distinct"])

    def test_cross_scenario_audit_propagates_scenario_audit_failure(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "response_plan_2",
        ):
            audit_cross_scenario_controls(
                [
                    {
                        "strategy": "response_plan_2",
                        "status": "failed",
                        "failure_type": "isolation_audit",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
