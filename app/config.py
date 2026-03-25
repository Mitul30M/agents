"""Application configuration."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""

    # API
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8000"))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"

    # Redis
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
    # channel used for incident events (existing behaviour)
    REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "deployment-incidents")
    # stream used for application logs (mirrors llama-chatbot repo)
    REDIS_LOG_STREAM = os.getenv("REDIS_LOG_STREAM", "app-logs")
    # stream used for anomaly incidents detected by the monitoring agent
    # defaults to REDIS_CHANNEL so existing deployments keep working
    INCIDENT_STREAM = os.getenv(
        "INCIDENT_STREAM", os.getenv("REDIS_CHANNEL", "incident_stream")
    )
    # stream used for diagnosis results produced by the diagnosis agent
    DIAGNOSIS_STREAM = os.getenv("DIAGNOSIS_STREAM", "diagnosis_stream")
    # stream used for remediation outputs produced by the remediation agent
    REMEDIATION_STREAM = os.getenv("REMEDIATION_STREAM", "remediation_stream")

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/agent.log")
    # directory where JSON log files are written by the Python side
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    # path to the Next.js application log file mounted into this container
    APP_LOG_PATH = os.getenv("APP_LOG_PATH", "/app/logs/app.log")

    # Monitoring
    MONITOR_INTERVAL = float(os.getenv("MONITOR_INTERVAL", "10"))
    MONITORING_AGENT_LLM = os.getenv("MONITORING_AGENT_LLM", "llama3.2:latest")
    # deterministic escalation thresholds before LLM classification
    MONITOR_MIN_ERRORS_FOR_INCIDENT = int(
        os.getenv("MONITOR_MIN_ERRORS_FOR_INCIDENT", "5")
    )
    MONITOR_MIN_GROUPS_FOR_INCIDENT = int(
        os.getenv("MONITOR_MIN_GROUPS_FOR_INCIDENT", "3")
    )

    # Orchestrator supervision (phase 1/2)
    ORCH_HEARTBEAT_SECONDS = float(os.getenv("ORCH_HEARTBEAT_SECONDS", "5"))
    ORCH_LIVENESS_TIMEOUT_SECONDS = float(
        os.getenv("ORCH_LIVENESS_TIMEOUT_SECONDS", "30")
    )
    ORCH_MAX_CHILD_RESTARTS = int(os.getenv("ORCH_MAX_CHILD_RESTARTS", "5"))
    ORCH_INCIDENT_STAGE_TIMEOUT_SECONDS = float(
        os.getenv("ORCH_INCIDENT_STAGE_TIMEOUT_SECONDS", "120")
    )
    ORCH_MAX_INCIDENT_RETRIES = int(os.getenv("ORCH_MAX_INCIDENT_RETRIES", "2"))
    ORCH_LOG_FILE_PATH = os.getenv("ORCH_LOG_FILE_PATH", "logs/orchestrator.log")
    ORCH_STATUS_KEY = os.getenv("ORCH_STATUS_KEY", "orchestrator:status")
    ORCH_TIMELINE_KEY = os.getenv("ORCH_TIMELINE_KEY", "orchestrator:timelines")

    # LLM / Ollama
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    DIAGNOSIS_AGENT_LLM = os.getenv("DIAGNOSIS_AGENT_LLM", "qwen3-coder:480b-cloud")
    REMEDIATION_AGENT_LLM = os.getenv("REMEDIATION_AGENT_LLM", "qwen3-coder:480b-cloud")
    REMEDIATION_PATCH_MAX_FILES = int(os.getenv("REMEDIATION_PATCH_MAX_FILES", "2"))
    # absolute path inside runtime/container that remediation is allowed to modify
    REMEDIATION_REPO_PATH = os.getenv(
        "REMEDIATION_REPO_PATH", "/workspace/llama-chatbot"
    )

    # Email / Communication
    SMTP_SERVER = os.getenv("SMTP_SERVER", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "")
    DEVELOPER_EMAIL = os.getenv("DEVELOPER_EMAIL", "")
