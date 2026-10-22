"""共享单轮执行参数。

这些值原先定义在五策略实验脚本中，导致历史复现必须导入该脚本才能得到
相同配置。集中到独立配置对象后，两种实验模式只共享配置，不共享编排器。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SimulationRuntimeConfig:
    max_agents: int = 30
    max_workers: int = 5
    incremental_comment_count: int = 20
    strategy_incremental_comment_count: int = 8
    random_seed: int = 2026
    comment_temperature: float = 0.5


DEFAULT_SIMULATION_RUNTIME = SimulationRuntimeConfig()


@dataclass(frozen=True)
class SimulationPaths:
    """一次仿真进程实际使用的文件路径。"""

    demo_dir: Path
    state_dir: Path
    persona_dir: Path
    event_file: Path
    event_state_file: Path
    policy_file: Path
    comment_pool_file: Path
    comment_profile_file: Path
    social_network_config_file: Path
    social_network_file: Path
    agent_state_file: Path
    decision_history_file: Path
    incremental_comment_file: Path
    metrics_history_file: Path
    propagation_history_file: Path
    single_llm_result_file: Path


@dataclass(frozen=True)
class AgentDecisionRuntimeConfig:
    """批量决策和个人可见范围使用的运行参数。"""

    max_agents: int
    max_workers: int
    retry_count: int
    visible_comment_count: int
    current_step_visible_count: int
    comment_visibility_seed: int
    comment_selection_top_k: int
    comment_selection_seed: int


@dataclass(frozen=True)
class ProjectRuntimeConfig:
    """从兼容配置模块组装出的显式运行配置。"""

    simulation: SimulationRuntimeConfig
    decision: AgentDecisionRuntimeConfig
    paths: SimulationPaths

    def ensure_runtime_directories(self) -> None:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)


def load_project_runtime_config() -> ProjectRuntimeConfig:
    """在应用边界读取旧配置，并转换为可注入对象。

    2026/10/15，重构功能：``project_config`` 继续作为兼容配置源，
    但领域服务不再分别导入二十余个全局常量。后续迁移其他模块时可以
    复用此对象，而不需要一次性改写全部入口。
    """

    import project_config as legacy

    simulation = SimulationRuntimeConfig(
        max_agents=legacy.MAX_AGENT_COUNT,
        max_workers=legacy.MAX_WORKERS,
        incremental_comment_count=legacy.INCREMENTAL_COMMENT_COUNT,
        strategy_incremental_comment_count=(
            legacy.STRATEGY_INCREMENTAL_COMMENT_COUNT
        ),
        random_seed=legacy.COMMENT_VISIBILITY_SEED,
        comment_temperature=legacy.COMMENT_POOL_TEMPERATURE,
    )
    decision = AgentDecisionRuntimeConfig(
        max_agents=legacy.MAX_AGENT_COUNT,
        max_workers=legacy.MAX_WORKERS,
        retry_count=legacy.RETRY_COUNT,
        visible_comment_count=legacy.VISIBLE_COMMENT_COUNT,
        current_step_visible_count=legacy.CURRENT_STEP_VISIBLE_COUNT,
        comment_visibility_seed=legacy.COMMENT_VISIBILITY_SEED,
        comment_selection_top_k=legacy.COMMENT_SELECTION_TOP_K,
        comment_selection_seed=legacy.COMMENT_SELECTION_SEED,
    )
    paths = SimulationPaths(
        demo_dir=legacy.DEMO_DIR,
        state_dir=legacy.STATE_DIR,
        persona_dir=legacy.PERSONA_DIR,
        event_file=legacy.EVENT_FILE,
        event_state_file=legacy.EVENT_STATE_FILE,
        policy_file=legacy.POLICY_FILE,
        comment_pool_file=legacy.COMMENT_POOL_FILE,
        comment_profile_file=legacy.COMMENT_PROFILE_FILE,
        social_network_config_file=legacy.SOCIAL_NETWORK_CONFIG_FILE,
        social_network_file=legacy.SOCIAL_NETWORK_FILE,
        agent_state_file=legacy.AGENT_STATE_FILE,
        decision_history_file=legacy.DECISION_HISTORY_FILE,
        incremental_comment_file=legacy.INCREMENTAL_COMMENT_FILE,
        metrics_history_file=legacy.METRICS_HISTORY_FILE,
        propagation_history_file=legacy.PROPAGATION_HISTORY_FILE,
        single_llm_result_file=legacy.SINGLE_LLM_RESULT_FILE,
    )
    return ProjectRuntimeConfig(
        simulation=simulation,
        decision=decision,
        paths=paths,
    )

