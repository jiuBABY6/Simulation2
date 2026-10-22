from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from visualization.historical.comparison_service import compare_negative_trends
from visualization.historical.real_data_processor import _build_real_trend_from_rows


EVENT_ID = "event_beiguo_xiantianxia_crash_20260920_002"


def _two_stage_rows() -> list[dict[str, str]]:
    return [
        {"A": "材料说明"},
        {
            "A": "关键节点",
            "B": "时间线",
            "C": "当前",
            "G": "社会情绪（负面/中性/正面）",
            "H": "网络当前舆论",
        },
        {
            "A": "通告前",
            "B": "2026.09.20 17:00-21:00",
            "C": "事故视频评论抽样",
            "G": "中性约40%，负面约35%，正面约25%",
            "H": "关注事故原因和伤情",
        },
        {
            "A": "通告",
            "B": "2026.09.20 21:00以后",
            "C": "通告发布后评论抽样",
            "G": "中性约45%，负面约30%，正面约25%",
            "H": "讨论转向权威信息",
        },
        {},
        {"A": "附注，不属于阶段"},
    ]


def _simulation(
    rates: list[float],
    event_id: str = EVENT_ID,
    calibration_steps: set[int] | None = None,
) -> dict:
    calibration_steps = calibration_steps or set()
    return {
        "event_id": event_id,
        "rounds": [
            {
                "step": index,
                "period": f"阶段{index}",
                "negative_rate": rate,
                "is_calibration_point": index in calibration_steps,
                "current_comment_distribution": {
                    "distribution": {"negative": {"rate": rate}}
                },
            }
            for index, rate in enumerate(rates, start=1)
        ],
    }


def _real_trend(rates: list[float], event_id: str = EVENT_ID) -> dict:
    return {
        "event_id": event_id,
        "periods": [
            {
                "step": index,
                "period": f"阶段{index}",
                "phase": f"节点{index}",
                "sampling_method": f"采样说明{index}",
                "sentiment": {"negative": {"estimate": rate}},
            }
            for index, rate in enumerate(rates, start=1)
        ],
    }


class RealDataProcessorTests(unittest.TestCase):
    def test_reads_all_valid_rows_and_preserves_sampling_method(self) -> None:
        result = _build_real_trend_from_rows(
            _two_stage_rows(),
            event_id=EVENT_ID,
            source_name="北国先(1).xlsx",
            sheet_name="Sheet1",
        )

        self.assertEqual(result["event_id"], EVENT_ID)
        self.assertEqual(result["stage_count"], 2)
        self.assertEqual(result["source"]["range"], "A3:H4")
        self.assertEqual(result["periods"][0]["phase"], "通告前")
        self.assertEqual(
            result["periods"][0]["sampling_method"], "事故视频评论抽样"
        )
        self.assertEqual(
            result["periods"][1]["sentiment"]["negative"]["estimate"],
            0.3,
        )

    def test_requires_at_least_two_valid_stages(self) -> None:
        rows = _two_stage_rows()[:3]
        with self.assertRaisesRegex(ValueError, "至少需要 2 个有效阶段"):
            _build_real_trend_from_rows(
                rows,
                event_id=EVENT_ID,
                source_name="single-stage.xlsx",
                sheet_name="Sheet1",
            )


