# LangGraph-Based Monitoring Agent Implementation

## Overview

This document describes the research-grade Monitoring Agent built using **LangGraph** for the AI-based Incident Orchestration system. The agent implements hybrid deterministic error aggregation with LLM-based anomaly classification.

## Architecture

### State Schema (TypedDict)

The monitoring workflow uses a `MonitoringState` TypedDict that flows through the graph:

```python
class MonitoringState(TypedDict):
    raw_logs: list[dict[str, Any]]           # Ingested logs
    error_logs: list[dict[str, Any]]         # Filtered error logs
    grouped_errors: dict[str, dict]          # Aggregated errors with counts
    anomaly_score: float                     # LLM-derived score (0-1)
    severity: str                            # LOW, MEDIUM, HIGH
    anomaly_reasoning: str                   # LLM reasoning
    incident: Optional[dict[str, Any]]       # Final incident (if created)
    monitoring_id: str                       # Unique cycle identifier
    timestamp: str                           # ISO timestamp
```

### Graph Nodes

The workflow consists of **5 nodes**:

#### 1. **ingest_logs_node**
- **Input:** Empty state
- **Action:** Reads recent logs using `LogReader.read_logs(limit=1000)`
- **Output:** Populates `state["raw_logs"]`
- **Purpose:** Data ingestion from application log files

#### 2. **filter_errors_node**
- **Input:** `raw_logs`
- **Action:** Filters logs where `level == "ERROR"`
- **Output:** Populates `state["error_logs"]`
- **Purpose:** Extract only error-level entries for analysis

#### 3. **aggregate_errors_node**
- **Input:** `error_logs`
- **Action:** Groups errors by message signature (first 100 chars) and counts frequency
- **Output:** Populates `state["grouped_errors"]` with structure:
  ```python
  {
    "signature": str,
    "count": int,
    "first_seen": str,
    "last_seen": str,
    "sample_entries": list[dict]
  }
  ```
- **Purpose:** Deterministic aggregation and spike detection

#### 4. **classify_anomaly_node**
- **Input:** `grouped_errors`
- **Threshold:** Only runs LLM if errors exceed threshold:
  - **More than 5 distinct error groups**, OR
  - **More than 10 total occurrences**
- **Action:** Calls Ollama LLM with structured output (Pydantic model)
  - Classifies severity (LOW, MEDIUM, HIGH)
  - Computes anomaly_score (0-1)
  - Provides reasoning
- **Fallback:** If LLM call fails, uses heuristic-based scoring
- **Output:** Populates `anomaly_score`, `severity`, `anomaly_reasoning`
- **Purpose:** LLM-based semantic analysis of error patterns

#### 5. **decision_node**
- **Input:** `anomaly_score`
- **Logic:**
  - If `anomaly_score < 0.7`: Route to END without incident
  - If `anomaly_score >= 0.7`: Create incident and publish to Redis
- **Output:** Creates structured incident dict with:
  - Timestamp, monitoring_id, severity
  - Aggregated error groups with counts
  - Published to Redis via `RedisStreamHandler.publish_incident()`
- **Return:** `Command(goto=END)`

### Graph Edges

```
START 
  ↓
ingest_logs_node 
  ↓
filter_errors_node 
  ↓
aggregate_errors_node 
  ↓
classify_anomaly_node 
  ↓
decision_node 
  ↓
END
```

## Key Design Decisions

### 1. **Deterministic Error Aggregation**
- Errors are grouped by message signature (not one-per-error)
- Frequency counting detects spikes
- Temporal tracking (first_seen, last_seen) shows duration

### 2. **Adaptive Threshold**
- LLM only invoked when errors exceed threshold
- Prevents LLM overhead for minor issues
- Heuristic fallback ensures robustness

### 3. **Structured LLM Output**
- Pydantic model `AnomalyClassification` ensures valid responses
- `with_structured_output()` enforces schema
- Prevents parsing errors from breaking the workflow

### 4. **Smart Incident Creation**
- **Only incidents with anomaly_score ≥ 0.7 are published**
- Prevents incident spam from minor errors
- Reduces downstream processing load
- Selectable threshold via the decision_node logic

