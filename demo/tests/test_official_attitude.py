"""官方态度个体裁决的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.official_attitude import resolve_official_attitude
from simulation.evidence_policy import official_statement_strength


def _profile(**overrides):
    profile = {
        "orientation": {"fact": 0.5, "opinion": 0.3, "questioning": 0.2},
        "state_inertia": 0.6,
        "attitude_change_threshold": 0.55,
        "official_acceptance_threshold": 0.55,
        "official_question_threshold": 0.50,
        "process_satisfaction_threshold": 0.55,
    }
    profile.update(overrides)
    return profile


def _evidence(evidence_id, target, score, *, unresolved=False, strength="strong"):
    return {
        "evidence_id": evidence_id,
        "evidence_group_id": evidence_id,
        "evidence_target": target,
        "evidence_strength": strength,
        "is_new_this_step": True,
        "unresolved_concern": unresolved,
        "personal_impact": {"official_attitude_score": score},
    }


class OfficialAttitudeTests(unittest.TestCase):
    def test_clear_statement_is_not_automatically_strong(self):
        self.assertEqual(
            official_statement_strength("clear", True),
            "moderate",
        )

    def test_same_evidence_is_interpreted_by_persona_thresholds(self):
        evidence = [
            _evidence("verified_fact", "fact_clarification", 0.65),
            _evidence(
                "public_concern",
                "process_accountability",
                0.55,
                unresolved=True,
            ),
        ]
        fact_profile = _profile(
            orientation={"fact": 0.8, "opinion": 0.1, "questioning": 0.1},
            official_acceptance_threshold=0.45,
            official_question_threshold=0.60,
        )
        questioning_profile = _profile(
            orientation={"fact": 0.1, "opinion": 0.1, "questioning": 0.8},
            official_acceptance_threshold=0.75,
            official_question_threshold=0.35,
        )

        fact_result = resolve_official_attitude(
            evidence,
            fact_profile,
            {},
            "clear",
            ["accept", "wait", "question"],
        )
        questioning_result = resolve_official_attitude(
            evidence,
            questioning_profile,
            {},
            "clear",
            ["accept", "wait", "question"],
        )

        self.assertEqual(fact_result["official_attitude"], "accept")
        self.assertEqual(questioning_result["official_attitude"], "question")
        self.assertEqual(fact_result["claim_position"], "accepted")
        self.assertEqual(questioning_result["claim_position"], "challenged")
        self.assertEqual(fact_result["process_evaluation"], "dissatisfied")

    def test_missing_new_evidence_keeps_previous_attitude(self):
        result = resolve_official_attitude(
            [],
            _profile(),
            {"official_attitude": "accept"},
            "clear",
            ["accept", "wait", "question"],
        )

        self.assertEqual(result["official_attitude"], "accept")
        self.assertEqual(result["transition_reason"], "held_without_new_evidence")

    def test_duplicate_claim_units_do_not_multiply_support(self):
        evidence = [
            {
                **_evidence("statement", "fact_clarification", 0.60),
                "evidence_group_id": "same_claim",
            },
            {
                **_evidence("statement_part", "fact_clarification", 0.59),
                "evidence_group_id": "same_claim",
            },
        ]

        result = resolve_official_attitude(
            evidence,
            _profile(official_acceptance_threshold=0.90),
            {},
            "clear",
            ["accept", "wait", "question"],
        )

        self.assertEqual(result["claim_confidence"], 0.60)
        self.assertEqual(result["supporting_evidence_ids"], ["statement"])

    def test_accepting_claim_can_coexist_with_process_dissatisfaction(self):
        """事实结论与处置过程必须允许形成不同方向的个体判断。"""

        evidence = [
            _evidence("verified_result", "fact_clarification", 0.72),
            _evidence(
                "unanswered_process_concern",
                "process_accountability",
                0.68,
                unresolved=True,
            ),
        ]

        result = resolve_official_attitude(
            evidence,
            _profile(
                official_acceptance_threshold=0.50,
                official_question_threshold=0.85,
                process_satisfaction_threshold=0.55,
            ),
            {},
            "clear",
            ["accept", "wait", "question"],
        )

        # 2026/10/14，新增功能验证：接受事实结论不等于满意处置过程。
        self.assertEqual(result["official_attitude"], "accept")
        self.assertEqual(result["claim_position"], "accepted")
        self.assertEqual(result["process_evaluation"], "dissatisfied")

    def test_process_evaluation_holds_without_new_process_evidence(self):
        """没有新的过程回应或关切时，不得把上一轮评价重置为partial。"""

        result = resolve_official_attitude(
            [],
            _profile(),
            {
                "official_attitude": "accept",
                "process_evaluation": "satisfied",
            },
            "clear",
            ["accept", "wait", "question"],
        )

        self.assertEqual(result["process_evaluation"], "satisfied")
        self.assertEqual(
            result["process_transition_reason"],
            "held_without_new_process_evidence",
        )

    def test_strong_unresolved_concern_can_reach_question(self):
        """真实强关切通过个体门槛后，应能从观望进入质疑。"""

        result = resolve_official_attitude(
            [
                _evidence(
                    "unresolved_gap",
                    "process_accountability",
                    0.45,
                    unresolved=True,
                    strength="moderate",
                )
            ],
            _profile(
                official_question_threshold=0.22,
                attitude_change_threshold=0.60,
                orientation={"fact": 0.2, "opinion": 0.2, "questioning": 0.6},
            ),
            {
                "official_attitude": "wait",
                "process_evaluation": "partial",
            },
            "incomplete",
            ["accept", "wait", "question"],
        )

        self.assertEqual(result["official_attitude"], "question")
        self.assertEqual(result["claim_position"], "challenged")
        self.assertEqual(result["process_evaluation"], "dissatisfied")


if __name__ == "__main__":
    unittest.main()
