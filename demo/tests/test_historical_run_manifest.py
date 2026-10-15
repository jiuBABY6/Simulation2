"""历史复现可重复性清单测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from historical_replay.run_manifest import save_historical_run_manifest


class HistoricalRunManifestTests(unittest.TestCase):
    def test_manifest_records_hashes_without_secret(self):
        profile = {"profile_version": "persona_decision_v3"}
        with patch(
            "historical_replay.run_manifest._collect_persona_profiles",
            return_value={"agent_1": profile},
        ), patch("historical_replay.run_manifest.save_json") as mocked_save:
            manifest = save_historical_run_manifest(
                DEMO_DIR / "tests",
                DEMO_DIR / "tests",
                {"event_input": Path(__file__)},
            )

        self.assertEqual(manifest["agent_ids"], ["agent_1"])
        self.assertEqual(manifest["agent_count"], 1)
        self.assertEqual(manifest["mechanism_version"], "persona_evidence_replay_v3")
        self.assertFalse(manifest["contains_secret"])
        serialized = json.dumps(manifest, ensure_ascii=False).lower()
        self.assertNotIn("api_key", serialized)
        mocked_save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
