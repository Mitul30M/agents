"""Background worker for async agent orchestration."""

import asyncio
import contextlib
import logging

from app import logger  # noqa: F401

from app.config import Config

logger = logging.getLogger(__name__)


async def main():
    """Main worker loop.

    Runs the monitoring cycle on a fixed interval and, in parallel, starts the
    diagnosis agent which continuously consumes incidents from Redis and
    publishes diagnosis results.
    """
    logger.info("Starting background worker")

    from agents.monitoring.agent import run_monitoring_cycle
    from agents.diagnosis.agent import DiagnosisAgent
    from agents.remediation.agent import RemediationAgent

    check_interval = Config.MONITOR_INTERVAL
    diagnosis_agent = DiagnosisAgent()
    remediation_agent = RemediationAgent()
    diagnosis_task = asyncio.create_task(diagnosis_agent.run_forever())
    remediation_task = asyncio.create_task(remediation_agent.run_forever())

    try:
        while True:
            try:
                result = await run_monitoring_cycle()
                logger.debug(f"monitoring cycle result: {result}")
            except Exception as exc:
                logger.exception(f"error during monitoring cycle: {exc}")
            await asyncio.sleep(check_interval)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        logger.info("Worker shutdown requested by user")
    except Exception as e:  # pragma: no cover - defensive
        logger.error("Worker error: %s", e)
        raise
    finally:
        diagnosis_task.cancel()
        remediation_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await diagnosis_task
        with contextlib.suppress(asyncio.CancelledError):
            await remediation_task


if __name__ == "__main__":
    asyncio.run(main())
