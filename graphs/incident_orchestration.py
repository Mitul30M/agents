"""LangGraph orchestration graphs using modern StateGraph API."""

from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END
import logging

from app import logger  # noqa: F401

logger = logging.getLogger(__name__)


class IncidentState(TypedDict):
    """State passed through the incident orchestration graph."""
    
    incident_id: str
    created_at: str
    logs: list[dict[str, Any]]
    error_message: str
    classification: dict[str, Any]
    diagnosis: dict[str, Any]
    remediation_plan: dict[str, Any]
    actions_taken: list[dict[str, Any]]
    resolved: bool
    resolution_summary: str


async def detect_incident(state: IncidentState) -> IncidentState:
    """Node: detect incident from logs."""
    print(f"[Graph] Detecting incident: {state['incident_id']}")
    logger.info(f"Detecting incident {state['incident_id']}")
    state["classification"] = {
        "type": "log_error",
        "severity": "high" if "error" in state["error_message"].lower() else "medium",
    }
    return state


async def diagnose_incident(state: IncidentState) -> IncidentState:
    """Node: diagnose the root cause."""
    from agents.diagnosis.agent import DiagnosisAgent
    
    print(f"[Graph] Diagnosing incident: {state['incident_id']}")
    logger.info(f"Diagnosing incident {state['incident_id']}")
    
    agent = DiagnosisAgent()
    diagnosis = await agent.diagnose({
        "summary": state["error_message"],
        "logs": state["logs"],
    })
    state["diagnosis"] = diagnosis
    return state


async def remediate_incident(state: IncidentState) -> IncidentState:
    """Node: execute remediation."""
    from agents.remediation.agent import RemediationAgent

    print(f"[Graph] Remediating incident: {state['incident_id']}")
    logger.info(f"Remediating incident {state['incident_id']}")

    agent = RemediationAgent()

    # Pass diagnosis output to remediation agent
    # The diagnosis dict should contain root_cause, confidence, patterns_detected, etc.
    remediation_payload = {
        "incident_id": state["incident_id"],
        **state["diagnosis"],  # Unpack all diagnosis fields
    }

    result = await agent.remediate(remediation_payload)

    # Record the remediation action
    state["actions_taken"].append(
        {
            "type": "remediation",
            "status": "completed",
            "result": result,
        }
    )

    # Remediation success = any GitHub action was created
    state["resolved"] = any(
        action.get("status") == "success" for action in result.get("github_actions", [])
    )

    # Generate resolution summary
    fix_type = result.get("fix_type", "UNKNOWN")
    if fix_type == "CODE_CHANGE":
        pr_actions = [
            a
            for a in result.get("github_actions", [])
            if a.get("action_type") == "create_pr"
        ]
        if pr_actions and pr_actions[0].get("status") == "success":
            state["resolution_summary"] = (
                f"PR created for code fix. "
                f"PR #{pr_actions[0].get('pr_number')} awaiting review."
            )
        else:
            state["resolution_summary"] = (
                f"Code patches generated. Manual PR submission required."
            )
    elif fix_type == "INFRASTRUCTURE":
        issue_actions = [
            a
            for a in result.get("github_actions", [])
            if a.get("action_type") == "create_issue"
        ]
        if issue_actions and issue_actions[0].get("status") == "success":
            state["resolution_summary"] = (
                f"Infrastructure issue reported. "
                f"Issue #{issue_actions[0].get('issue_number')} created for investigation."
            )
        else:
            state["resolution_summary"] = (
                "Infrastructure issue escalated. Manual action required."
            )
    else:
        state["resolution_summary"] = (
            "Issue requires further investigation. Check GitHub for details."
        )

    return state


async def communicate_incident(state: IncidentState) -> IncidentState:
    """Node: send notifications about the incident."""
    from agents.communication.agent import CommunicationAgent
    
    print(f"[Graph] Communicating incident: {state['incident_id']}")
    logger.info(f"Communicating incident {state['incident_id']}")
    
    agent = CommunicationAgent()
    await agent.notify({
        "id": state["incident_id"],
        "resolved": state["resolved"],
        "summary": state["resolution_summary"],
    })
    return state


def build_incident_graph():
    """Build the incident orchestration graph."""
    graph = StateGraph(IncidentState)
    
    # Add nodes
    graph.add_node("detect", detect_incident)
    graph.add_node("diagnose", diagnose_incident)
    graph.add_node("remediate", remediate_incident)
    graph.add_node("communicate", communicate_incident)
    
    # Add edges
    graph.add_edge(START, "detect")
    graph.add_edge("detect", "diagnose")
    graph.add_edge("diagnose", "remediate")
    graph.add_edge("remediate", "communicate")
    graph.add_edge("communicate", END)
    
    return graph.compile()


class MonitoringState(TypedDict):
    """State for the monitoring graph."""
    
    cycle_id: str
    logs_checked: int
    errors_found: int
    incidents_created: list[dict[str, Any]]


async def scan_logs(state: MonitoringState) -> MonitoringState:
    """Node: scan application logs."""
    from agents.monitoring.agent import run_monitoring_cycle

    print(f"[Graph] Starting monitoring cycle: {state['cycle_id']}")
    logger.info(f"Starting monitoring cycle {state['cycle_id']}")

    result = await run_monitoring_cycle()

    state["logs_checked"] = result.get("logs_checked", 0)
    state["errors_found"] = 1 if result.get("incident_created") else 0
    state["incidents_created"] = [result] if result.get("incident_created") else []

    return state


def build_monitoring_graph():
    """Build the monitoring loop graph."""
    graph = StateGraph(MonitoringState)
    
    # For now just a simple scan step (could add more nodes)
    graph.add_node("scan_logs", scan_logs)
    
    graph.add_edge(START, "scan_logs")
    graph.add_edge("scan_logs", END)
    
    return graph.compile()
