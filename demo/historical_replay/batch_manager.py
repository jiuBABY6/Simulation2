"""为历史趋势复现创建独立且不可覆盖的实验批次。"""

from pathlib import Path

if __package__:
    from .runtime_paths import DEMO_DIR, EXPERIMENT_DIR  # noqa: F401
else:  # pragma: no cover - 保留直接脚本启动方式
    from runtime_paths import DEMO_DIR, EXPERIMENT_DIR  # noqa: F401

from comments.pool_generator import generate_comment_pool
from historical_replay.public_context import (
    validate_public_context_timeline,
)
from historical_replay.initial_opinion import validate_initial_opinion
from infrastructure.json_storage import save_json
from project_config import COMMENT_POOL_SIZE, COMMENT_PROFILE_FILE
from simulation.batch_manager import generate_experiment_id


# 2026/09/02 历史趋势复现，新增功能：保存事件和时间线快照，不复用五策略实验配置。
def prepare_historical_batch(
    event_input,
    timeline,
    initial_opinion=None,
    public_context_timeline=None,
    experiment_id=None,
):
    """创建历史复现实验目录，并返回本批次全部输入路径。"""
    if not isinstance(event_input, dict) or not event_input.get("event_id"):
        raise ValueError("event_input 必须包含有效的 event_id。")
    if timeline.get("event_id") != event_input["event_id"]:
        raise ValueError("历史时间线与事件编号不一致。")

    # 2026/10/8，修改功能：创建目录前先完成校验，配置错误时不留下空的实验批次。
    normalized_initial_opinion = validate_initial_opinion(
        initial_opinion,
        expected_event_id=event_input["event_id"],
        expected_comment_count=COMMENT_POOL_SIZE,
    )
    normalized_public_context = validate_public_context_timeline(
        public_context_timeline,
        expected_event_id=event_input["event_id"],
        expected_total_steps=timeline.get("total_steps"),
    )
    batch_id = str(
        experiment_id or generate_experiment_id(event_input["event_id"])
    ).strip()
    if Path(batch_id).name != batch_id or batch_id in {".", ".."}:
        raise ValueError("experiment_id 不能包含目录路径。")

    experiment_dir = EXPERIMENT_DIR / batch_id
    if experiment_dir.exists():
        raise FileExistsError(f"实验目录已经存在，不允许覆盖：{experiment_dir}")
    experiment_dir.mkdir(parents=True, exist_ok=False)

    event_file = experiment_dir / "event_input.json"
    timeline_file = experiment_dir / "official_response_timeline.json"
    comment_pool_file = experiment_dir / "comment_pool.json"
    initial_opinion_file = experiment_dir / "initial_opinion.json"
    public_context_file = experiment_dir / "public_context_timeline.json"
    save_json(event_file, event_input)
    save_json(timeline_file, timeline)
    # 2026/10/8，新增功能：把人工初始条件固化为批次快照，源文件变化不会改写旧实验。
    save_json(initial_opinion_file, normalized_initial_opinion)
    # 2026/10/10，修改功能：逐轮公众语境与其余输入一起固化，确保
    # 批次可审计且事件源后续修改不会改写历史结果。
    save_json(public_context_file, normalized_public_context)
    return {
        "experiment_id": batch_id,
        "experiment_dir": experiment_dir,
        "event_file": event_file,
        "timeline_file": timeline_file,
        "comment_pool_file": comment_pool_file,
        "initial_opinion_file": initial_opinion_file,
        "public_context_file": public_context_file,
    }


# 2026/09/02 历史趋势复现，新增功能：为历史批次生成独立初始评论池。
def prepare_historical_comment_pool(
    event_input,
    comment_pool_file,
    initial_opinion=None,
):
    """调用现有评论生成核心，并保存当前批次的评论池快照。"""
    path = Path(comment_pool_file)
    if path.exists():
        raise FileExistsError(f"本批次评论池已经存在：{path}")
    comment_pool = generate_comment_pool(
        event_input=event_input,
        profile_file=COMMENT_PROFILE_FILE,
        comment_count=COMMENT_POOL_SIZE,
        # 2026/10/8，修改功能：仅历史入口显式传入人工初始条件；五策略沿用默认 None。
        initial_opinion=initial_opinion,
    )
    save_json(path, comment_pool)
    return comment_pool
