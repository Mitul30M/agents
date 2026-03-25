# Orchestrator Agent Implementation (Supervisor + Timeline Intelligence)

## Overview

The Orchestrator Agent is the control plane for the incident pipeline. It supervises child agents, tracks incident lifecycle state with transition guards, and builds correlated timelines from Redis streams plus orchestrator log markers.

Current runtime model:

Monitoring Agent -> Diagnosis Agent -> Remediation Agent -> Communication Agent

The Orchestrator Agent does not replace domain logic inside child agents. It manages health, sequencing signals, retries, escalation, and observability snapshots.

Primary implementation files:

- agents/orchestrator/agent.py
- agents/orchestrator/state.py

Entrypoint:

- app/worker.py runs OrchestratorAgent.run_forever()

## Core Responsibilities

### 1. Child Supervision

- Starts all child loops:
  - monitoring
  - diagnosis
  - remediation
  - communication
- Detects task failure/completion
- Restarts failed children with restart budget protection
- Performs regular supervisor heartbeat cycles

### 2. Heartbeat and Health

Health model is process heartbeat based:

- Running child task = healthy
- Done/cancelled task = unhealthy -> restart attempt
- Idle activity does not imply failure

Two time signals are exposed for observability:

- last heartbeat age: child runtime heartbeat updated each supervise cycle
- last activity age: updated when correlated stream/log activity is observed

### 3. Incident Lifecycle State Management

Uses guarded transitions in an in-memory state store.

Lifecycle states:

- DETECTED
- DIAGNOSING
- DIAGNOSED
- REMEDIATING
- REMEDIATED
- COMMUNICATING
- RESOLVED
- RETRYING
- ESCALATED

Invalid transitions are rejected and recorded as timeline events.

### 4. Timeout and Retry Policy

- Detects stale incidents in active states
- Increments retry counter
- Moves incident to RETRYING
- Restarts stage-specific child when needed
- Requeues incident back to prior stage
- Escalates to ESCALATED when retry budget is exceeded

### 5. Live Execution Intelligence

Builds per-incident timelines by correlating:

- stream events from INCIDENT_STREAM, DIAGNOSIS_STREAM, REMEDIATION_STREAM
- log markers from shared orchestrator.log

Typical log-derived markers:

- Published diagnosis
- Published remediation
- Preparing incident report
- Incident notification sent

### 6. Snapshot Publishing for API

Each heartbeat, orchestrator publishes read-only snapshots into Redis:

- orchestrator status payload
- incident timeline payload

API reads these snapshots for:

- GET /orchestrator/status
- GET /orchestrator/timelines

## Child Agent Runtime Model

Each child is tracked using runtime metadata:

- task handle
- restart count
- last heartbeat timestamp
- last activity timestamp

Restart triggers:

- missing task
- task completed unexpectedly
- task raised exception

No restart trigger for inactivity alone.

## Timeline and State Store Model

The state store tracks:

- current lifecycle state
- retry count
- created/updated timestamps
- append-only event history

Event fields:

- timestamp
- source
- event_type
- message
- metadata

This gives a complete incident execution trail for debugging and audit.

## Redis Correlation Paths

### Stream Correlation

- incident stream event:
  - ensure incident
  - DETECTED -> DIAGNOSING
- diagnosis stream event:
  - DIAGNOSED -> REMEDIATING
- remediation stream event:
  - REMEDIATED -> COMMUNICATING

### Log Correlation

Log watcher tails JSON lines from ORCH_LOG_FILE_PATH and maps specific messages to lifecycle transitions.

## Configuration

From app/config.py:

- ORCH_HEARTBEAT_SECONDS
- ORCH_LIVENESS_TIMEOUT_SECONDS
- ORCH_MAX_CHILD_RESTARTS
- ORCH_INCIDENT_STAGE_TIMEOUT_SECONDS
- ORCH_MAX_INCIDENT_RETRIES
- ORCH_LOG_FILE_PATH
- ORCH_STATUS_KEY
- ORCH_TIMELINE_KEY

Related stream config:

- REDIS_URL
- INCIDENT_STREAM
- DIAGNOSIS_STREAM
- REMEDIATION_STREAM

## API Endpoints (Read-Only)

- GET /orchestrator/status
  - returns child health snapshot and supervisor settings
- GET /orchestrator/timelines
  - returns correlated per-incident timeline snapshot

If no snapshot is published yet, endpoints return unavailable status.

## Operational Runbook

### Start

- Launch API service
- Launch worker service (orchestrator supervisor)
- Confirm status endpoint is publishing

### Verify Child Health

- Check /orchestrator/status
- Confirm all child task_state values are running
- Watch restart counters for unexpected growth

### Verify Incident Progress

- Trigger an incident
- Inspect /orchestrator/timelines
- Confirm state transitions progress through expected stages

### Debug Stream/Log Correlation

- Verify Redis stream names match config
- Verify ORCH_LOG_FILE_PATH points to mounted orchestrator log
- Check timeline events for missing or rejected transitions

## Failure Modes and Safeguards

### Child Crash Loop

- Restart attempts bounded by ORCH_MAX_CHILD_RESTARTS
- Exceeded budget is logged as error

### Stuck Incident Stage

- Timeout policy increments retries
- Automatic retry path applied
- Escalates after ORCH_MAX_INCIDENT_RETRIES

### Invalid State Motion

- Transition guard rejects illegal state change
- Rejection recorded as invalid_transition event

## Design Notes

- Orchestrator is supervisory, not business-logic replacement
- Streams provide canonical progression signals
- Log watcher enriches live observability and timeline context
- Snapshot publishing decouples worker process from API process

---

Version: 1.0  
Date: 2026-03-25  
Status: Active Implementation
