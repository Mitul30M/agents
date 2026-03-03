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

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "logs/agent.log")
    LOG_DIR = os.getenv("LOG_DIR", "logs")

    # Monitoring
    MONITOR_INTERVAL = float(os.getenv("MONITOR_INTERVAL", "10"))
    MONITORING_AGENT_LLM = os.getenv("MONITORING_AGENT_LLM", "gpt-oss:120b-cloud")
