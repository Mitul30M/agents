from __future__ import annotations

"""Orchestrator supervisor for child agents and incident lifecycle intelligence."""

import asyncio
import contextlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import redis

from app.config import Config
from agents.monitoring.agent import run_monitoring_cycle
from agents.diagnosis.agent import DiagnosisAgent
from agents.remediation.agent import RemediationAgent
from agents.communication.agent import CommunicationAgent
from .state import IncidentLifecycleState, IncidentStateStore

logger = logging.getLogger(__name__)


IncidentActiveStates = {
    IncidentLifecycleState.DETECTED,
    IncidentLifecycleState.DIAGNOSING,
    IncidentLifecycleState.DIAGNOSED,
    IncidentLifecycleState.REMEDIATING,
    IncidentLifecycleState.REMEDIATED,
    IncidentLifecycleState.COMMUNICATING,
    IncidentLifecycleState.RETRYING,
}


@dataclass
class ChildRuntime:
    name: str
    starter: Callable[[], Awaitable[None]]
    task: asyncio.Task[None] | None = None
    restarts: int = 0
    last_heartbeat_ts: float = 0.0
    last_activity_ts: float = 0.0


class OrchestratorLogWatcher:
    """Tail JSON lines from shared orchestrator log file."""

    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)
        self._position: int = 0
        self._inode: tuple[int, int] | None = None

    def _current_inode(self) -> tuple[int, int] | None:
        if not self._path.exists():
            return None
        stat = self._path.stat()
        return (stat.st_dev, stat.st_ino)

    async def initialize(self) -> None:
        def _init() -> None:
            if not self._path.exists():
                return
            self._position = self._path.stat().st_size
            self._inode = self._current_inode()

        await asyncio.to_thread(_init)

    async def poll(self) -> list[dict[str, Any]]:
        def _read_lines() -> list[dict[str, Any]]:
            if not self._path.exists():
                return []

            inode = self._current_inode()
            if inode != self._inode:
                self._position = 0
                self._inode = inode

            entries: list[dict[str, Any]] = []
            with self._path.open("r", encoding="utf-8") as fh:
                fh.seek(self._position)
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        entries.append(payload)
                self._position = fh.tell()
            return entries

        return await asyncio.to_thread(_read_lines)


