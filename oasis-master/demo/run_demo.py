from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from pathlib import Path

from weibo_demo.comment_mapping import (
    KeywordCommentMapper,
    scenario_with_comment_populations,
)
from weibo_demo.config import ScenarioConfig, load_scenario
from weibo_demo.engine import SimulationEngine
from weibo_demo.models import StatementType, TimingPolicy
from weibo_demo.storage import JsonlEventStore

DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIO = DEMO_ROOT / "config" / "scenario.json"
DEFAULT_OUTPUT_DIR = DEMO_ROOT / "outputs"


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _prepare_scenario(args: argparse.Namespace) -> ScenarioConfig:
    scenario = load_scenario(args.scenario).with_runtime_overrides(
        steps=args.steps,
        seed=args.seed,
        timing_policy=TimingPolicy(args.policy) if args.policy else None,
        statement_type=(
            StatementType(args.statement) if args.statement else None
        ),
    )
    if args.use_comment_population and not args.comments:
        raise ValueError("--use-comment-population 必须与 --comments 同时使用。")
    if args.comments:
        mapper = KeywordCommentMapper(scenario.groups)
        mapping = mapper.map_jsonl(args.comments, text_field=args.text_field)
        _write_json(args.output_dir / "comment_mapping.json", mapping.to_dict())
        print(
            f"已映射 {mapping.total_comments} 条评论，"
            f"结果写入 {args.output_dir / 'comment_mapping.json'}"
        )
        if args.use_comment_population:
            scenario = scenario_with_comment_populations(scenario, mapping)
    return scenario


async def _run_once(
    scenario: ScenarioConfig,
    output_dir: Path,
) -> dict:
    suffix = (
        f"{scenario.official.timing_policy.value}_"
        f"{scenario.official.statement_type.value}_{scenario.seed}"
    )
    event_path = output_dir / f"events_{suffix}.jsonl"
    summary_path = output_dir / f"summary_{suffix}.json"
    engine = SimulationEngine(
        scenario,
        event_store=JsonlEventStore(event_path),
    )
    result = await engine.run()
    summary = result.summary()
    _write_json(summary_path, summary)
    print(
        f"{summary['timing_policy']}/{summary['statement_type']} "
        f"进场 step={summary['intervention_step']}，"
        f"峰值={summary['peak_intensity']:.3f}，"
        f"最终风险={summary['final_metrics']['risk_score']:.3f}"
    )
    return summary


async def _run_comparison(
    scenario: ScenarioConfig,
    output_dir: Path,
) -> list[dict]:
    summaries = []
    for policy in TimingPolicy:
        candidate = replace(
            scenario,
            official=replace(scenario.official, timing_policy=policy),
        )
        summaries.append(await _run_once(candidate, output_dir))
    comparison_path = (
        output_dir
        / f"comparison_{scenario.official.statement_type.value}_{scenario.seed}.json"
    )
    _write_json(comparison_path, summaries)
    print(f"策略对比结果写入 {comparison_path}")
    return summaries


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行十个群体 Agent 的微博舆情传播 Demo。"
    )
    parser.add_argument(
        "--scenario",
        type=Path,
        default=DEFAULT_SCENARIO,
        help="场景 JSON 路径。",
    )
    parser.add_argument("--steps", type=int, help="覆盖仿真步数。")
    parser.add_argument("--seed", type=int, help="覆盖随机种子。")
    parser.add_argument(
        "--policy",
        choices=[item.value for item in TimingPolicy],
        help="覆盖官方进场策略 S0-S4。",
    )
    parser.add_argument(
        "--statement",
        choices=[item.value for item in StatementType],
        help="覆盖声明类型 A-D。",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="使用相同场景与种子比较 S0-S4。",
    )
    parser.add_argument(
        "--comments",
        type=Path,
        help="可选的 UTF-8 JSONL 评论文件。",
    )
    parser.add_argument(
        "--text-field",
        default="text",
        help="评论正文所在字段，默认 text。",
    )
    parser.add_argument(
        "--use-comment-population",
        action="store_true",
        help="用评论分类计数替换场景中的群体规模。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录，默认 demo/outputs。",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scenario = _prepare_scenario(args)
    if args.compare:
        asyncio.run(_run_comparison(scenario, args.output_dir))
    else:
        asyncio.run(_run_once(scenario, args.output_dir))


if __name__ == "__main__":
    main()
