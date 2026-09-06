"""事件输入和事件状态的读取、校验与组合。"""

from infrastructure.json_storage import load_json
from project_config import EVENT_FILE, EVENT_STATE_FILE


# 2026/08/28 第十七次联调修复-修复证据时间语义，新增功能：根据状态历史计算当前声明的首次发布轮次和持续时间。
def build_official_statement_timing(
    event_state_history,
    current_state,
    event_id,
):
    """返回当前声明的首次发布轮次、持续轮数和本轮新发布标记。"""
    current_statement = str(
        current_state.get("official_statement", "")
    ).strip()
    current_status = current_state.get("official_statement_status", "none")
    current_step = current_state.get("step")
    if (
        not current_statement
        or current_status == "none"
        or not isinstance(current_step, int)
    ):
        return {
            "introduced_step": None,
            "active_round_count": 0,
            "is_new": False,
        }

    current_identity = (current_statement, current_status)
    relevant_states = sorted(
        (
            state
            for state in event_state_history
            if isinstance(state, dict)
            and state.get("event_id") == event_id
            and isinstance(state.get("step"), int)
            and state["step"] <= current_step
        ),
        key=lambda state: state["step"],
        reverse=True,
    )

    introduced_step = current_step
    for state in relevant_states:
        state_identity = (
            str(state.get("official_statement", "")).strip(),
            state.get("official_statement_status", "none"),
        )
        if state_identity != current_identity:
            break
        introduced_step = state["step"]

    return {
        "introduced_step": introduced_step,
        "active_round_count": current_step - introduced_step + 1,
        "is_new": introduced_step == current_step,
    }


# 2026/08/28 第十七次联调修复-修复证据时间语义，修改功能：向当前事件上下文加入只读的声明时间信息。
def load_event_context(event_file=EVENT_FILE, event_state_file=EVENT_STATE_FILE):
    """读取固定事件和当前动态状态，并校验事件编号一致。"""
    event_input = load_json(event_file)
    event_state_history = load_json(event_state_file)
    event_id = event_input.get("event_id")
    event_state = dict(
        select_latest_event_state(
            event_state_history,
            event_id=event_id,
        )
    )

    if event_id != event_state.get("event_id"):
        raise ValueError("固定事件和事件状态的 event_id 不一致。")

    state_history = (
        event_state_history
        if isinstance(event_state_history, list)
        else event_state_history.get("history", [])
        if isinstance(event_state_history, dict)
        else []
    )
    event_state["official_statement_timing"] = (
        build_official_statement_timing(
            state_history,
            event_state,
            event_id,
        )
    )

    return {
        "event_id": event_input["event_id"],
        "event_content": event_input.get("event_content", ""),
        "event_labels": event_input.get("event_labels", {}),
        "current_state": event_state,
    }


def select_latest_event_state(event_state_data, event_id=None):
    """读取指定事件 step 最大的最新状态，兼容旧对象格式。"""
    if isinstance(event_state_data, list):
        valid_states = [
            item for item in event_state_data
            if (
                isinstance(item, dict)
                and isinstance(item.get("step"), int)
                and (event_id is None or item.get("event_id") == event_id)
            )
        ]
        if not valid_states:
            raise ValueError("event_state_history.json 中没有有效的事件状态记录。")
        return max(valid_states, key=lambda item: item["step"])

    if isinstance(event_state_data, dict):
        if isinstance(event_state_data.get("history"), list):
            return select_latest_event_state(
                event_state_data["history"],
                event_id=event_id,
            )
        if isinstance(event_state_data.get("step"), int):
            return {
                key: value
                for key, value in event_state_data.items()
                if key != "history"
            }

    raise ValueError("event_state_history.json 必须是状态数组或有效状态对象。")


def validate_event_input(event_input):
    """检查直接传入的事件是否包含生成评论池所需的基本字段。"""
    if not isinstance(event_input, dict):
        raise ValueError("事件输入必须是字典。")
    if not event_input.get("event_id"):
        raise ValueError("事件必须包含 event_id。")
    if not event_input.get("event_content"):
        raise ValueError("事件必须包含 event_content。")
    return event_input
