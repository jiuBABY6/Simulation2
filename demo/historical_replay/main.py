"""历史舆情趋势复现的独立启动入口。"""

import argparse
import json
import sys
import traceback

if __package__:
    from .runtime_paths import DEMO_DIR  # noqa: F401
    from .event_repository import list_events, resolve_event_files
    from .batch_manager import (
        prepare_historical_batch,
        prepare_historical_comment_pool,
    )
    from .replay_runner import run_historical_replay
    from .timeline_service import load_official_response_timeline
else:  # pragma: no cover - 保留既有直接脚本命令
    from runtime_paths import DEMO_DIR  # noqa: F401
    from event_repository import list_events, resolve_event_files
    from batch_manager import (
        prepare_historical_batch,
        prepare_historical_comment_pool,
    )
    from replay_runner import run_historical_replay
    from timeline_service import load_official_response_timeline
from historical_replay.public_context import (
    load_public_context_timeline,
)
from historical_replay.initial_opinion import validate_initial_opinion

from simulation.event_context import validate_event_input
from application.error_summary import summarize_scenario_error
from infrastructure.json_storage import load_json, save_json


# 2026/09/02 历史趋势复现，新增功能：独立准备批次并执行固定官方信息时间线。
# 2026/10/10，修改功能：主线恢复为公众语境约束下的 LLM 直接历史回放。
def run_historical_simulation(event_id=None):
    """运行历史趋势复现，不调用动态进场和五策略实验。"""
    batch_context = None
    try:
        event_paths = resolve_event_files(event_id)
        event_file = event_paths["event_file"]
        timeline_file = event_paths["timeline_file"]
        event_input = validate_event_input(load_json(event_file))
        timeline = load_official_response_timeline(
            timeline_file,
            event_input["event_id"],
        )
        initial_opinion = validate_initial_opinion(
            load_json(event_paths["initial_opinion_file"]),
            expected_event_id=event_input["event_id"],
        )
        public_context = load_public_context_timeline(
            event_paths["public_context_file"],
            expected_event_id=event_input["event_id"],
            expected_total_steps=timeline["total_steps"],
        )
        batch_context = prepare_historical_batch(
            event_input,
            timeline,
            initial_opinion=initial_opinion,
            public_context_timeline=public_context,
        )

        print(f"历史事件：{event_paths['event_id']}")
        print(f"事件源目录：{event_paths['event_dir']}")
        print("复现模式：历史公众语境约束下的LLM连续回放。")
        print("第一轮初始化：使用人工情绪比例校准。")
        print("正在为历史复现批次生成初始评论池……")
        comment_pool = prepare_historical_comment_pool(
            event_input,
            batch_context["comment_pool_file"],
            initial_opinion=initial_opinion,
        )
        print(f"初始评论池生成完成，共 {len(comment_pool['comments'])} 条评论。")
        print("开始运行历史舆情趋势复现……")

        result = run_historical_replay(
            experiment_id=batch_context["experiment_id"],
            experiment_dir=batch_context["experiment_dir"],
            event_file=batch_context["event_file"],
            comment_pool_file=batch_context["comment_pool_file"],
            timeline_file=batch_context["timeline_file"],
            public_context_file=batch_context["public_context_file"],
        )
        print(
            "历史趋势复现完成，结果保存在："
            f"{batch_context['experiment_dir'] / 'historical_replay_result.json'}"
        )
        print(json.dumps(_build_console_summary(result), ensure_ascii=False, indent=2))
        return result
    except Exception as error:
        result = {
            "mode": "historical_replay",
            "status": "failed",
            "error": str(error),
            "traceback": traceback.format_exc(),
        }
        if batch_context is not None:
            result["experiment_id"] = batch_context["experiment_id"]
            save_json(
                batch_context["experiment_dir"]
                / "historical_replay_result.json",
                result,
            )
        print(f"历史趋势复现失败：{summarize_scenario_error(error)}")
        return result


def _build_console_summary(result):
    """返回适合控制台查看的精简复现结果。"""
    return {
        "experiment_id": result["experiment_id"],
        "status": result["status"],
        "step_count": result["step_count"],
        "official_update_count": result["official_update_count"],
        # 2026/10/8，新增功能：控制台明确提示第一轮是否属于人工校准初始条件。
        "initialization": result.get("initialization"),
        "public_context_enabled": result.get("public_context_enabled"),
        "final_metrics": result["final_metrics"],
        "comment_quality": result["comment_quality"],
    }


def main():
    parser = argparse.ArgumentParser(description="按事件目录运行历史舆情趋势复现")
    parser.add_argument(
        "--event-id",
        help="events 下的事件编号；省略时读取 active_event.json",
    )
    parser.add_argument(
        "--list-events",
        action="store_true",
        help="列出已归档的历史事件源数据，不运行仿真",
    )
    args = parser.parse_args()
    if args.list_events:
        print(json.dumps(list_events(), ensure_ascii=False, indent=2))
        return 0

    simulation_result = run_historical_simulation(args.event_id)
    if simulation_result.get("status") != "completed":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
