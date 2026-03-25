"""Main API entry point."""

import asyncio
import json
from contextlib import asynccontextmanager

# configure logging early (module import performs the setup)
from app import logger  # noqa: F401 - side effect only (sets up root logger)

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import redis

from app.config import Config
from agents.monitoring.agent import run_monitoring_cycle
from tools.redis_stream import RedisStreamHandler

# ``app.logger`` has already configured the root logger via import above.
# individual modules may still acquire their own logger instance:
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager."""
    logger.info("Application startup")
    yield
    logger.info("Application shutdown")


app = FastAPI(
    title="Deployment Incident Orchestration",
    description="AI-powered incident management for Next.js deployments",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return JSONResponse({"status": "healthy"})


@app.get("/")
async def root():
    """Root endpoint."""
    return JSONResponse(
        {
            "name": "Deployment Incident Orchestration",
            "version": "0.1.0",
            "status": "running",
        }
    )


@app.get("/monitor/run")
async def run_monitor():
    """Run a single monitoring cycle and return results."""
    return await run_monitoring_cycle()


@app.get("/incidents")
async def list_incidents(count: int = 20):
    """Return the most recent incidents read from the incident stream."""
    handler = RedisStreamHandler(Config.REDIS_URL, Config.INCIDENT_STREAM)
    return await handler.read_incidents(count)


@app.get("/diagnosis")
async def list_diagnosis(count: int = 20):
    """Return the most recent diagnosis results from Redis."""
    handler = RedisStreamHandler(Config.REDIS_URL, Config.DIAGNOSIS_STREAM)
    return await handler.read_incidents(count)


async def _read_orchestrator_snapshot(redis_key: str) -> dict:
    """Read JSON snapshot payload from Redis key as a dictionary."""

    def _read() -> dict:
        client = redis.from_url(Config.REDIS_URL)
        raw = client.get(redis_key)
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            payload = json.loads(raw)
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    return await asyncio.to_thread(_read)


@app.get("/orchestrator/status")
async def orchestrator_status():
    """Return latest orchestrator child health snapshot."""
    payload = await _read_orchestrator_snapshot(Config.ORCH_STATUS_KEY)
    if not payload:
        return JSONResponse(
            {
                "status": "unavailable",
                "message": "No orchestrator status has been published yet",
            },
            status_code=503,
        )
    return JSONResponse(payload)


@app.get("/orchestrator/timelines")
async def orchestrator_timelines():
    """Return latest in-memory incident timelines from orchestrator."""
    payload = await _read_orchestrator_snapshot(Config.ORCH_TIMELINE_KEY)
    if not payload:
        return JSONResponse(
            {
                "status": "unavailable",
                "message": "No orchestrator timeline data has been published yet",
                "timelines": {},
            },
            status_code=503,
        )
    return JSONResponse({"status": "ok", "timelines": payload})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=Config.API_HOST,
        port=Config.API_PORT,
        reload=Config.DEBUG,
    )
