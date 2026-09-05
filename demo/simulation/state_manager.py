"""统一管理单个策略状态目录的初始化、检查和调试重置。

本模块只处理运行状态文件，不修改事件输入、初始评论池、基础 Persona
或已经完成的历史实验。
"""

import shutil
from pathlib import Path

from simulation.event_state_updater import is_valid_state_record
from infrastructure.json_storage import load_json, save_json, validate_jsonl
from project_config import DEFAULT_STATE_DIR, DEMO_DIR


EVENT_STATE_FILE_NAME = "event_state_history.json"
JSONL_STATE_FILE_NAMES = (
    "decision_history.jsonl",
    "agent_state_history.jsonl",
    "incremental_comment_history.jsonl",
    "metrics_history.jsonl",
)


# 2026/08/22 系统重置与状态初始化 新增功能：检查状态目录是否位于Demo范围内且目录名合法。
def validate_state_directory_path(state_dir):
    """检查状态目录必须位于 demo 下，并且最后一级目录名为 state。"""
    state_path = Path(state_dir).resolve()
    demo_path = DEMO_DIR.resolve()

    try:
        state_path.relative_to(demo_path)
    except ValueError as error:
        raise ValueError(f"状态目录必须位于 demo 目录下：{state_path}") from error

    if state_path == demo_path or state_path.name != "state":
        raise ValueError(f"状态目录必须是 demo 下名为 state 的目录：{state_path}")
    return state_path


# 2026/08/22 系统重置与状态初始化 新增功能：集中生成一次仿真的全部状态文件路径。
def build_state_file_paths(state_dir):
    """根据状态目录生成事件状态文件和全部JSONL状态文件路径。"""
    state_path = validate_state_directory_path(state_dir)
    paths = {
        "event_state": state_path / EVENT_STATE_FILE_NAME,
    }
    for file_name in JSONL_STATE_FILE_NAMES:
        paths[Path(file_name).stem] = state_path / file_name
    return paths


# 2026/08/22 系统重置与状态初始化 新增功能：创建第一个时间步的精简事件状态。
def build_initial_event_state(event_input):
    """根据固定事件信息创建无官方声明的第一个时间步状态。"""
    if not isinstance(event_input, dict) or not event_input.get("event_id"):
        raise ValueError("event_input 必须包含有效的 event_id。")
    return {
        "event_id": event_input["event_id"],
        "step": 1,
        "official_statement": "",
        "official_statement_status": "none",
    }


# 2026/08/22 系统重置与状态初始化 新增功能：为新仿真创建完整且不覆盖旧数据的状态目录。
def initialize_simulation_state(state_dir, event_input):
    """创建新状态目录、第一步事件状态和空JSONL文件。"""
    initial_state = build_initial_event_state(event_input)
    paths = build_state_file_paths(state_dir)
    state_path = paths["event_state"].parent
    existing_entries = []
    if state_path.exists():
        if not state_path.is_dir():
            raise ValueError(f"状态路径不是目录：{state_path}")
        existing_entries = [
            item for item in state_path.iterdir() if item.name != ".gitkeep"
        ]
    if existing_entries:
        raise FileExistsError(
            f"状态目录已经包含数据，不允许自动覆盖：{state_path}"
        )

    state_path.mkdir(parents=True, exist_ok=True)
    save_json(paths["event_state"], [initial_state])

    for file_name in JSONL_STATE_FILE_NAMES:
        (state_path / file_name).write_text("", encoding="utf-8")

    return validate_simulation_state(state_path, event_input["event_id"])


# 2026/08/25 第八次联调问题修复，新增功能：从官方进场前的共享快照创建独立场景状态。
def initialize_state_from_snapshot(source_state_dir, state_dir, event_id):
    """复制一份已校验的状态快照，并保证不覆盖目标目录中的现有数据。"""
    validate_simulation_state(source_state_dir, event_id)
    source_paths = build_state_file_paths(source_state_dir)
    target_paths = build_state_file_paths(state_dir)
    target_state_path = target_paths["event_state"].parent

    existing_entries = []
    if target_state_path.exists():
        if not target_state_path.is_dir():
            raise ValueError(f"状态路径不是目录：{target_state_path}")
        existing_entries = [
            item for item in target_state_path.iterdir() if item.name != ".gitkeep"
        ]
    if existing_entries:
        raise FileExistsError(
            f"状态目录已经包含数据，不允许复制覆盖：{target_state_path}"
        )

    target_state_path.mkdir(parents=True, exist_ok=True)
    for name, source_path in source_paths.items():
        shutil.copy2(source_path, target_paths[name])

    return validate_simulation_state(target_state_path, event_id)


# 2026/08/22 系统重置与状态初始化 新增功能：严格检查状态文件、事件编号和时间步完整性。
def validate_simulation_state(state_dir, event_id):
    """检查状态目录和全部状态文件，返回文件及记录数量摘要。"""
    if not event_id:
        raise ValueError("event_id 不能为空。")

    paths = build_state_file_paths(state_dir)
    state_path = paths["event_state"].parent
    if not state_path.exists() or not state_path.is_dir():
        raise FileNotFoundError(f"状态目录不存在，请先初始化：{state_path}")

    missing_files = [
        str(path.name) for path in paths.values() if not path.is_file()
    ]
    if missing_files:
        raise FileNotFoundError(
            "状态目录缺少必要文件：" + "、".join(missing_files)
        )

    event_states = load_json(paths["event_state"])
    if not isinstance(event_states, list) or not event_states:
        raise ValueError("event_state_history.json 必须是非空状态数组。")

    state_keys = set()
    for index, state in enumerate(event_states, start=1):
        if not is_valid_state_record(state):
            raise ValueError(f"事件状态历史第 {index} 条记录不合法。")
        if state["event_id"] != event_id:
            raise ValueError(
                f"事件状态历史中的 event_id 与当前事件不一致："
                f"{state['event_id']} != {event_id}"
            )

        state_key = (state["event_id"], state["step"])
        if state_key in state_keys:
            raise ValueError(
                f"事件状态历史存在重复时间步："
                f"event_id={state['event_id']}，step={state['step']}"
            )
        state_keys.add(state_key)

    if (event_id, 1) not in state_keys:
        raise ValueError(f"事件 {event_id} 缺少第 1 个时间步状态。")

    record_counts = {}
    for file_name in JSONL_STATE_FILE_NAMES:
        file_path = state_path / file_name
        record_counts[file_name] = validate_jsonl(file_path)

    return {
        "valid": True,
        "event_id": event_id,
        "state_dir": str(state_path),
        "file_count": len(paths),
        "event_state_count": len(event_states),
        "jsonl_record_counts": record_counts,
    }


# 2026/08/22 系统重置与状态初始化，修改功能：明确该函数只重置默认调试状态。
def reset_default_debug_state(event_input):
    """重置默认 demo/state，仅用于直接运行仿真执行器时的本地调试。"""
    initial_state = build_initial_event_state(event_input)
    state_path = validate_state_directory_path(DEFAULT_STATE_DIR)
    expected_path = (DEMO_DIR / "state").resolve()
    if state_path != expected_path:
        raise ValueError("只允许重置固定的 demo/state 目录。")

    state_path.mkdir(parents=True, exist_ok=True)
    paths = build_state_file_paths(state_path)
    save_json(paths["event_state"], [initial_state])

    for file_name in JSONL_STATE_FILE_NAMES:
        (state_path / file_name).write_text("", encoding="utf-8")

    return validate_simulation_state(state_path, event_input["event_id"])
