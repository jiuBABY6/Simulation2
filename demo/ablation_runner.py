"""运行输入受控且可恢复的策略机制消融实验。

2026/10/18，新增功能：各机制变体共用初始评论池、固定社交网络、
第 1 轮 Agent 状态和官方投入轮次。该入口不修改正式事件文件；普通
``python demo/main.py`` 始终继续使用完整机制。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from agents.persona_repository import load_personas
from comments.pool_generator import generate_comment_pool
from experiment_runner import (
    MAX_AGENTS,
    MAX_STEPS,
    NO_RESPONSE_SCENARIO,
    attach_control_net_effect_metrics,
    compare_strategy_results,
    load_official_response_options,
    prepare_experiment_social_network,
    run_one_content_strategy,
    run_shared_pre_entry_baseline,
    summarize_scenario_error,
)
from infrastructure.json_storage import load_json, save_json
from project_config import (
    COMMENT_POOL_SIZE,
    COMMENT_PROFILE_FILE,
    EVENT_FILE,
    EXPERIMENT_DIR,
    OFFICIAL_RESPONSE_FILE,
)
from simulation.batch_manager import generate_experiment_id
from simulation.counterfactual_controls import (
    CounterfactualIsolationError,
    audit_cross_scenario_controls,
    build_shared_input_manifest,
    build_state_snapshot_manifest,
)
from simulation.event_context import validate_event_input
from simulation.options import get_ablation_options


ABLATION_VARIANTS = {
    "full_feedback": {
        "incremental_public_comment_mode": "llm_incremental",
        "state_comment_evidence_mode": "all_visible",
        "neighbor_feedback_enabled": True,
    },
    "frozen_public": {
        "incremental_public_comment_mode": "frozen_after_initial",
        "state_comment_evidence_mode": "all_visible",
        "neighbor_feedback_enabled": True,
    },
    "public_context_only": {
        "incremental_public_comment_mode": "llm_incremental",
        "state_comment_evidence_mode": "exclude_llm_incremental",
        "neighbor_feedback_enabled": True,
    },
    "no_neighbor_feedback": {
        "incremental_public_comment_mode": "llm_incremental",
        "state_comment_evidence_mode": "all_visible",
        "neighbor_feedback_enabled": False,
    },
}
DEFAULT_VARIANTS = (
    "full_feedback",
    "frozen_public",
    "public_context_only",
)


def _sha256_file(path: Path) -> str:
    """计算文件哈希，确认各变体实际复用了同一输入。"""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value) -> str:
    """计算结构化输入的稳定哈希。"""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _build_variant_event(event_input, variant_name, fixed_response_step):
    """在事件副本中写入消融开关，不修改正式事件对象。"""

    event_copy = copy.deepcopy(event_input)
    simulation_options = event_copy.setdefault("simulation_options", {})
    if not isinstance(simulation_options, dict):
        raise ValueError("event_input.simulation_options 必须是 JSON 对象。")
    simulation_options["ablation"] = {
        **ABLATION_VARIANTS[variant_name],
        "fixed_response_step": fixed_response_step,
    }
    return validate_event_input(event_copy)


def _select_response_plans(response_options, response_plan, all_plans):
    """默认只运行一个回应方案，以控制消融实验的 API 成本。"""

    plans = response_options["content_strategies"]
    if all_plans:
        return list(plans)
    selected = [item for item in plans if item["strategy_id"] == response_plan]
    if not selected:
        available = ", ".join(item["strategy_id"] for item in plans)
        raise ValueError(
            f"找不到回应方案 {response_plan}；可用方案：{available}。"
        )
    return selected


def _run_variant(
    variant_name,
    variant_dir,
    event_input,
    event_file,
    comment_pool_file,
    social_network_file,
    shared_baseline,
    response_options,
    response_plans,
    fixed_inputs,
):
    """从同一首轮快照运行一项机制变体。"""

    variant_dir.mkdir(parents=True, exist_ok=False)
    save_json(event_file, event_input)
    save_json(
        variant_dir / "official_response_options.json",
        response_options,
    )
    # 2026/10/20，修改功能：消融实验沿用正式实验的反事实隔离契约。
    # 每个变体可以改变机制开关，但该变体内所有回应方案必须共享同一组
    # 客观输入，并从同一个进场前状态快照分叉；不共享任何方案运行后
    # 生成的公众评论或Agent表达。
    shared_input_manifest = build_shared_input_manifest(
        event_input,
        event_file,
        comment_pool_file,
        social_network_file,
    )
    baseline_snapshot_manifest = build_state_snapshot_manifest(
        shared_baseline["state_dir"]
    )
    scenarios = [(NO_RESPONSE_SCENARIO, "no_response")]
    scenarios.extend(
        (plan, response_options["entry_strategy"])
        for plan in response_plans
    )
    results = []
    for content_strategy, entry_strategy in scenarios:
        strategy_id = content_strategy["strategy_id"]
        print(f"[{variant_name}] 正在运行：{strategy_id}")
        try:
            result = run_one_content_strategy(
                content_strategy=content_strategy,
                entry_strategy=entry_strategy,
                event_input=event_input,
                experiment_dir=variant_dir,
                event_file=event_file,
                comment_pool_file=comment_pool_file,
                shared_baseline=shared_baseline,
                social_network_file=social_network_file,
                shared_input_manifest=shared_input_manifest,
                baseline_snapshot_manifest=baseline_snapshot_manifest,
            )
        except Exception as error:
            print(
                f"[{variant_name}] {strategy_id} 失败："
                f"{summarize_scenario_error(error)}"
            )
            result = {
                "strategy": strategy_id,
                "strategy_name": content_strategy["strategy_name"],
                "entry_strategy": entry_strategy,
                "ablation_config": get_ablation_options(event_input),
                "status": "failed",
                "error": str(error),
            }
            if isinstance(error, CounterfactualIsolationError):
                result["failure_type"] = "isolation_audit"
            scenario_dir = variant_dir / strategy_id
            scenario_dir.mkdir(parents=True, exist_ok=True)
            save_json(scenario_dir / "scenario_result.json", result)
        results.append(result)

    attach_control_net_effect_metrics(results, variant_dir)
    successful = [item for item in results if item.get("status") == "success"]
    try:
        cross_scenario_audit = audit_cross_scenario_controls(results)
    except RuntimeError as error:
        cross_scenario_audit = {
            "status": "failed",
            "error": str(error),
        }
    isolation_failed = (
        cross_scenario_audit.get("status") == "failed"
        or any(
            item.get("failure_type") == "isolation_audit"
            for item in results
        )
    )
    variant_result = {
        "variant": variant_name,
        "status": (
            "failed_isolation_audit"
            if isolation_failed
            else "completed"
            if len(successful) == len(results)
            else "partial_failed"
            if successful
            else "failed"
        ),
        "ablation_config": get_ablation_options(event_input),
        "fixed_inputs": fixed_inputs,
        "strategy_results": results,
        "counterfactual_controls": {
            "version": shared_input_manifest["version"],
            "shared_input_sha256": shared_input_manifest[
                "shared_input_sha256"
            ],
            "components": shared_input_manifest["components"],
            "pre_entry_snapshot_sha256": baseline_snapshot_manifest[
                "snapshot_sha256"
            ],
            "public_reactions_shared": False,
            "scenario_reactions_independent": True,
            "cross_scenario_audit": cross_scenario_audit,
        },
        "comparison": (
            compare_strategy_results(results)
            if len(successful) == len(results) and not isolation_failed
            else {}
        ),
    }
    save_json(variant_dir / "variant_result.json", variant_result)
    return variant_result


def _build_comparison_matrix(variant_results):
    """提取跨变体可直接比较的逐轮诊断，不重新计算业务指标。"""

    matrix = []
    for variant in variant_results:
        for scenario in variant.get("strategy_results", []):
            if scenario.get("status") != "success":
                continue
            round_series = []
            for round_result in scenario.get("rounds", []):
                expression = round_result.get(
                    "agent_expression_distribution", {}
                )
                expression_distribution = expression.get("distribution", {})
                neighbor = round_result.get(
                    "neighbor_exposure_diagnostics", {}
                )
                state_diagnostics = round_result.get(
                    "strategy_state_diagnostics", {}
                )
                generation = round_result.get("comment_generation", {})
                round_series.append(
                    {
                        "step": round_result.get("step"),
                        "internal_negative_rate": round_result.get(
                            "policy_metrics", {}
                        ).get("negative_rate"),
                        "expression_negative_rate": expression_distribution.get(
                            "negative", {}
                        ).get("rate"),
                        "participation_rate": expression.get(
                            "participation_rate"
                        ),
                        "effective_neighbor_exposure_rate": neighbor.get(
                            "effective_neighbor_exposure_rate"
                        ),
                        "neighbor_state_evidence_retention_rate": (
                            state_diagnostics.get(
                                "neighbor_state_evidence_retention_rate"
                            )
                        ),
                        "public_state_evidence_retention_rate": (
                            state_diagnostics.get(
                                "public_state_evidence_retention_rate"
                            )
                        ),
                        "effective_non_peer_evidence_count": (
                            state_diagnostics.get(
                                "effective_non_peer_evidence_count"
                            )
                        ),
                        "peer_transition_allowed_count": (
                            state_diagnostics.get(
                                "peer_transition_allowed_count"
                            )
                        ),
                        "incremental_generation_mode": generation.get(
                            "generation_mode",
                            "initial_pool",
                        ),
                    }
                )
            matrix.append(
                {
                    "variant": variant.get("variant"),
                    "strategy": scenario.get("strategy"),
                    "strategy_name": scenario.get("strategy_name"),
                    "rounds": round_series,
                }
            )
    return matrix


def run_ablation_experiment(
    event_file=EVENT_FILE,
    official_response_file=OFFICIAL_RESPONSE_FILE,
    response_plan="response_plan_1",
    variants=DEFAULT_VARIANTS,
    fixed_response_step=2,
    all_response_plans=False,
    group_id=None,
):
    """创建一组共享输入和首轮状态的机制消融实验。"""

    event_file = Path(event_file).resolve()
    official_response_file = Path(official_response_file).resolve()
    base_event = validate_event_input(load_json(event_file))
    response_options = load_official_response_options(
        official_response_file,
        base_event["event_id"],
    )
    invalid_variants = [name for name in variants if name not in ABLATION_VARIANTS]
    if not variants:
        raise ValueError("至少需要指定一个消融变体。")
    if invalid_variants:
        raise ValueError(f"未知消融变体：{invalid_variants}")
    if not 2 <= fixed_response_step <= MAX_STEPS:
        raise ValueError(
            f"fixed_response_step 必须在 2 到 {MAX_STEPS} 之间。"
        )
    response_plans = _select_response_plans(
        response_options,
        response_plan,
        all_response_plans,
    )

    experiment_group_id = group_id or generate_experiment_id(
        f"ablation_{base_event['event_id']}"
    )
    group_dir = EXPERIMENT_DIR / experiment_group_id
    group_dir.mkdir(parents=True, exist_ok=False)
    common_event_file = group_dir / "event_input.json"
    common_pool_file = group_dir / "comment_pool.json"
    common_response_file = group_dir / "official_response_options.json"

    # 第 1 轮尚未产生消融差异，因此只运行一次并由所有变体共享。
    common_event = _build_variant_event(
        base_event,
        "full_feedback",
        fixed_response_step,
    )
    save_json(common_event_file, common_event)
    save_json(common_response_file, response_options)
    print("正在生成全部消融组共用的初始评论池……")
    comment_pool = generate_comment_pool(
        event_input=base_event,
        profile_file=COMMENT_PROFILE_FILE,
        comment_count=COMMENT_POOL_SIZE,
    )
    save_json(common_pool_file, comment_pool)
    social_network_file = prepare_experiment_social_network(group_dir)

    print("正在生成全部消融组共用的第 1 轮 Agent 状态……")
    shared_baseline = run_shared_pre_entry_baseline(
        entry_strategy=response_options["entry_strategy"],
        event_input=common_event,
        experiment_dir=group_dir,
        event_file=common_event_file,
        comment_pool_file=common_pool_file,
        social_network_file=social_network_file,
        stagnation_rounds=response_options["stagnation_rounds"],
        improvement_tolerance=response_options[
            "negative_rate_improvement_tolerance"
        ],
    )
    if shared_baseline.get("response_step") != fixed_response_step:
        raise RuntimeError(
            "共享首轮状态未在指定轮次结束，不能进行可比消融。"
        )

    selected_personas = load_personas(max_count=MAX_AGENTS)
    fixed_inputs = {
        "response_step": fixed_response_step,
        "persona_count": len(selected_personas),
        "persona_sha256": _sha256_json(selected_personas),
        "comment_pool_sha256": _sha256_file(common_pool_file),
        "social_network_sha256": _sha256_file(social_network_file),
        "official_response_sha256": _sha256_file(common_response_file),
        "shared_baseline_state_dir": str(shared_baseline["state_dir"]),
    }
    variant_results = []
    for variant_name in variants:
        variant_dir = group_dir / variant_name
        variant_event_file = variant_dir / "event_input.json"
        variant_event = _build_variant_event(
            base_event,
            variant_name,
            fixed_response_step,
        )
        variant_results.append(
            _run_variant(
                variant_name=variant_name,
                variant_dir=variant_dir,
                event_input=variant_event,
                event_file=variant_event_file,
                comment_pool_file=common_pool_file,
                social_network_file=social_network_file,
                shared_baseline=shared_baseline,
                response_options=response_options,
                response_plans=response_plans,
                fixed_inputs=fixed_inputs,
            )
        )

    group_result = {
        "experiment_type": "mechanism_ablation",
        "experiment_group_id": experiment_group_id,
        "event_id": base_event["event_id"],
        "variants": list(variants),
        "response_plans": [item["strategy_id"] for item in response_plans],
        "fixed_inputs": fixed_inputs,
        "variant_results": variant_results,
        "comparison_matrix": _build_comparison_matrix(variant_results),
        "status": (
            "completed"
            if all(item["status"] == "completed" for item in variant_results)
            else "partial_failed"
        ),
    }
    result_file = group_dir / "ablation_result.json"
    save_json(result_file, group_result)
    print(f"消融实验完成：{result_file}")
    return group_result


def main():
    parser = argparse.ArgumentParser(description="运行策略机制消融实验")
    parser.add_argument("--event-file", type=Path, default=EVENT_FILE)
    parser.add_argument(
        "--official-response-file",
        type=Path,
        default=OFFICIAL_RESPONSE_FILE,
    )
    parser.add_argument("--response-plan", default="response_plan_1")
    parser.add_argument("--all-response-plans", action="store_true")
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help="逗号分隔的消融变体编号",
    )
    parser.add_argument("--fixed-response-step", type=int, default=2)
    parser.add_argument("--group-id")
    args = parser.parse_args()
    variants = tuple(
        item.strip() for item in args.variants.split(",") if item.strip()
    )
    result = run_ablation_experiment(
        event_file=args.event_file,
        official_response_file=args.official_response_file,
        response_plan=args.response_plan,
        variants=variants,
        fixed_response_step=args.fixed_response_step,
        all_response_plans=args.all_response_plans,
        group_id=args.group_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
