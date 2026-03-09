# Diagnosis Agent Implementation (Redis + Ollama)

## Overview

The Diagnosis Agent is responsible for **root cause analysis** of incidents detected by the Monitoring Agent or other producers. It:

- Subscribes to a Redis **incident stream**.
- Fetches **surrounding log context** from the shared application log file.
- Runs **rule-based pattern detection** for common production failures.
- Uses an **Ollama-hosted open-source LLM** for reasoning.
- Produces a **structured diagnosis report** and publishes it to a Redis **diagnosis stream**.

It can be used in two ways:

1. **Streaming mode** (continuous): `DiagnosisAgent.run_forever()` consumes from Redis, diagnoses incidents, and publishes results.
2. **In-memory mode** (per-incident): `DiagnosisAgent.diagnose(payload)` is called directly by the LangGraph incident orchestration (`graphs/incident_orchestration.py`).

---

## Architecture

### 1. Data Schemas (Pydantic)

Defined in `agents/diagnosis/schemas.py`:

```python
class IncidentEvent(BaseModel):
    incident_id: str
    timestamp: datetime      # ISO8601, with or without trailing "Z"
    service: str             # e.g. "nextjs-app"
    log_snippet: str         # key log message related to the incident


class DiagnosisRequest(BaseModel):
    incident: IncidentEvent
    log_context: list[str]   # raw log lines around the incident time
    patterns: list[str]      # rule-based patterns detected


class DiagnosisResult(BaseModel):
    incident_id: str
    root_cause: str
    confidence: float        # 0.0–1.0
    patterns_detected: list[str]
    explanation: str
    recommended_action: str
    raw_model_output: dict | None  # optional raw JSON from LLM
```

These ensure a consistent contract between:

- Redis event payloads
- Pattern detection
- LLM reasoning
- Published diagnosis reports

---

### 2. Main Agent Class

Implemented in `agents/diagnosis/agent.py`:

```python
class DiagnosisAgent:
    def __init__(self, redis_url: str | None = None,
                 incident_stream: str | None = None,
                 diagnosis_stream: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        self._incident_stream = incident_stream or Config.INCIDENT_STREAM
        self._publisher = DiagnosisPublisher(redis_url=redis_url,
                                             stream=diagnosis_stream)
        self._last_id: str = "0-0"  # last processed Redis stream ID
```

Two key methods:

- **`diagnose(payload: dict) -> dict`**  
  Runs the full diagnosis pipeline for a single payload (used by LangGraph).

- **`run_forever(poll_interval: float = 2.0)`**  
  Background loop that continuously reads from Redis, calls `diagnose`, and publishes results.

---

## Pipeline Steps

### Step 1 – Ingest Incident Payload

Entry point: `DiagnosisAgent.diagnose(payload: dict)`.

The agent first normalises the incoming payload into an `IncidentEvent`:

- If the payload already has:
  - `incident_id`, `timestamp`, `service`, `log_snippet` → used directly.
- Otherwise (e.g. from `IncidentState` graph):
  - `incident_id` falls back to `id` or `"unknown-incident"`.
  - `timestamp` defaults to `datetime.utcnow().isoformat()` if missing.
  - `service` defaults to `"nextjs-app"`.
  - `log_snippet` is derived from:
    - `log_snippet` field if present, else
    - `summary` field if present, else
    - First few `logs` entries joined as a snippet, else
    - `"No log snippet available"`.

This makes `diagnose()` robust to different producers and use cases.

---

### Step 2 – Fetch Log Context (±30s)

Implemented in `agents/diagnosis/log_context.py` via `fetch_log_context()`:

- Reads the application log file at `Config.APP_LOG_PATH` (default `/logs/app.log`).
- Parses each line, attempting to extract a timestamp:
  - If line is JSON, looks for `timestamp`, `time`, or `ts`.
  - If not JSON, interprets the first whitespace-separated token as a timestamp.
- Collects all lines where the log timestamp is within ±30 seconds of the incident timestamp.
- Returns a list of raw log lines (strings). If the log file is missing or unreadable, returns an empty list and logs a warning.

This gives the LLM a focused window of context around the incident.

---

### Step 3 – Rule-Based Pattern Detection

Implemented in `agents/diagnosis/analyzer.py` via `detect_patterns(log_lines)`:

