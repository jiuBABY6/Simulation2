"""Experiment execution skills

Provides experiment execution and result management.
"""

from .runner import start_experiment, stop_experiment, get_experiment_status, list_experiments
from .models import ExperimentConfig, ExperimentStatus, ExperimentInfo
from .init_tool import ExperimentConfigTool
from .module_discovery import (
    get_available_env_modules,
    get_available_agent_modules,
    get_modules_summary,
    validate_module_selection,
    get_module_selection_guidance,
    validate_hypothesis_modules,
)
from .claude_integration import (
    suggest_modules_for_topic,
    generate_hypothesis_config,
    validate_experiment_ready,
    get_experiment_template,
    format_module_suggestion_message,
)

__all__ = [
    "ExperimentConfig",
    "ExperimentConfigTool",
    "ExperimentInfo",
    "ExperimentStatus",
    "format_module_suggestion_message",
    "generate_hypothesis_config",
    "get_available_agent_modules",
    # Module discovery
    "get_available_env_modules",
    "get_experiment_status",
    "get_experiment_template",
    "get_module_selection_guidance",
    "get_modules_summary",
    "list_experiments",
    "start_experiment",
    "stop_experiment",
    # Claude Code integration
    "suggest_modules_for_topic",
    "validate_experiment_ready",
    "validate_hypothesis_modules",
    "validate_module_selection",
]
