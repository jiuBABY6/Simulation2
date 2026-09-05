"""创建相互独立的完整模拟批次。

本模块只负责实验编号、实验目录、事件和官方内容策略快照，
不负责评论生成、Agent 决策、策略运行或指标计算。
"""

import re
from datetime import datetime
from pathlib import Path

from infrastructure.json_storage import save_json
from project_config import EXPERIMENT_DIR


# 2026/08/22 系统重置与状态初始化，新增功能：为每次完整模拟生成唯一实验编号。
def generate_experiment_id(event_id):
    """根据事件编号和当前时间生成可用作目录名的实验编号。"""
    safe_event_id = re.sub(r"[^0-9A-Za-z_-]+", "_", str(event_id)).strip("_")
    if not safe_event_id:
        safe_event_id = "event"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{safe_event_id}_{timestamp}"


# 2026/08/23 内容策略对照，修改功能：新批次可同时保存人工官方内容策略快照。
def prepare_simulation_batch(
    event_input,
    experiment_id=None,
    official_response_options=None,
):
    """创建新的实验批次，并返回该批次使用的文件路径。"""
    if not isinstance(event_input, dict) or not event_input.get("event_id"):
        raise ValueError("event_input 必须包含有效的 event_id。")
    if official_response_options is not None:
        if not isinstance(official_response_options, dict):
            raise ValueError("official_response_options 必须是 JSON 对象。")
        if official_response_options.get("event_id") != event_input["event_id"]:
            raise ValueError("官方内容策略与当前事件的 event_id 不一致。")

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
    comment_pool_file = experiment_dir / "comment_pool.json"
    official_response_file = experiment_dir / "official_response_options.json"
    save_json(event_file, event_input)
    if official_response_options is not None:
        save_json(official_response_file, official_response_options)

    return {
        "experiment_id": batch_id,
        "experiment_dir": experiment_dir,
        "event_file": event_file,
        "comment_pool_file": comment_pool_file,
        "official_response_file": (
            official_response_file
            if official_response_options is not None
            else None
        ),
    }
