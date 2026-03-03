"""Background worker for async agent orchestration."""

import asyncio
import logging

from app import logger  # noqa: F401

from app.config import Config

logger = logging.getLogger(__name__)


async def main():
    """Main worker loop."""
    logger.info("Starting background worker")

    from agents.monitoring.agent import run_monitoring_cycle

    check_interval = Config.MONITOR_INTERVAL

    try:
        while True:
            try:
                result = await run_monitoring_cycle()
                logger.debug(f"monitoring cycle result: {result}")
            except Exception as exc:
                logger.exception(f"error during monitoring cycle: {exc}")
            await asyncio.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("Worker shutdown")
    except Exception as e:
        logger.error(f"Worker error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
