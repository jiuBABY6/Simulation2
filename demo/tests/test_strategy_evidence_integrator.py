"""回应方案方向性证据整合器测试。"""

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.strategy_evidence_integrator import (  # noqa: E402
    evidence_direction,
    resolve_strategy_emotion,
)
from simulation.evidence_policy import (  # noqa: E402
    build_official_statement_evidence,
)


def profile(*, positive, neutral, negative, inertia, margin=0.02):
    return {
        "emotion_prior": {
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
        },
        "state_inertia": inertia,
        "emotion_switch_margin": margin,
    }


def comment_evidence(
    evidence_id,
    *,
    emotion="negative",
    group_id=None,
    score=0.15,
    threshold=0.5,
    neighbor=True,
):
    item = {
        "evidence_id": evidence_id,
        "evidence_group_id": group_id or evidence_id,
        "evidence_type": "simulated_comment",
        "comment_source": (
            "current_repost" if neighbor else "current_generated"
        ),
        "evidence_strength": "weak",
        "is_new_this_step": True,
        "emotion": emotion,
        "positive_eligible": emotion == "positive",
        "personal_impact": {
            "emotion_score": score,
            "emotion_change_threshold": threshold,
        },
    }
    if neighbor:
        item["network_influence_weight"] = 0.8
        item["source_agent_ids"] = [f"source_{evidence_id}"]
    return item


