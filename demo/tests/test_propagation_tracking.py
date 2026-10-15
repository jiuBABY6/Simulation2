"""原创表达与邻居传播关系的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from simulation.propagation_tracking import (
    attach_expression_lineage,
    build_propagation_events,
)


class PropagationTrackingTests(unittest.TestCase):
    @staticmethod
    def _original_result(evidence_ids=None, will_comment=True):
        selected_comment = None
        if will_comment:
            selected_comment = {
                "comment_id": "agent_comment_new",
                "source_type": "agent_original_expression",
                "evidence_ids": list(evidence_ids or []),
            }
        return {
            "event_id": "event_test",
            "step": 3,
            "status": "success",
            "agent_id": "agent_target",
            "decision": {
                "will_comment": will_comment,
                "selected_comment_id": (
                    "agent_comment_new" if will_comment else None
                ),
                "selected_comment": selected_comment,
            },
        }

    @staticmethod
    def _neighbor_comment(
        comment_id,
        source_expression_id,
        root_expression_id,
        depth,
    ):
        return {
            "comment_id": comment_id,
            "source_type": "neighbor_propagation",
            "source_expression_ids": [source_expression_id],
            "root_expression_ids": [root_expression_id],
            "propagation_depth": depth,
            "propagation_sources": [
                {
                    "source_expression_id": source_expression_id,
                    "root_expression_ids": [root_expression_id],
                    "source_agent_id": "agent_source",
                    "propagation_depth": depth,
                    "influence_weight": 2.0,
                    "decay_factor": 0.7,
                    "effective_weight": 1.4,
                }
            ],
        }

    def test_uncited_original_expression_starts_a_new_root(self):
        result = attach_expression_lineage(
            self._original_result(["verified_fact"]),
            {"visible_comments": []},
        )

        decision = result["decision"]
        self.assertEqual(decision["propagation_depth"], 0)
        self.assertEqual(decision["parent_expression_ids"], [])
        self.assertEqual(
            decision["root_expression_ids"],
            [decision["expression_id"]],
        )

    def test_original_expression_inherits_cited_neighbor_lineage(self):
        neighbor = self._neighbor_comment(
            "neighbor_comment",
            "expression_parent",
            "expression_root",
            1,
        )
        result = attach_expression_lineage(
            self._original_result(["neighbor_comment"]),
            {"visible_comments": [neighbor]},
        )

        decision = result["decision"]
        self.assertEqual(decision["propagation_depth"], 1)
        self.assertEqual(
            decision["parent_expression_ids"],
            ["expression_parent"],
        )
        self.assertEqual(decision["root_expression_ids"], ["expression_root"])

    def test_original_expression_can_continue_a_second_hop(self):
        neighbor = self._neighbor_comment(
            "neighbor_comment",
            "expression_parent_depth_1",
            "expression_root",
            2,
        )
        result = attach_expression_lineage(
            self._original_result(["neighbor_comment"]),
            {"visible_comments": [neighbor]},
        )

        self.assertEqual(result["decision"]["propagation_depth"], 2)
        self.assertEqual(
            result["decision"]["root_expression_ids"],
            ["expression_root"],
        )

    def test_original_expression_keeps_multiple_cited_parents(self):
        comments = [
            self._neighbor_comment("neighbor_a", "parent_a", "root_a", 1),
            self._neighbor_comment("neighbor_b", "parent_b", "root_b", 2),
        ]
        result = attach_expression_lineage(
            self._original_result(["neighbor_a", "neighbor_b"]),
            {"visible_comments": comments},
        )

        decision = result["decision"]
        self.assertEqual(decision["propagation_depth"], 2)
        self.assertEqual(
            decision["parent_expression_ids"],
            ["parent_a", "parent_b"],
        )
        self.assertEqual(decision["root_expression_ids"], ["root_a", "root_b"])

    def test_silent_agent_has_no_expression_lineage(self):
        result = attach_expression_lineage(
            self._original_result(will_comment=False),
            {"visible_comments": []},
        )

        decision = result["decision"]
        self.assertIsNone(decision["expression_id"])
        self.assertIsNone(decision["propagation_depth"])
        self.assertEqual(decision["parent_expression_ids"], [])

    def test_original_expression_can_continue_cited_neighbor_exposure(self):
        views = {
            "agent_target": {
                "event_id": "event_test",
                "step": 2,
                "visible_comments": [
                    {
                        "comment_id": "neighbor_comment",
                        "source_type": "neighbor_propagation",
                        "propagation_sources": [
                            {
                                "source_expression_id": "expression_parent",
                                "root_expression_ids": ["expression_root"],
                                "source_agent_id": "agent_source",
                                "propagation_depth": 1,
                                "influence_weight": 2.0,
                                "decay_factor": 0.7,
                                "effective_weight": 1.4,
                            }
                        ],
                    }
                ],
            }
        }
        results = [self._original_result(["neighbor_comment"])]
        results[0] = attach_expression_lineage(
            results[0],
            views["agent_target"],
        )

        events = build_propagation_events(views, results)

        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["was_selected"])
        self.assertEqual(
            events[0]["resulting_expression_id"],
            results[0]["decision"]["expression_id"],
        )


if __name__ == "__main__":
    unittest.main()