### 5. **Redis Integration**
- Incidents published using `RedisStreamHandler.publish_incident()`
- Preserves existing incident stream interface
- Allows downstream workers to process incidents

### 6. **Async + LangGraph**
- All nodes are fully async
- Graph uses `.ainvoke()` for async execution
- Compatible with FastAPI integration

## API Endpoints

### `/monitor/run` (GET)
Manually trigger a single monitoring cycle.

**Response:**
```json
{
  "monitoring_id": "uuid-string",
  "logs_checked": 1000,
  "errors_found": 23,
  "error_groups": 5,
  "anomaly_score": 0.85,
  "severity": "HIGH",
  "incident_created": true,
  "incident": {
    "created_at": "2026-03-03T...",
    "monitoring_id": "uuid-string",
    "source": "monitoring",
    "type": "anomaly_detection",
    "severity": "HIGH",
    "anomaly_score": 0.85,
    "summary": "Anomaly detected: 5 error patterns...",
    "reasoning": "High error frequency with clustering...",
    "error_groups": { ... },
    "id": "redis-entry-id"
  }
}
```

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MONITORING_AGENT_LLM` | `gpt-oss:120b-cloud` | Ollama model for classification |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection |
| `REDIS_CHANNEL` | `deployment-incidents` | Incident stream channel |
| `MONITOR_INTERVAL` | `10` | Worker cycle interval (seconds) |
| `LOG_DIR` | `logs` | Directory for application logs |

### Ollama Setup

The agent expects an Ollama service running at `http://localhost:11434`.

```bash
# Start Ollama
ollama serve

# Pull a model (in another terminal)
ollama pull gpt-oss:120b-cloud
```

## Testing

### Test 1: Sync with No Errors
```bash
curl http://localhost:8000/monitor/run
```
Expected: `"logs_checked": N, "errors_found": 0, "incident_created": false`

### Test 2: With Error Threshold Exceeded
- Generate multiple errors in logs
- Run monitoring cycle
- Expect: LLM classification + incident if anomaly_score ≥ 0.7

### Test 3: Worker Loop
```bash
python -m app.worker
```
Continuously monitors every `MONITOR_INTERVAL` seconds.

## Implementation Files Modified

| File | Changes |
|------|---------|
| `agents/monitoring/agent.py` | Complete LangGraph implementation |
| `agents/monitoring/prompts.py` | Added ANOMALY_CLASSIFICATION_PROMPT |
| `agents/monitoring/tools.py` | Fixed read_logs wrapper |
| `app/main.py` | Updated to use run_monitoring_cycle() |
| `app/worker.py` | Updated to use run_monitoring_cycle() |

## Error Handling

1. **LLM Unavailable:** Falls back to heuristic scoring
2. **Redis Publish Fails:** Logs error but continues graph execution
3. **Parsing Errors:** Pydantic validation ensures structured output
4. **Empty Logs:** Gracefully handles no logs (0 errors, no incident)

## Research Extensions

This implementation is designed for research flexibility:

1. **Threshold Tuning:** Modify error group count/frequency thresholds in `aggregate_errors_node`
2. **LLM Model Switching:** Change `MONITORING_AGENT_LLM` for different models
3. **Classification Schema:** Extend `AnomalyClassification` Pydantic model
4. **Node Custom Logic:** Each node can be independently modified
5. **Scoring Strategy:** Replace anomaly_score calculation in `classify_anomaly_node`

## Performance Notes

- **Log Ingestion:** O(n) where n = log file size
- **Error Filtering:** O(n) single pass
- **Aggregation:** O(n) hashing with O(e) groups (e << n typically)
- **LLM Call:** Depends on Ollama, ~1-5 seconds typical
- **Overall Cycle:** 1-10 seconds depending on log volume and model latency

## Future Enhancements

1. **Multi-window Anomaly Detection:** Track patterns across multiple cycles
2. **ML-based Severity:** Replace LLM with trained classifier
3. **Custom Error Signatures:** Use stack trace hashing instead of message
4. **Incident Deduplication:** Prevent same incident from being published multiple times
5. **Metrics Integration:** Add Prometheus/metrics support alongside logs
6. **Container Health:** Integrate Docker API checks

---

**Version:** 1.0  
**Date:** 2026-03-03  
**Status:** Research-Grade Implementation