class ComparisonServiceTests(unittest.TestCase):
    def test_rejects_different_event_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_id 不一致"):
            compare_negative_trends(
                _simulation([0.4, 0.3]),
                _real_trend([0.35, 0.3], event_id="another-event"),
            )

    def test_two_points_only_expose_exploratory_metrics(self) -> None:
        result = compare_negative_trends(
            _simulation([0.4, 0.3]),
            _real_trend([0.35, 0.3]),
        )

        self.assertEqual(result["alignment"]["method"], "按 2 个共同事件阶段的顺序对齐")
        self.assertEqual(result["metric_scope"]["transition_count"], 1)
        self.assertEqual(result["metric_scope"]["status"], "limited_two_stage")
        self.assertEqual(result["metrics"]["direction_agreement_rate"], 1.0)
        self.assertEqual(result["pairs"][0]["sampling_method"], "采样说明1")
        self.assertNotIn("peak_step_difference", result["metrics"])
        self.assertIn("不代表模型准确率", result["interpretation"])

    def test_three_points_can_report_peak_step_difference(self) -> None:
        result = compare_negative_trends(
            _simulation([0.2, 0.6, 0.3]),
            _real_trend([0.2, 0.3, 0.7]),
        )

        self.assertEqual(result["metric_scope"]["status"], "multi_stage_exploratory")
        self.assertEqual(result["metrics"]["peak_step_difference"], 1)

    # 2026/10/8，新增功能：人工初始条件保留在趋势图中，但不参与MAE和峰值计算。
    def test_calibration_point_is_excluded_from_point_metrics(self) -> None:
        result = compare_negative_trends(
            _simulation(
                [0.85, 0.2, 0.7, 0.3],
                calibration_steps={1},
            ),
            _real_trend([0.85, 0.2, 0.3, 0.8]),
        )

        self.assertTrue(result["pairs"][0]["is_calibration_point"])
        self.assertFalse(result["pairs"][0]["included_in_point_error"])
        self.assertEqual(result["metrics"]["mean_absolute_error"], 0.3)
        self.assertEqual(result["metrics"]["peak_step_difference"], 1)
        self.assertEqual(result["metric_scope"]["observation_count"], 3)
        self.assertEqual(result["metric_scope"]["calibration_point_count"], 1)
        self.assertEqual(result["metric_scope"]["transition_count"], 3)
        self.assertIn("不计入MAE", result["interpretation"])

    # 2026/10/9，新增功能：活跃舆情口径支持三分类误差且不强制归一化人工估计。
    def test_active_opinion_reports_three_sentiment_macro_error(self) -> None:
        simulation = _simulation([0.5, 0.4])
        real = _real_trend([0.6, 0.3])
        for round_item in simulation["rounds"]:
            negative = round_item["current_comment_distribution"][
                "distribution"
            ]["negative"]["rate"]
            round_item["active_comment_distribution"] = {
                "distribution": {
                    "negative": {"rate": negative},
                    "neutral": {"rate": 0.4},
                    "positive": {"rate": 0.1},
                }
            }
        for period in real["periods"]:
            period["sentiment"].update(
                {
                    "neutral": {"estimate": 0.3},
                    "positive": {"estimate": 0.1},
                }
            )

        result = compare_negative_trends(
            simulation,
            real,
            basis="active_opinion",
        )

        self.assertEqual(result["comparison_basis"], "active_opinion")
        self.assertEqual(result["metrics"]["per_sentiment_mae"]["positive"], 0.0)
        self.assertIsNotNone(result["metrics"]["macro_mean_absolute_error"])

    def test_agent_expression_is_supported_as_primary_observation(self) -> None:
        simulation = _simulation([0.9, 0.8])
        for step, round_item in enumerate(simulation["rounds"], start=1):
            round_item["agent_expression_distribution"] = {
                "distribution": {
                    "negative": {"rate": 0.2 * step},
                    "neutral": {"rate": 1 - 0.2 * step},
                    "positive": {"rate": 0.0},
                }
            }
        real = _real_trend([0.2, 0.4])

        result = compare_negative_trends(
            simulation,
            real,
            basis="agent_expression",
        )

        self.assertEqual(result["comparison_basis"], "agent_expression")
        self.assertEqual(result["metrics"]["mean_absolute_error"], 0.0)
        # 内部情绪仍作为解释字段保留，不能覆盖实际表达主口径。
        self.assertEqual(result["pairs"][0]["simulation_agent_rate"], 0.9)


if __name__ == "__main__":
    unittest.main()
