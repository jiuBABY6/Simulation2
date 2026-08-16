"""Hypothesis management module

Provides functionality for:
- Creating hypotheses
- Reading hypotheses
- Listing hypotheses
- Deleting hypotheses
"""

from agentsociety2.skills.hypothesis.models import (
    HypothesisModel,
    ExperimentGroupModel,
    HypothesisDataModel,
)
from agentsociety2.skills.hypothesis.manager import (
    find_existing_hypotheses,
    get_next_hypothesis_id,
    validate_hypothesis_schema,
    create_hypothesis_structure,
    generate_hypothesis_markdown,
    generate_experiment_markdown,
    generate_sim_settings,
    add_hypothesis,
    add_hypothesis_with_validation,
    get_hypothesis,
    list_hypotheses,
    delete_hypothesis,
)

__all__ = [
    "ExperimentGroupModel",
    "HypothesisDataModel",
    # Models
    "HypothesisModel",
    "add_hypothesis",
    "add_hypothesis_with_validation",
    "create_hypothesis_structure",
    "delete_hypothesis",
    # Manager
    "find_existing_hypotheses",
    "generate_experiment_markdown",
    "generate_hypothesis_markdown",
    "generate_sim_settings",
    "get_hypothesis",
    "get_next_hypothesis_id",
    "list_hypotheses",
    "validate_hypothesis_schema",
]
