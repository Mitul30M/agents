"""Code patch generator for the remediation agent.

Generates minimal, safe code patches based on diagnostics and source files.
"""

from __future__ import annotations

import logging
import json
import os
import re
from pathlib import Path
from typing import Optional
from app.config import Config

from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from .schemas import CodePatch, DiagnosisInput, ClassificationResult

logger = logging.getLogger(__name__)


class PatchGenerationOutput(BaseModel):
    """Structured patch generation output."""
    
    file_path: str = Field(..., description="Path to file relative to repo root")
    description: str = Field(..., description="What was changed and why")
    change_summary: str = Field(..., description="High-level summary of changes")
    original_content: str = Field(..., description="Original file content")
    patched_content: str = Field(..., description="New file content with patch applied")


PATCH_GENERATION_PROMPT = """You are an expert Python developer reviewing error diagnostics and generating code fixes.

## Error Analysis:
Root Cause: {root_cause}
Diagnosis: {explanation}
Affected Files: {affected_files}
Suggested Fix Area: {suggested_fix_area}

## Source File Context:
File: {file_path}
Content:
{file_content}

## Your Task:

Generate a minimal, correct code patch that fixes the issue. You MUST:

1. Keep changes minimal and focused on the root cause
2. Preserve existing code style and formatting
3. Add explanatory comments for the fix
4. Never break existing functionality
5. Return ONLY the modified file content

Guidelines:
- For missing imports: add at the top with existing imports
- For logic bugs: fix the specific logic error, not unrelated code
- For configuration: update hard-coded values or defaults
- For error handling: add try-catch or validation before operations
- For null checks: add guards before dereferencing

Return the COMPLETE updated file content below.
Include all original content plus your fix.
Do NOT include explanations or comments about the patch outside the code.

---
PATCHED CODE:
"""


