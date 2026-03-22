"""Issue classifier for the remediation agent.

Uses LLM to decide if an issue is fixable via code changes or is an infrastructure problem.
"""

from __future__ import annotations

import logging
import json
from typing import Any, Dict

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from .schemas import FixType, ClassificationResult, DiagnosisInput
from app.config import Config

logger = logging.getLogger(__name__)


class ClassificationOutput(BaseModel):
    """Structured output from the classifier LLM."""
    
    fix_type: FixType = Field(
        ...,
        description="CODE_CHANGE, INFRASTRUCTURE, or UNKNOWN"
    )
    reasoning: str = Field(
        ...,
        description="Detailed explanation of the classification decision"
    )
    affected_files: list[str] = Field(
        default_factory=list,
        description="If CODE_CHANGE, list of likely affected files"
    )
    suggested_fix_area: str | None = Field(
        default=None,
        description="Brief description of what area needs fixing"
    )
    confidence_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in this classification"
    )


CLASSIFICATION_PROMPT = """You are an expert software engineer analyzing incident diagnostics.

Based on the error logs and diagnosis, determine if this issue can be fixed by modifying code.

## Input Diagnosis:
Root Cause: {root_cause}
Confidence: {confidence}%
Patterns Detected: {patterns}
Explanation: {explanation}

## Decision Framework:

**CODE_CHANGE** (fixable by modifying application code):
- Syntax errors
- Missing imports or functions
- Incorrect API/library usage
- Logic bugs or wrong algorithms
- Misconfigured values in code (wrong constants, thresholds)
- Type errors or null pointer dereferences
- Missing validation or error handling
- Incorrect data transformations

**INFRASTRUCTURE** (requires ops/deployment changes):
- Service/container down (Redis, DB, Docker)
- Network connectivity issues
- Environment variables missing or misconfigured
- Port conflicts or firewall issues
- Resource exhaustion (memory, disk, CPU)
- Service not responding to health checks
- Deployment/configuration tool failures
- External service timeouts

**UNKNOWN** (unclear or insufficient information):
- Ambiguous diagnostics
- Multiple possible root causes
- Insufficient information to classify

## Your Task:

Analyze the diagnosis and classify it into one of the three categories above.

Return ONLY valid JSON with this exact structure:
{{
    "fix_type": "CODE_CHANGE" | "INFRASTRUCTURE" | "UNKNOWN",
    "reasoning": "Clear explanation of why you chose this type",
    "affected_files": ["file1.py", "file2.ts"],  // empty list if not CODE_CHANGE
    "suggested_fix_area": "Brief description of what needs fixing" or null,
    "confidence_score": 0.85
}}
"""


async def classify_issue(diagnosis: DiagnosisInput) -> ClassificationResult:
    """Classify whether an issue is a code change, infrastructure, or unknown.
    
    Args:
        diagnosis: Input from the Diagnosis Agent
        
    Returns:
        ClassificationResult with fix type and reasoning
    """
    logger.info(
        f"[Classifier] Classifying incident {diagnosis.incident_id}: "
        f"{diagnosis.root_cause}"
    )

    # Prepare LLM
    llm = ChatOllama(
        model=Config.REMEDIATION_AGENT_LLM,
        temperature=0.1,
        base_url=Config.OLLAMA_BASE_URL,
    )

    # Prepare patterns string
    patterns_str = ", ".join(diagnosis.patterns_detected) if diagnosis.patterns_detected else "none"

    # Build prompt
    prompt = CLASSIFICATION_PROMPT.format(
        root_cause=diagnosis.root_cause,
        confidence=int(diagnosis.confidence * 100),
        patterns=patterns_str,
        explanation=diagnosis.explanation,
    )

    try:
        # Call LLM with structured output
        llm_with_struct = llm.with_structured_output(ClassificationOutput)
        response = await llm_with_struct.ainvoke(prompt)

        logger.info(
            f"[Classifier] Classification: {response.fix_type} "
            f"(confidence: {response.confidence_score})"
        )

        return ClassificationResult(
            fix_type=response.fix_type,
            reasoning=response.reasoning,
            affected_files=response.affected_files,
            suggested_fix_area=response.suggested_fix_area,
        )

    except Exception as e:
        logger.error(f"[Classifier] LLM error: {e}. Falling back to heuristic.")

        # Fallback heuristic classification
        root_cause_lower = diagnosis.root_cause.lower()

        # Infrastructure keywords
        infra_keywords = [
            "redis", "database", "container", "docker", "service",
            "network", "connection", "timeout", "port", "env",
            "environment", "deployment", "crashed", "down",
            "unavailable", "unreachable", "refused"
        ]

        # Code keywords
        code_keywords = [
            "syntax", "import", "undefined", "null", "error handling",
            "algorithm", "logic", "type", "reference", "value",
            "function", "method", "missing", "incorrect"
        ]

        is_infra = any(kw in root_cause_lower for kw in infra_keywords)
        is_code = any(kw in root_cause_lower for kw in code_keywords)

        if is_code and not is_infra:
            fix_type = FixType.CODE_CHANGE
            reasoning = "Heuristic: Keywords suggest code-level fix"
        elif is_infra and not is_code:
            fix_type = FixType.INFRASTRUCTURE
            reasoning = "Heuristic: Keywords suggest infrastructure issue"
        else:
            fix_type = FixType.UNKNOWN
            reasoning = "Heuristic: Ambiguous or multiple factors involved"

        return ClassificationResult(
            fix_type=fix_type,
            reasoning=reasoning,
            affected_files=[],
            suggested_fix_area=None,
        )


__all__ = ["classify_issue", "ClassificationOutput"]
