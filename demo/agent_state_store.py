"""独立管理 Agent 的动态状态和历史摘要。

Persona 保存长期稳定特征；本模块只保存事件模拟过程中会变化的状态。
默认文件位置：demo/state/agent_state_history.jsonl。
"""

from collections import Counter

from json_storage import append_jsonl_many, read_jsonl
from project_config import AGENT_STATE_FILE, DEMO_DIR


DEFAULT_AGENT_STATE = {
    "current_emotion": None,
    "official_attitude": None,
    "will_comment": False,
    "last_action": "none",
    "last_comment_faction": None,
    "last_comment_id": None,
}


def create_empty_agent_state():
    """创建一个不会被不同 Agent 共享引用的空状态。"""
    return dict(DEFAULT_AGENT_STATE)


class AgentStateStore:
    """负责 Agent 状态历史的读取、摘要和追加保存。"""

    def __init__(self, state_file=AGENT_STATE_FILE, legacy_state_file=None):
        self.state_file = state_file
        # 兼容重构前 demo/agent_state_history.jsonl 中已有的示例状态。
        self.legacy_state_file = legacy_state_file or DEMO_DIR / "agent_state_history.jsonl"

    def _read_records(self):
        """读取新路径和旧路径中的状态记录。"""
        records = read_jsonl(self.state_file)
        if not records and self.legacy_state_file != self.state_file:
            records = read_jsonl(self.legacy_state_file)
        return records

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

    def build_history_summary(self, agent_id, event_id, before_step=None):
        """将完整状态历史压缩为适合放入 LLM 输入的结构化摘要。"""
        history = self.get_history(agent_id, event_id, before_step)
        if not history:
            return {
                "history_step_count": 0,
                "recent_emotions": [],
                "recent_official_attitudes": [],
                "action_counts": {},
                "comment_count": 0,
                "faction_counts": {},
            }

        states = [record.get("state", {}) for record in history]
        recent_states = states[-3:]
        actions = [state.get("last_action", "none") for state in states]
        factions = [
            state.get("last_comment_faction")
            for state in states
            if state.get("last_comment_faction")
        ]

        return {
            "history_step_count": len(states),
            "first_step": history[0].get("step"),
            "last_step": history[-1].get("step"),
            "recent_emotions": [state.get("current_emotion") for state in recent_states],
            "recent_official_attitudes": [
                state.get("official_attitude") for state in recent_states
            ],
            "action_counts": dict(Counter(actions)),
            "comment_count": sum(
                1 for state in states if state.get("will_comment") is True
            ),
            "faction_counts": dict(Counter(factions)),
        }

    def build_state_record(self, event_id, step, agent_id, decision):
        """把一次 Agent 决策转换为统一的历史状态记录。"""
        will_comment = bool(decision.get("will_comment", False))
        return {
            "event_id": event_id,
            "step": step,
            "agent_id": agent_id,
            "state": {
                "current_emotion": decision.get("current_emotion"),
                "official_attitude": decision.get("official_attitude"),
                "will_comment": will_comment,
                "last_action": "comment" if will_comment else "wait",
                "last_comment_faction": decision.get("comment_faction") if will_comment else None,
                "last_comment_id": decision.get("selected_comment_id") if will_comment else None,
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

