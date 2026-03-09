from __future__ import annotations

"""Log context fetching utilities for the diagnosis agent."""

import json
import logging
import os
import glob
from datetime import datetime, timedelta
from typing import List, Optional, Union

from app.config import Config

logger = logging.getLogger(__name__)


def _parse_timestamp(value: str) -> Optional[datetime]:
    """Best-effort parsing of an ISO-like timestamp string."""
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1]
        return datetime.fromisoformat(v)
    except Exception:
        return None


def _extract_timestamp_from_line(line: str) -> Optional[datetime]:
    """Try to extract a timestamp from a log line."""
    line = line.strip()
    if not line:
        return None

    # JSON line with a `timestamp` or `time` field
    try:
        data = json.loads(line)
        for key in ("timestamp", "time", "ts"):
            if key in data:
                ts = _parse_timestamp(str(data[key]))
                if ts:
                    return ts
    except Exception:
        # not JSON – fall back to first token heuristic
        pass

    # First token as timestamp (e.g. "2024-01-02T12:34:56.789Z message...")
    first_token = line.split(" ", 1)[0]
    return _parse_timestamp(first_token)


def fetch_log_context(
    timestamp: Union[str, datetime],
    window_seconds: int = 30,
    log_path: Optional[str] = None,
) -> List[str]:
    """Fetch log lines around a given timestamp."""
    if isinstance(timestamp, datetime):
        target_ts = timestamp
    else:
        target_ts = _parse_timestamp(str(timestamp))

    if target_ts is None:
        logger.warning("Invalid timestamp supplied to fetch_log_context: %r", timestamp)
        return []

    configured_path = log_path or Config.APP_LOG_PATH

    # Primary path first, then graceful fallback to rotated files in LOG_DIR.
    candidate_files: List[str] = []
    if configured_path and os.path.exists(configured_path):
        candidate_files.append(configured_path)
    else:
        log_dir = Config.LOG_DIR
        if os.path.isdir(log_dir):
            rotated = sorted(
                glob.glob(os.path.join(log_dir, "app-*.log")),
                key=os.path.getmtime,
                reverse=True,
            )
            current = os.path.join(log_dir, "app.log")
            if os.path.exists(current):
                candidate_files.append(current)
            candidate_files.extend(rotated[:3])

    if not candidate_files:
        logger.warning(
            "No log files found for diagnosis context (APP_LOG_PATH=%s, LOG_DIR=%s)",
            configured_path,
            Config.LOG_DIR,
        )
        return []

    window = timedelta(seconds=window_seconds)
    lines: List[str] = []

    try:
        for path in candidate_files:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    ts = _extract_timestamp_from_line(line)
                    if ts is None:
                        continue
                    if abs(ts - target_ts) <= window:
                        lines.append(line.rstrip("\n"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Failed to read diagnosis log context: %s", exc)
        return []

    return lines


__all__ = ["fetch_log_context"]

