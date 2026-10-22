from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


VISUALIZATION_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = VISUALIZATION_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from visualization.historical.real_trend_repository import (
    load_real_trend,
    real_trend_path,
)
from visualization.api_router import API_PATHS, dispatch_api
from visualization.shared.artifact_io import load_json_object, load_jsonl_objects
from visualization.shared.experiment_catalog import (
    describe_experiment,
    resolve_experiment_dir,
)
from visualization.shared.event_resources import resolve_event_json_path
from visualization.shared.network.service import (
    build_comment_cascade,
    build_comment_catalog,
    build_network_view,
    build_report_summary,
)
from visualization.strategy.service import (
    load_dashboard as load_strategy_dashboard,
)


HISTORICAL_EXPERIMENT = (
    "event_beiguo_xiantianxia_crash_20260920_001_20261007_210546_310373"
)
STRATEGY_EXPERIMENT = "event_gaoyang_assault_001_20260906_143939_040535"
HUXINYU_EXPERIMENT = "event_huxinyu_2022_001_20260902_170113_704837"


def _experiment_exists(experiment_id: str) -> bool:
    try:
        resolve_experiment_dir(experiment_id)
    except FileNotFoundError:
        return False
    return True


class ExperimentCatalogTests(unittest.TestCase):
    def test_api_router_rejects_unknown_and_missing_parameters(self) -> None:
        self.assertIn("/api/network/view", API_PATHS)
        with self.assertRaises(LookupError):
            dispatch_api("/api/unknown", {})
        with self.assertRaisesRegex(ValueError, "experiment_id"):
            dispatch_api("/api/strategy/dashboard", {})

    def test_shared_artifact_reader_validates_top_level_types(self) -> None:
        with patch.object(Path, "read_text", return_value='{"value": 1}'):
            self.assertEqual(load_json_object(Path("object.json"))["value"], 1)
        with patch.object(
            Path, "read_text", return_value='{"value": 1}\n\n'
        ):
            self.assertEqual(len(load_jsonl_objects(Path("records.jsonl"))), 1)

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "实验编号不合法"):
            resolve_experiment_dir("../outside")
        with self.assertRaisesRegex(ValueError, "event_id 不合法"):
            resolve_event_json_path(Path("real_trends"), "../outside")

    # 2026/10/12，修改功能：历史页面默认公开 Agent 实际表达主口径，
    # 三种评论池口径继续作为环境诊断项。
    def test_historical_page_exposes_opinion_basis_and_context(self) -> None:
        static_dir = VISUALIZATION_DIR / "historical" / "static"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = (static_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="metric-basis-select"', html)
        self.assertIn('value="agent_expression"', html)
        self.assertIn('value="active_opinion"', html)
        self.assertIn('id="context-timeline"', html)
        self.assertIn("active_comment_distribution", script)
        self.assertIn("agent_expression_distribution", script)

    # 2026/10/9，新增功能：网络页必须提供逐轮演化、累计传播和情绪图例。
    def test_network_page_exposes_round_evolution_controls(self) -> None:
        static_dir = VISUALIZATION_DIR / "shared" / "network" / "static"
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = (static_dir / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="step-timeline"', html)
        self.assertIn('data-flow-mode="round"', html)
        self.assertIn('data-flow-mode="cumulative"', html)
        self.assertIn("function renderStepTimeline", script)
        self.assertIn("round_exposure_count", script)
        self.assertIn("current_emotion", script)
        self.assertIn('id="network-official-details"', html)
        self.assertIn("timeline-official-marker", script)
        self.assertIn("official_responses", script)

    def test_real_trends_are_stored_by_event_id(self) -> None:
        beiguo = load_real_trend(
            "event_beiguo_xiantianxia_crash_20260920_002"
        )
        huxinyu = load_real_trend("event_huxinyu_2022_001")

        self.assertEqual(beiguo["stage_count"], 3)
        self.assertEqual(beiguo["source"]["file"], "北国先[1].xlsx")
        self.assertEqual(huxinyu["stage_count"], 8)
        self.assertEqual(huxinyu["source"]["file"], "example.xlsx")
        with self.assertRaisesRegex(ValueError, "event_id 不合法"):
            real_trend_path("../outside")

    @unittest.skipUnless(
        _experiment_exists(HISTORICAL_EXPERIMENT),
        "当前工作区没有北国先天下历史复现批次",
    )
    def test_describes_historical_replay(self) -> None:
        descriptor = describe_experiment(HISTORICAL_EXPERIMENT)

        self.assertEqual(descriptor["mode"], "historical_replay")
        self.assertEqual(descriptor["step_count"], 2)
        self.assertEqual(descriptor["scenario_count"], 1)
        self.assertTrue(descriptor["capabilities"]["network"])
        self.assertTrue(descriptor["capabilities"]["comment_trace"])
        self.assertTrue(descriptor["capabilities"]["real_trend_comparison"])

    @unittest.skipUnless(
        _experiment_exists(HUXINYU_EXPERIMENT),
        "当前工作区没有胡鑫宇历史复现批次",
    )
    def test_old_historical_batch_keeps_trend_without_network(self) -> None:
        descriptor = describe_experiment(HUXINYU_EXPERIMENT)

        self.assertEqual(descriptor["step_count"], 8)
        self.assertTrue(descriptor["capabilities"]["real_trend_comparison"])
        self.assertFalse(descriptor["capabilities"]["network"])
        self.assertFalse(descriptor["capabilities"]["comment_trace"])


class UnifiedNetworkReportTests(unittest.TestCase):
    @unittest.skipUnless(
        _experiment_exists(HISTORICAL_EXPERIMENT),
        "当前工作区没有北国先天下历史复现批次",
    )
    def test_historical_report_uses_dynamic_two_stage_data(self) -> None:
        report = build_report_summary(HISTORICAL_EXPERIMENT)
        network = build_network_view(
            HISTORICAL_EXPERIMENT, "historical_replay", 2
        )

        self.assertEqual(report["mode"], "historical_replay")
        self.assertEqual(report["max_step"], 2)
        self.assertEqual(len(report["rounds"]), 2)
        self.assertEqual(len(network["nodes"]), 30)
        self.assertEqual(len(network["edges"]), 150)
        self.assertGreater(network["event_count"], 0)
        self.assertIn("round_event_count", network)
        self.assertIn("round_active_edge_count", network)
        self.assertIn("emotion_distribution", network)
        self.assertTrue(
            all("round_exposure_count" in edge for edge in network["edges"])
        )
        self.assertTrue(
            all("current_emotion" in node for node in network["nodes"])
        )
        with self.assertRaisesRegex(ValueError, "1 到 2"):
            build_network_view(
                HISTORICAL_EXPERIMENT, "historical_replay", 3
            )

    @unittest.skipUnless(
        _experiment_exists(HISTORICAL_EXPERIMENT),
        "当前工作区没有北国先天下历史复现批次",
    )
    def test_historical_comment_catalog_opens_a_cascade(self) -> None:
        catalog = build_comment_catalog(
            HISTORICAL_EXPERIMENT, "historical_replay"
        )

        self.assertTrue(catalog["comments"])
        cascade = build_comment_cascade(
            HISTORICAL_EXPERIMENT,
            "historical_replay",
            catalog["comments"][0]["comment_id"],
        )
        self.assertGreater(cascade["summary"]["exposure_count"], 0)
        self.assertTrue(cascade["nodes"])

    @unittest.skipUnless(
        _experiment_exists(STRATEGY_EXPERIMENT),
        "当前工作区没有五策略验收批次",
    )
    def test_existing_strategy_report_remains_compatible(self) -> None:
        report = build_report_summary(STRATEGY_EXPERIMENT)

        self.assertEqual(report["mode"], "strategy_comparison")
        self.assertEqual(len(report["scenarios"]), 5)
        self.assertEqual(report["max_step"], 10)
        network = build_network_view(
            STRATEGY_EXPERIMENT, report["default_scenario_id"], 10
        )
        self.assertEqual(len(network["nodes"]), 10)
        self.assertEqual(len(network["edges"]), 50)
        self.assertIn("round_event_count", network)
        self.assertIn("emotion_distribution", network)
        response_network = build_network_view(
            STRATEGY_EXPERIMENT, "fact_report", 10
        )
        self.assertTrue(response_network["official_responses"])
        self.assertEqual(response_network["official_responses"][0]["step"], 2)
        self.assertIn(
            "official_statement", response_network["official_responses"][0]
        )

    @unittest.skipUnless(
        _experiment_exists(STRATEGY_EXPERIMENT),
        "当前工作区没有五策略验收批次",
    )
    def test_strategy_dashboard_is_separate_from_network_report(self) -> None:
        dashboard = load_strategy_dashboard(STRATEGY_EXPERIMENT)
        static_dir = VISUALIZATION_DIR / "strategy" / "static"

        self.assertEqual(dashboard["mode"], "strategy_comparison")
        self.assertEqual(len(dashboard["strategies"]), 5)
        self.assertTrue((static_dir / "index.html").is_file())
        self.assertTrue((static_dir / "app.js").is_file())
        fact_report = next(
            item
            for item in dashboard["strategies"]
            if item["scenario_id"] == "fact_report"
        )
        self.assertEqual(fact_report["official_response_count"], 1)
        self.assertEqual(fact_report["official_responses"][0]["step"], 2)
        self.assertIn(
            "official_statement", fact_report["official_responses"][0]
        )
        self.assertIn("negative_area", fact_report["effect_metrics"])
        self.assertIn("performance", fact_report)
        self.assertIn("comment_generation", fact_report["rounds"][1])
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        script = (static_dir / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="announcement-details"', html)
        self.assertIn('id="effect-table"', html)
        self.assertIn('id="metric-groups"', html)
        self.assertIn('id="round-table"', html)
        self.assertIn('id="round-quality-table"', html)
        self.assertIn('id="agent-emotion-chart"', html)
        self.assertIn('id="agent-expression-chart"', html)
        self.assertIn('id="official-attitude-chart"', html)
        self.assertIn('id="performance-summary"', html)
        self.assertIn("official-guide", script)
        self.assertIn("official-group-marker", script)
        self.assertIn("negative_area_reduction", script)
        self.assertIn("renderMetricDetail", script)
        self.assertIn("renderRoundDiagnostics", script)
        self.assertIn("agent_emotion_distribution", script)
        self.assertIn("official_attitude_distribution", script)


if __name__ == "__main__":
    unittest.main()
