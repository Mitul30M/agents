"""Logging setup for the orchestration application.

Mimics the behaviour of the Next.js project in the sibling repository:
- JSON-formatted lines written to daily-rotated files in ``LOG_DIR``
- Console output for local development
- Best-effort push of each record to a Redis stream (``REDIS_LOG_STREAM``)

The handlers are attached to the root logger so that ``logging.getLogger``
returns a correctly-configured logger in every module.
"""

import json
import logging
import os
from logging.handlers import TimedRotatingFileHandler

import redis

from app.config import Config


class JsonFormatter(logging.Formatter):
    """Convert a LogRecord into a JSON string."""

    def format(self, record: logging.LogRecord) -> str:
        # base structure
        obj: dict[str, object] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname.lower(),
            "message": record.getMessage(),
        }

        # include any extra metadata passed via ``logger.info(..., extra={...})``
        extras = {k: v for k, v in record.__dict__.items() if k not in logging.LogRecord.__dict__}
        if extras:
            obj["meta"] = extras

        if record.exc_info:
            obj["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(obj)


class RedisStreamHandler(logging.Handler):
    """A logging handler that pushes each record into a Redis stream.

    The record is converted to JSON in the same shape as the file logger so that
    consumers (e.g. :class:`tools.log_reader.LogReader`) can read from either source.
    """

    def __init__(self, redis_url: str, stream: str):
        super().__init__()
        self.stream = stream
        self.client = redis.from_url(redis_url)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # each entry stored under a single field named "data"
            self.client.xadd(self.stream, {"data": msg})
        except Exception:
            # best-effort, don't crash the application for logging failures
            pass


# ensure log directory exists
os.makedirs(Config.LOG_DIR, exist_ok=True)

# root logger configuration
_root_logger = logging.getLogger()
_root_logger.setLevel(Config.LOG_LEVEL)

# console handler for stdout/stderr
_console = logging.StreamHandler()
_console.setLevel(Config.LOG_LEVEL)
_console.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
_root_logger.addHandler(_console)

# file handler (daily rotation).  we want names like "app-YYYY-MM-DD.log" to mirror the
# Next.js service.
_base_path = os.path.join(Config.LOG_DIR, "app.log")
_file_handler = TimedRotatingFileHandler(_base_path, when="midnight", backupCount=7, encoding="utf-8")
# the default name after rotation will be "app.log.%Y-%m-%d"; we use a custom namer
# to convert it into "app-YYYY-MM-DD.log" exactly.
_file_handler.suffix = "%Y-%m-%d"
_file_handler.namer = lambda name: name.replace("app.log.", "app-") + ".log"
_file_handler.setLevel(Config.LOG_LEVEL)
_file_handler.setFormatter(JsonFormatter())
_root_logger.addHandler(_file_handler)

# redis stream handler
_redis_handler = RedisStreamHandler(Config.REDIS_URL, Config.REDIS_LOG_STREAM)
_redis_handler.setLevel(Config.LOG_LEVEL)
_redis_handler.setFormatter(JsonFormatter())
_root_logger.addHandler(_redis_handler)


# expose a convenience logger
logger = logging.getLogger(__name__)


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured by this module."""
    return logging.getLogger(name)
