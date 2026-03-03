"""Incident state definition for LangGraph."""

from dataclasses import dataclass, field
from typing import Any

from orchestration.handoffs.state_machine import IncidentState


@dataclass
class IncidentStateData:
    """State schema for incident handling."""

    # Incident metadata
    incident_id: str
    created_at: str
    current_state: IncidentState = IncidentState.DETECTED

    # Data
    logs: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    # Analysis results
    classification: dict[str, Any] = field(default_factory=dict)
    diagnosis: dict[str, Any] = field(default_factory=dict)
    remediation_plan: dict[str, Any] = field(default_factory=dict)

    # Execution
    remediation_steps: list[dict[str, Any]] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)

    # Resolution
    resolved: bool = False
    resolution_summary: str = ""

    # History
    state_history: list[tuple[IncidentState, str]] = field(default_factory=list)