- Lowercases and concatenates all context lines.
- Searches for keyword patterns grouped under higher-level labels:
  - **`database_timeout`**:
    - `"connection timeout"`, `"timeout exceeded"`, `"database timeout"`, `"timed out after"`.
  - **`api_upstream_failure`**:
    - `"503 upstream error"`, `"upstream connect error"`, `"bad gateway"`, `"gateway timeout"`.
  - **`memory_error`**:
    - `"heap out of memory"`, `"javascript heap out of memory"`, `"out of memory"`, `"memory leak detected"`.
  - **`dependency_crash`**:
    - `"service unavailable"`, `"process exited with code"`, `"service crashed"`, `"dependency crash"`.
  - **`connection_refused`**:
    - `"econnrefused"`, `"connection refused"`.

Output: list of detected pattern IDs, e.g.:

```json
["database_timeout", "connection_refused"]
```

These are passed to the LLM as hints and also surface in the final report.

---

### Step 4 – LLM Root Cause Reasoning (Ollama)

Implemented in `agents/diagnosis/reasoning.py`.

1. **Prompt Construction**

   - `SYSTEM_PROMPT` (in `prompts.py`) describes the agent as a senior SRE and enforces a strict JSON-only response schema.
   - `build_user_prompt(...)` injects:
     - `incident_id`, `service`, `timestamp`
     - `log_snippet`
     - `patterns_detected` list
     - Full log window (±30s)

   Combined into a single `prompt_text`:

   ```python
   prompt_text = SYSTEM_PROMPT + "\n\n" + build_user_prompt(...)
   ```

2. **Ollama Call**

   - Uses `langchain_ollama.ChatOllama`:

   ```python
   llm = ChatOllama(
       model=Config.DIAGNOSIS_AGENT_LLM,
       temperature=0.2,
       base_url=Config.OLLAMA_BASE_URL,
   )
   response = llm.invoke(prompt_text)
   ```

   - Executed via `asyncio.to_thread` so the main event loop is not blocked.

3. **JSON Parsing & Recovery**

   - Expects the model to return a JSON object matching:

     ```json
     {
       "incident_id": "string",
       "root_cause": "string",
       "confidence": 0.0,
       "patterns_detected": [],
       "explanation": "string",
       "recommended_action": "string"
     }
     ```

   - If parsing fails:
     - Attempts to extract the substring between the first `{` and last `}` and parse again.
     - If still unsuccessful, falls back to a safe default `DiagnosisResult` with `"Unknown"` root cause and `confidence` ≈ 0.3, preserving the raw text in `raw_model_output`.

4. **Fallback on LLM Failure**

   - If the Ollama call raises an exception (unreachable, model missing, etc.):
     - Returns a `DiagnosisResult` with:
       - `root_cause = "Unknown – LLM call failed"`
       - Low `confidence` (0.2)
       - `patterns_detected` from the heuristic detector
       - Clear explanation and recommended action to check Ollama configuration.

---

### Step 5 – Publish Diagnosis to Redis

Implemented in `agents/diagnosis/publisher.py`.

```python
class DiagnosisPublisher:
    def __init__(self, redis_url: str | None = None, stream: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        self._stream = stream or Config.DIAGNOSIS_STREAM

    async def publish(self, diagnosis: DiagnosisResult) -> str:
        payload = {"data": json.dumps(diagnosis.dict(exclude_none=True))}
        entry_id = self._redis.xadd(self._stream, payload)
        ...
```

- Writes to the configured **diagnosis stream** (default: `diagnosis_stream`).
- Uses the same `"data": "<json>"` convention as the Monitoring Agent’s incident publishing.
- Any Redis errors are logged, but do not crash the agent.

Downstream consumers (API, dashboards, other agents) can read from `Config.DIAGNOSIS_STREAM` and parse the JSON.

---

## Streaming Loop: `run_forever`

`DiagnosisAgent.run_forever()` performs continuous background processing:

1. Uses Redis `XREAD` to read from `Config.INCIDENT_STREAM` starting at `self._last_id`.
2. For each new entry:
   - Decodes fields; if a `data` field exists, tries to parse it as JSON.
   - Calls `diagnose(payload)` to run the full analysis pipeline.
   - Increments `self._last_id` to the latest processed entry ID.
3. When no new entries are available, sleeps for `poll_interval` seconds and tries again.
4. Handles exceptions gracefully (logging and retry loop).

The worker wiring in `app/worker.py` starts this loop alongside monitoring:

- Monitoring cycles run on a fixed interval (`MONITOR_INTERVAL`).
- Diagnosis loop runs continuously, reacting to newly published incidents.

---

## Integration Points

### 1. With Monitoring Agent

- Monitoring Agent publishes anomalies to a Redis stream (configured via `Config.INCIDENT_STREAM` / `REDIS_CHANNEL`).
- Diagnosis Agent subscribes to the same stream and enriches those incidents with root-cause insights and recommended actions.

