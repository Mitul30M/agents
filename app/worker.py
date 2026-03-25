"""Background worker entrypoint for the orchestrator supervisor."""

import asyncio
import logging

from app import logger  # noqa: F401

logger = logging.getLogger(__name__)


async def main():
    """Run OrchestratorAgent as the process-level supervisor."""
    logger.info("Starting background worker")
    from agents.orchestrator.agent import OrchestratorAgent

    orchestrator = OrchestratorAgent()

    try:
        await orchestrator.run_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        logger.info("Worker shutdown requested by user")
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Worker error: %s", e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
