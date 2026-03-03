"""
LangGraph-based Monitoring Agent
Hybrid deterministic + LLM anomaly detection workflow.
"""

import logging
from typing import TypedDict, Dict, Any, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.types import Command
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from tools.log_reader import LogReader
from tools.redis_stream import RedisStreamHandler
from app.config import Config

logger = logging.getLogger(__name__)

# =============================================================================
# STATE DEFINITION
# =============================================================================

class MonitoringState(TypedDict):
    raw_logs: list
    error_logs: list
    grouped_errors: Dict[str, Any]
    stats: Dict[str, Any]
    anomaly_score: float
    severity: str
    reasoning: str
    incident: Optional[Dict[str, Any]]

# =============================================================================
# LLM STRUCTURED OUTPUT
# =============================================================================

class AnomalyClassification(BaseModel):
    severity: str = Field(..., description="LOW, MEDIUM, HIGH")
    anomaly_score: float = Field(..., ge=0.0, le=1.0)
    likely_cause: str
    reasoning: str

# =============================================================================
# NODE 1 — INGEST LOGS
# =============================================================================

async def ingest_logs_node(state: MonitoringState) -> MonitoringState:
    logger.info("[Monitoring] Ingesting logs")
    reader = LogReader()
    logs = await reader.read_logs(limit=500)
    return {**state, "raw_logs": logs}

# =============================================================================
# NODE 2 — FILTER ERRORS
# =============================================================================

async def filter_errors_node(state: MonitoringState) -> MonitoringState:
    logs = state["raw_logs"]
    errors = [l for l in logs if l.get("level", "").lower() == "error"]
    logger.info(f"[Monitoring] Found {len(errors)} error logs")
    return {**state, "error_logs": errors}

# =============================================================================
# NODE 3 — AGGREGATE ERRORS
# =============================================================================

async def aggregate_errors_node(state: MonitoringState) -> MonitoringState:
    grouped: Dict[str, Dict[str, Any]] = {}

    for error in state["error_logs"]:
        signature = error.get("message", "")[:120]

        if signature not in grouped:
            grouped[signature] = {
                "count": 0,
                "first_seen": error.get("timestamp"),
                "last_seen": error.get("timestamp"),
            }

        grouped[signature]["count"] += 1
        grouped[signature]["last_seen"] = error.get("timestamp")

    stats = {
        "total_errors": len(state["error_logs"]),
        "distinct_groups": len(grouped),
    }

    logger.info(
        f"[Monitoring] Aggregated into {stats['distinct_groups']} groups "
        f"with {stats['total_errors']} total errors"
    )

    return {**state, "grouped_errors": grouped, "stats": stats}

# =============================================================================
# NODE 4 — CLASSIFY ANOMALY (LLM)
# =============================================================================

async def classify_anomaly_node(state: MonitoringState) -> MonitoringState:
    total_errors = state["stats"]["total_errors"]
    groups = state["stats"]["distinct_groups"]

    # deterministic threshold
    if total_errors <= 10 and groups <= 5:
        logger.info("[Monitoring] Below anomaly threshold")
        return {
            **state,
            "anomaly_score": 0.0,
            "severity": "LOW",
            "reasoning": "Below deterministic threshold",
        }

    logger.info("[Monitoring] Threshold exceeded — invoking LLM")

    summary = "\n".join(
        f"- {sig}: {data['count']} occurrences"
        for sig, data in state["grouped_errors"].items()
    )

    prompt = f"""
You are an anomaly detection expert.

Error patterns:
{summary}

Total distinct groups: {groups}
Total errors: {total_errors}

Classify severity and anomaly_score (0–1).
"""

    llm = ChatOllama(
        model=Config.MONITORING_AGENT_LLM,
        temperature=0.2,
        base_url=Config.OLLAMA_BASE_URL,
    )

    structured_llm = llm.with_structured_output(AnomalyClassification)
    result = await structured_llm.ainvoke(prompt)

    return {
        **state,
        "severity": result.severity,
        "anomaly_score": result.anomaly_score,
        "reasoning": result.reasoning,
    }

# =============================================================================
# NODE 5 — DECISION & INCIDENT CREATION
# =============================================================================

async def decision_node(state: MonitoringState) -> Command:
    if state["anomaly_score"] < 0.7:
        logger.info("[Monitoring] No incident created")
        return Command(goto=END)

    logger.info("[Monitoring] Creating incident")

    incident = {
        "created_at": datetime.utcnow().isoformat(),
        "source": "monitoring",
        "type": "anomaly_detection",
        "severity": state["severity"],
        "anomaly_score": state["anomaly_score"],
        "reasoning": state["reasoning"],
        "error_groups": state["grouped_errors"],
    }

    handler = RedisStreamHandler(Config.REDIS_URL, Config.REDIS_CHANNEL)
    await handler.publish_incident(incident)

    logger.info("[Monitoring] Incident published")

    return Command(
        update={"incident": incident},
        goto=END,
    )

# =============================================================================
# GRAPH CONSTRUCTION
# =============================================================================

def build_monitoring_graph():
    graph = StateGraph(MonitoringState)

    graph.add_node("ingest", ingest_logs_node)
    graph.add_node("filter", filter_errors_node)
    graph.add_node("aggregate", aggregate_errors_node)
    graph.add_node("classify", classify_anomaly_node)
    graph.add_node("decide", decision_node)

    graph.set_entry_point("ingest")

    graph.add_edge("ingest", "filter")
    graph.add_edge("filter", "aggregate")
    graph.add_edge("aggregate", "classify")
    graph.add_edge("classify", "decide")
    graph.add_edge("decide", END)

    return graph.compile()

# =============================================================================
# EXECUTION ENTRYPOINT
# =============================================================================

async def run_monitoring_cycle() -> Dict[str, Any]:
    logger.info("========== MONITORING CYCLE START ==========")

    workflow = build_monitoring_graph()

    initial_state: MonitoringState = {
        "raw_logs": [],
        "error_logs": [],
        "grouped_errors": {},
        "stats": {},
        "anomaly_score": 0.0,
        "severity": "LOW",
        "reasoning": "",
        "incident": None,
    }

    final_state = await workflow.ainvoke(initial_state)

    logger.info("========== MONITORING CYCLE END ==========")

    return {
        "anomaly_score": final_state.get("anomaly_score"),
        "severity": final_state.get("severity"),
        "incident_created": final_state.get("incident") is not None,
    }