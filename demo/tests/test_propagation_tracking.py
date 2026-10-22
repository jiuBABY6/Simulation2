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
from simulation.propagation import (  # noqa: E402
    extract_recent_agent_expressions,
    sample_neighbor_comments,
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

    def test_recent_expression_window_keeps_three_rounds(self):
        """策略传播池应保留最近三轮并记录准确轮龄。"""

        records = []
        for step in (1, 2, 3):
            records.append(
                {
                    "event_id": "event_test",
                    "step": step,
                    "status": "success",
                    "agent_id": "agent_source",
                    "decision": {
                        "will_comment": True,
                        "selected_comment": {
                            "comment_id": f"comment_{step}",
                            "text": f"第{step}轮表达",
                        },
                    },
                }
            )

        result = extract_recent_agent_expressions(
            records,
            "event_test",
            step=4,
            window_rounds=3,
        )

        self.assertEqual(
            [item["expression_age"] for item in result["agent_source"]],
            [1, 2, 3],
        )

    def test_neighbor_sampling_prefers_recent_and_deduplicates_root(self):
        """同一根传播链只曝光一次，且最近表达先占邻居名额。"""

        network = {
            "nodes": [
                {"agent_id": "target", "influence_weight": 1.0},
                {"agent_id": "source_a", "influence_weight": 1.0},
                {"agent_id": "source_b", "influence_weight": 1.0},
            ],
            "edges": [
                {"source_agent_id": "target", "target_agent_id": "source_a"},
                {"source_agent_id": "target", "target_agent_id": "source_b"},
            ],
            "propagation_decay_factor": 0.7,
        }
        expressions = {
            "source_a": [
                {
                    "comment_id": "recent_root_a",
                    "expression_id": "expression_recent_a",
                    "root_expression_ids": ["root_a"],
                    "expression_age": 1,
                    "propagation_depth": 0,
                },
                {
                    "comment_id": "old_root_b",
                    "expression_id": "expression_old_b",
                    "root_expression_ids": ["root_b"],
                    "expression_age": 3,
                    "propagation_depth": 0,
                },
            ],
            "source_b": [
                {
                    "comment_id": "duplicate_root_a",
                    "expression_id": "expression_duplicate_a",
                    "root_expression_ids": ["root_a"],
                    "expression_age": 2,
                    "propagation_depth": 0,
                }
            ],
        }

        result = sample_neighbor_comments(
            network,
            expressions,
            "target",
            "event_test",
            step=4,
            sample_count=2,
            random_seed=2026,
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["comment_id"], "recent_root_a")
        self.assertEqual(
            {item["root_expression_ids"][0] for item in result},
            {"root_a", "root_b"},
        )
        self.assertLess(
            result[1]["propagation_weight"],
            result[0]["propagation_weight"],
        )


if __name__ == "__main__":
    unittest.main()
