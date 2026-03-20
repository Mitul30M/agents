"""Redis stream operations for incident queuing."""

from typing import Any

import redis


class RedisStreamHandler:
    """Handle incident streaming via Redis."""

    def __init__(self, redis_url: str, channel: str):
        """
        Initialize Redis stream handler.
        
        Args:
            redis_url: Redis connection URL
            channel: Channel name for incidents
        """
        self.redis_client = redis.from_url(redis_url)
        self.channel = channel

    async def read_incidents(self, count: int = 10) -> list[dict[str, Any]]:
        """
        Read the most recent entries from the Redis stream. This is a helper used by the
        worker to fetch pending incidents.
        """
        import asyncio
        import json

        def _read() -> list[dict[str, Any]]:
            try:
                # use XREVRANGE to read latest entries
                raw = self.redis_client.xrevrange(self.channel, max="+", min="-", count=count)
                result: list[dict[str, Any]] = []
                for entry_id, data in raw:
                    # redis returns bytes
                    decoded = {k.decode(): v.decode() for k, v in data.items()}
                    # attempt to parse json in a single field
                    if "data" in decoded:
                        try:
                            decoded["data"] = json.loads(decoded["data"])
                        except Exception:
                            pass
                    result.append({"id": entry_id.decode(), **decoded})
                return result
            except Exception:
                return []

        return await asyncio.to_thread(_read)

    async def publish_incident(self, incident: dict[str, Any]) -> str:
        """
        Publish an incident dictionary to the configured Redis stream. The dictionary is
        JSON-serialized and stored under a field named "data" to keep the schema simple.
        """
        import asyncio
        import json

        def _publish() -> str:
            try:
                payload = {"data": json.dumps(incident)}
                entry_id = self.redis_client.xadd(self.channel, payload)
                return entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            except Exception:
                return ""

        return await asyncio.to_thread(_publish)

    async def delete_entries(self, entry_ids: list[str]) -> int:
        """
        Delete processed entries from the configured Redis stream.

        Args:
            entry_ids: Stream entry IDs to delete.

        Returns:
            Number of deleted entries.
        """
        import asyncio

        if not entry_ids:
            return 0

        def _delete() -> int:
            try:
                normalized: list[str] = [
                    str(entry_id) for entry_id in entry_ids if entry_id
                ]
                if not normalized:
                    return 0
                return int(self.redis_client.xdel(self.channel, *normalized))
            except Exception:
                return 0

        return await asyncio.to_thread(_delete)
