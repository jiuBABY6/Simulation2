"""独立管理 Agent 的动态状态和历史摘要。

Persona 保存长期稳定特征；本模块只保存事件模拟过程中会变化的状态。
默认文件位置：demo/state/agent_state_history.jsonl。
"""

from collections import Counter

from infrastructure.json_storage import append_jsonl_many, read_jsonl
from project_config import AGENT_STATE_FILE


DEFAULT_AGENT_STATE = {
    "current_emotion": None,
    "official_attitude": None,
    "will_comment": False,
    "last_action": "none",
    "last_comment_faction": None,
    "last_comment_id": None,
    # 2026/08/25 Agent个人评论历史，新增功能：保留上一条完整评论供后续汇总个人记忆。
    "last_comment": None,
}

# 2026/08/25 Agent个人评论历史，新增功能：集中定义个人评论记忆需要保留的字段。
COMMENT_MEMORY_FIELDS = (
    "comment_id",
    "text",
    "emotion",
    "faction",
    "orientation",
    "stance",
    "introduced_step",
)


def create_empty_agent_state():
    """创建一个不会被不同 Agent 共享引用的空状态。"""
    return dict(DEFAULT_AGENT_STATE)


# 2026/08/25 Agent个人评论历史，新增功能：从本轮决策提取可写入Agent状态的完整评论。
def build_comment_memory(decision):
    """提取Agent实际选择的评论；旧格式缺少完整对象时保留评论编号。"""
    if decision.get("will_comment") is not True:
        return None

    selected_comment = decision.get("selected_comment")
    if isinstance(selected_comment, dict):
        comment_memory = {
            field: selected_comment.get(field)
            for field in COMMENT_MEMORY_FIELDS
            if field in selected_comment
        }
        if comment_memory.get("comment_id"):
            return comment_memory

    selected_comment_id = decision.get("selected_comment_id")
    if selected_comment_id:
        return {"comment_id": selected_comment_id}
    return None


# 2026/08/27 Agent情绪状态转换，新增功能：将逐轮情绪压缩为可解释的转换摘要。
def summarize_emotion_transitions(history):
    """统计上一轮情绪、累计转换次数和最近一次转换时间步。"""
    emotion_records = []
    for record in history:
        emotion = record.get("state", {}).get("current_emotion")
        if emotion in {"positive", "neutral", "negative"}:
            emotion_records.append((record.get("step"), emotion))

    if not emotion_records:
        return {
            "previous_emotion": None,
            "transition_count": 0,
            "last_change_step": None,
        }

    transition_count = 0
    last_change_step = None
    previous_emotion = emotion_records[0][1]
    for step, emotion in emotion_records[1:]:
        if emotion != previous_emotion:
            transition_count += 1
            last_change_step = step
        previous_emotion = emotion

    return {
        "previous_emotion": previous_emotion,
        "transition_count": transition_count,
        "last_change_step": last_change_step,
    }


class AgentStateStore:
    """负责 Agent 状态历史的读取、摘要和追加保存。"""

    def __init__(self, state_file=AGENT_STATE_FILE):
        self.state_file = state_file

    def _read_records(self):
        """从统一路径读取 Agent 状态记录。"""
        return read_jsonl(self.state_file)

    def get_history(self, agent_id, event_id, before_step=None):
        """读取指定 Agent 在某个时间步之前的去重历史。"""
        history_by_step = {}
        for record in self._read_records():
            if record.get("agent_id") != agent_id:
                continue
            if record.get("event_id") != event_id:
                continue
            step = record.get("step")
            if not isinstance(step, int):
                continue
            if before_step is not None and step >= before_step:
                continue
            history_by_step[step] = record
        return [history_by_step[step] for step in sorted(history_by_step)]

    def get_latest_state(self, agent_id, event_id, before_step=None):
        """读取指定 Agent 最近的一条动态状态。"""
        history = self.get_history(agent_id, event_id, before_step)
        if not history:
            return create_empty_agent_state()

        latest = history[-1].get("state", {})
        state = create_empty_agent_state()
        state.update(latest)
        return state

    # 2026/08/25 Agent个人评论历史，修改功能：按时间顺序向历史摘要加入Agent此前全部评论。
    # 2026/08/27 Agent情绪状态转换，修改功能：用转换摘要替代连续重复的最近情绪列表。
    def build_history_summary(self, agent_id, event_id, before_step=None):
        """将完整状态历史压缩为适合放入 LLM 输入的结构化摘要。"""
        history = self.get_history(agent_id, event_id, before_step)
        if not history:
            return {
                "history_step_count": 0,
                "emotion_transition": summarize_emotion_transitions([]),
                "latest_official_attitude": None,
                "action_counts": {},
                "comment_count": 0,
                "faction_counts": {},
                "own_comment_history": [],
            }

        states = [record.get("state", {}) for record in history]
        actions = [state.get("last_action", "none") for state in states]
        factions = [
            state.get("last_comment_faction")
            for state in states
            if state.get("last_comment_faction")
        ]
        own_comment_history = []
        for record, state in zip(history, states):
            if state.get("will_comment") is not True:
                continue

            comment_memory = state.get("last_comment")
            if isinstance(comment_memory, dict) and comment_memory.get(
                "comment_id"
            ):
                own_comment_history.append(
                    {"step": record.get("step"), **comment_memory}
                )
                continue

            # 兼容旧状态：旧记录只有评论编号和派系时仍保留可追踪信息。
            comment_id = state.get("last_comment_id")
            if comment_id:
                own_comment_history.append(
                    {
                        "step": record.get("step"),
                        "comment_id": comment_id,
                        "faction": state.get("last_comment_faction"),
                    }
                )

        return {
            "history_step_count": len(states),
            "first_step": history[0].get("step"),
            "last_step": history[-1].get("step"),
            "emotion_transition": summarize_emotion_transitions(history),
            "latest_official_attitude": states[-1].get(
                "official_attitude"
            ),
            "action_counts": dict(Counter(actions)),
            "comment_count": sum(
                1 for state in states if state.get("will_comment") is True
            ),
            "faction_counts": dict(Counter(factions)),
            "own_comment_history": own_comment_history,
        }

    # 2026/08/25 Agent个人评论历史，修改功能：状态记录同时保存本轮完整评论记忆。
    def build_state_record(self, event_id, step, agent_id, decision):
        """把一次 Agent 决策转换为统一的历史状态记录。"""
        will_comment = bool(decision.get("will_comment", False))
        last_comment = build_comment_memory(decision)
        return {
            "event_id": event_id,
            "step": step,
            "agent_id": agent_id,
            "state": {
                "current_emotion": decision.get("current_emotion"),
                "official_attitude": decision.get("official_attitude"),
                "will_comment": will_comment,
                "last_action": "comment" if will_comment else "wait",
                "last_comment_faction": (
                    decision.get("comment_faction") if will_comment else None
                ),
                "last_comment_id": (
                    decision.get("selected_comment_id") if will_comment else None
                ),
                "last_comment": last_comment,
            },
        }

    def save_decision_states(self, decision_results):
        """将本轮成功决策转换后追加到独立状态文件。"""
        records = []
        for result in decision_results:
            if result.get("status") != "success":
                continue
            records.append(
                self.build_state_record(
                    result["event_id"],
                    result["step"],
                    result["agent_id"],
                    result["decision"],
                )
            )
        if records:
            append_jsonl_many(self.state_file, records)
        return records
