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
OPTIONAL_STATE_FIELDS = (
    "official_evidence_dimensions",
    "public_context",
    "public_context_timing",
    "objective_event_context",
    "objective_event_timing",
    "simulation_mode",
    # 2026/10/20，新增功能：策略分叉后显式记录所属场景和共同输入
    # 指纹，供增量评论标记来源及运行后跨场景污染检查使用。
    "scenario_id",
    "shared_input_sha256",
)


def append_event_state_record(
    event_input,
    official_statement="",
    official_statement_status="none",
    official_evidence_dimensions=None,
    public_context=None,
    public_context_timing=None,
    objective_event_context=None,
    objective_event_timing=None,
    simulation_mode=None,
    scenario_id=None,
    shared_input_sha256=None,
    state_file=EVENT_STATE_FILE,
):
    """追加当前时间步的事件状态记录。

    参数：
        event_input：固定事件信息，至少包含 event_id。
        official_statement：本轮人工输入的官方声明，没有声明时传空字符串。
        official_statement_status：本轮人工选择的声明类型，只能是 none、clear、
            incomplete 或 conflict。
        official_evidence_dimensions：可选的人工通告语义维度布尔映射；用于
            补充关键词识别，不直接指定Agent结论。
        public_context：条件化历史回放的本轮公众语境。
        public_context_timing：该语境对应的阶段与时间范围。
        objective_event_context：可选的本轮客观事件，只由历史复现入口传入。
        objective_event_timing：可选的客观事件阶段和时间范围。
        simulation_mode：可选运行模式标记。
        scenario_id：策略分叉后的场景编号。
        shared_input_sha256：事件、初始评论、网络和客观事实时间线的共同哈希。
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
    if official_evidence_dimensions is not None:
        if not isinstance(official_evidence_dimensions, dict) or any(
            not isinstance(value, bool)
            for value in official_evidence_dimensions.values()
        ):
            raise ValueError("official_evidence_dimensions 必须是布尔值对象。")
        state_record["official_evidence_dimensions"] = dict(
            official_evidence_dimensions
        )
    if public_context is not None:
        if not isinstance(public_context, dict):
            raise ValueError("public_context 必须是 JSON 对象。")
        state_record["public_context"] = dict(public_context)
    if public_context_timing is not None:
        if not isinstance(public_context_timing, dict):
            raise ValueError("public_context_timing 必须是 JSON 对象。")
        state_record["public_context_timing"] = dict(public_context_timing)
    if objective_event_context is not None:
        if not isinstance(objective_event_context, dict):
            raise ValueError("objective_event_context 必须是 JSON 对象。")
        state_record["objective_event_context"] = dict(
            objective_event_context
        )
    if objective_event_timing is not None:
        if not isinstance(objective_event_timing, dict):
            raise ValueError("objective_event_timing 必须是 JSON 对象。")
        state_record["objective_event_timing"] = dict(
            objective_event_timing
        )
    if simulation_mode is not None:
        normalized_mode = str(simulation_mode).strip()
        if not normalized_mode:
            raise ValueError("simulation_mode 不能为空。")
        state_record["simulation_mode"] = normalized_mode
    if scenario_id is not None:
        normalized_scenario_id = str(scenario_id).strip()
        if not normalized_scenario_id:
            raise ValueError("scenario_id 不能为空。")
        state_record["scenario_id"] = normalized_scenario_id
    if shared_input_sha256 is not None:
        normalized_fingerprint = str(shared_input_sha256).strip().lower()
        if len(normalized_fingerprint) != 64 or any(
            character not in "0123456789abcdef"
            for character in normalized_fingerprint
        ):
            raise ValueError("shared_input_sha256 必须是64位十六进制SHA-256。")
        state_record["shared_input_sha256"] = normalized_fingerprint

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
        normalized_record = {field: record[field] for field in STATE_FIELDS}
        for field in OPTIONAL_STATE_FIELDS:
            if field in record:
                normalized_record[field] = record[field]
        normalized.append(normalized_record)

    normalized.sort(key=lambda item: (item["event_id"], item["step"]))
    return normalized
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
    if "objective_event_context" in record and not isinstance(
        record["objective_event_context"], dict
    ):
        return False
    if "official_evidence_dimensions" in record and (
        not isinstance(record["official_evidence_dimensions"], dict)
        or any(
            not isinstance(value, bool)
            for value in record["official_evidence_dimensions"].values()
        )
    ):
        return False
    if "public_context" in record and not isinstance(
        record["public_context"], dict
    ):
        return False
    if "public_context_timing" in record and not isinstance(
        record["public_context_timing"], dict
    ):
        return False
    if "objective_event_timing" in record and not isinstance(
        record["objective_event_timing"], dict
    ):
        return False
    if "simulation_mode" in record and not str(record["simulation_mode"]).strip():
        return False
    if "scenario_id" in record and not str(record["scenario_id"]).strip():
        return False
    if "shared_input_sha256" in record:
        fingerprint = str(record["shared_input_sha256"]).strip().lower()
        if len(fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in fingerprint
        ):
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
