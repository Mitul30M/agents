# Monitoring Agent Implementation (LangGraph)

## Overview

The Monitoring Agent runs a periodic anomaly-detection workflow over application logs and publishes incidents to Redis when the anomaly score passes a decision threshold.

Current entrypoints:

- `app.worker.main()` calls `run_monitoring_cycle()` every `MONITOR_INTERVAL` seconds.
- `GET /monitor/run` in `app/main.py` triggers one cycle on demand.

Implementation file:

- `agents/agents/monitoring/agent.py`

## State Model

The graph uses `MonitoringState`:

```python
class MonitoringState(TypedDict):
    raw_logs: list
    error_logs: list
    grouped_errors: Dict[str, Any]
    stats: Dict[str, Any]
    anomaly_score: float
    severity: str
    reasoning: str
    incident: Optional[Dict[str, Any]]
```

## Graph Topology

Execution order:

`ingest -> filter -> aggregate -> classify -> decide -> END`

Graph is built via `StateGraph` and executed asynchronously with `workflow.ainvoke(initial_state)`.

## Node Behavior

### 1. `ingest_logs_node`

- Reads up to 500 log entries via `LogReader.read_logs(limit=500)`.
- Stores them in `state["raw_logs"]`.

### 2. `filter_errors_node`

- Keeps only entries where `level.lower() == "error"`.
- Stores them in `state["error_logs"]`.

### 3. `aggregate_errors_node`

- Groups by a stable signature of the full error object:
  - `json.dumps(error, sort_keys=True, separators=(",", ":"))`
- This avoids depending only on `message` and preserves the complete payload.

Each group stores:

- `count`
- `first_seen`
- `last_seen`
- `sample` (full error object)
- `logs` (all matching full error objects)

Also computes:

- `total_errors`
- `distinct_groups`

### 4. `classify_anomaly_node`

Deterministic gate before LLM:

- If `total_errors <= 10` and `distinct_groups <= 5`:
  - `anomaly_score = 0.0`
  - `severity = "LOW"`
  - no LLM call.

Otherwise:

- Builds a compact summary from grouped samples.
- Calls `ChatOllama(...).with_structured_output(AnomalyClassification)`.
- Expects:
  - `severity`
  - `anomaly_score` in `[0, 1]`
  - `reasoning`
- Logs `severity` and `anomaly_score`.

### 5. `decision_node`

Incident threshold:

- If `anomaly_score < 0.5`: no incident.
- If `anomaly_score >= 0.5`: create and publish incident.

Published incident includes:

- `created_at`
- `source = "monitoring"`
- `type = "anomaly_detection"`
- `severity`
- `anomaly_score`
- `reasoning`
- `error_groups` (full grouped payloads)

Publish target:

- Redis stream `Config.INCIDENT_STREAM` via `RedisStreamHandler.publish_incident()`.

## Log Source Behavior (`tools/log_reader.py`)

Monitoring ingestion now reads application logs with safety filters:

- Filesystem source: `LOG_DIR/app-*.log`
- Excludes orchestrator/self logs by logger name prefix:
  - `agents.`
  - `app.`
  - `tools.`
  - `__main__`
  - `httpx`
- Redis fallback: if no filesystem logs are found, reads from `REDIS_LOG_STREAM` and applies the same filter.

## Returned Cycle Result

`run_monitoring_cycle()` returns:

```json
{
  "anomaly_score": 0.0,
  "severity": "LOW",
  "incident_created": false
}
```

## Environment Variables

Key runtime config from `app/config.py`:

- `MONITOR_INTERVAL` (default `10`)
- `MONITORING_AGENT_LLM` (default `llama3.2:latest`)
- `OLLAMA_BASE_URL` (default `http://host.docker.internal:11434`)
- `REDIS_URL` (default `redis://localhost:6379`)
- `INCIDENT_STREAM` (default from `REDIS_CHANNEL`, fallback `incident_stream`)
- `LOG_DIR` (default `logs`)
- `REDIS_LOG_STREAM` (default `app-logs`)

## Operational Notes

- Large error volume does not guarantee incident creation; the final decision depends on `anomaly_score >= 0.5`.
- If Ollama/model connectivity fails during classification, the cycle currently raises and is caught by `app/worker.py`, which logs `error during monitoring cycle` and continues next cycle.

---

**Version:** 2.0  
**Date:** 2026-03-09  
**Status:** Active Implementation
