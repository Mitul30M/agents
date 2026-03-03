# Architecture

## High-Level Overview

The Deployment Incident Orchestration system is built around a multi-agent architecture coordinated by LangGraph. The system monitors Next.js deployments, detects incidents, diagnoses root causes, and executes remediation autonomously while maintaining human oversight.

## Core Components

### 1. Orchestration Layer

**LangGraph Graphs:**
- `incident_graph.py`: Main incident response workflow
- `monitoring_graph.py`: Continuous monitoring and detection
- `remediation_graph.py`: Automated remediation execution

**Supervision:**
- `main_supervisor.py`: Coordinates all agents and workflows
- `dispatch.py`: Routes incidents to appropriate agents

**Routing:**
- `log_router.py`: Routes logs to processing pipelines
- `classification.py`: Classifies incidents by type and severity

**State Management:**
- `state_machine.py`: Defines incident lifecycle states
- `transitions.py`: Validates and manages state transitions

### 2. Agent Layer

Four specialized agents handle different aspects of incident management:

**Monitoring Agent**
- Continuously observes logs and metrics
- Detects anomalies and errors
- Triggers incident workflows
- Implementation lives in `agents/monitoring/agent.py` and uses `tools/log_reader.py`

**Diagnosis Agent**
- Performs root cause analysis
- Analyzes error messages and system state
- Generates remediation recommendations
- Stub in `agents/diagnosis/agent.py`

**Remediation Agent**
- Executes automated fixes (e.g. restart container)
- Verifies fix success
- Stub in `agents/remediation/agent.py`

**Communication Agent**
- Sends notifications (Slack, email)
- Provides status updates
- Stub in `agents/communication/agent.py`

**Diagnosis Agent**
- Performs root cause analysis
- Analyzes error messages and system state
- Generates remediation recommendations

**Remediation Agent**
- Executes automated fixes
- Restarts containers, rolls back deployments
- Verifies fix success

**Communication Agent**
- Sends notifications (Slack, email)
- Provides status updates
- Generates post-incident summaries

**Human Review Middleware**
- Gates high-risk actions
- Requests operator approval
- Implements approval policies

### 3. Tools & Utilities

**System Integration:**
- `redis_stream.py`: Incident queuing and streaming (used by the monitoring agent)
- `log_reader.py`: Log aggregation and parsing (reads from file system or Redis stream)
- `docker_controller.py`: Container operations
- `file_editor.py`: Configuration safe edits
- `notification.py`: External notifications

### 4. State Management

**Global State:**
- `incident_state.py`: Incident-specific state and history
- `monitoring_state.py`: Monitoring workflow state
- `shared_state.py`: Shared context across all agents

**Persistence:**
- `checkpointer.py`: Graph state checkpointing
- `storage.py`: Long-term incident storage

### 5. Evaluation & Research

- `metrics.py`: Performance and efficiency metrics
- `experiments.py`: Controlled experiment framework
- `benchmark_scenarios.py`: Standard test scenarios

## Data Flow

```
Detection
   ↓
Monitoring Graph → Classifications & Routing
   ↓
Incident Graph (Supervised)
   ├→ Diagnosis Agent
   ├→ Remediation Agent (with approval gates)
   └→ Communication Agent
   ↓
Persistence & Metrics
```

## State Machine

```
DETECTED → CLASSIFIED → INVESTIGATING → REMEDIATING
   ↓           ↓             ↓              ↓
   └─────────────────────────────────→ RESOLVED

Any state → ESCALATED (human intervention needed)
Any state → ROLLED_BACK (remediation failed)
```

## Key Design Decisions

1. **LangGraph for Orchestration**: Provides reliable coordination, checkpointing, and human-in-the-loop capabilities

2. **Multi-Agent Specialization**: Each agent has a focused responsibility, easier to test and improve

3. **Human Review Gates**: Critical actions require human approval to maintain safety

4. **Persistent State**: Full incident history enables learning and debugging

5. **Redis Streaming**: Decouples monitoring from incident processing

## Integration Points

- **LLM Calls**: All agents leverage Claude/GPT for reasoning
- **Docker API**: Container lifecycle management
- **Redis**: Incident queuing and streaming
- **Notification APIs**: Slack, email, PagerDuty
- **Log Aggregation**: Application log reading

## Deployment

The system runs as:
- API service (FastAPI)
- Background workers (async task processing)
- Docker container with all dependencies

See deployment documentation for setup details.
