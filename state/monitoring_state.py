"""Monitoring state definition for LangGraph."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MonitoringStateData:
    """State schema for monitoring workflows."""

    # Monitoring metadata
    monitoring_id: str
    started_at: str

    # Data collected
    recent_logs: list[dict[str, Any]] = field(default_factory=list)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    container_status: dict[str, Any] = field(default_factory=dict)

    # Analysis
    anomalies_detected: list[dict[str, Any]] = field(default_factory=list)
    errors_found: list[dict[str, Any]] = field(default_factory=list)

    # Incidents triggered
    incidents_created: list[str] = field(default_factory=list)

    # Monitoring status
    monitoring_active: bool = True
    last_check: str = ""
