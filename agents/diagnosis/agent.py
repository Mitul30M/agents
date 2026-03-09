from __future__ import annotations

"""Diagnosis Agent implementation.

This module lives inside the ``agents.diagnosis`` package so that the
LangGraph orchestration can import ``agents.diagnosis.agent.DiagnosisAgent``
directly.

Responsibilities:
- Subscribe to the Redis ``incident_stream``.
- For each incoming incident, fetch surrounding log context from the shared
  application log file.
- Run rule-based pattern detection for common failure modes.
- Use an LLM (via an Ollama-hosted open-source model) to reason about the most
  likely root cause.
- Publish a structured diagnosis report to the ``diagnosis_stream``.

The public :meth:`DiagnosisAgent.diagnose` method is also used by the incident
orchestration graph for in-memory diagnosis.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict

import redis
from langgraph.graph import StateGraph, END

from app.config import Config
from .analyzer import detect_patterns
from .log_context import fetch_log_context
from .publisher import DiagnosisPublisher
from .reasoning import run_llm_diagnosis
from .schemas import DiagnosisRequest, DiagnosisResult, IncidentEvent

logger = logging.getLogger(__name__)


class DiagnosisState(TypedDict):
    payload: Dict[str, Any]
    incident: Optional[IncidentEvent]
    log_context: list[str]
    patterns: list[str]
    diagnosis_result: Optional[DiagnosisResult]
    published_entry_id: Optional[str]


class DiagnosisAgent:
    """Root cause analysis agent driven by logs and LLM reasoning."""

    def __init__(
        self,
        redis_url: str | None = None,
        incident_stream: str | None = None,
        diagnosis_stream: str | None = None,
    ) -> None:
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        self._incident_stream = incident_stream or Config.INCIDENT_STREAM
        self._publisher = DiagnosisPublisher(
            redis_url=redis_url, stream=diagnosis_stream
        )
        # last_id tracks the most recent entry ID we've processed from the incident stream
        self._last_id: str = "0-0"
        self._workflow = self._build_diagnosis_graph()

    # -------------------------------------------------------------------------
    # Public API used by orchestration graph
    # -------------------------------------------------------------------------

    async def diagnose(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run diagnosis as a LangGraph node pipeline for one incident payload."""
        initial_state: DiagnosisState = {
            "payload": payload,
            "incident": None,
            "log_context": [],
            "patterns": [],
            "diagnosis_result": None,
            "published_entry_id": None,
        }

        final_state = await self._workflow.ainvoke(initial_state)
        result = final_state.get("diagnosis_result")
        if result is None:
            logger.error("Diagnosis workflow ended without diagnosis_result")
            return {
                "incident_id": str(
                    payload.get("incident_id")
                    or payload.get("id")
                    or "unknown-incident"
                ),
                "root_cause": "Unknown",
                "confidence": 0.2,
                "patterns_detected": [],
                "explanation": "Diagnosis workflow did not produce a result.",
                "recommended_action": "Inspect logs and diagnosis worker runtime.",
            }

        return result.dict(exclude_none=True)

    # -------------------------------------------------------------------------
    # LangGraph node pipeline
    # -------------------------------------------------------------------------

    def _build_diagnosis_graph(self):
        graph = StateGraph(DiagnosisState)
        graph.add_node("normalize_incident", self._normalize_incident_node)
        graph.add_node("fetch_context", self._fetch_context_node)
        graph.add_node("detect_patterns", self._detect_patterns_node)
        graph.add_node("run_reasoning", self._run_reasoning_node)
        graph.add_node("publish", self._publish_result_node)

        graph.set_entry_point("normalize_incident")
        graph.add_edge("normalize_incident", "fetch_context")
        graph.add_edge("fetch_context", "detect_patterns")
        graph.add_edge("detect_patterns", "run_reasoning")
        graph.add_edge("run_reasoning", "publish")
        graph.add_edge("publish", END)

        return graph.compile()

    async def _normalize_incident_node(self, state: DiagnosisState) -> DiagnosisState:
        incident = self._payload_to_incident(state["payload"])
        return {**state, "incident": incident}

    async def _fetch_context_node(self, state: DiagnosisState) -> DiagnosisState:
        incident = state["incident"]
        if incident is None:
            return {**state, "log_context": []}

        context = fetch_log_context(incident.timestamp, window_seconds=30)
        return {**state, "log_context": context}

    async def _detect_patterns_node(self, state: DiagnosisState) -> DiagnosisState:
        patterns = await detect_patterns(state["log_context"])
        return {**state, "patterns": patterns}

    async def _run_reasoning_node(self, state: DiagnosisState) -> DiagnosisState:
        incident = state["incident"]
        if incident is None:
            fallback = DiagnosisResult(
                incident_id="unknown-incident",
                root_cause="Unknown",
                confidence=0.2,
                patterns_detected=state["patterns"],
                explanation="Incident normalization failed.",
                recommended_action="Inspect incident payload schema.",
                raw_model_output=None,
            )
            return {**state, "diagnosis_result": fallback}

        request = DiagnosisRequest(
            incident=incident,
            log_context=state["log_context"],
            patterns=state["patterns"],
        )
        result = await run_llm_diagnosis(request)
        return {**state, "diagnosis_result": result}

    async def _publish_result_node(self, state: DiagnosisState) -> DiagnosisState:
        result = state["diagnosis_result"]
        if result is None:
            return state

        try:
            entry_id = await self._publisher.publish(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "Failed to publish diagnosis for %s: %s", result.incident_id, exc
            )
            entry_id = None

        return {**state, "published_entry_id": entry_id}

    # -------------------------------------------------------------------------
    # Redis streaming loop
    # -------------------------------------------------------------------------

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        """Continuously consume incidents from the Redis stream and diagnose them."""
        logger.info(
            "Starting DiagnosisAgent loop (incident_stream=%s, diagnosis_stream=%s)",
            self._incident_stream,
            Config.DIAGNOSIS_STREAM,
        )

        try:
            while True:
                try:
                    handled = await self._process_new_incidents()
                    if handled == 0:
                        await asyncio.sleep(poll_interval)
                except Exception as exc:
                    logger.exception("Error in diagnosis loop: %s", exc)
                    await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown
            logger.info("DiagnosisAgent loop cancelled; shutting down")

    async def _process_new_incidents(
        self, count: int = 10, block_ms: int = 1000
    ) -> int:
        """Read and process new incidents from the Redis stream."""

        def _read():
            try:
                streams = {self._incident_stream: self._last_id}
                return self._redis.xread(streams, count=count, block=block_ms)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to read from incident stream %s: %s",
                    self._incident_stream,
                    exc,
                )
                return []

        data = await asyncio.to_thread(_read)
        if not data:
            return 0

        handled = 0
        for _stream, messages in data:
            for entry_id, fields in messages:
                self._last_id = (
                    entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                )
                try:
                    payload = self._decode_fields(fields)
                    await self.diagnose(payload)
                    handled += 1
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception(
                        "Failed to process incident entry %s: %s", self._last_id, exc
                    )

        return handled

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _decode_fields(fields: dict[bytes, bytes]) -> Dict[str, Any]:
        """Decode Redis stream fields into a Python dictionary."""
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        if "data" in decoded:
            try:
                return json.loads(decoded["data"])
            except Exception:
                logger.warning(
                    "Failed to parse incident JSON payload; using raw fields"
                )
        return decoded

    @staticmethod
    def _payload_to_incident(payload: Dict[str, Any]) -> IncidentEvent:
        """Normalise an arbitrary incident-like payload into :class:`IncidentEvent`."""
        # If payload already matches the expected schema, construction will succeed.
        if {"incident_id", "timestamp", "service", "log_snippet"} <= payload.keys():
            return IncidentEvent(**payload)

        # Fallback for payloads from orchestration and monitoring flows.
        incident_id = (
            payload.get("incident_id")
            or payload.get("id")
            or payload.get("created_at")
            or f"incident-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        )
        timestamp_raw: Optional[str] = (
            payload.get("timestamp")
            or payload.get("created_at")
            or datetime.utcnow().isoformat()
        )
        service = payload.get("service") or payload.get("source") or "nextjs-app"

        if "log_snippet" in payload:
            log_snippet = str(payload["log_snippet"])
        elif "summary" in payload:
            log_snippet = str(payload["summary"])
        elif "error_groups" in payload:
            groups = payload.get("error_groups") or {}
            try:
                first_group = next(iter(groups.values())) if groups else {}
            except Exception:
                first_group = {}

            if isinstance(first_group, dict):
                sample = first_group.get("sample")
                logs = first_group.get("logs") or []
                if sample is not None:
                    log_snippet = json.dumps(sample, ensure_ascii=True)
                elif logs:
                    log_snippet = json.dumps(logs[0], ensure_ascii=True)
                else:
                    log_snippet = str(first_group)
            else:
                log_snippet = str(first_group)
        elif "logs" in payload:
            # Best-effort: join a few log messages into a single snippet
            try:
                log_snippet = "\n".join(str(l) for l in payload["logs"][:5])
            except Exception:
                log_snippet = "No log snippet available"
        else:
            log_snippet = "No log snippet available"

        return IncidentEvent(
            incident_id=str(incident_id),
            timestamp=timestamp_raw,
            service=str(service),
            log_snippet=log_snippet,
        )
