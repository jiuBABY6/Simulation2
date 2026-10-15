"""历史增量评论最小情绪覆盖的离线测试。"""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from comments.angle_planner import build_incremental_angle_tasks
from comments.incremental_generator import summarize_emotion_coverage


ANGLE_PLAN = {
    "angles": [
        {
            "angle_id": "event_fact",
            "angle_name": "事实进展",
            "focus": "关注调查进展",
            "source_type": "event",
        }
    ]
}


def _state(with_positive: bool = True) -> dict:
    return {
        "step": 2,
        "official_statement": "",
        "official_statement_status": "none",
        "objective_event_context": {
            "events": [
                {
                    "objective_event_id": "objective_002",
                    "event_type": (
                        "search_action" if with_positive else "fact_discovery"
                    ),
                    "content": "搜寻仍在继续。",
                }
            ],
        },
    }


PREVIOUS_COMMENTS = [
    {
        "comment_id": "comment_001",
        "text": "目前信息仍然有限。",
        "emotion": "neutral",
    },
    {
        "comment_id": "comment_002",
        "text": "失联事件令人担忧。",
        "emotion": "negative",
    },
]


class IncrementalEmotionCoverageTests(unittest.TestCase):
    def test_evidence_mode_assigns_only_minimum_coverage(self) -> None:
        tasks = build_incremental_angle_tasks(
            ANGLE_PLAN,
            _state(),
            20,
            evidence_based=True,
            previous_comments=PREVIOUS_COMMENTS,
        )
        counts = Counter(
            task.get("required_emotion")
            for task in tasks
            if task.get("required_emotion")
        )

        self.assertEqual(counts, Counter({"positive": 1, "neutral": 1, "negative": 1}))
        self.assertTrue(
            next(task for task in tasks if task.get("required_emotion") == "positive")[
                "positive_evidence"
            ]
        )

    def test_no_positive_evidence_does_not_force_positive_comment(self) -> None:
        tasks = build_incremental_angle_tasks(
            ANGLE_PLAN,
            _state(with_positive=False),
            20,
            evidence_based=True,
            previous_comments=PREVIOUS_COMMENTS,
        )

        self.assertNotIn("positive", {task.get("required_emotion") for task in tasks})

    def test_persistent_statement_does_not_force_new_positive_comment(self) -> None:
        state = {
            "step": 3,
            "official_statement": "此前调查通告继续有效。",
            "official_statement_status": "clear",
            "official_statement_timing": {
                "introduced_step": 2,
                "active_round_count": 2,
                "is_new": False,
            },
            "objective_event_context": {"events": []},
        }
        previous_comments = [
            comment
            for comment in PREVIOUS_COMMENTS
            if comment["emotion"] != "positive"
        ]

        tasks = build_incremental_angle_tasks(
            ANGLE_PLAN,
            state,
            20,
            evidence_based=True,
            previous_comments=previous_comments,
        )

        self.assertNotIn(
            "positive",
            {task.get("required_emotion") for task in tasks},
        )
        neutral_task = next(
            task for task in tasks if task.get("required_emotion") == "neutral"
        )
        self.assertEqual(
            neutral_task["evidence_ids"],
            ["official_statement_step_2"],
        )

    def test_coverage_reports_missing_required_task(self) -> None:
        tasks = build_incremental_angle_tasks(
            ANGLE_PLAN,
            _state(),
            3,
            evidence_based=True,
            previous_comments=PREVIOUS_COMMENTS,
        )
        completed = [
            {
                "task_id": task["task_id"],
                "emotion": task["required_emotion"],
            }
            for task in tasks
            if task.get("required_emotion") != "positive"
        ]

        summary = summarize_emotion_coverage(completed, tasks)
        self.assertEqual(summary["status"], "incomplete")
        self.assertEqual(len(summary["missing_task_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
