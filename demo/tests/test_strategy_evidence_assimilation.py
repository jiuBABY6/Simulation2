"""回应方案权威证据渐进吸收测试。"""

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.strategy_evidence_assimilation import (  # noqa: E402
    consume_groups,
    persona_assimilation_rate,
    prepare_assimilated_groups,
)


def profile(*, fact, opinion, questioning, interest, inertia):
    return {
        "orientation": {
            "fact": fact,
            "opinion": opinion,
            "questioning": questioning,
        },
        "topic_interest": interest,
        "state_inertia": inertia,
    }


def authoritative_group():
    return {
        "evidence_group_id": "official_step_2",
        "evidence_ids": ["official_step_2_part_1"],
        "source_kinds": ["authoritative"],
        "directional_support": {
            "positive": 0.0,
            "neutral": 0.8,
            "negative": 0.0,
        },
        "base_directional_support": {
            "positive": 0.0,
            "neutral": 0.8,
            "negative": 0.0,
        },
        "supporting_id_by_emotion": {
            "neutral": "official_step_2_part_1"
        },
        "positive_eligible": False,
        "semantic_dimensions": ["verified_fact"],
        "evidence_types": ["official_statement_unit"],
        "max_evidence_strength": "moderate",
    }


class StrategyEvidenceAssimilationTests(unittest.TestCase):
    def test_persona_changes_assimilation_rate(self):
        fast = persona_assimilation_rate(
            profile(
                fact=0.9,
                opinion=0.05,
                questioning=0.05,
                interest=0.9,
                inertia=0.2,
            ),
            authoritative_group(),
        )
        slow = persona_assimilation_rate(
            profile(
                fact=0.05,
                opinion=0.1,
                questioning=0.85,
                interest=0.2,
                inertia=0.9,
            ),
            authoritative_group(),
        )

        self.assertGreater(fast, slow)

    def test_authoritative_evidence_absorbs_gradually_then_expires(self):
        decision_profile = profile(
            fact=0.5,
            opinion=0.2,
            questioning=0.3,
            interest=0.6,
            inertia=0.6,
        )
        first = prepare_assimilated_groups(
            {},
            2,
            [authoritative_group()],
            decision_profile,
        )
        second = prepare_assimilated_groups(
            {"strategy_evidence_assimilation": first["memory"]},
            3,
            [],
            decision_profile,
        )
        third = prepare_assimilated_groups(
            {"strategy_evidence_assimilation": second["memory"]},
            4,
            [],
            decision_profile,
        )
        expired = prepare_assimilated_groups(
            {"strategy_evidence_assimilation": third["memory"]},
            5,
            [],
            decision_profile,
        )

        fractions = [
            result["groups"][0]["absorbed_fraction"]
            for result in (first, second, third)
        ]
        self.assertLess(fractions[0], fractions[1])
        self.assertLess(fractions[1], fractions[2])
        self.assertEqual(expired["groups"], [])
        self.assertEqual(expired["diagnostics"]["expired_group_count"], 1)

    def test_consumed_group_is_not_restored(self):
        decision_profile = profile(
            fact=0.5,
            opinion=0.2,
            questioning=0.3,
            interest=0.6,
            inertia=0.6,
        )
        first = prepare_assimilated_groups(
            {},
            2,
            [authoritative_group()],
            decision_profile,
        )
        consumed = consume_groups(first["memory"], ["official_step_2"], 2)
        second = prepare_assimilated_groups(
            {"strategy_evidence_assimilation": consumed},
            3,
            [],
            decision_profile,
        )

        self.assertEqual(second["groups"], [])
        self.assertEqual(second["diagnostics"]["restored_group_count"], 0)


if __name__ == "__main__":
    unittest.main()
