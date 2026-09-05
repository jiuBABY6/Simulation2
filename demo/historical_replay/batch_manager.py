"""为历史趋势复现创建独立且不可覆盖的实验批次。"""

from pathlib import Path

from runtime_paths import DEMO_DIR, EXPERIMENT_DIR  # noqa: F401

from comments.pool_generator import generate_comment_pool
from infrastructure.json_storage import save_json
from project_config import COMMENT_POOL_SIZE, COMMENT_PROFILE_FILE
from simulation.batch_manager import generate_experiment_id


# 2026/09/02 历史趋势复现，新增功能：保存事件和时间线快照，不复用五策略实验配置。
def prepare_historical_batch(event_input, timeline, experiment_id=None):
    """创建历史复现实验目录，并返回本批次全部输入路径。"""
    if not isinstance(event_input, dict) or not event_input.get("event_id"):
        raise ValueError("event_input 必须包含有效的 event_id。")
    if timeline.get("event_id") != event_input["event_id"]:
        raise ValueError("历史时间线与事件编号不一致。")

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
    save_json(event_file, event_input)
    save_json(timeline_file, timeline)
    return {
        "experiment_id": batch_id,
        "experiment_dir": experiment_dir,
        "event_file": event_file,
        "timeline_file": timeline_file,
        "comment_pool_file": comment_pool_file,
    }


# 2026/09/02 历史趋势复现，新增功能：为历史批次生成独立初始评论池。
def prepare_historical_comment_pool(event_input, comment_pool_file):
    """调用现有评论生成核心，并保存当前批次的评论池快照。"""
    path = Path(comment_pool_file)
    if path.exists():
        raise FileExistsError(f"本批次评论池已经存在：{path}")
    comment_pool = generate_comment_pool(
        event_input=event_input,
        profile_file=COMMENT_PROFILE_FILE,
        comment_count=COMMENT_POOL_SIZE,
    )
    save_json(path, comment_pool)
    return comment_pool