class OrchestratorAgent:
    """Phase-1/2 supervisor: child liveness + timeline intelligence."""

    _INCIDENT_ID_PATTERNS = (
        re.compile(r"for\s+([A-Za-z0-9_.:-]+)"),
        re.compile(r"incident\s+([A-Za-z0-9_.:-]+)", re.IGNORECASE),
    )

    _AGENT_LOGGER_TO_CHILD = {
        "agents.monitoring.agent": "monitoring",
        "agents.diagnosis.agent": "diagnosis",
        "agents.remediation.agent": "remediation",
        "agents.communication.agent": "communication",
    }

    def __init__(self) -> None:
        self._redis = redis.from_url(Config.REDIS_URL)
        self._state_store = IncidentStateStore()
        self._check_interval = Config.MONITOR_INTERVAL
        self._heartbeat_seconds = Config.ORCH_HEARTBEAT_SECONDS
        self._liveness_timeout_seconds = Config.ORCH_LIVENESS_TIMEOUT_SECONDS
        self._incident_timeout_seconds = Config.ORCH_INCIDENT_STAGE_TIMEOUT_SECONDS
        self._max_restarts = Config.ORCH_MAX_CHILD_RESTARTS
        self._max_incident_retries = Config.ORCH_MAX_INCIDENT_RETRIES

        # XREAD cursor per stream. "$" means only events after orchestrator startup.
        self._stream_offsets: dict[str, str] = {
            Config.INCIDENT_STREAM: "$",
            Config.DIAGNOSIS_STREAM: "$",
            Config.REMEDIATION_STREAM: "$",
        }

        self._log_watcher = OrchestratorLogWatcher(Config.ORCH_LOG_FILE_PATH)
        self._children: dict[str, ChildRuntime] = {
            "monitoring": ChildRuntime("monitoring", self._run_monitoring_loop),
            "diagnosis": ChildRuntime("diagnosis", self._run_diagnosis_loop),
            "remediation": ChildRuntime("remediation", self._run_remediation_loop),
            "communication": ChildRuntime(
                "communication", self._run_communication_loop
            ),
        }
        self._instance_started_at = datetime.now(timezone.utc).isoformat()

    async def run_forever(self) -> None:
        logger.info("Starting OrchestratorAgent supervisor")
        await self._log_watcher.initialize()

        for runtime in self._children.values():
            await self._start_child(runtime, reason="initial_start")

        try:
            while True:
                await self._heartbeat_cycle()
                await asyncio.sleep(self._heartbeat_seconds)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown path
            logger.info("OrchestratorAgent loop cancelled; shutting down")
            raise
        finally:
            await self._shutdown_children()

    async def _run_monitoring_loop(self) -> None:
        while True:
            await run_monitoring_cycle()
            await asyncio.sleep(self._check_interval)

    async def _run_diagnosis_loop(self) -> None:
        await DiagnosisAgent().run_forever()

    async def _run_remediation_loop(self) -> None:
        await RemediationAgent().run_forever()

    async def _run_communication_loop(self) -> None:
        await CommunicationAgent().run_forever()

    async def _start_child(self, runtime: ChildRuntime, reason: str) -> None:
        logger.info("[Orchestrator] Starting child '%s' (%s)", runtime.name, reason)
        runtime.task = asyncio.create_task(runtime.starter(), name=f"child:{runtime.name}")
        now = asyncio.get_running_loop().time()
        runtime.last_heartbeat_ts = now
        runtime.last_activity_ts = now

    async def _shutdown_children(self) -> None:
        for runtime in self._children.values():
            if runtime.task and not runtime.task.done():
                runtime.task.cancel()

        for runtime in self._children.values():
            if runtime.task:
                with contextlib.suppress(asyncio.CancelledError):
                    await runtime.task

    async def _restart_child(self, runtime: ChildRuntime, reason: str) -> None:
        if runtime.restarts >= self._max_restarts:
            logger.error(
                "[Orchestrator] Child '%s' exceeded restart budget (%d)",
                runtime.name,
                self._max_restarts,
            )
            return

        runtime.restarts += 1
        logger.warning(
            "[Orchestrator] Restarting child '%s' (%s). restart=%d/%d",
            runtime.name,
            reason,
            runtime.restarts,
            self._max_restarts,
        )

        if runtime.task and not runtime.task.done():
            runtime.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runtime.task

        await self._start_child(runtime, reason=reason)

    async def _heartbeat_cycle(self) -> None:
        await self._ingest_stream_events()
        await self._ingest_log_events()
        await self._supervise_children()
        await self._apply_incident_timeout_policy()
        await self._publish_runtime_snapshot()

    def _child_status_snapshot(self) -> dict[str, dict[str, Any]]:
        now = asyncio.get_running_loop().time()
        snapshot: dict[str, dict[str, Any]] = {}

        for name, runtime in self._children.items():
            task_state = "missing"
            last_error: str | None = None

            if runtime.task is not None:
                if runtime.task.cancelled():
                    task_state = "cancelled"
                elif runtime.task.done():
                    task_state = "done"
                    with contextlib.suppress(Exception):
                        exc = runtime.task.exception()
                        if exc is not None:
                            last_error = str(exc)
                else:
                    task_state = "running"

            snapshot[name] = {
                "task_state": task_state,
                "restarts": runtime.restarts,
                "seconds_since_last_heartbeat": round(
                    max(0.0, now - runtime.last_heartbeat_ts), 3
                ),
                "seconds_since_last_activity": round(
                    max(0.0, now - runtime.last_activity_ts), 3
                ),
                "liveness_timeout_seconds": self._liveness_timeout_seconds,
                "last_error": last_error,
            }

        return snapshot

    async def _publish_runtime_snapshot(self) -> None:
        status_payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "instance_started_at": self._instance_started_at,
            "heartbeat_seconds": self._heartbeat_seconds,
            "incident_timeout_seconds": self._incident_timeout_seconds,
            "max_incident_retries": self._max_incident_retries,
            "children": self._child_status_snapshot(),
        }
        timelines_payload = self.get_timeline_snapshot()

        def _write() -> None:
            self._redis.set(Config.ORCH_STATUS_KEY, json.dumps(status_payload))
            self._redis.set(Config.ORCH_TIMELINE_KEY, json.dumps(timelines_payload))

        try:
            await asyncio.to_thread(_write)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[Orchestrator] Failed to publish runtime snapshot: %s", exc)

    async def _supervise_children(self) -> None:
        now = asyncio.get_running_loop().time()

        for runtime in self._children.values():
            task = runtime.task
            if task is None:
                await self._start_child(runtime, reason="missing_task")
                continue

            if task.done():
                err = None
                with contextlib.suppress(Exception):
                    err = task.exception()
                reason = "task_exception" if err else "task_completed"
                await self._restart_child(runtime, reason=reason)
                continue

            # Heartbeat model: a running task is healthy, even if idle.
            runtime.last_heartbeat_ts = now

    async def _ingest_stream_events(self) -> None:
        streams = {
            Config.INCIDENT_STREAM: self._stream_offsets[Config.INCIDENT_STREAM],
            Config.DIAGNOSIS_STREAM: self._stream_offsets[Config.DIAGNOSIS_STREAM],
            Config.REMEDIATION_STREAM: self._stream_offsets[Config.REMEDIATION_STREAM],
        }

        def _read() -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
            try:
                return self._redis.xread(streams=streams, count=100, block=1)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("[Orchestrator] Stream read failed: %s", exc)
                return []

        batches = await asyncio.to_thread(_read)
        if not batches:
            return

        for stream_name_raw, events in batches:
            stream_name = (
                stream_name_raw.decode()
                if isinstance(stream_name_raw, bytes)
                else str(stream_name_raw)
            )
            for entry_id_raw, fields in events:
                entry_id = (
                    entry_id_raw.decode()
                    if isinstance(entry_id_raw, bytes)
                    else str(entry_id_raw)
                )
                self._stream_offsets[stream_name] = entry_id
                payload = self._decode_stream_fields(fields)
                await self._correlate_stream_event(stream_name, entry_id, payload)

    @staticmethod
    def _decode_stream_fields(fields: dict[bytes, bytes]) -> dict[str, Any]:
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        data = decoded.get("data")
        if data:
            with contextlib.suppress(Exception):
                return json.loads(data)
        return decoded

    async def _correlate_stream_event(
        self,
        stream_name: str,
        entry_id: str,
        payload: dict[str, Any],
    ) -> None:
        incident_id = self._extract_incident_id(payload)
        if not incident_id:
            return

        self._state_store.add_event(
            incident_id,
            source=stream_name,
            event_type="stream_event",
            message=f"Stream event received from {stream_name}",
            metadata={"entry_id": entry_id, "payload": payload},
        )

        if stream_name == Config.INCIDENT_STREAM:
            self._touch_child("monitoring")
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.DETECTED,
                source=stream_name,
                reason="incident_published",
            )
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.DIAGNOSING,
                source=stream_name,
                reason="queued_for_diagnosis",
            )
            return

        if stream_name == Config.DIAGNOSIS_STREAM:
            self._touch_child("diagnosis")
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.DIAGNOSED,
                source=stream_name,
                reason="diagnosis_published",
            )
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.REMEDIATING,
                source=stream_name,
                reason="queued_for_remediation",
            )
            return

        if stream_name == Config.REMEDIATION_STREAM:
            self._touch_child("remediation")
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.REMEDIATED,
                source=stream_name,
                reason="remediation_published",
            )
            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.COMMUNICATING,
                source=stream_name,
                reason="queued_for_communication",
            )

    async def _ingest_log_events(self) -> None:
        entries = await self._log_watcher.poll()
        if not entries:
            return

        for entry in entries:
            logger_name = str(entry.get("name") or "")
            message = str(entry.get("message") or "")

            child_name = self._AGENT_LOGGER_TO_CHILD.get(logger_name)
            if child_name:
                self._touch_child(child_name)

            incident_id = self._extract_incident_id(entry)
            if not incident_id:
                continue

            self._state_store.add_event(
                incident_id,
                source="orchestrator.log",
                event_type="log_event",
                message=message,
                metadata={"logger": logger_name},
            )

            if "Published diagnosis" in message:
                self._state_store.transition(
                    incident_id,
                    IncidentLifecycleState.DIAGNOSED,
                    source="orchestrator.log",
                    reason="diagnosis_log_marker",
                )
            elif "Published remediation" in message:
                self._state_store.transition(
                    incident_id,
                    IncidentLifecycleState.REMEDIATED,
                    source="orchestrator.log",
                    reason="remediation_log_marker",
                )
            elif "Preparing incident report" in message:
                self._state_store.transition(
                    incident_id,
                    IncidentLifecycleState.COMMUNICATING,
                    source="orchestrator.log",
                    reason="communication_started",
                )
            elif "Incident notification sent" in message:
                self._state_store.transition(
                    incident_id,
                    IncidentLifecycleState.RESOLVED,
                    source="orchestrator.log",
                    reason="communication_completed",
                )

    def _touch_child(self, name: str) -> None:
        runtime = self._children.get(name)
        if runtime:
            runtime.last_activity_ts = asyncio.get_running_loop().time()

    def _extract_incident_id(self, payload: dict[str, Any]) -> str | None:
        if "incident_id" in payload and payload["incident_id"]:
            return str(payload["incident_id"])
        if "id" in payload and payload["id"]:
            return str(payload["id"])

        message = str(payload.get("message") or "")
        for pattern in self._INCIDENT_ID_PATTERNS:
            match = pattern.search(message)
            if match:
                return match.group(1)
        return None

    async def _apply_incident_timeout_policy(self) -> None:
        stale = self._state_store.stale_incidents(
            timeout_seconds=self._incident_timeout_seconds,
            active_states=IncidentActiveStates,
        )
        for timeline in stale:
            incident_id = timeline.incident_id
            current_state = timeline.current_state
            reason = (
                f"state {current_state.value} exceeded "
                f"{self._incident_timeout_seconds:.0f}s timeout"
            )

            retries = self._state_store.increment_retry(
                incident_id,
                source="orchestrator",
                reason=reason,
            )

            if retries > self._max_incident_retries:
                self._state_store.transition(
                    incident_id,
                    IncidentLifecycleState.ESCALATED,
                    source="orchestrator",
                    reason="retry_budget_exceeded",
                )
                logger.error(
                    "[Orchestrator] Escalated incident %s after %d retries",
                    incident_id,
                    retries,
                )
                continue

            self._state_store.transition(
                incident_id,
                IncidentLifecycleState.RETRYING,
                source="orchestrator",
                reason=reason,
            )

            target_child = self._target_child_for_state(current_state)
            if target_child:
                await self._restart_child(
                    self._children[target_child],
                    reason=f"incident_retry:{incident_id}",
                )

            self._state_store.transition(
                incident_id,
                current_state,
                source="orchestrator",
                reason="retry_requeued",
            )

    @staticmethod
    def _target_child_for_state(state: IncidentLifecycleState) -> str | None:
        if state in {IncidentLifecycleState.DETECTED, IncidentLifecycleState.DIAGNOSING}:
            return "diagnosis"
        if state in {IncidentLifecycleState.DIAGNOSED, IncidentLifecycleState.REMEDIATING}:
            return "remediation"
        if state in {
            IncidentLifecycleState.REMEDIATED,
            IncidentLifecycleState.COMMUNICATING,
        }:
            return "communication"
        return None

    def get_timeline_snapshot(self) -> dict[str, dict[str, Any]]:
        """Expose in-memory timeline state for diagnostics/tests."""
        return self._state_store.get_snapshot()


def resolve_orchestrator_log_path() -> str:
    configured = Config.ORCH_LOG_FILE_PATH
    if configured:
        return configured

    log_dir = Path(Config.LOG_DIR)
    candidate = log_dir / "orchestrator.log"
    return os.fspath(candidate)