### 2. With Incident Orchestration Graph

In `graphs/incident_orchestration.py`:

```python
from agents.diagnosis.agent import DiagnosisAgent

agent = DiagnosisAgent()
diagnosis = await agent.diagnose({
    "summary": state["error_message"],
    "logs": state["logs"],
})
state["diagnosis"] = diagnosis
```

Here the agent is used in **in-memory mode**, without going through Redis streams. The same internal pipeline is shared between both modes.

### 3. API Exposure

The FastAPI app exposes diagnosis results via:

- `/diagnosis` – reads recent entries from `Config.DIAGNOSIS_STREAM` using the shared `RedisStreamHandler` helper.

---

## Configuration

### Environment Variables

Key values used by the Diagnosis Agent:

| Variable               | Default                         | Purpose                                      |
|------------------------|---------------------------------|----------------------------------------------|
| `REDIS_URL`            | `redis://localhost:6379`       | Redis connection URL                         |
| `INCIDENT_STREAM`      | `incident_stream` or `REDIS_CHANNEL` | Stream with incident events            |
| `DIAGNOSIS_STREAM`     | `diagnosis_stream`             | Stream for diagnosis reports                 |
| `APP_LOG_PATH`         | `/logs/app.log`                | Path to Next.js/Winston app log file         |
| `OLLAMA_BASE_URL`      | `http://localhost:11434`       | Ollama HTTP endpoint                         |
| `DIAGNOSIS_AGENT_LLM`  | `gpt-oss:120b-cloud`           | Ollama model name for diagnosis              |

These are demonstrated in `.env.example`.

### Ollama Setup

The Diagnosis Agent assumes an Ollama server is reachable:

```bash
ollama serve
ollama pull gpt-oss:120b-cloud   # or your chosen model
```

Then set:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434
DIAGNOSIS_AGENT_LLM=gpt-oss:120b-cloud
```

---

## Error Handling & Robustness

1. **Missing Logs**
   - If `APP_LOG_PATH` does not exist, `fetch_log_context` returns an empty list and logs a warning. The pipeline still runs, but with no context lines.

2. **Redis Failures**
   - Read and publish operations catch exceptions, log them, and continue retrying (no hard crash).

3. **LLM Failures**
   - If Ollama is unreachable or errors, the agent returns a low-confidence diagnosis with `"Unknown – LLM call failed"` and instructions to check configuration.

4. **Non-JSON LLM Output**
   - Attempts to recover a JSON substring.
   - Falls back to a safe default `DiagnosisResult` when parsing fails.

5. **Schema Flexibility**
   - `IncidentEvent` accepts extra fields without failing.
   - Input payloads without full schema are normalised via `_payload_to_incident`.

---

## Example Flow

1. Monitoring Agent detects an anomaly and **publishes** an event to `incident_stream`.
2. Diagnosis Agent’s `run_forever` loop:
   - Reads the new incident.
   - Normalises it into `IncidentEvent`.
   - Fetches ±30s of surrounding logs from `/logs/app.log`.
   - Runs pattern detection (e.g. `database_timeout`, `api_upstream_failure`).
   - Calls the Ollama LLM for root cause reasoning.
   - Produces a `DiagnosisResult` with `root_cause`, `confidence`, `explanation`, and `recommended_action`.
   - Publishes the result to `diagnosis_stream`.
3. API / UI / downstream agents:
   - Read from `diagnosis_stream`.
   - Use the structured JSON to drive remediation and communication flows.

---

## Implementation Files

| File                               | Role                                            |
|------------------------------------|-------------------------------------------------|
| `agents/diagnosis/agent.py`        | Main DiagnosisAgent class and Redis loop        |
| `agents/diagnosis/schemas.py`      | Pydantic models for events and results          |
| `agents/diagnosis/log_context.py`  | Log window extraction around incident timestamp  |
| `agents/diagnosis/analyzer.py`     | Rule-based failure pattern detection            |
| `agents/diagnosis/prompts.py`      | System + user prompts for the LLM               |
| `agents/diagnosis/reasoning.py`    | Ollama integration + JSON parsing               |
| `agents/diagnosis/publisher.py`    | Redis stream publisher for diagnosis reports    |
| `app/worker.py`                    | Starts `DiagnosisAgent.run_forever()`           |
| `app/main.py`                      | Exposes `/diagnosis` endpoint                   |

---

**Version:** 1.0  
**Date:** 2026-03-08  
**Status:** Research-Grade Implementation

