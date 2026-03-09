from __future__ import annotations

"""Redis publishing utilities for diagnosis results."""

import asyncio
import json
import logging
from typing import Any

import redis

from app.config import Config
from agents.diagnosis.schemas import DiagnosisResult

logger = logging.getLogger(__name__)


class DiagnosisPublisher:
    """Publish diagnosis results to a Redis stream."""

    def __init__(self, redis_url: str | None = None, stream: str | None = None) -> None:
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        self._stream = stream or Config.DIAGNOSIS_STREAM

    async def publish(self, diagnosis: DiagnosisResult) -> str:
        """Publish a :class:`DiagnosisResult` to the configured Redis stream."""

        def _publish() -> str:
            try:
                payload: dict[str, Any] = {
                    "data": json.dumps(diagnosis.dict(exclude_none=True)),
                }
                entry_id = self._redis.xadd(self._stream, payload)
                encoded = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                logger.info("Published diagnosis %s to stream %s", diagnosis.incident_id, self._stream)
                return encoded
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Failed to publish diagnosis %s: %s", diagnosis.incident_id, exc)
                return ""

        return await asyncio.to_thread(_publish)


__all__ = ["DiagnosisPublisher"]

