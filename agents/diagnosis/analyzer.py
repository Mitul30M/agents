from __future__ import annotations

"""LLM-based pattern detection over log context using Ollama.

This module asks an Ollama-hosted open-source model to look at a window of
log lines and return a *structured* list of error pattern identifiers.  This
means we are no longer limited to a fixed set of hard-coded keywords; the
model can surface new patterns as they appear in production.
"""

from typing import Iterable, List
import asyncio
import json
import logging
import re

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from app.config import Config

logger = logging.getLogger(__name__)


def _heuristic_patterns(text: str) -> List[str]:
    """Best-effort fallback when LLM structured parsing fails."""
    lowered = text.lower()
    patterns: set[str] = set()

    keyword_to_pattern = {
        "timeout": "timeout",
        "connection refused": "connection_refused",
        "all connection attempts failed": "connection_attempts_failed",
        "503": "http_503",
        "502": "http_502",
        "500": "http_500",
        "ollamaerror": "ollama_error",
        "rate limit": "rate_limit_exceeded",
        "out of memory": "memory_error",
    }

    for keyword, pattern in keyword_to_pattern.items():
        if keyword in lowered:
            patterns.add(pattern)

    # detect common `chat.post.stream.error` or similar dotted signatures
    for match in re.findall(r"[a-z0-9_]+(?:\.[a-z0-9_]+){2,}", lowered):
        if "error" in match:
            patterns.add(match.replace(".", "_"))

    return sorted(patterns)


class PatternAnalysis(BaseModel):
    """Structured output schema for pattern detection."""

    patterns: List[str] = Field(
        default_factory=list,
        description="Short, machine-readable pattern identifiers, e.g. "
        "database_timeout, api_upstream_failure, memory_error.",
    )
    reasoning: str = Field(
        default="",
        description="Optional natural-language explanation of why these patterns were detected.",
    )


async def detect_patterns(log_lines: Iterable[str]) -> List[str]:
    """Use an Ollama LLM to detect error patterns in log lines.

    Args:
        log_lines: Iterable of raw log line strings from the surrounding
            incident window.

    Returns:
        A list of pattern identifiers (strings). The model is encouraged to
        emit short, kebab/underscore-case labels such as `database_timeout`,
        `api_upstream_failure`, `memory_error`, etc.
    """
    text = "\n".join(log_lines).strip()
    if not text:
        return []

    llm = ChatOllama(
        model=Config.DIAGNOSIS_AGENT_LLM,
        temperature=0.1,
        base_url=Config.OLLAMA_BASE_URL,
        format="json",
    )

    structured_llm = llm.with_structured_output(PatternAnalysis)

    prompt = (
        "You are an expert SRE reading application logs from a production "
        "Next.js service. Look for *recurring* error patterns and output "
        "concise, machine-readable pattern identifiers.\n\n"
        "Guidelines:\n"
        "- Use short slugs like `database_timeout`, `api_upstream_failure`, "
        "`memory_error`, `dependency_crash`, `connection_refused`.\n"
        "- You MAY invent new slugs if needed (e.g. `auth_failure`, "
        "`rate_limit_exceeded`).\n"
        "- Only include patterns that are clearly supported by the logs.\n\n"
        "Logs:\n"
        f"{text}\n"
    )

    try:
        result = await structured_llm.ainvoke(prompt)
        patterns = {p.strip().lower() for p in result.patterns if p.strip()}
        logger.debug("LLM pattern detection yielded: %s", patterns)
        return sorted(patterns)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Pattern detection via Ollama failed: %s", exc)
        return _heuristic_patterns(text)


__all__ = ["detect_patterns", "PatternAnalysis"]
