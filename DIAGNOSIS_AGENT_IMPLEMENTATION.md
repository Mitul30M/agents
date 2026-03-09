# Diagnosis Agent Implementation (LangGraph + Redis + Ollama)

## Overview

The Diagnosis Agent performs root-cause analysis for incidents from Redis and publishes structured diagnosis results.

It supports two modes:

1. Streaming mode: `run_forever()` continuously consumes incidents from Redis.
2. Direct mode: `diagnose(payload)` runs the full diagnosis graph for one payload.

Primary implementation file:

- `agents/agents/diagnosis/agent.py`

## State Model

Diagnosis graph state (`DiagnosisState`):

```python
class DiagnosisState(TypedDict):
    payload: Dict[str, Any]
    incident: Optional[IncidentEvent]
    log_context: list[str]
    patterns: list[str]
    diagnosis_result: Optional[DiagnosisResult]
    published_entry_id: Optional[str]
```

## Graph Topology

Node flow:

`normalize_incident -> fetch_context -> detect_patterns -> run_reasoning -> publish -> END`

Constructed in `_build_diagnosis_graph()` and invoked via `self._workflow.ainvoke(initial_state)`.

## Node Behavior

### 1. `normalize_incident`

Uses `_payload_to_incident(payload)` to normalize flexible producer payloads into `IncidentEvent`.

Supported payload patterns:

- Canonical fields:
  - `incident_id`, `timestamp`, `service`, `log_snippet`
- Monitoring-style fields:
  - `created_at`, `source`, `error_groups`
- Orchestration fallback fields:
  - `id`, `summary`, `logs`

For monitoring payloads with `error_groups`, it derives `log_snippet` from group `sample` (or first `logs` item).

### 2. `fetch_context`

Calls `fetch_log_context(incident.timestamp, window_seconds=30)`.

Log context source behavior (`agents/agents/diagnosis/log_context.py`):

- Uses `APP_LOG_PATH` if present.
- Else falls back to `LOG_DIR` with:
  - `app.log` (if present)
  - recent `app-*.log` files (up to 3 newest)
- Extracts timestamps from JSON fields `timestamp`, `time`, `ts`, or first token fallback.
- Returns lines within `+-30s` window.

### 3. `detect_patterns`

Calls `detect_patterns(log_context)` from `agents/agents/diagnosis/analyzer.py`.

Pattern detection strategy:

- Primary path: LLM structured output with:
  - `ChatOllama(..., format="json")`
  - `with_structured_output(PatternAnalysis)`
- On parser/LLM failure: heuristic fallback over text for patterns like:
  - `timeout`
  - `connection_refused`
  - `connection_attempts_failed`
  - `http_503/http_502/http_500`
  - `ollama_error`
  - `rate_limit_exceeded`
  - `memory_error`
  - dotted error signatures converted to underscore format

### 4. `run_reasoning`

Builds `DiagnosisRequest(incident, log_context, patterns)` and calls `run_llm_diagnosis()`.

Reasoning layer (`agents/agents/diagnosis/reasoning.py`) provides:

- Prompted JSON-only diagnosis output.
- Parse recovery attempts for partially wrapped JSON.
- Safe fallback result on LLM failure or invalid output.

### 5. `publish`

Publishes `DiagnosisResult` to `Config.DIAGNOSIS_STREAM` using `DiagnosisPublisher.publish()`.

On publish failure, logs exception and continues.

## Streaming Loop Behavior

`run_forever(poll_interval=2.0)`:

- Reads new entries with Redis `XREAD` from `Config.INCIDENT_STREAM` using `self._last_id` cursor.
- Decodes stream payload (`data` JSON if present).
- Calls `await diagnose(payload)` per incident.
- Updates `self._last_id` to avoid reprocessing.
- Sleeps when no messages are available.

## Redis Streams

- Input stream: `INCIDENT_STREAM`
- Output stream: `DIAGNOSIS_STREAM`
- Payload convention: single field `data` containing JSON string.

## Config Keys (Current)

From `app/config.py`:

- `REDIS_URL` (default `redis://localhost:6379`)
- `INCIDENT_STREAM` (default from `REDIS_CHANNEL`, fallback `incident_stream`)
- `DIAGNOSIS_STREAM` (default `diagnosis_stream`)
- `APP_LOG_PATH` (default `/app/logs/app.log`)
- `LOG_DIR` (default `logs`)
- `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`)
- `DIAGNOSIS_AGENT_LLM` (default `qwen3-coder:480b-cloud`)

## Integration Points

- `app/worker.py` starts `DiagnosisAgent.run_forever()` in background.
- `app/main.py` exposes `/diagnosis` for recent diagnosis stream entries.
- Monitoring publishes incidents consumed by diagnosis.

## Reliability Notes

- Missing or unreadable logs produce empty context but do not stop diagnosis.
- Redis read/publish failures are handled defensively with retries on next loop.
- Non-JSON LLM output in pattern detection falls back to heuristics.
- Reasoning step has additional fallback outputs for LLM/parsing failures.

---

**Version:** 2.0  
**Date:** 2026-03-09  
**Status:** Active Implementation
