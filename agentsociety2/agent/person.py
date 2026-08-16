"""Workspace-backed PersonAgent (thin).

中文：``PersonAgent`` 现在只负责 person 专属逻辑（memory、todo、person prompt、
observe），通用的 agent 机器（workspace / skill / tool / react）已下沉到
``agent.base``。
English: ``PersonAgent`` now owns only person-specific logic (memory, todo,
person prompt, observe).  The generic agent machinery (workspace / skill /
tool / react) has been pushed down into ``agent.base``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentsociety2.agent.base import AgentBase, ReactToolResult
from agentsociety2.agent.memory_runtime import (
    MemoryRuntimeConfig,
    PersonMemoryRuntime,
)
from agentsociety2.agent.person_prompt import build_react_messages
from agentsociety2.logger import get_logger

if TYPE_CHECKING:
    from agentsociety2.agent.service_proxy import ServiceProxy

logger = get_logger()


class PersonAgent(AgentBase):
    """Workspace-backed simulated person agent.

    Person-specific responsibilities:

    - Memory runtime (``PersonMemoryRuntime``): ``MEMORY.md`` + episodes, plus
      the ``memory_*`` tool dispatch.
    - ``todo_*`` tool dispatch (the generic TODO state store + helpers live on
      :class:`AgentBase`; PersonAgent routes the ``todo_*`` prefix to them).
    - Person prompt building (``build_react_messages``) — the prompt hook the
      generic ReAct loop calls.
    - ``step`` / ``ask`` orchestration (observe + react loop + lifecycle hooks).

    Generic agent machinery (workspace binding, skill discovery, file/skill/ask_env
    tool dispatch, the ReAct loop, LLM dispatch, response parsing, TODO state,
    trace spans, AGENT.json persistence, construction model) is inherited from
    :class:`AgentBase`.
    """

    # ==================== Workspace contract ====================
    # ``create`` / ``from_workspace`` are inherited verbatim from AgentBase
    # (they delegate to the concrete base implementations, which call
    # ``cls()`` + ``await agent.restore(...)``).  PersonAgent only overrides
    # ``restore`` to add person-specific state on top of the base restore.

    # ==================== Descriptions ====================

    @classmethod
    def description(cls) -> str:
        """Return a short registry description."""
        return (
            "PersonAgent: lightweight workspace-backed person agent rewrite. "
            "Current slice supports workspace lifecycle, skill catalog discovery, "
            "and detailed behavior tracing; ReAct tools are added incrementally."
        )

    @classmethod
    def init_description(cls) -> str:
        """Return initialization guidance for generated configs."""
        return """PersonAgent initialization (workspace-based).

Agents are created via ``PersonAgent.create(workspace_path, profile, config)``
and reconstructed via ``await PersonAgent.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

Required profile fields:
- id (int): unique agent id.
- name (str | None): optional display name.

Config dict keys (written to ``config.json``, round-tripped by ``from_workspace``):
- max_react_turns (int): max ReAct turns per step. Default 10.
- enable_todo_list (bool): default true.
- enable_memory (bool): default true.
- memory_context_max_chars (int): default 4000.
- recent_memory_limit (int): default 8.
- memory_consolidation_pending_threshold (int): default 10.
- memory_consolidation_interval_steps (int): default 8.
- memory_high_importance_threshold (float): default 0.75.
- disabled_skill_ids (list[str]): default [].
- default_activated_skill_ids (list[str]): default [].

