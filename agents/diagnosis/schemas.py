from __future__ import annotations

"""Typed schemas for the diagnosis agent."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, validator


class IncidentEvent(BaseModel):
    """Inbound incident event as published to the `incident_stream`."""

    incident_id: str = Field(..., description="Unique incident identifier")
    timestamp: datetime = Field(..., description="Incident timestamp in ISO8601 format")
    service: str = Field(..., description="Service or application name")
    log_snippet: str = Field(..., description="Representative log snippet for the incident")

    class Config:
        extra = "allow"

    @validator("timestamp", pre=True)
    def _parse_timestamp(cls, value: object) -> datetime:
        """Parse ISO8601 timestamps, accepting a trailing 'Z'."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            v = value.strip()
            if v.endswith("Z"):
                v = v[:-1]
            return datetime.fromisoformat(v)
        raise TypeError("timestamp must be a datetime or ISO8601 string")


class PatternDetectionResult(BaseModel):
    """Result of rule-based pattern detection over a log window."""

    patterns: List[str] = Field(default_factory=list)


class DiagnosisRequest(BaseModel):
    """Payload passed into the LLM reasoning step."""

    incident: IncidentEvent
    log_context: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(default_factory=list)


class DiagnosisResult(BaseModel):
    """Final structured diagnosis report."""

    incident_id: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    patterns_detected: List[str]
    explanation: str
    recommended_action: str
    raw_model_output: Optional[dict] = Field(
        default=None, description="Optional raw JSON returned by the LLM for debugging."
    )


__all__ = [
    "IncidentEvent",
    "PatternDetectionResult",
    "DiagnosisRequest",
    "DiagnosisResult",
]

