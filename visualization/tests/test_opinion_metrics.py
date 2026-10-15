"""评论舆情三种统计口径的离线测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from visualization.historical.opinion_metrics import (
    calculate_active_comment_distribution,
    calculate_comment_distribution,
)


class OpinionMetricsTests(unittest.TestCase):
    def test_distribution_uses_only_classified_comments_as_denominator(self) -> None:
        result = calculate_comment_distribution(
            [
                {"emotion": "negative"},
                {"emotion": "neutral"},
                {"emotion": "unknown"},
            ]
        )

        self.assertEqual(result["comment_count"], 3)
        self.assertEqual(result["classified_count"], 2)
        self.assertEqual(result["distribution"]["negative"]["rate"], 0.5)

    def test_active_distribution_uses_only_recent_round_window(self) -> None:
        groups = [
            [{"emotion": "negative"}] * 10,
            [{"emotion": "neutral"}] * 10,
            [{"emotion": "positive"}] * 10,
        ]
        result = calculate_active_comment_distribution(groups, 2)

        self.assertEqual(result["comment_count"], 20)
        self.assertEqual(result["distribution"]["negative"]["rate"], 0.0)
        self.assertEqual(result["distribution"]["neutral"]["rate"], 0.5)
        self.assertEqual(result["distribution"]["positive"]["rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
