# LangGraph Workflows

This document describes the LangGraph graphs that orchestrate the agentic system.

## Incident Graph

Main graph for handling individual incidents.

### States

- `CREATED`: Incident received
- `CLASSIFIED`: Incident type and severity determined
- `INVESTIGATING`: Diagnosis agent analyzing root cause
- `REMEDIATING`: Remediation agent executing fixes
- `RESOLVED`: Incident closed
- `ESCALATED`: Human intervention required
- `ROLLED_BACK`: Remediation failed, reverting

### Nodes

1. **classifier_node**: Classify incident and determine severity
2. **diagnosis_node**: Run diagnosis agent for root cause analysis
3. **approval_node**: Check if remediation requires human approval
4. **remediation_node**: Execute remediation steps
5. **verification_node**: Verify fix was successful
6. **communication_node**: Send notifications
7. **storage_node**: Persist incident record

### Edges

```
START → classifier_node
       ↓
    diagnosis_node
       ↓
    approval_node
       ├→ [high_risk] escalate_node → END
       └→ [low_risk] remediation_node
                     ↓
                 verification_node
                     ├→ [success] communication_node → END
                     └→ [failure] rollback_node → END
```

## Monitoring Graph

Continuous monitoring and anomaly detection.

### States

- `IDLE`: Waiting for next check cycle
- `COLLECTING`: Gathering logs and metrics
- `ANALYZING`: Analyzing for anomalies
- `INCIDENT_TRIGGERED`: Dispatching new incidents

### Nodes

1. **log_collection_node**: Fetch recent logs
2. **metrics_node**: Collect system metrics
3. **anomaly_detection_node**: Analyze for issues
4. **router_node**: Route detected issues
5. **dispatch_node**: Create incident records

### Cycle

The graph runs on a configurable schedule (e.g., every minute) and:
1. Collects fresh logs and metrics
2. Analyzes for anomalies
3. Creates incidents for detected problems
4. Returns to idle state

## Remediation Graph

Detailed remediation workflow.

### States

- `READY`: Ready to start remediation
- `EXECUTING`: Running remediation steps
- `VERIFYING`: Checking if fix worked
- `COMPLETE`: Remediation finished

### Nodes

1. **plan_remediation_node**: Create step-by-step plan
2. **execute_steps_node**: Run remediation steps sequentially
3. **verify_node**: Confirm remediation worked
4. **rollback_node**: Revert if needed
5. **report_node**: Generate remediation report

## Supervisor Pattern

The main supervisor:

1. Receives incidents from monitoring graph
2. Dispatches to incident graph
3. Monitors incident progress
4. Handles escalations
5. Aggregates metrics and results

### Example Flow

```python
supervisor_state = {
    "incident_id": "inc_123",
    "type": "deployment_failure",
    "severity": "critical"
}

# Supervisor routes to incident_graph
incident_result = await incident_graph.invoke(supervisor_state)

# Updates tracking and metrics
metrics.record_incident(incident_result)
```

## Handoff & State Machine

State transitions are validated before execution:

```python
# Before transition
can_transition(CLASSIFIED, INVESTIGATING, incident_context)
# Returns: True/False

# Record transition
log_transition(CLASSIFIED, INVESTIGATING, "Diagnosis started by supervisor")
```

This ensures the incident lifecycle is tracked and respects business rules.

## Error Handling

Each graph node includes error handling:

- Transient errors: Retry with exponential backoff
- Permanent errors: Escalate to human review
- Timeout errors: Fall back to safe state

## Checkpointing

All graphs checkpoint state at critical points:

```python
checkpoint_id = await checkpointer.save_checkpoint(
    incident_id="inc_123",
    state=incident_state
)
```

This enables:
- Recovery from failures
- Reexecution from checkpoints
- Full audit trail
