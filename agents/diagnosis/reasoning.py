from __future__ import annotations

"""LLM-backed root cause reasoning for incidents."""

import asyncio
import json
import logging

from langchain_ollama import ChatOllama

from app.config import Config
from agents.diagnosis.prompts import SYSTEM_PROMPT, build_user_prompt
from agents.diagnosis.schemas import DiagnosisRequest, DiagnosisResult

logger = logging.getLogger(__name__)


async def _call_ollama(prompt: str) -> str:
    """Call an Ollama-hosted open-source model asynchronously."""

    def _run() -> str:
        llm = ChatOllama(
            model=Config.DIAGNOSIS_AGENT_LLM,
            temperature=0.2,
            base_url=Config.OLLAMA_BASE_URL,
        )
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    return await asyncio.to_thread(_run)


async def run_llm_diagnosis(request: DiagnosisRequest) -> DiagnosisResult:
    """Run the LLM reasoning step and return a structured diagnosis."""
    logger.info(
        "Running LLM diagnosis for incident %s (patterns=%s)",
        request.incident.incident_id,
        ", ".join(request.patterns) or "none",
    )

    prompt_text = SYSTEM_PROMPT + "\n\n" + build_user_prompt(
        incident=request.incident,
        log_context=request.log_context,
        patterns=request.patterns,
    )

    try:
        raw_content = await _call_ollama(prompt_text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Ollama call failed for incident %s: %s", request.incident.incident_id, exc)
        # fall back to a very simple heuristic-based diagnosis
        return DiagnosisResult(
            incident_id=request.incident.incident_id,
            root_cause="Unknown – LLM call failed",
            confidence=0.2,
            patterns_detected=request.patterns,
            explanation=(
                "The LLM-based diagnosis step failed. "
                "Inspect the patterns_detected field and raw logs to continue investigation."
            ),
            recommended_action="Check Ollama configuration and review the surrounding logs manually.",
            raw_model_output=None,
        )

    parsed: dict
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.warning(
            "LLM returned non-JSON output for incident %s; attempting to recover",
            request.incident.incident_id,
        )
        # try to extract JSON substring if the model wrapped it in prose
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(raw_content[start : end + 1])
            except Exception:
                parsed = {}
        else:
            parsed = {}

    if not parsed:
        logger.error(
            "Failed to parse LLM output for incident %s, falling back to heuristic default",
            request.incident.incident_id,
        )
        return DiagnosisResult(
            incident_id=request.incident.incident_id,
            root_cause="Unknown",
            confidence=0.3,
            patterns_detected=request.patterns,
            explanation="The model response could not be parsed as JSON.",
            recommended_action="Review the incident logs and patterns_detected manually.",
            raw_model_output={"raw": raw_content},
        )

    # Ensure required fields exist; if missing, populate sensible defaults.
    incident_id = parsed.get("incident_id") or request.incident.incident_id
    root_cause = parsed.get("root_cause") or "Unknown"
    confidence = float(parsed.get("confidence", 0.5))
    patterns_detected = parsed.get("patterns_detected") or request.patterns
    explanation = parsed.get("explanation") or ""
    recommended_action = parsed.get("recommended_action") or ""

    # Clamp confidence into the allowed range
    confidence = max(0.0, min(1.0, confidence))

    return DiagnosisResult(
        incident_id=incident_id,
        root_cause=root_cause,
        confidence=confidence,
        patterns_detected=list(patterns_detected),
        explanation=explanation,
        recommended_action=recommended_action,
        raw_model_output=parsed,
    )


__all__ = ["run_llm_diagnosis"]

