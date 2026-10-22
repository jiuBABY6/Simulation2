"""策略实验证据作用通道路由测试。"""

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.evidence_impact_router import (  # noqa: E402
    route_emotion_support,
    route_evidence_impact,
)


class EvidenceImpactRouterTests(unittest.TestCase):
    def test_public_discussion_does_not_directly_rewrite_event_emotion(self):
        support, routing = route_emotion_support(
            {
                "reaction_target": "public_discourse",
                "evidence_role": "opinion",
                "information_source_type": "agent",
            },
            {"positive": 0.0, "neutral": 0.0, "negative": 1.0},
        )

        self.assertEqual(support["negative"], 0.0)
        self.assertEqual(routing["participation"], 1.0)

    def test_event_harm_keeps_full_event_emotion_signal(self):
        support, routing = route_emotion_support(
            {
                "reaction_target": "event_harm",
                "evidence_role": "opinion",
                "information_source_type": "public",
            },
            {"positive": 0.0, "neutral": 0.0, "negative": 0.8},
        )

        self.assertEqual(support["negative"], 0.8)
        self.assertEqual(routing["event_emotion"], 1.0)

    def test_process_question_routes_to_attitude_not_event_harm(self):
        routing = route_evidence_impact(
            {
                "reaction_target": "investigation_process",
                "evidence_role": "question",
                "information_source_type": "public",
            }
        )

        self.assertLess(routing["event_emotion"], 0.1)
        self.assertEqual(routing["official_attitude"], 1.0)
        self.assertGreater(routing["participation"], 0.5)


if __name__ == "__main__":
    unittest.main()
