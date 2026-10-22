"""跨 Agent、仿真编排器和应用层使用的稳定数据契约。

领域对象只描述一次决策需要什么、返回什么，不读取文件、不访问环境变量，
也不包含具体决策规则。现有 JSON 字典仍是外部存储格式，契约负责在边界处
校验并转换，避免业务函数继续依赖分散的隐式字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def _copy_mapping(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} 必须是映射对象。")
    return dict(value)


@dataclass(frozen=True)
class SimulationContext:
    """一轮仿真的事件上下文。

    ``payload`` 保留原有事件上下文字典，确保提示词、指标和历史文件格式
    不发生变化；常用标识通过属性集中校验，调用方不再各自猜测字段结构。
    """

    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        payload = _copy_mapping(self.payload, "payload")
        event_id = payload.get("event_id")
        current_state = payload.get("current_state")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("SimulationContext 缺少合法 event_id。")
        if not isinstance(current_state, Mapping):
            raise ValueError("SimulationContext 缺少 current_state。")
        step = current_state.get("step")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("SimulationContext.current_state.step 必须是正整数。")
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SimulationContext":
        if isinstance(payload, cls):
            return payload
        return cls(payload)

    @property
    def event_id(self) -> str:
        return str(self.payload["event_id"])

    @property
    def step(self) -> int:
        return int(self.payload["current_state"]["step"])

    def to_mapping(self) -> dict[str, Any]:
        """返回兼容现有规则函数的浅拷贝。"""

        return dict(self.payload)


@dataclass(frozen=True)
class AgentDecisionInput:
    """单个 Agent 决策所需的全部显式输入。"""

    persona: Mapping[str, Any]
    context: SimulationContext
    policy: Mapping[str, Any]
    visible_comments: Sequence[Mapping[str, Any]]
    previous_state: Mapping[str, Any]
    history_summary: Mapping[str, Any]

    def __post_init__(self) -> None:
        persona = _copy_mapping(self.persona, "persona")
        agent_id = persona.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("AgentDecisionInput.persona 缺少合法 agent_id。")
        if not isinstance(self.context, SimulationContext):
            raise TypeError("AgentDecisionInput.context 必须是 SimulationContext。")
        object.__setattr__(self, "persona", persona)
        object.__setattr__(self, "policy", _copy_mapping(self.policy, "policy"))
        object.__setattr__(
            self,
            "visible_comments",
            tuple(
                _copy_mapping(item, "visible_comments item")
                for item in self.visible_comments
            ),
        )
        object.__setattr__(
            self,
            "previous_state",
            _copy_mapping(self.previous_state, "previous_state"),
        )
        object.__setattr__(
            self,
            "history_summary",
            _copy_mapping(self.history_summary, "history_summary"),
        )

    @property
    def agent_id(self) -> str:
        return str(self.persona["agent_id"])


@dataclass(frozen=True)
class AgentDecisionResult:
    """单个 Agent 的标准化决策结果。

    ``to_record`` 继续生成旧版 JSON 字典，外部文件和可视化无需迁移。
    """

    event_id: str
    step: int
    agent_id: str
    decision_method: str
    status: str
    decision: Mapping[str, Any] | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"success", "failed"}:
            raise ValueError("AgentDecisionResult.status 必须为 success 或 failed。")
        if self.status == "success" and not isinstance(self.decision, Mapping):
            raise ValueError("成功的 AgentDecisionResult 必须包含 decision。")
        if self.status == "failed" and not str(self.error or "").strip():
            raise ValueError("失败的 AgentDecisionResult 必须包含 error。")

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event_id": self.event_id,
            "step": self.step,
            "agent_id": self.agent_id,
            "decision_method": self.decision_method,
            "status": self.status,
        }
        if self.decision is not None:
            record["decision"] = dict(self.decision)
        if self.error is not None:
            record["error"] = self.error
        record.update(dict(self.metadata))
        return record
