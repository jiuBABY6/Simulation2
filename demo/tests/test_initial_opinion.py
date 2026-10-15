"""历史复现人工初始条件的离线回归测试。"""

from __future__ import annotations

from collections import Counter
import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = PROJECT_ROOT / "demo"
HISTORICAL_DIR = DEMO_DIR / "historical_replay"
for import_path in (DEMO_DIR, HISTORICAL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from comments.angle_planner import apply_required_emotion_targets
from historical_replay.event_repository import resolve_event_files
from historical_replay.initial_opinion import validate_initial_opinion


EVENT_ID = "event_huxinyu_2022_001"
CONFIG_FILE = (
    HISTORICAL_DIR / "events" / EVENT_ID / "initial_opinion.json"
)


class InitialOpinionTests(unittest.TestCase):
    # 2026/10/8，新增功能：确认胡某宇人工初始条件固定为60条且精确满足51/9/0。
    def test_huxinyu_initial_opinion_is_valid(self) -> None:
        payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        normalized = validate_initial_opinion(
            payload,
            expected_event_id=EVENT_ID,
            expected_comment_count=60,
        )

        self.assertEqual(
            normalized["emotion_targets"],
            {"negative": 51, "neutral": 9, "positive": 0},
        )
        self.assertEqual(normalized["evaluation_role"], "initial_condition")

    def test_rejects_mismatched_target_total(self) -> None:
        payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        payload["emotion_targets"]["negative"] = 50

        with self.assertRaisesRegex(ValueError, "总数必须等于"):
            validate_initial_opinion(payload, expected_event_id=EVENT_ID)

    def test_rejects_public_reaction_summary(self) -> None:
        payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        payload["public_discourse_context"] = {"summary": "公众普遍质疑"}

        with self.assertRaisesRegex(ValueError, "只允许使用人工情绪比例"):
            validate_initial_opinion(payload, expected_event_id=EVENT_ID)

    def test_event_repository_requires_historical_inputs(self) -> None:
        huxinyu = resolve_event_files(EVENT_ID)
        beiguo = resolve_event_files(
            "event_beiguo_xiantianxia_crash_20260920_001"
        )

        self.assertTrue(Path(huxinyu["initial_opinion_file"]).is_file())
        self.assertTrue(Path(huxinyu["public_context_file"]).is_file())
        self.assertTrue(Path(beiguo["initial_opinion_file"]).is_file())
        self.assertTrue(Path(beiguo["public_context_file"]).is_file())

    # 2026/10/8，新增功能：人工情绪配额按任务分散写入，不允许数量漂移。
    def test_required_emotions_are_exact_and_interleaved(self) -> None:
        tasks = [
            {
                "task_id": f"initial_{index:03d}",
                "angle_id": f"angle_{index % 8}",
                "angle_name": f"角度{index % 8}",
                "focus": "测试焦点",
                "expression_mode": "impact",
                "expression_instruction": "关注影响。",
            }
            for index in range(1, 61)
        ]
        calibrated = apply_required_emotion_targets(
            tasks,
            {"negative": 51, "neutral": 9, "positive": 0},
        )
        counts = Counter(item["required_emotion"] for item in calibrated)
        neutral_positions = [
            index
            for index, item in enumerate(calibrated, start=1)
            if item["required_emotion"] == "neutral"
        ]

        self.assertEqual(counts, Counter({"negative": 51, "neutral": 9}))
        self.assertLess(neutral_positions[0], 10)
        self.assertGreater(neutral_positions[-1], 50)


if __name__ == "__main__":
    unittest.main()
