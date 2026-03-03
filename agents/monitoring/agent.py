"""Monitoring agent implementation."""

from typing import Any
import logging

# ensure logging is configured before anything else runs
from app import logger  # noqa: F401

logger = logging.getLogger(__name__)


class MonitoringAgent:
    """
    Agent responsible for continuous system monitoring.

    Monitors:
    - Server logs
    - Application metrics
    - Docker container health
    - Deployment status

    Triggers incident detection when anomalies found.
    """

    async def monitor(self) -> dict[str, Any]:
        """
        Run a single monitoring cycle.  This implementation reads recent logs, looks for
        entries with level == "error", and if any are found it creates a lightweight
        incident record and pushes it onto the Redis incident stream.

        Returns:
            Monitoring results and any detected incidents
        """
        from datetime import datetime
        from agents.monitoring.tools import read_logs
        from tools.redis_stream import RedisStreamHandler
        from app.config import Config

        logger.info("========== MONITORING CYCLE START ==========")
        # read the last 500 entries, any level
        logs = await read_logs(limit=500)
        errors = [l for l in logs if l.get("level") == "error"]
        incidents: list[dict[str, Any]] = []

        logger.debug(f"Total logs scanned: {len(logs)}")
        logger.debug(f"Errors detected: {len(errors)}")
        logger.info(f"Scanned {len(logs)} logs, found {len(errors)} errors")

        if errors:
            handler = RedisStreamHandler(Config.REDIS_URL, Config.REDIS_CHANNEL)
            # create a simple incident for each error (could be batched)
            for err in errors:
                inc = {
                    "created_at": datetime.utcnow().isoformat(),
                    "source": "monitoring",
                    "type": "log_error",
                    "summary": err.get("message", ""),
                    "details": err,
                }
                entry_id = await handler.publish_incident(inc)
                incidents.append({"id": entry_id, **inc})
                logger.info(f"Created incident {entry_id}: {err.get('message')}")

        result = {
            "logs_checked": len(logs),
            "errors": len(errors),
            "incidents": incidents,
        }
        logger.info("========== MONITORING CYCLE END ==========")
        logger.debug(f"Result: {result}")
        return result