Minimal config example:
```json
{
  "profile": {"id": 1, "name": "Alice", "occupation": "engineer"},
  "config": {"enable_memory": true, "max_react_turns": 6}
}
```
"""

    # ==================== Person-specific config helpers ====================

    def _apply_person_config(self) -> None:
        """Parse person-specific config fields from ``self._config``.

        Called by :meth:`restore` after the base restore.  The generic
        react-loop / tool flags (``_max_react_turns``, ``_enable_todo_list``)
        are now parsed by :meth:`AgentBase.restore`; this method only parses
        the person-specific memory configuration.
        """
        cfg = self._config
        self._enable_memory = bool(cfg.get("enable_memory", True))
        self._memory_context_max_chars = max(
            500, int(cfg.get("memory_context_max_chars", 4000) or 4000)
        )
        self._recent_memory_limit = max(0, int(cfg.get("recent_memory_limit", 8) or 0))

    # ==================== restore override ====================

    async def restore(
        self,
        workspace_path: Path,
        service_proxy: "ServiceProxy",
    ) -> None:
        """Restore base state, then build person-specific runtime (memory).

        Args:
            workspace_path: Agent workspace root.
            service_proxy: Shared service container.
        """
        await super().restore(workspace_path, service_proxy)
        self._apply_person_config()
        self._world_description: str = ""
        self._build_memory_runtime()

    def _build_memory_runtime(self) -> None:
        """Construct the ``PersonMemoryRuntime`` bound to this agent."""
        from agentsociety2.agent.memory import MemoryConsolidationConfig

        cfg = self._config
        self._memory_runtime = PersonMemoryRuntime(
            agent_id=self.id,
            agent_name=self.name,
            config=MemoryRuntimeConfig(
                enabled=self._enable_memory,
                context_max_chars=self._memory_context_max_chars,
                recent_limit=self._recent_memory_limit,
                consolidation=MemoryConsolidationConfig(
                    pending_threshold=max(
                        1,
                        int(
                            cfg.get("memory_consolidation_pending_threshold", 10) or 10
                        ),
                    ),
                    interval_steps=max(
                        1, int(cfg.get("memory_consolidation_interval_steps", 8) or 8)
                    ),
                    high_importance_threshold=max(
                        0.0,
                        min(
                            1.0,
                            float(
                                cfg.get("memory_high_importance_threshold", 0.75)
                                or 0.75
                            ),
                        ),
                    ),
                    max_memory_chars=self._memory_context_max_chars,
                ),
            ),
            get_model_name=lambda: self._model_name,
            dispatch_llm=lambda **kwargs: self._dispatcher.call(**kwargs),
            get_profile=self.get_profile,
            logger=logger,
            trace_span=self.trace_span,
        )

    # ==================== to_workspace ====================

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state back to the workspace.

        Writes ``AGENT.json`` (profile / step_count / current_time / skills /
        initialized_at). ``config.json`` is NOT rewritten.  Memory
        (``MEMORY.md`` + episodes) is persisted via the memory runtime's
        ``after_step`` path during ``step()``.

        Args:
            workspace_path: Agent workspace root.
        """
        workspace_path = Path(workspace_path)
        if self._workspace_root is None:
            self._bind_workspace(workspace_path)
        self.persist_agent_json(
            tick=None,
            t=self._current_time,
        )

    # ==================== AGENT.json override (memory fields) ====================

    def build_agent_json(
        self,
        *,
        tick: int | None,
        t: datetime | None,
    ) -> dict[str, Any]:
        """Build AGENT.json with person-specific memory / skill fields."""
        data = super().build_agent_json(tick=tick, t=t)
        # Enrich with person-specific memory + skill-disabled/default fields.
        data["skills"] = {
            "visible": sorted(self.skill_runtime.visible_skill_ids()),
            "activated": sorted(self.skill_runtime.activated_skill_ids()),
            "disabled": sorted(self._disabled_skill_ids),
            "default_activated": sorted(self._default_activated_skill_ids),
        }
        data["memory"] = {
            "enabled": self._enable_memory,
            "summary_path": "MEMORY.md" if self._enable_memory else None,
            "episodes_path": "memory/episodes.jsonl" if self._enable_memory else None,
        }
        return data

    # ==================== TODO helpers ====================
    # The generic TODO helpers (_todo_store, _ensure_todo_state,
    # _build_todo_context, _current_simulation_time,
    # _normalize_todo_due_value, _normalize_todo_tool_args,
    # dispatch_todo_tool) are inherited from AgentBase.

    # ==================== Memory helpers ====================

    def _ensure_memory_store(self):
        """Return initialized core memory store when enabled."""
        from agentsociety2.agent.memory import AgentMemoryStore

        store: AgentMemoryStore | None = self._memory_runtime.ensure_store(
            self.workspace_root_path()
        )
        return store

    def _build_memory_context(self) -> dict[str, Any]:
        """Build compact prompt context from MEMORY.md and recent episodes."""
        store = self._ensure_memory_store()
        if store is None:
            return {}
        return self._memory_runtime.build_context()

    # ==================== Person-specific react tool dispatch ====================

    async def dispatch_react_tool(
        self,
        action: str,
        args: dict[str, Any],
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """Dispatch person-specific prefixes, then delegate the rest to base.

        Person-specific prefixes handled here:

        - ``memory_*`` → :meth:`_dispatch_memory_tool` (person memory runtime).
        - ``todo_*`` → :meth:`dispatch_todo_tool` (inherited from
          :class:`AgentBase`; the generic TODO store + arg normalization).

        All other actions (workspace / skill / ask_env) are delegated to
        ``await super().dispatch_react_tool(action, args, readonly=readonly)``.
        """
        try:
            if readonly and action.startswith("todo_") and action != "todo_list":
                return ReactToolResult(
                    False,
                    f"{action} is disabled in readonly mode",
                    {"action": action, "readonly": True},
                )
            if action.startswith("memory_"):
                return self._dispatch_memory_tool(action, args)
            if action.startswith("todo_"):
                return self.dispatch_todo_tool(action, args)
        except Exception as exc:
            return ReactToolResult(False, str(exc), {"error": str(exc)})
        return await super().dispatch_react_tool(action, args, readonly=readonly)

    def _react_tool_overrides(self, *, readonly: bool) -> dict[str, Any]:
        """Replace the ``finish`` tool per mode.

        - ask / readonly mode: answer-only ``finish`` (external question).
        - step mode: ``finish`` with a short ``final`` AND inline ``memories``,
          so the model records step memories in the same call that ends the
          step — removing the separate memory-extraction LLM pass. ``step()``
          feeds the captured memories into ``memory_runtime.after_step``.
        """
        from agentsociety2.agent.person_tools import (
            finish_ask_tool_schema,
            finish_step_tool_schema,
        )

        return {
            "finish": finish_ask_tool_schema() if readonly else finish_step_tool_schema()
        }

    def _dispatch_memory_tool(
        self,
        action: str,
        args: dict[str, Any],
    ) -> ReactToolResult:
        """Dispatch built-in read-only memory retrieval tools."""
        ok, observation, data = self._memory_runtime.dispatch_tool(action, args)
        return ReactToolResult(ok, observation, data)

    # ==================== ReAct prompt hook ====================

    def build_react_messages(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]],
        question: str | None = None,
        readonly: bool = False,
        skill_hooks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """Build ReAct prompt messages (person-specific)."""
        return build_react_messages(
            name=self.name,
            world_description=self._world_description,
            skill_catalog=self.skill_runtime.skill_catalog(),
            activated_skill_content=self.skill_runtime.activated_skill_content_xml(),
            observations=observations,
            agent_json=self.build_agent_json(tick=tick, t=t),
            memory_context=self._build_memory_context()
            if self._enable_memory
            else None,
            todo_context=self._build_todo_context(t)
            if self._enable_todo_list
            else None,
            question=question,
            readonly=readonly,
            disable_skills=self.skill_runtime.visible_skill_count() == 0,
            skill_hooks=skill_hooks,
        )

    # The generic ReAct loop, LLM call, and response parsing
    # (run_react_loop, _call_react_llm, _call_react_llm_with_messages,
    # _complete_react_once, _parse_react_responses) are inherited from
    # AgentBase; they call this ``build_react_messages`` hook polymorphically.

    async def _load_world_description(self) -> str:
        """Load the current world description from the environment."""
        if self._env is None:
            return ""
        getter = getattr(self._env, "get_world_description", None)
        if getter is None:
            return ""
        try:
            value = await getter()
        except Exception as exc:
            logger.warning("Agent %s: get_world_description failed: %s", self.id, exc)
            return ""
        return str(value or "")

    async def _ensure_initialized(self) -> None:
        """Lazily run first-use initialization (idempotent)."""
        if self._initialized_at is not None:
            return
        self._initialized_at = datetime.now().isoformat()
        with self.trace_span(
            "agent.init",
            attributes={
                "operation.type": "agent",
                "event.type": "agent_init",
                "agent.id": self.id,
            },
        ) as span:
            self._ensure_todo_state()
            self._ensure_memory_store()
            discovered = (
                self.discover_skill_sources(self._env) if self._env is not None else {}
            )
            self._world_description = await self._load_world_description()
            self.persist_agent_json(tick=None, t=None)
            span.attributes.update(
                {
                    "workspace": str(self.workspace_root_path()),
                    "profile.keys": sorted(self.get_profile().keys()),
                    "skill.visible_count": self.skill_runtime.visible_skill_count(),
                    "skill.discovery_sources": len(discovered),
                    "world.description_chars": len(self._world_description),
                }
            )

    # ==================== step / ask ====================

    async def step(self, tick: int, t: datetime) -> str:
        """Run one simulation step."""
        await self._ensure_initialized()
        self._step_count += 1
        self._current_time = t

        with self.trace_span(
            "agent.step",
            attributes={
                "agent.tick": tick,
                "operation.type": "agent",
                "event.type": "step",
                "input.summary": {"time": t.isoformat(), "tick": tick},
            },
        ) as span:
            self._refresh_visible_skills()
            self.persist_agent_json(tick=tick, t=t)

            initial_obs: list[dict[str, Any]] = []
            pre_hooks = await self.run_lifecycle_hooks("pre_step", tick=tick, t=t)
            skill_hooks: list[dict[str, Any]] | None = None
            if pre_hooks:
                skill_hooks = [
                    {
                        "skill": item["skill_id"],
                        "hook": item["hook_type"],
                        "ok": item["ok"],
                        "output": item["stdout"],
                    }
                    for item in pre_hooks
                    if item.get("ok") and item.get("stdout")
                ] or None

            if self._env is not None:
                try:
                    with self.trace_span(
                        "react.tool",
                        attributes={
                            "operation.type": "react",
                            "react.action": "observe",
                        },
                    ) as obs_span:
                        _env_span = self._current_trace_span
                        _, observation = await self.ask_env(
                            {"id": self.id},
                            "<observe>",
                            readonly=True,
                            trace_id=_env_span.trace_id if _env_span else None,
                            parent_span_id=_env_span.span_id if _env_span else None,
                        )
                        obs_text = str(observation or "")
                        obs_span.attributes.update(
                            {
                                "result.ok": True,
                                "output.summary": {"observation": obs_text},
                            }
                        )
                        initial_obs.append(
                            {
                                "turn": 0,
                                "action": "observe",
                                "ok": True,
                                "observation": obs_text,
                            }
                        )
                except Exception:
                    logger.debug("Observation failed for agent", exc_info=True)

            result = await self.run_react_loop(
                tick=tick, t=t, observations=initial_obs, skill_hooks=skill_hooks
            )
            post_hooks = await self.run_lifecycle_hooks("post_step", tick=tick, t=t)
            memory_episodes = await self._memory_runtime.after_step(
                tick=tick,
                t=t,
                step_count=self._step_count,
                finish_memories=self._last_finish_memories,
            )
            span.attributes.update(
                {
                    "step.count": self._step_count,
                    "skill.visible_count": self.skill_runtime.visible_skill_count(),
                    "skill.pre_hook_count": len(pre_hooks),
                    "skill.post_hook_count": len(post_hooks),
                    "memory.episode_count": len(memory_episodes),
                    "output.summary": {"result": result},
                }
            )
        return result

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """Answer an external question through the ReAct loop."""
        if self._env is None:
            raise RuntimeError("PersonAgent.ask requires an initialized environment")
        await self._ensure_initialized()

        with self.trace_span(
            "agent.ask",
            attributes={
                "operation.type": "agent",
                "event.type": "ask",
                "input.summary": {
                    "readonly": readonly,
                    "message_chars": len(message),
                },
            },
        ) as span:
            try:
                now = t or self._current_time or datetime.now()
                self._current_time = now
                self._refresh_visible_skills()
                self.persist_agent_json(tick=None, t=now)
                answer_text = await self.run_react_loop(
                    tick=0,
                    t=now,
                    observations=[],
                    question=message,
                    readonly=readonly,
                )
            except Exception as exc:
                span.attributes["error.message"] = str(exc)[:300]
                raise

            span.attributes["output.summary"] = {"answer_chars": len(answer_text)}
        return answer_text
