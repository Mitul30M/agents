from __future__ import annotations

"""State primitives for orchestrator supervision and timelines."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IncidentLifecycleState(str, Enum):
    DETECTED = "DETECTED"
    DIAGNOSING = "DIAGNOSING"
    DIAGNOSED = "DIAGNOSED"
    REMEDIATING = "REMEDIATING"
    REMEDIATED = "REMEDIATED"
    COMMUNICATING = "COMMUNICATING"
    RESOLVED = "RESOLVED"
    RETRYING = "RETRYING"
    ESCALATED = "ESCALATED"


_ALLOWED_TRANSITIONS: dict[IncidentLifecycleState, set[IncidentLifecycleState]] = {
    IncidentLifecycleState.DETECTED: {
        IncidentLifecycleState.DIAGNOSING,
        IncidentLifecycleState.DIAGNOSED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.DIAGNOSING: {
        IncidentLifecycleState.DIAGNOSED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.DIAGNOSED: {
        IncidentLifecycleState.REMEDIATING,
        IncidentLifecycleState.REMEDIATED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.REMEDIATING: {
        IncidentLifecycleState.REMEDIATED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.REMEDIATED: {
        IncidentLifecycleState.COMMUNICATING,
        IncidentLifecycleState.RESOLVED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.COMMUNICATING: {
        IncidentLifecycleState.RESOLVED,
        IncidentLifecycleState.RETRYING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.RETRYING: {
        IncidentLifecycleState.DETECTED,
        IncidentLifecycleState.DIAGNOSING,
        IncidentLifecycleState.DIAGNOSED,
        IncidentLifecycleState.REMEDIATING,
        IncidentLifecycleState.REMEDIATED,
        IncidentLifecycleState.COMMUNICATING,
        IncidentLifecycleState.ESCALATED,
    },
    IncidentLifecycleState.RESOLVED: set(),
    IncidentLifecycleState.ESCALATED: set(),
}


@dataclass
class TimelineEvent:
    timestamp: str
    source: str
    event_type: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IncidentTimeline:
    incident_id: str
    current_state: IncidentLifecycleState
    created_at: str
    updated_at: str
    retry_count: int = 0
    events: list[TimelineEvent] = field(default_factory=list)


class IncidentStateStore:
    """In-memory incident state/timeline store with guarded transitions."""

    def __init__(self) -> None:
        self._timelines: dict[str, IncidentTimeline] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def ensure_incident(self, incident_id: str) -> IncidentTimeline:
        existing = self._timelines.get(incident_id)
        if existing:
            return existing

        now = self._now()
        timeline = IncidentTimeline(
            incident_id=incident_id,
            current_state=IncidentLifecycleState.DETECTED,
            created_at=now,
            updated_at=now,
        )
        self._timelines[incident_id] = timeline
        return timeline

    def add_event(
        self,
        incident_id: str,
        source: str,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timeline = self.ensure_incident(incident_id)
        timeline.events.append(
            TimelineEvent(
                timestamp=self._now(),
                source=source,
                event_type=event_type,
                message=message,
                metadata=metadata or {},
            )
        )
        timeline.updated_at = self._now()

    def can_transition(
        self, current: IncidentLifecycleState, target: IncidentLifecycleState
    ) -> bool:
        if current == target:
            return True
        return target in _ALLOWED_TRANSITIONS.get(current, set())

    def transition(
        self,
        incident_id: str,
        target: IncidentLifecycleState,
        source: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        timeline = self.ensure_incident(incident_id)
        current = timeline.current_state

        if not self.can_transition(current, target):
            self.add_event(
                incident_id,
                source=source,
                event_type="invalid_transition",
                message=f"Transition rejected: {current.value} -> {target.value}",
                metadata={"reason": reason, **(metadata or {})},
            )
            return False

        timeline.current_state = target
        timeline.updated_at = self._now()
        self.add_event(
            incident_id,
            source=source,
            event_type="state_transition",
            message=f"{current.value} -> {target.value}",
            metadata={"reason": reason, **(metadata or {})},
        )
        return True

    def increment_retry(self, incident_id: str, source: str, reason: str) -> int:
        timeline = self.ensure_incident(incident_id)
        timeline.retry_count += 1
        timeline.updated_at = self._now()
        self.add_event(
            incident_id,
            source=source,
            event_type="retry",
            message=f"Retry #{timeline.retry_count}",
            metadata={"reason": reason},
        )
        return timeline.retry_count

    def stale_incidents(
        self,
        timeout_seconds: float,
        active_states: set[IncidentLifecycleState],
    ) -> list[IncidentTimeline]:
        now = datetime.now(timezone.utc)
        stale: list[IncidentTimeline] = []
        for timeline in self._timelines.values():
            if timeline.current_state not in active_states:
                continue
            elapsed = now - datetime.fromisoformat(timeline.updated_at)
            if elapsed.total_seconds() >= timeout_seconds:
                stale.append(timeline)
        return stale

    def get_snapshot(self) -> dict[str, dict[str, Any]]:
        snapshot: dict[str, dict[str, Any]] = {}
        for incident_id, timeline in self._timelines.items():
            snapshot[incident_id] = {
                "current_state": timeline.current_state.value,
                "created_at": timeline.created_at,
                "updated_at": timeline.updated_at,
                "retry_count": timeline.retry_count,
                "events": [
                    {
                        "timestamp": event.timestamp,
                        "source": event.source,
                        "event_type": event.event_type,
                        "message": event.message,
                        "metadata": event.metadata,
                    }
                    for event in timeline.events
                ],
            }
        return snapshot
