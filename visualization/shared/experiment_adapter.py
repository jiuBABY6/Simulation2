"""统一适配五策略与历史复现实验的只读数据路径和摘要。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from visualization.shared.artifact_io import load_json_object
from visualization.shared.experiment_catalog import (
    HISTORICAL_MODE,
    STRATEGY_MODE,
    describe_experiment,
    resolve_experiment_dir,
)


STRATEGY_NAMES = {
    "no_response": "不回应",
    "fact_report": "事实通报",
    "empathy": "共情安抚",
    "rumor_clarification": "辟谣澄清",
    "handling_progress": "处置进展",
}


class ExperimentAdapter:
    """对两种实验目录暴露统一的场景、轮次和传播文件接口。"""

    def __init__(self, experiment_id: str):
        self.experiment_dir = resolve_experiment_dir(experiment_id)
        self.descriptor = describe_experiment(experiment_id)
        self.mode = str(self.descriptor["mode"])
        result_name = (
            "historical_replay_result.json"
            if self.mode == HISTORICAL_MODE
            else "experiment_result.json"
        )
        self.result_path = self.experiment_dir / result_name
        self.result = load_json_object(self.result_path)

    @property
    def experiment_id(self) -> str:
        return str(self.descriptor["experiment_id"])

    @property
    def event_id(self) -> str:
        return str(self.descriptor.get("event_id") or "")

    @property
    def step_count(self) -> int:
        return int(self.descriptor.get("step_count") or 0)

    @property
    def network_file(self) -> Path:
        if self.mode == HISTORICAL_MODE:
            return (
                self.experiment_dir
                / "historical_replay"
                / "state"
                / "social_network_snapshot.json"
            )
        return self.experiment_dir / "social_network_snapshot.json"

    def scenarios(self) -> list[dict[str, Any]]:
        if self.mode == HISTORICAL_MODE:
            return [
                {
                    "scenario_id": "historical_replay",
                    "scenario_name": "历史复现",
                    "step_count": self.step_count,
                }
            ]
        scenarios = []
        for item in self.result.get("strategy_results", []):
            if not isinstance(item, dict):
                continue
            scenario_id = str(item.get("strategy") or "").strip()
            if not scenario_id:
                continue
            scenarios.append(
                {
                    "scenario_id": scenario_id,
                    "scenario_name": str(
                        item.get("strategy_name")
                        or STRATEGY_NAMES.get(scenario_id)
                        or scenario_id
                    ),
                    "step_count": len(item.get("rounds", [])),
                }
            )
        return scenarios

    def _scenario_descriptor(self, scenario_id: str | None) -> dict[str, Any]:
        scenarios = self.scenarios()
        normalized = str(scenario_id or "").strip()
        if not normalized and scenarios:
            return scenarios[0]
        for item in scenarios:
            if item["scenario_id"] == normalized:
                return item
        raise ValueError(f"当前实验不存在场景：{normalized}")

    def scenario_name(self, scenario_id: str | None) -> str:
        return str(self._scenario_descriptor(scenario_id)["scenario_name"])

    def scenario_step_count(self, scenario_id: str | None) -> int:
        return int(self._scenario_descriptor(scenario_id)["step_count"])

    def state_dir(self, scenario_id: str | None) -> Path:
        descriptor = self._scenario_descriptor(scenario_id)
        return (
            self.experiment_dir
            / str(descriptor["scenario_id"])
            / "state"
        )

    def state_file(self, scenario_id: str | None, file_name: str) -> Path:
        return self.state_dir(scenario_id) / file_name

    def scenario_result(self, scenario_id: str | None) -> dict[str, Any]:
        descriptor = self._scenario_descriptor(scenario_id)
        if self.mode == HISTORICAL_MODE:
            return self.result
        target = descriptor["scenario_id"]
        for item in self.result.get("strategy_results", []):
            if isinstance(item, dict) and item.get("strategy") == target:
                return item
        raise ValueError(f"找不到场景结果：{target}")

    def propagation_summary(self, scenario_id: str | None) -> dict[str, Any]:
        return dict(self.scenario_result(scenario_id).get("propagation_summary", {}))

    def comment_quality(self, scenario_id: str | None) -> dict[str, Any]:
        return dict(self.scenario_result(scenario_id).get("comment_quality", {}))

    def rounds(self, scenario_id: str | None) -> list[dict[str, Any]]:
        return [
            item
            for item in self.scenario_result(scenario_id).get("rounds", [])
            if isinstance(item, dict)
        ]

    def round_summaries(self, scenario_id: str | None) -> list[dict[str, Any]]:
        return [
            {
                "step": item.get("step"),
                "period": item.get("period"),
                "phase": item.get("phase"),
                "propagation": dict(item.get("propagation_metrics", {})),
            }
            for item in self.rounds(scenario_id)
        ]

    def final_trend(self, scenario_id: str | None) -> Any:
        descriptor = self._scenario_descriptor(scenario_id)
        if self.mode == STRATEGY_MODE:
            return self.result.get("comparison", {}).get(
                "final_trends", {}
            ).get(descriptor["scenario_id"])
        rounds = self.rounds(scenario_id)
        return rounds[-1].get("global_trend") if rounds else None

    def validate_network_files(self) -> None:
        required = [self.result_path, self.network_file]
        for scenario in self.scenarios():
            scenario_id = str(scenario["scenario_id"])
            required.extend(
                [
                    self.state_file(scenario_id, "propagation_history.jsonl"),
                    self.state_file(scenario_id, "decision_history.jsonl"),
                ]
            )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError("实验传播文件不完整：" + "；".join(missing))


def get_experiment_adapter(experiment_id: str) -> ExperimentAdapter:
    return ExperimentAdapter(experiment_id)