async def generate_patch(
    repo_path: str | Path,
    diagnosis: DiagnosisInput,
    classification: ClassificationResult,
    file_path: Optional[str] = None,
) -> list[CodePatch]:
    """Generate code patches for the issue.
    
    Args:
        repo_path: Path to the repository root
        diagnosis: Diagnosis information
        classification: Classification result
        file_path: Specific file to patch (if None, uses classification hints)
        
    Returns:
        List of CodePatch objects
    """
    logger.info(
        f"[PatchGenerator] Generating patches for {diagnosis.incident_id}"
    )

    repo_path = Path(repo_path)
    patches: list[CodePatch] = []

    excluded_dirs = {"node_modules", ".next", ".git", "logs", "dist", "build"}

    def _iter_repo_files() -> list[Path]:
        files: list[Path] = []
        for root, dirs, filenames in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            for name in filenames:
                files.append(Path(root) / name)
        return files

    def _detect_repo_type() -> str:
        has_package_json = (repo_path / "package.json").exists()
        has_next_signals = (
            any(
                (repo_path / name).exists()
                for name in ["next.config.ts", "next.config.js", "next-env.d.ts"]
            )
            or (repo_path / "app").exists()
        )

        if has_package_json and has_next_signals:
            return "nextjs"
        if (repo_path / "requirements.txt").exists() or (
            repo_path / "pyproject.toml"
        ).exists():
            return "python"
        return "generic"

    def _tokenize(text: str) -> list[str]:
        raw = re.findall(r"[a-zA-Z0-9_\-/\.]+", text.lower())
        stop = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "that",
            "this",
            "into",
            "error",
            "failed",
            "issue",
            "service",
            "application",
            "requests",
            "request",
            "resulting",
        }
        tokens = [t for t in raw if len(t) >= 3 and t not in stop]
        return list(dict.fromkeys(tokens))

    def _allow_file_for_repo_type(rel: str, ext: str, repo_type: str) -> bool:
        rel_lower = rel.lower()
        if repo_type == "nextjs":
            if rel_lower.startswith(("app/", "lib/", "components/", "public/")):
                return ext in {".ts", ".tsx", ".js", ".mjs", ".cjs", ".json"}
            if rel_lower in {
                "package.json",
                "next.config.ts",
                "next.config.js",
                "tsconfig.json",
            }:
                return True
            if rel_lower == ".env.example":
                return True
            return False

        if repo_type == "python":
            if ext in {".py", ".toml", ".ini", ".yaml", ".yml", ".json"}:
                return True
            if rel_lower in {"requirements.txt", ".env.example"}:
                return True
            return False

        return ext in {
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".json",
            ".toml",
            ".yaml",
            ".yml",
            ".ini",
            ".md",
        }

    def _find_by_basename(name: str) -> list[str]:
        matches: list[str] = []
        target = Path(name).name.lower()
        if not target:
            return matches
        for file_path in _iter_repo_files():
            if file_path.name.lower() == target:
                matches.append(str(file_path.relative_to(repo_path)).replace("\\", "/"))
        return matches

    def _discover_target_files() -> list[str]:
        repo_type = _detect_repo_type()
        context = f"{diagnosis.root_cause} {diagnosis.explanation} {classification.suggested_fix_area or ''}".lower()
        tokens = _tokenize(context)

        include_env_template = any(
            k in context
            for k in ["env", "environment", "variable", "api key", "base url"]
        )
        scored: list[tuple[int, str]] = []

        for file_path in _iter_repo_files():
            rel = str(file_path.relative_to(repo_path)).replace("\\", "/")
            rel_lower = rel.lower()
            ext = file_path.suffix.lower()

            # Never edit local secret files automatically.
            if rel_lower == ".env.local":
                continue
            if rel_lower == ".env.example" and not include_env_template:
                continue

            if not _allow_file_for_repo_type(rel, ext, repo_type):
                continue

            score = 0

            # Prioritize API/route files for chat/model failures in Next.js repos.
            if repo_type == "nextjs" and any(
                k in context for k in ["chat", "ollama", "model", "503", "404"]
            ):
                if "/api/" in rel_lower or "route." in rel_lower:
                    score += 8
                if "chat" in rel_lower:
                    score += 4

            # Generic lexical relevance scoring.
            for token in tokens:
                if token in rel_lower:
                    score += 2

            if score > 0:
                scored.append((score, rel))

        scored.sort(key=lambda item: (-item[0], item[1]))

        # Keep fixes focused; avoid broad, unrelated edits.
        max_files = max(1, int(getattr(Config, "REMEDIATION_PATCH_MAX_FILES", 2)))
        if not scored:
            return []

        top_score = scored[0][0]
        # Only keep files close to the best evidence score.
        min_score = max(1, top_score - 2)
        selected = [rel for score, rel in scored if score >= min_score][:max_files]

        # Hard preference for API route when diagnosis clearly points to chat/model failures.
        if repo_type == "nextjs" and any(
            k in context for k in ["ollama", "model", "chat", "404", "503"]
        ):
            route = "app/api/chat/route.ts"
            if route in selected:
                selected = [route] + [f for f in selected if f != route]
            elif (repo_path / route).exists():
                selected = [route] + selected
                selected = selected[:max_files]

        if selected:
            logger.info(
                "[PatchGenerator] Repo-aware discovery selected files: %s",
                ", ".join(selected),
            )
        return selected

    def _resolve_repo_relative(file_to_patch: str) -> Path:
        candidate = (repo_path / file_to_patch).resolve()
        try:
            candidate.relative_to(repo_path.resolve())
        except ValueError as exc:
            raise ValueError(
                f"Target path escapes repository root: {file_to_patch}"
            ) from exc
        return candidate

    # Determine which files to target
    target_files = [file_path] if file_path else list(classification.affected_files)

    # Resolve non-existing guessed paths (e.g. chat_service.py) to actual repo files.
    resolved_targets: list[str] = []
    for target in target_files:
        try:
            candidate = _resolve_repo_relative(target)
            if candidate.exists() and candidate.is_file():
                resolved_targets.append(target)
                continue
        except ValueError:
            pass

        basename_matches = _find_by_basename(target)
        if basename_matches:
            resolved_targets.append(basename_matches[0])

    target_files = resolved_targets

    # If classifier supplied invalid/non-existing files, try context-driven discovery.
    if not target_files:
        target_files = _discover_target_files()

    if not target_files:
        logger.warning(
            "[PatchGenerator] No resolvable target files after fallback discovery."
        )

    if not target_files:
        logger.warning(
            "[PatchGenerator] No target files specified. "
            "Cannot generate patches."
        )
        return patches

    # Prepare LLM
    llm = ChatOllama(
        model=Config.REMEDIATION_AGENT_LLM,
        temperature=0.1,
        base_url=Config.OLLAMA_BASE_URL,
    )

    for file_to_patch in target_files:
        try:
            file_full_path = _resolve_repo_relative(file_to_patch)
        except ValueError as e:
            logger.warning(f"[PatchGenerator] Invalid target path: {e}. Skipping.")
            continue

        # Check if file exists
        if not file_full_path.exists():
            logger.warning(
                f"[PatchGenerator] File not found: {file_to_patch}. Skipping."
            )
            continue

        # Read original file content
        try:
            with open(file_full_path, "r", encoding="utf-8") as f:
                original_content = f.read()
        except Exception as e:
            logger.error(f"[PatchGenerator] Failed to read {file_to_patch}: {e}")
            continue

        logger.info(f"[PatchGenerator] Patching {file_to_patch}")

        # Build patch prompt
        affected_files_str = ", ".join(classification.affected_files or [file_to_patch])
        prompt = PATCH_GENERATION_PROMPT.format(
            root_cause=diagnosis.root_cause,
            explanation=diagnosis.explanation,
            affected_files=affected_files_str,
            suggested_fix_area=classification.suggested_fix_area or "code fix needed",
            file_path=file_to_patch,
            file_content=original_content,
        )

        try:
            # Call LLM
            response = await llm.ainvoke(prompt)
            patched_content = response.content.strip()

            # Remove markdown code block markers if present
            if patched_content.startswith("```"):
                patched_content = "\n".join(
                    patched_content.split("\n")[1:]
                ).rstrip("`").rstrip()

            # Create patch object
            patch = CodePatch(
                file_path=file_to_patch,
                original_content=original_content,
                patched_content=patched_content,
                description=f"Fix for: {diagnosis.root_cause}",
                change_summary=f"Applied fix to {file_to_patch}",
            )

            patches.append(patch)
            logger.info(f"[PatchGenerator] ✓ Generated patch for {file_to_patch}")
        except Exception as e:
            logger.error(
                f"[PatchGenerator] Failed to generate patch for {file_to_patch}: {e}"
            )
            continue

    return patches


def validate_patches(patches: list[CodePatch]) -> tuple[bool, str]:
    """Validate that patches are syntactically correct (for Python files).
    
    Args:
        patches: List of patches to validate
        
    Returns:
        Tuple of (is_valid, message)
    """
    logger.info(f"[PatchValidator] Validating {len(patches)} patches")
    
    for patch in patches:
        if not patch.file_path.endswith(".py"):
            continue  # Skip non-Python files
        
        try:
            compile(patch.patched_content, patch.file_path, "exec")
            logger.info(f"[PatchValidator] ✓ {patch.file_path} is syntactically valid")
        except SyntaxError as e:
            logger.error(
                f"[PatchValidator] ✗ Syntax error in {patch.file_path}: {e}"
            )
            return False, f"Syntax error in {patch.file_path}: {e}"
    
    return True, "All patches validated"


__all__ = ["generate_patch", "validate_patches", "PatchGenerationOutput"]
