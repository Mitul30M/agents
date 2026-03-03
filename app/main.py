"""Main API entry point."""

from contextlib import asynccontextmanager

# configure logging early (module import performs the setup)
from app import logger  # noqa: F401 - side effect only (sets up root logger)

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

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
    """Return the most recent incidents read from Redis."""
    handler = RedisStreamHandler(Config.REDIS_URL, Config.REDIS_CHANNEL)
    return await handler.read_incidents(count)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=Config.API_HOST,
        port=Config.API_PORT,
        reload=Config.DEBUG,
    )