class StrategyEvidenceIntegratorTests(unittest.TestCase):
    def test_general_enforcement_is_not_positive_transition_evidence(self):
        enforcement = build_official_statement_evidence(
            {
                "step": 4,
                "official_statement": "警方已控制涉事人员并开展调查。",
                "official_statement_status": "clear",
            }
        )
        repaired = build_official_statement_evidence(
            {
                "step": 4,
                "official_statement": "现场隐患已消除，秩序恢复正常。",
                "official_statement_status": "clear",
            }
        )

        self.assertFalse(enforcement["positive_eligible"])
        self.assertTrue(repaired["positive_eligible"])

    def test_official_group_uses_multiple_semantic_dimensions(self):
        common = {
            "evidence_group_id": "official_step_4",
            "evidence_type": "official_statement_unit",
            "evidence_strength": "strong",
            "is_new_this_step": True,
            "positive_eligible": False,
            "personal_impact": {
                "emotion_score": 0.5,
                "emotion_change_threshold": 0.5,
            },
        }
        result = resolve_strategy_emotion(
            profile(
                positive=0.1,
                neutral=0.2,
                negative=0.7,
                inertia=0.9,
            ),
            {"current_emotion": "negative"},
            [
                {
                    **common,
                    "evidence_id": "official_step_4_part_1",
                    "content": "警方已控制涉事人员并送伤者就医。",
                    "evidence_target": "fact_clarification",
                },
                {
                    **common,
                    "evidence_id": "official_step_4_part_2",
                    "content": "案件正在进一步调查，结果将及时公布。",
                    "evidence_target": "investigation_process",
                    "unresolved_concern": True,
                },
            ],
            ["positive", "neutral", "negative"],
            current_step=4,
        )

        group = result["directional_evidence_groups"][0]
        self.assertEqual(
            set(group["semantic_dimensions"]),
            {"completed_action", "verified_fact", "unresolved_process"},
        )
        # 权威证据首轮只吸收一部分；语义组合仍须产生明确的中性方向，
        # 但不能在一次曝光中释放全部潜力。
        self.assertGreater(group["directional_support"]["neutral"], 0.15)
        self.assertLess(group["directional_support"]["neutral"], 0.95)
        self.assertGreater(group["absorbed_fraction"], 0.0)
        self.assertLess(group["absorbed_fraction"], 1.0)

    def test_unconsumed_authoritative_evidence_decays_for_two_rounds(self):
        item = {
            "evidence_id": "official_step_4_part_1",
            "evidence_group_id": "official_step_4",
            "evidence_type": "official_statement_unit",
            "content": "警方已开展调查并固定相关证据。",
            "evidence_target": "fact_clarification",
            "evidence_strength": "moderate",
            "is_new_this_step": True,
            "positive_eligible": False,
            "personal_impact": {
                "emotion_score": 0.18,
                "emotion_change_threshold": 0.5,
            },
        }
        stable_profile = profile(
            positive=0.0,
            neutral=0.1,
            negative=0.9,
            inertia=1.0,
        )
        first = resolve_strategy_emotion(
            stable_profile,
            {"current_emotion": "negative"},
            [item],
            ["positive", "neutral", "negative"],
            current_step=4,
        )
        second = resolve_strategy_emotion(
            stable_profile,
            {
                "current_emotion": "negative",
                "strategy_evidence_memory": first[
                    "strategy_evidence_memory"
                ],
                "strategy_evidence_assimilation": first[
                    "strategy_evidence_assimilation"
                ],
            },
            [],
            ["positive", "neutral", "negative"],
            current_step=5,
        )
        fourth = resolve_strategy_emotion(
            stable_profile,
            {
                "current_emotion": "negative",
                "strategy_evidence_memory": second[
                    "strategy_evidence_memory"
                ],
                "strategy_evidence_assimilation": second[
                    "strategy_evidence_assimilation"
                ],
            },
            [],
            ["positive", "neutral", "negative"],
            current_step=7,
        )

        self.assertEqual(
            second["evidence_lifecycle"]["restored_group_count"],
            1,
        )
        self.assertGreater(
            second["directional_evidence_groups"][0]["absorbed_fraction"],
            first["directional_evidence_groups"][0]["absorbed_fraction"],
        )
        self.assertEqual(
            fourth["evidence_lifecycle"]["restored_group_count"],
            0,
        )

    def test_consumed_evidence_cannot_move_same_agent_twice(self):
        item = {
            "evidence_id": "official_step_4_part_1",
            "evidence_group_id": "official_step_4",
            "evidence_type": "official_statement_unit",
            "content": "警方已控制涉事人员并送伤者就医。",
            "evidence_target": "fact_clarification",
            "evidence_strength": "strong",
            "is_new_this_step": True,
            "positive_eligible": False,
            "personal_impact": {
                "emotion_score": 0.5,
                "emotion_change_threshold": 0.5,
            },
        }
        responsive_profile = profile(
            positive=0.8,
            neutral=0.15,
            negative=0.05,
            inertia=0.0,
            margin=0.0,
        )
        first = resolve_strategy_emotion(
            responsive_profile,
            {"current_emotion": "negative"},
            [item],
            ["positive", "neutral", "negative"],
            current_step=4,
        )
        second = resolve_strategy_emotion(
            responsive_profile,
            {
                "current_emotion": first["selected_emotion"],
                "strategy_evidence_memory": first[
                    "strategy_evidence_memory"
                ],
            },
            [],
            ["positive", "neutral", "negative"],
            current_step=5,
        )

        self.assertEqual(first["selected_emotion"], "neutral")
        self.assertEqual(
            first["evidence_lifecycle"]["consumed_group_count"],
            1,
        )
        self.assertEqual(
            second["evidence_lifecycle"]["restored_group_count"],
            0,
        )
        self.assertEqual(second["selected_emotion"], "neutral")

    def test_same_root_duplicates_do_not_bypass_independence_gate(self):
        result = resolve_strategy_emotion(
            profile(
                positive=0.05,
                neutral=0.15,
                negative=0.8,
                inertia=0.1,
            ),
            {"current_emotion": "neutral"},
            [
                comment_evidence("n1", group_id="root_1"),
                comment_evidence("n2", group_id="root_1"),
            ],
            ["positive", "neutral", "negative"],
        )

        self.assertEqual(result["directional_evidence_group_count"], 1)
        self.assertEqual(result["emotion_options"], ["neutral"])
        self.assertEqual(
            result["transition_reason"],
            "held_without_independent_roots",
        )

    def test_same_evidence_can_produce_different_persona_outcomes(self):
        evidence = [comment_evidence("n1"), comment_evidence("n2")]
        responsive = resolve_strategy_emotion(
            profile(
                positive=0.1,
                neutral=0.1,
                negative=0.8,
                inertia=0.1,
            ),
            {"current_emotion": "neutral"},
            evidence,
            ["positive", "neutral", "negative"],
        )
        stable = resolve_strategy_emotion(
            profile(
                positive=0.0,
                neutral=1.0,
                negative=0.0,
                inertia=1.0,
            ),
            {"current_emotion": "neutral"},
            evidence,
            ["positive", "neutral", "negative"],
        )

        self.assertEqual(responsive["emotion_options"], ["negative"])
        self.assertEqual(stable["emotion_options"], ["neutral"])

    def test_completed_action_is_stronger_than_pending_statement(self):
        completed = evidence_direction(
            {
                "evidence_type": "official_statement_unit",
                "content": "警方已控制涉事人员并送伤者就医。",
                "evidence_target": "investigation_process",
            }
        )
        pending = evidence_direction(
            {
                "evidence_type": "official_statement_unit",
                "content": "警方正在进一步调查，结果将及时公布。",
                "evidence_target": "investigation_process",
                "unresolved_concern": True,
            }
        )

        self.assertGreater(completed["neutral"], pending["neutral"])
        self.assertGreater(completed["positive"], pending["positive"])
        self.assertGreater(pending["negative"], completed["negative"])

    def test_statement_semantics_can_change_outcome_without_plan_quota(self):
        base = {
            "evidence_id": "official_2",
            "evidence_group_id": "official_2",
            "evidence_type": "official_statement_unit",
            "evidence_target": "investigation_process",
            "evidence_strength": "moderate",
            "is_new_this_step": True,
            "positive_eligible": True,
            "personal_impact": {
                "emotion_score": 0.25,
                "emotion_change_threshold": 0.5,
            },
        }
        decision_profile = profile(
            positive=0.0,
            neutral=0.4,
            negative=0.6,
            inertia=0.5,
        )
        completed = resolve_strategy_emotion(
            decision_profile,
            {"current_emotion": "negative"},
            [
                {
                    **base,
                    "content": "警方已控制涉事人员并送伤者就医。",
                    "evidence_target": "fact_clarification",
                }
            ],
            ["positive", "neutral", "negative"],
        )
        pending = resolve_strategy_emotion(
            decision_profile,
            {"current_emotion": "negative"},
            [
                {
                    **base,
                    "content": "警方正在进一步调查，结果将及时公布。",
                    "unresolved_concern": True,
                }
            ],
            ["positive", "neutral", "negative"],
        )

        self.assertEqual(completed["selected_emotion"], "neutral")
        self.assertEqual(pending["selected_emotion"], "negative")

    def test_adjacent_transition_prevents_negative_to_positive_jump(self):
        result = resolve_strategy_emotion(
            profile(
                positive=0.9,
                neutral=0.05,
                negative=0.05,
                inertia=0.0,
                margin=0.0,
            ),
            {"current_emotion": "negative"},
            [
                comment_evidence("p1", emotion="positive", score=0.5),
                comment_evidence("p2", emotion="positive", score=0.5),
            ],
            ["positive", "neutral", "negative"],
        )

        self.assertNotEqual(result["selected_emotion"], "positive")
        self.assertIn(result["selected_emotion"], {"negative", "neutral"})

    def test_no_new_directional_evidence_holds_previous_state(self):
        result = resolve_strategy_emotion(
            profile(
                positive=0.1,
                neutral=0.2,
                negative=0.7,
                inertia=0.2,
            ),
            {"current_emotion": "neutral"},
            [],
            ["positive", "neutral", "negative"],
        )

        self.assertEqual(result["emotion_options"], ["neutral"])
        self.assertEqual(
            result["state_change_basis"],
            "held_without_directional_evidence",
        )


if __name__ == "__main__":
    unittest.main()
