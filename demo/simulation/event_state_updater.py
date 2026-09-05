"""事件状态历史保存模块。

本模块只负责保存人工或实验策略已经确定的官方声明状态，
不负责判断声明类型，也不负责预测下一轮事件状态。
"""

from pathlib import Path

from infrastructure.json_storage import load_json, save_json
from project_config import EVENT_STATE_FILE


VALID_STATEMENT_STATUS = ("none", "clear", "incomplete", "conflict")
STATE_FIELDS = (
    "event_id",
    "step",
    "official_statement",
    "official_statement_status",
)


def append_event_state_record(
    event_input,
    official_statement="",
    official_statement_status="none",
    state_file=EVENT_STATE_FILE,
):
    """追加当前时间步的事件状态记录。

    参数：
        event_input：固定事件信息，至少包含 event_id。
        official_statement：本轮人工输入的官方声明，没有声明时传空字符串。
        official_statement_status：本轮人工选择的声明类型，只能是 none、clear、
            incomplete 或 conflict。
        state_file：事件状态历史 JSON 文件路径。

    返回：
        本次新增的完整状态记录。

    说明：
        step 根据该事件已有记录的最大值自动加 1，不表示预测未来状态。
    """
    validate_event_input(event_input)
    validate_statement_status(official_statement_status)

    event_id = event_input["event_id"]
    history = load_event_state_history(state_file)
    event_steps = [
        record["step"]
        for record in history
        if record["event_id"] == event_id
    ]
    next_step = max(event_steps, default=0) + 1

    state_record = {
        "event_id": event_id,
        "step": next_step,
        "official_statement": normalize_text(official_statement),
        "official_statement_status": official_statement_status,
    }

    history.append(state_record)
    history.sort(key=lambda item: (item["event_id"], item["step"]))
    save_json(state_file, history)
    return state_record


def load_event_state_history(state_file=EVENT_STATE_FILE, event_id=None):
    """读取事件状态历史，并返回统一格式的记录列表。

    参数：
        state_file：事件状态历史 JSON 文件路径。
        event_id：可选事件编号。传入后只返回该事件的记录。

    返回：
        按 step 排序的事件状态记录列表。
    """
    path = Path(state_file)
    if not path.exists():
        return []

    document = load_json(path)
    if not isinstance(document, list):
        raise ValueError("event_state_history.json 必须是状态记录数组。")

    records = document
    normalized = []

    for record in records:
        if not is_valid_state_record(record):
            continue
        if event_id is not None and record["event_id"] != event_id:
            continue
        normalized.append(
            {field: record[field] for field in STATE_FIELDS}
        )

    normalized.sort(key=lambda item: (item["event_id"], item["step"]))
    return normalized


def get_latest_event_state(state_file=EVENT_STATE_FILE, event_id=None):
    """读取指定事件最新时间步的状态记录。"""
    history = load_event_state_history(state_file, event_id)
    if not history:
        return None
    return max(history, key=lambda item: item["step"])


def is_valid_state_record(record):
    """检查单条记录是否包含完整的精简状态字段。"""
    if not isinstance(record, dict):
        return False
    if not all(field in record for field in STATE_FIELDS):
        return False
    if not record.get("event_id"):
        return False
    if not isinstance(record.get("step"), int) or record["step"] < 1:
        return False
    if record.get("official_statement_status") not in VALID_STATEMENT_STATUS:
        return False
    return True


def validate_event_input(event_input):
    """检查固定事件信息是否包含 event_id。"""
    if not isinstance(event_input, dict):
        raise ValueError("event_input 必须是字典。")
    if not event_input.get("event_id"):
        raise ValueError("event_input 缺少 event_id。")


def validate_statement_status(status):
    """检查官方声明类型是否合法。"""
    if status not in VALID_STATEMENT_STATUS:
        raise ValueError(
            "official_statement_status 只能是 none、clear、incomplete 或 conflict。"
        )


def normalize_text(value):
    """将声明转换为去除首尾空白的字符串。"""
    if value is None:
        return ""
    return str(value).strip()
