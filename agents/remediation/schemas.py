"""Typed schemas for the remediation agent."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class FixType(str, Enum):
    """Classification of issue type."""
    CODE_CHANGE = "CODE_CHANGE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


class DiagnosisInput(BaseModel):
    """Input from the Diagnosis Agent."""
    
    incident_id: str
    error_logs: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    patterns_detected: List[str] = Field(default_factory=list)
    explanation: str
    recommended_action: str


class ClassificationResult(BaseModel):
    """Result of issue classification."""
    
    fix_type: FixType
    reasoning: str
    affected_files: List[str] = Field(default_factory=list)
    suggested_fix_area: Optional[str] = None


class CodePatch(BaseModel):
    """Generated code patch."""
    
    file_path: str
    original_content: str
    patched_content: str
    description: str
    change_summary: str


class PRMetadata(BaseModel):
    """Metadata for creating a GitHub PR."""
    
    title: str
    branch_name: str
    description: str
    change_summary: str
    risk_assessment: str
    files_changed: List[str]
    patches: List[CodePatch] = Field(default_factory=list)


class GitHubAction(BaseModel):
    """Result of a GitHub operation."""
    
    action_type: str  # "create_pr" | "create_issue"
    status: str  # "success" | "failed"
    url: Optional[str] = None
    issue_number: Optional[int] = None
    pr_number: Optional[int] = None
    error_message: Optional[str] = None


class RemediationResult(BaseModel):
    """Final remediation output."""
    
    incident_id: str
    fix_type: FixType
    decision: str
    classification_reasoning: str
    github_actions: List[GitHubAction] = Field(default_factory=list)
    patches_generated: List[CodePatch] = Field(default_factory=list)
    explanation: str
    next_steps: Optional[str] = None


__all__ = [
    "FixType",
    "DiagnosisInput",
    "ClassificationResult",
    "CodePatch",
    "PRMetadata",
    "GitHubAction",
    "RemediationResult",
]
