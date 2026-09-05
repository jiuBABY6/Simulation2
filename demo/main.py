"""多 Agent 舆情模拟 Demo 的统一启动入口。

运行本文件后，程序会自动准备初始评论池，并完成全部官方回应策略实验。
具体业务继续由已有模块实现，本文件只负责按顺序调用。
"""

import json
import time

from comments.pool_generator import generate_comment_pool
from simulation.event_context import validate_event_input
from experiment_runner import load_official_response_options, run_experiment
from infrastructure.json_storage import load_json, save_json
from infrastructure.llm_service import (
    get_llm_performance_stats,
    merge_llm_performance_stats,
    reset_llm_performance_stats,
)
from project_config import (
    COMMENT_POOL_SIZE,
    COMMENT_PROFILE_FILE,
    EVENT_FILE,
    OFFICIAL_RESPONSE_FILE,
)
from simulation.batch_manager import prepare_simulation_batch


# 2026/08/22 系统重置与状态初始化，修改功能：为每个新批次生成并保存独立评论池。
def prepare_comment_pool(event_input, comment_pool_file):
    """根据当前事件生成评论池，并保存到当前实验批次目录。"""
    if comment_pool_file.exists():
        raise FileExistsError(f"本批次评论池已经存在：{comment_pool_file}")

    print("正在为新实验批次生成初始评论池……")
    comment_pool = generate_comment_pool(
        event_input=event_input,
        profile_file=COMMENT_PROFILE_FILE,
        comment_count=COMMENT_POOL_SIZE,
    )
    save_json(comment_pool_file, comment_pool)
    print(f"初始评论池生成完成，共 {len(comment_pool['comments'])} 条评论。")
    return comment_pool


# 2026/08/22 系统重置与状态初始化，修改功能：每次启动都创建独立模拟批次并使用独立输入文件。
def run_complete_simulation():
    """准备运行数据，并执行完整的官方回应策略对照实验。"""
    # 2026/09/04 Demo性能基线，新增功能：记录从统一入口启动到最终结果汇总的完整耗时。
    complete_run_start_time = time.perf_counter()
    event_input = validate_event_input(load_json(EVENT_FILE))
    # 2026/08/23 内容策略对照，新增功能：启动前读取并校验人工维护的官方内容策略。
    official_response_options = load_official_response_options(
        OFFICIAL_RESPONSE_FILE,
        event_input["event_id"],
    )
    # 2026/08/23 内容策略对照，修改功能：为本批次保存独立的官方内容策略快照。
    batch_context = prepare_simulation_batch(
        event_input,
        official_response_options=official_response_options,
    )

    # 2026/09/04 Demo性能基线，新增功能：独立统计事件角度和初始评论池生成的耗时及LLM调用。
    reset_llm_performance_stats()
    initial_comment_start_time = time.perf_counter()
    prepare_comment_pool(event_input, batch_context["comment_pool_file"])
    initial_comment_duration = time.perf_counter() - initial_comment_start_time
    initial_comment_llm_stats = get_llm_performance_stats()

    print("开始运行多 Agent 舆情模拟……")
    experiment_result = run_experiment(
        experiment_id=batch_context["experiment_id"],
        experiment_dir=batch_context["experiment_dir"],
        event_file=batch_context["event_file"],
        comment_pool_file=batch_context["comment_pool_file"],
        official_response_file=batch_context["official_response_file"],
    )
    performance = experiment_result.setdefault("performance", {})
    performance["initial_comment_pool_duration_seconds"] = round(
        initial_comment_duration,
        3,
    )
    performance["total_duration_seconds"] = round(
        time.perf_counter() - complete_run_start_time,
        3,
    )
    stage_duration = performance.setdefault("stage_duration_seconds", {})
    stage_duration["initial_comment_pool"] = round(
        initial_comment_duration,
        3,
    )
    performance["llm_requests"] = merge_llm_performance_stats(
        initial_comment_llm_stats,
        performance.get("llm_requests"),
    )
    # 2026/09/04 Demo性能基线，修改功能：将统一入口补充的完整性能数据写回最终实验结果。
    save_json(
        batch_context["experiment_dir"] / "experiment_result.json",
        experiment_result,
    )
    # 2026/08/22 系统重置与状态初始化，修改功能：直接使用实验执行器统一计算的完成状态。
    summary = {
        "experiment_id": experiment_result["experiment_id"],
        "status": experiment_result["status"],
        "strategy_count": experiment_result["strategy_count"],
        "success_count": experiment_result["success_count"],
        "not_run_count": experiment_result.get("not_run_count", 0),
        "failed_count": experiment_result["failed_count"],
        "entry_triggered": experiment_result.get("entry_triggered", False),
        "entry_reason": experiment_result.get("entry_reason"),
        "comparison_status": experiment_result.get("comparison_status"),
        "comparison": experiment_result["comparison"],
        "performance_summary": {
            "total_duration_seconds": performance.get(
                "total_duration_seconds"
            ),
            "logical_request_count": performance.get(
                "llm_requests",
                {},
            ).get("logical_request_count", 0),
            "http_attempt_count": performance.get(
                "llm_requests",
                {},
            ).get("http_attempt_count", 0),
            "retry_count": performance.get("llm_requests", {}).get(
                "retry_count",
                0,
            ),
        },
    }
    if experiment_result["failed_count"]:
        print("仿真运行结束，但存在失败的实验策略。")
    elif experiment_result.get("comparison_status") == "not_evaluable":
        # 2026/08/27 第十二次联调修复，新增功能：控制台明确区分仿真完成与内容策略对照未执行。
        print("仿真运行结束，官方未进场，内容策略对照未执行。")
    else:
        print("全部仿真任务已经完成。")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return experiment_result


if __name__ == "__main__":
    run_complete_simulation()
