"""Diagnosis agent implementation."""

from typing import Any

class DiagnosisAgent:
    """
    Responsible for determining the root cause of a detected incident.
    The agent receives error logs and other context, and returns a structured
    diagnosis object that can be used by the remediation workflow.
    """

    async def diagnose(self, incident: dict[str, Any]) -> dict[str, Any]:
        """Perform simple heuristic diagnosis based on the incident data."""
        # placeholder logic -- just echo the message for now
        return {"root_cause": incident.get("summary", "unknown"), "confidence": 0.5}
