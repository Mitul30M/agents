"""Tools available to the monitoring agent."""

from typing import Any


async def read_logs(limit: int = 1000) -> list[dict[str, Any]]:
    """
    Convenience wrapper around the shared LogReader.  Will first attempt to read from
    the filesystem and fall back to the Redis stream if the directory is empty.
    """
    from tools.log_reader import LogReader
    reader = LogReader()
    logs = await reader.read_logs(limit=limit)
    if logs:
        return logs
    # fallback to redis
    return await reader.read_logs_from_redis(count=limit)


# async def get_metrics(timeframe: str = "1h") -> dict[str, Any]:
#     """
#     Placeholder for retrieving application metrics.  In a real deployment this might
#     query Prometheus, a hosted metric service, or inspect container stats.
#     """
#     # TODO: integrate with real metrics system
#     return {"cpu": "unknown", "memory": "unknown", "timeframe": timeframe}


# async def check_container_health() -> dict[str, Any]:
#     """
#     Simple stub that returns a healthy status.  Later this could call the Docker API
#     or Kubernetes readiness endpoints.
#     """
#     return {"status": "healthy"}
