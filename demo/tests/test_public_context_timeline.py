"""历史趋势复现逐轮公众语境的离线回归测试。"""

from __future__ import annotations

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

from historical_replay.public_context import (
    get_public_context_for_step,
    validate_public_context_timeline,
)


PUBLIC_CONTEXT_FILE = (
    HISTORICAL_DIR
    / "events"
    / "event_huxinyu_2022_001"
    / "public_context_timeline.json"
)


class PublicContextTimelineTests(unittest.TestCase):
    def _load_payload(self) -> dict:
        return json.loads(PUBLIC_CONTEXT_FILE.read_text(encoding="utf-8"))

    def test_huxinyu_context_covers_all_steps(self) -> None:
        timeline = validate_public_context_timeline(
            self._load_payload(),
            expected_event_id="event_huxinyu_2022_001",
            expected_total_steps=8,
        )

        self.assertEqual(
            [item["step"] for item in timeline["steps"]],
            list(range(1, 9)),
        )
        self.assertTrue(
            get_public_context_for_step(timeline, 1)["public_discourse"]
        )
        self.assertEqual(
            get_public_context_for_step(timeline, 2)["verified_updates"][0][
                "evidence_strength"
            ],
            "background",
        )
        self.assertEqual(
            get_public_context_for_step(timeline, 7)["verified_updates"][0][
                "update_kind"
            ],
            "final_conclusion",
        )

    def test_rejects_numeric_outcome_target_at_any_depth(self) -> None:
        payload = self._load_payload()
        payload["steps"][1]["public_discourse"][0]["negative_rate"] = 0.85

        with self.assertRaisesRegex(ValueError, "数值拟合目标"):
            validate_public_context_timeline(payload)

    def test_rejects_missing_step(self) -> None:
        payload = self._load_payload()
        payload["steps"].pop()

        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            validate_public_context_timeline(
                payload,
                expected_total_steps=8,
            )

    def test_rejects_empty_source_reference(self) -> None:
        payload = self._load_payload()
        payload["steps"][0]["verified_updates"][0]["source_refs"] = []

        with self.assertRaisesRegex(ValueError, "source_refs"):
            validate_public_context_timeline(payload)

    def test_rejects_invalid_evidence_strength(self) -> None:
        payload = self._load_payload()
        payload["steps"][0]["verified_updates"][0][
            "evidence_strength"
        ] = "decisive"

        with self.assertRaisesRegex(ValueError, "evidence_strength"):
            validate_public_context_timeline(payload)


if __name__ == "__main__":
    unittest.main()
