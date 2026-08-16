"""事件输入和事件状态的读取、校验与组合。"""

from json_storage import load_json
from project_config import EVENT_FILE, EVENT_STATE_FILE


def load_event_context(event_file=EVENT_FILE, event_state_file=EVENT_STATE_FILE):
    """读取固定事件和当前动态状态，并校验事件编号一致。"""
    event_input = load_json(event_file)
    event_state = load_json(event_state_file)

    if event_input.get("event_id") != event_state.get("event_id"):
        raise ValueError("固定事件和事件状态的 event_id 不一致。")

    return {
        "event_id": event_input["event_id"],
        "event_content": event_input.get("event_content", ""),
        "event_labels": event_input.get("event_labels", {}),
        "current_state": event_state,
    }


def validate_event_input(event_input):
    """检查直接传入的事件是否包含生成评论池所需的基本字段。"""
    if not isinstance(event_input, dict):
        raise ValueError("事件输入必须是字典。")
    if not event_input.get("event_id"):
        raise ValueError("事件必须包含 event_id。")
    if not event_input.get("event_content"):
        raise ValueError("事件必须包含 event_content。")
    return event_input

