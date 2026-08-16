"""可复现的微博舆情群体 Agent 仿真骨架。"""

from .config import ScenarioConfig, load_scenario
from .engine import SimulationEngine

__all__ = ["ScenarioConfig", "SimulationEngine", "load_scenario"]
