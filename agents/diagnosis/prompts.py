from __future__ import annotations

"""Prompt templates for the diagnosis agent."""

from typing import List

from agents.diagnosis.schemas import IncidentEvent


SYSTEM_PROMPT = """
You are a senior Site Reliability Engineer responsible for diagnosing production
incidents in a cloud-native Next.js application.

You receive:
- a high-level incident summary,
- a focused window of raw application logs around the incident timestamp,
- a list of simple rule-based patterns that were detected (if any).

Your job is to:
1. Determine the most likely root cause of the incident.
2. Estimate your confidence as a float between 0.0 and 1.0.
3. Provide a concise but clear explanation aimed at on-call engineers.
4. Recommend a concrete, actionable next step to remediate or investigate.

IMPORTANT OUTPUT FORMAT:
- You MUST reply with ONLY a single JSON object.
- Do NOT include any markdown, prose, or comments.
- The JSON schema MUST be:
  {
    "incident_id": "string",
    "root_cause": "string",
    "confidence": 0.0,
    "patterns_detected": ["string", "..."],
    "explanation": "string",
    "recommended_action": "string"
  }
"""


def build_user_prompt(
    incident: IncidentEvent,
    log_context: List[str],
    patterns: List[str],
) -> str:
    """Build the user-facing prompt for the LLM."""
    logs_text = "\n".join(log_context) if log_context else "<no matching logs found in the requested window>"
    patterns_text = ", ".join(patterns) if patterns else "none"

    return f"""
Incident summary:
- Incident ID: {incident.incident_id}
- Service: {incident.service}
- Timestamp: {incident.timestamp.isoformat()}
- Triggering log snippet:
{incident.log_snippet}

Detected patterns (rule-based heuristics): {patterns_text}

Log window (±30s around the incident timestamp):
{logs_text}

Based on this information, analyse the situation and respond ONLY with a JSON
object following the required schema. Do not include any additional text.
"""


__all__ = ["SYSTEM_PROMPT", "build_user_prompt"]

