"""Log file reading and parsing utilities."""

from typing import Any
import logging

logger = logging.getLogger(__name__)


class LogReader:
    """Read and parse application logs."""

    async def read_logs(self, limit: int = 1000, filter_level: str = None) -> list[dict[str, Any]]:
        """
        Read logs from the application files located in the shared log directory.
        The most recent file is scanned first and results are returned in reverse chronological
        order (newest first).

        Args:
            limit: Maximum number of logs to return
            filter_level: Optional log level filter (INFO, ERROR, etc.)

        Returns:
            List of log entries
        """
        import asyncio
        import os
        import glob
        import json
        from app.config import Config

        def _load() -> list[dict[str, Any]]:
            entries: list[dict[str, Any]] = []
            log_dir = Config.LOG_DIR
            print(f"\n[LogReader] Reading from directory: {log_dir}")
            logger.info(f"Reading logs from {log_dir}")
            if not os.path.isdir(log_dir):
                print(f"[LogReader] Directory {log_dir} does not exist")
                return entries

            # pick the newest log file (rotation pattern app-YYYY-MM-DD.log)
            pattern = os.path.join(log_dir, "app-*.log")
            files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            print(f"[LogReader] Found {len(files)} log files: {files}")
            logger.debug(f"Found {len(files)} log files")
            
            for fname in files:
                try:
                    print(f"[LogReader] Processing file: {fname}")
                    with open(fname, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                print(f"  - level={entry.get('level')}, message={entry.get('message')}")
                            except json.JSONDecodeError:
                                continue
                            if filter_level and entry.get("level") != filter_level:
                                continue
                            entries.append(entry)
                            if len(entries) >= limit:
                                return entries
                except Exception as e:
                    print(f"[LogReader] Error reading {fname}: {e}")
                    logger.error(f"Error reading {fname}: {e}")
                    continue
            print(f"[LogReader] Total logs read: {len(entries)}\n")
            logger.info(f"Loaded {len(entries)} log entries")
            return entries

        return await asyncio.to_thread(_load)

    async def search_logs(self, query: str) -> list[dict[str, Any]]:
        """
        Search logs for the specified text anywhere in the JSON blob.
        This is a simple substring search running against the most recent log files.
        """
        import asyncio
        import os
        import glob
        import json
        from app.config import Config

        def _search() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []
            log_dir = Config.LOG_DIR
            pattern = os.path.join(log_dir, "app-*.log")
            files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
            for fname in files:
                try:
                    with open(fname, "r", encoding="utf-8") as f:
                        for line in f:
                            if query in line:
                                try:
                                    results.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
                except Exception:
                    continue
            return results

        return await asyncio.to_thread(_search)

    async def read_logs_from_redis(self, stream: str | None = None, count: int = 100) -> list[dict[str, Any]]:
        """
        Fetch recent log entries from a Redis stream.  The stream is assumed to contain
        JSON-serialized entries under a single field named `data` (same format used by the
        Next.js logger pushLogToStream helper).  By default the stream name is taken from
        :class:`app.config.Config.REDIS_LOG_STREAM` so that it matches the value used by
        the application logger.
        """
        import asyncio
        import asyncio
        import redis
        import json
        from app.config import Config

        def _read() -> list[dict[str, Any]]:
            try:
                client = redis.from_url(Config.REDIS_URL)
                stream_name = stream or Config.REDIS_LOG_STREAM
                raw = client.xrevrange(stream_name, max="+", min="-", count=count)
                result: list[dict[str, Any]] = []
                for entry_id, data in raw:
                    decoded = {k.decode(): v.decode() for k, v in data.items()}
                    if "data" in decoded:
                        try:
                            result.append(json.loads(decoded["data"]))
                        except Exception:
                            continue
                return result
            except Exception:
                return []

        return await asyncio.to_thread(_read)

    async def get_error_trace(self, error_id: str) -> dict[str, Any]:
        """
        Look through the logs for an entry with a matching error id and return the full object.
        The implementation assumes that `error_id` is stored in a top-level field named `error` or
        `messageID` depending on the logging format.
        """
        entries = await self.search_logs(error_id)
        for entry in entries:
            # match on a few common keys
            if entry.get("error") and error_id in str(entry.get("error")):
                return entry
            if entry.get("messageID") == error_id:
                return entry
        return {}
