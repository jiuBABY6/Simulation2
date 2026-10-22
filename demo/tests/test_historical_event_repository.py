from __future__ import annotations

import json
import hashlib
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = PROJECT_ROOT / "demo"
HISTORICAL_DIR = DEMO_DIR / "historical_replay"
for import_path in (DEMO_DIR, HISTORICAL_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from historical_replay.event_repository import (
    get_active_event_id,
    list_events,
    resolve_event_files,
)


class HistoricalEventRepositoryTests(unittest.TestCase):
    def test_active_event_resolves_to_a_complete_event(self) -> None:
        event_id = get_active_event_id()
        resolved = resolve_event_files(event_id)

        self.assertEqual(resolved["event_id"], event_id)
        self.assertTrue(Path(resolved["event_file"]).is_file())
        self.assertTrue(Path(resolved["timeline_file"]).is_file())
        self.assertTrue(Path(resolved["initial_opinion_file"]).is_file())
        self.assertTrue(Path(resolved["public_context_file"]).is_file())

    def test_current_historical_sources_are_listed(self) -> None:
        events = {item["event_id"]: item for item in list_events()}

        self.assertIn(
            "event_beiguo_xiantianxia_crash_20260920_002", events
        )
        self.assertIn("event_huxinyu_2022_001", events)
        # 2026/10/10，修改功能：主线历史回放要求所有事件具备初始条件
        # 与逐轮同期公众语境，不使用额外旧模式开关。
        self.assertTrue(events["event_huxinyu_2022_001"]["has_initial_opinion"])
        self.assertTrue(events["event_huxinyu_2022_001"]["has_public_context"])
        self.assertTrue(
            events["event_beiguo_xiantianxia_crash_20260920_002"][
                "has_initial_opinion"
            ]
        )
        self.assertTrue(
            events["event_beiguo_xiantianxia_crash_20260920_002"][
                "has_public_context"
            ]
        )

    # 2026/10/9，修改功能：胡某宇历史复现阶段边界必须与人工趋势逐轮一致。
    def test_huxinyu_timeline_periods_match_real_trend(self) -> None:
        resolved = resolve_event_files("event_huxinyu_2022_001")
        timeline = json.loads(
            Path(resolved["timeline_file"]).read_text(encoding="utf-8")
        )
        public_context = json.loads(
            Path(resolved["public_context_file"]).read_text(encoding="utf-8")
        )
        real_trend_path = (
            PROJECT_ROOT
            / "visualization"
            / "data"
            / "real_trends"
            / "event_huxinyu_2022_001.json"
        )
        real_trend = json.loads(real_trend_path.read_text(encoding="utf-8"))

        simulation_periods = [
            item["period"] for item in timeline["step_periods"]
        ]
        reference_periods = [
            item["period"] for item in real_trend["periods"]
        ]
        context_periods = [
            item["period"] for item in public_context["steps"]
        ]

        normalize_period = lambda value: (  # noqa: E731 - 测试内局部规范化。
            value.replace("以后", "~").replace("～", "~").replace(" ", "")
        )
        self.assertEqual(
            [normalize_period(item) for item in simulation_periods],
            [normalize_period(item) for item in reference_periods],
        )
        self.assertEqual(
            [normalize_period(item) for item in context_periods],
            [normalize_period(item) for item in reference_periods],
        )
        self.assertEqual(simulation_periods[3], "2023.01.12-2023.01.27")
        self.assertEqual(simulation_periods[4], "2023.01.28-2023.01.29")

    def test_manifest_hash_matches_current_beiguo_source(self) -> None:
        resolved = resolve_event_files(
            "event_beiguo_xiantianxia_crash_20260920_002"
        )
        manifest_path = Path(resolved["event_dir"]) / "event_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(
            Path(resolved["real_trend_source"]).read_bytes()
        ).hexdigest().upper()

        self.assertEqual(
            manifest["real_trend_source_original_name"], "北国先[1].xlsx"
        )
        self.assertEqual(manifest["real_trend_source_sha256"], digest)

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_id 不合法"):
            resolve_event_files("../outside")


if __name__ == "__main__":
    unittest.main()
