"""历史舆情趋势复现的独立启动入口。"""

import json
import sys
import traceback

from runtime_paths import EVENT_FILE, TIMELINE_FILE

from simulation.event_context import validate_event_input
from experiment_runner import summarize_scenario_error
from infrastructure.json_storage import load_json, save_json
from batch_manager import (
    prepare_historical_batch,
    prepare_historical_comment_pool,
)
from replay_runner import run_historical_replay
from timeline_service import load_official_response_timeline


# 2026/09/02 历史趋势复现，新增功能：独立准备批次并执行固定官方信息时间线。
def run_historical_simulation():
    """运行历史复现，不调用动态进场和五策略实验。"""
    batch_context = None
    try:
        event_input = validate_event_input(load_json(EVENT_FILE))
        timeline = load_official_response_timeline(
            TIMELINE_FILE,
            event_input["event_id"],
        )
        batch_context = prepare_historical_batch(event_input, timeline)

        print("正在为历史复现批次生成初始评论池……")
        comment_pool = prepare_historical_comment_pool(
            event_input,
            batch_context["comment_pool_file"],
        )
        print(f"初始评论池生成完成，共 {len(comment_pool['comments'])} 条评论。")
        print("开始运行历史舆情趋势复现……")

        result = run_historical_replay(
            experiment_id=batch_context["experiment_id"],
            experiment_dir=batch_context["experiment_dir"],
            event_file=batch_context["event_file"],
            comment_pool_file=batch_context["comment_pool_file"],
            timeline_file=batch_context["timeline_file"],
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
        "final_metrics": result["final_metrics"],
        "comment_quality": result["comment_quality"],
    }


if __name__ == "__main__":
    simulation_result = run_historical_simulation()
    if simulation_result.get("status") != "completed":
        sys.exit(1)
