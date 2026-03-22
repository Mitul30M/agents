"""Remediation Agent implementation.

Uses LangGraph to orchestrate:
1. Classification of the issue (code vs infrastructure)
2. Code patch generation (if applicable)
3. GitHub operations (PR or Issue creation)
"""

from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

import redis
from langgraph.graph import StateGraph, END
from langgraph.types import Command

from app.config import Config
from .schemas import (
    DiagnosisInput,
    RemediationResult,
    FixType,
    CodePatch,
    GitHubAction,
)
from .classifier import classify_issue
from .patch_generator import generate_patch, validate_patches
from .github_operations import GitHubOperations

logger = logging.getLogger(__name__)


class RemediationState(TypedDict):
    """State for the remediation workflow."""

    payload: Dict[str, Any]
    diagnosis: Optional[DiagnosisInput]
    classification: Optional[Dict[str, Any]]
    patches: list[CodePatch]
    github_actions: list[GitHubAction]
    remediation_result: Optional[RemediationResult]
    published_entry_id: Optional[str]
    human_approval: Optional[bool]
    approval_notes: Optional[str]


class RemediationAgent:
    """
    Executes corrective actions for an incident.

    Responsibilities:
    1. Classify the issue (CODE_CHANGE, INFRASTRUCTURE, UNKNOWN)
    2. If CODE_CHANGE: generate patch & create PR
    3. If INFRASTRUCTURE: create GitHub issue
    4. Include human-in-the-loop approval before execution
    """

    def __init__(
        self,
        redis_url: str | None = None,
        repo_path: str | None = None,
        diagnosis_stream: str | None = None,
        remediation_stream: str | None = None,
    ) -> None:
        self._redis = redis.from_url(redis_url or Config.REDIS_URL)
        resolved_repo_path = Path(repo_path or Config.REMEDIATION_REPO_PATH).resolve()
        if not resolved_repo_path.exists() or not resolved_repo_path.is_dir():
            raise ValueError(
                f"Invalid remediation repo path: {resolved_repo_path}. "
                "Set REMEDIATION_REPO_PATH to a valid mounted repository directory."
            )

        self._repo_path = resolved_repo_path
        self._diagnosis_stream = diagnosis_stream or Config.DIAGNOSIS_STREAM
        self._remediation_stream = remediation_stream or Config.REMEDIATION_STREAM
        self._github_ops = GitHubOperations(repo_path=str(self._repo_path))
        self._last_id: str = "0-0"
        self._workflow = self._build_remediation_graph()

    # -------------------------------------------------------------------------
    # Public API used by orchestration graph
    # -------------------------------------------------------------------------

    async def remediate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run remediation workflow for one incident payload.

        Args:
            payload: Incident payload typically from Diagnosis Agent output

        Returns:
            Dictionary with remediation results
        """
        final_state = await self._run_workflow(payload)
        result = final_state.get("remediation_result")

        if result is None:
            logger.error("Remediation workflow ended without result")
            return {
                "incident_id": str(payload.get("incident_id", "unknown")),
                "status": "failed",
                "error": "Remediation workflow did not produce a result",
            }

        return result.dict(exclude_none=True)

    async def _run_workflow(self, payload: Dict[str, Any]) -> RemediationState:
        """Execute remediation workflow and return final state."""
        initial_state: RemediationState = {
            "payload": payload,
            "diagnosis": None,
            "classification": None,
            "patches": [],
            "github_actions": [],
            "remediation_result": None,
            "published_entry_id": None,
            "human_approval": None,
            "approval_notes": None,
        }

        final_state = await self._workflow.ainvoke(initial_state)
        return final_state

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        """Continuously consume diagnosis results and run remediation."""
        logger.info(
            "Starting RemediationAgent loop (diagnosis_stream=%s, remediation_stream=%s)",
            self._diagnosis_stream,
            self._remediation_stream,
        )

        try:
            while True:
                try:
                    handled = await self._process_new_diagnoses()
                    if handled == 0:
                        await asyncio.sleep(poll_interval)
                except Exception as exc:
                    logger.exception("Error in remediation loop: %s", exc)
                    await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown
            logger.info("RemediationAgent loop cancelled; shutting down")

    async def _process_new_diagnoses(
        self, count: int = 10, block_ms: int = 1000
    ) -> int:
        """Read and process new diagnosis entries from Redis stream."""

        def _read():
            try:
                streams = {self._diagnosis_stream: self._last_id}
                return self._redis.xread(streams, count=count, block=block_ms)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception(
                    "Failed to read from diagnosis stream %s: %s",
                    self._diagnosis_stream,
                    exc,
                )
                return []

        data = await asyncio.to_thread(_read)
        if not data:
            return 0

        handled = 0
        for _stream, messages in data:
            for entry_id, fields in messages:
                self._last_id = (
                    entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
                )

                try:
                    payload = self._decode_fields(fields)
                    result = await self.remediate(payload)

                    published = await self._publish_result(result)
                    if published:
                        deleted = await asyncio.to_thread(
                            self._redis.xdel, self._diagnosis_stream, self._last_id
                        )
                        logger.info(
                            "Deleted %d diagnosis entry from %s after remediation publish: %s",
                            int(deleted),
                            self._diagnosis_stream,
                            self._last_id,
                        )
                        handled += 1
                    else:
                        logger.warning(
                            "Remediation not published for diagnosis entry %s; retained in stream",
                            self._last_id,
                        )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.exception(
                        "Failed to process diagnosis entry %s: %s", self._last_id, exc
                    )

        return handled

    async def _publish_result(self, result: Dict[str, Any]) -> bool:
        """Publish remediation result to remediation stream."""

        def _publish() -> bool:
            try:
                payload = {"data": json.dumps(result)}
                entry_id = self._redis.xadd(self._remediation_stream, payload)
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                logger.info(
                    "Published remediation %s to stream %s",
                    result.get("incident_id", "unknown-incident"),
                    self._remediation_stream,
                )
                return True
            except Exception as exc:
                logger.exception(
                    "Failed to publish remediation result to %s: %s",
                    self._remediation_stream,
                    exc,
                )
                return False

        return await asyncio.to_thread(_publish)

    @staticmethod
    def _decode_fields(fields: dict[bytes, bytes]) -> Dict[str, Any]:
        """Decode Redis stream fields into a Python dictionary."""
        decoded = {k.decode(): v.decode() for k, v in fields.items()}
        if "data" in decoded:
            try:
                return json.loads(decoded["data"])
            except Exception:
                logger.warning(
                    "Failed to parse diagnosis JSON payload; using raw fields"
                )
        return decoded

    # -------------------------------------------------------------------------
    # LangGraph node pipeline
    # -------------------------------------------------------------------------

    def _build_remediation_graph(self):
        """Build the remediation workflow graph."""
        graph = StateGraph(RemediationState)

        graph.add_node("normalize_diagnosis", self._normalize_diagnosis_node)
        graph.add_node("classify_issue", self._classify_issue_node)
        graph.add_node("generate_patches", self._generate_patches_node)
        graph.add_node("request_approval", self._request_approval_node)
        graph.add_node("create_pr", self._create_pr_node)
        graph.add_node("create_issue", self._create_issue_node)
        graph.add_node("finalize", self._finalize_node)

        graph.set_entry_point("normalize_diagnosis")
        graph.add_edge("normalize_diagnosis", "classify_issue")
        graph.add_edge("classify_issue", "generate_patches")

        # After patch generation, branch based on fix type
        graph.add_conditional_edges(
            "generate_patches",
            self._route_by_fix_type,
            {
                "code_change": "request_approval",
                "infrastructure": "create_issue",
                "unknown": "create_issue",
            },
        )

        graph.add_edge("request_approval", "create_pr")
        graph.add_edge("create_pr", "finalize")
        graph.add_edge("create_issue", "finalize")
        graph.add_edge("finalize", END)

        return graph.compile()

    async def _normalize_diagnosis_node(
        self, state: RemediationState
    ) -> RemediationState:
        """Normalize diagnosis payload into DiagnosisInput."""
        logger.info("[Remediation] Normalizing diagnosis payload")

        payload = state["payload"]

        # Support multiple payload formats (from diagnosis agent or direct)
        diagnosis = DiagnosisInput(
            incident_id=str(
                payload.get("incident_id") or payload.get("id") or "unknown-incident"
            ),
            error_logs=payload.get("error_logs") or payload.get("logs") or "",
            root_cause=payload.get("root_cause") or "Unknown",
            confidence=float(payload.get("confidence") or 0.5),
            patterns_detected=payload.get("patterns_detected", []),
            explanation=payload.get("explanation") or "",
            recommended_action=payload.get("recommended_action") or "",
        )

        logger.info(
            f"[Remediation] Diagnosis: {diagnosis.root_cause} "
            f"(confidence: {diagnosis.confidence})"
        )

        return {**state, "diagnosis": diagnosis}

    async def _classify_issue_node(self, state: RemediationState) -> RemediationState:
        """Classify the issue type."""
        diagnosis = state["diagnosis"]
        if diagnosis is None:
            logger.error("[Remediation] No diagnosis available")
            return state

        logger.info(f"[Remediation] Classifying issue for {diagnosis.incident_id}")

        classification = await classify_issue(diagnosis)

        return {
            **state,
            "classification": classification.dict(exclude_none=True),
        }

    async def _generate_patches_node(self, state: RemediationState) -> RemediationState:
        """Generate code patches if applicable."""
        classification_dict = state["classification"]
        diagnosis = state["diagnosis"]

        if not classification_dict or not diagnosis:
            logger.warning("[Remediation] Missing classification or diagnosis")
            return state

        if classification_dict.get("fix_type") != FixType.CODE_CHANGE:
            logger.info("[Remediation] Not a code change - skipping patch generation")
            return state

        logger.info(f"[Remediation] Generating patches for {diagnosis.incident_id}")

        # Convert dict back to typed object for type safety
        from .classifier import ClassificationOutput

        classification = ClassificationOutput(**classification_dict)

        patches = await generate_patch(
            self._repo_path,
            diagnosis,
            classification,
        )

        if patches:
            # Validate patches
            is_valid, validation_msg = validate_patches(patches)
            logger.info(f"[Remediation] Validation: {validation_msg}")

            if not is_valid:
                logger.error(f"[Remediation] ✗ Patches failed validation")
                return {**state, "patches": []}

        logger.info(f"[Remediation] ✓ Generated {len(patches)} patches")
        return {**state, "patches": patches}

    async def _request_approval_node(self, state: RemediationState) -> RemediationState:
        """Request human approval before applying patches.

        In a real system, this would:
        - Pause execution
        - Present patches to a human
        - Wait for approve/edit/reject

        For MVP, we'll just log and proceed (but mark that approval is needed).
        """
        diagnosis = state["diagnosis"]
        patches = state["patches"]

        if not diagnosis or not patches:
            logger.info("[Remediation] No patches to approve")
            return {**state, "human_approval": True}

        logger.info(
            f"[Remediation] ⏸ HUMAN APPROVAL REQUIRED for {diagnosis.incident_id}"
        )
        logger.info(f"Number of patches: {len(patches)}")
        for patch in patches:
            logger.info(f"  - {patch.file_path}: {patch.change_summary}")

        # TODO: Integrate with approval system (Slack, email, API endpoint)
        # For now, assume approval on patches
        logger.info(
            "[Remediation] ✓ Assuming approval (TODO: integrate approval system)"
        )

        return {**state, "human_approval": True}

    async def _create_pr_node(self, state: RemediationState) -> RemediationState:
        """Create GitHub PR with patches."""
        diagnosis = state["diagnosis"]
        patches = state["patches"]
        classification_dict = state["classification"]

        if not diagnosis or not patches:
            logger.info("[Remediation] No patches to PR - skipping")
            return state

        logger.info(f"[Remediation] Creating PR for {diagnosis.incident_id}")

        try:
            # Create feature branch
            fix_type = (classification_dict or {}).get("suggested_fix_area", "fix")
            # Sanitize branch name
            sanitized_fix = fix_type.lower().replace(" ", "-").replace("_", "-")[:30]
            branch_name = f"fix/{sanitized_fix}-{diagnosis.incident_id[:8]}"

            success, msg = self._github_ops.create_branch(branch_name)
            if not success:
                raise Exception(f"Failed to create branch: {msg}")

            requested_files = [p.file_path for p in patches]
            stageable_files, ignored_files = self._github_ops.filter_stageable_paths(
                requested_files
            )

            if ignored_files:
                logger.warning(
                    "[Remediation] Skipping git-ignored/non-stageable files: %s",
                    ", ".join(ignored_files),
                )

            if not stageable_files:
                raise Exception(
                    "All generated patches target ignored/non-stageable files. "
                    "Cannot create commit."
                )

            # Apply patches
            for patch in patches:
                if patch.file_path not in stageable_files:
                    continue
                success, msg = self._github_ops.apply_patch(
                    patch.file_path,
                    patch.original_content,
                    patch.patched_content,
                )
                if not success:
                    logger.warning(f"[Remediation] Failed to apply patch: {msg}")

            # Stage changes
            file_paths = stageable_files
            success, msg = self._github_ops.stage_changes(file_paths)
            if not success:
                raise Exception(f"Failed to stage changes: {msg}")

            # Commit
            commit_msg = f"fix: {diagnosis.root_cause[:50]}\n\n{diagnosis.explanation}"
            success, msg = self._github_ops.commit_changes(commit_msg, file_paths)
            if not success:
                raise Exception(f"Failed to commit: {msg}")

            # Create PR
            pr_title = f"Fix: {diagnosis.root_cause[:60]}"
            pr_body = self._generate_pr_description(diagnosis, patches)

            success, pr_number, msg = self._github_ops.create_pull_request(
                title=pr_title,
                body=pr_body,
                base_branch="main",
                head_branch=branch_name,
            )

            action = GitHubAction(
                action_type="create_pr",
                status="success" if success else "failed",
                pr_number=pr_number,
                error_message=msg if not success else None,
            )

            logger.info(f"[Remediation] PR creation: {action.status}")

            # Checkout back to main
            self._github_ops.checkout_main()

            return {
                **state,
                "github_actions": state["github_actions"] + [action],
            }

        except Exception as e:
            logger.error(f"[Remediation] Failed to create PR: {e}")
            action = GitHubAction(
                action_type="create_pr",
                status="failed",
                error_message=str(e),
            )
            return {
                **state,
                "github_actions": state["github_actions"] + [action],
            }

    async def _create_issue_node(self, state: RemediationState) -> RemediationState:
        """Create GitHub issue for infrastructure/unknown issues."""
        diagnosis = state["diagnosis"]

        if not diagnosis:
            return state

        logger.info(f"[Remediation] Creating issue for {diagnosis.incident_id}")

        try:
            fix_type = (state.get("classification") or {}).get(
                "fix_type", FixType.UNKNOWN
            )

            if fix_type == FixType.INFRASTRUCTURE:
                title = f"Infrastructure Issue: {diagnosis.root_cause[:60]}"
                labels = ["infrastructure", "incident"]
            else:
                title = f"Investigation Required: {diagnosis.root_cause[:60]}"
                labels = ["needs-investigation", "incident"]

            body = self._generate_issue_description(diagnosis)

            success, issue_number, msg = self._github_ops.create_issue(
                title=title,
                body=body,
                labels=labels,
            )

            action = GitHubAction(
                action_type="create_issue",
                status="success" if success else "failed",
                issue_number=issue_number,
                error_message=msg if not success else None,
            )

            logger.info(f"[Remediation] Issue creation: {action.status}")

            return {
                **state,
                "github_actions": state["github_actions"] + [action],
            }

        except Exception as e:
            logger.error(f"[Remediation] Failed to create issue: {e}")
            action = GitHubAction(
                action_type="create_issue",
                status="failed",
                error_message=str(e),
            )
            return {
                **state,
                "github_actions": state["github_actions"] + [action],
            }

    async def _finalize_node(self, state: RemediationState) -> RemediationState:
        """Finalize remediation and create result."""
        diagnosis = state["diagnosis"]
        classification_dict = state["classification"]
        patches = state["patches"]
        github_actions = state["github_actions"]

        if not diagnosis:
            return state

        fix_type_str = (classification_dict or {}).get("fix_type", FixType.UNKNOWN)
        fix_type = FixType(fix_type_str)

        # Determine next steps
        if fix_type == FixType.CODE_CHANGE:
            if github_actions:
                pr_action = next(
                    (a for a in github_actions if a.action_type == "create_pr"), None
                )
                issue_action = next(
                    (a for a in github_actions if a.action_type == "create_issue"),
                    None,
                )
                if pr_action and pr_action.status == "success":
                    next_steps = f"PR #{pr_action.pr_number} created. Awaiting code review and merge."
                elif issue_action and issue_action.status == "success":
                    next_steps = (
                        f"No safe patch was generated automatically. "
                        f"Issue #{issue_action.issue_number} created for investigation."
                    )
                else:
                    next_steps = "Manual investigation/PR creation required due to automation failure."
            else:
                next_steps = "No GitHub action completed. Manual investigation required."
        else:
            if github_actions:
                issue_action = next(
                    (a for a in github_actions if a.action_type == "create_issue"), None
                )
                if issue_action and issue_action.status == "success":
                    next_steps = (
                        f"Issue #{issue_action.issue_number} created. "
                        "Manual investigation and action required."
                    )
                else:
                    next_steps = "Manual issue creation and investigation required."
            else:
                next_steps = "Manual investigation required."

        result = RemediationResult(
            incident_id=diagnosis.incident_id,
            fix_type=fix_type,
            decision=fix_type.value,
            classification_reasoning=(classification_dict or {}).get("reasoning", ""),
            github_actions=github_actions,
            patches_generated=patches,
            explanation=diagnosis.explanation,
            next_steps=next_steps,
        )

        logger.info(
            f"[Remediation] ✓ Completed for {diagnosis.incident_id}: {fix_type}"
        )

        return {**state, "remediation_result": result}

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _route_by_fix_type(self, state: RemediationState) -> str:
        """Route to appropriate handler based on classification."""
        classification_dict = state.get("classification", {})
        fix_type = classification_dict.get("fix_type", FixType.UNKNOWN)

        if fix_type == FixType.CODE_CHANGE and state.get("patches"):
            return "code_change"

        # If classified as code change but no patch could be generated, escalate
        # as investigation-required instead of silently skipping PR creation.
        return "unknown"

    def _generate_pr_description(
        self,
        diagnosis: DiagnosisInput,
        patches: list[CodePatch],
    ) -> str:
        """Generate comprehensive PR description."""
        return f"""## 🔧 Automated Remediation PR

### Issue Summary
{diagnosis.root_cause}

### Root Cause Analysis
{diagnosis.explanation}

### Confidence Level
{int(diagnosis.confidence * 100)}%

### Patterns Detected
{', '.join(diagnosis.patterns_detected) if diagnosis.patterns_detected else 'None'}

### Changes Made
{len(patches)} file(s) modified:

{chr(10).join([f'- {p.file_path}: {p.change_summary}' for p in patches])}

### Recommended Action
{diagnosis.recommended_action}

### Risk Assessment
This PR contains automated fixes based on LLM analysis. Please review carefully before merging.

⚠️ **Before merging:**
1. Review all changes carefully
2. Run full test suite
3. Check for any side effects
4. Consider staging deployment first

---
*Generated by Remediation Agent on {datetime.now().isoformat()}*
"""

    def _generate_issue_description(self, diagnosis: DiagnosisInput) -> str:
        """Generate comprehensive issue description."""
        return f"""## 🚨 Automated Incident Report

### Root Cause
**{diagnosis.root_cause}**

### Analysis
{diagnosis.explanation}

### Confidence Level
{int(diagnosis.confidence * 100)}%

### Patterns Detected
- {chr(10).join([f'- {p}' for p in diagnosis.patterns_detected]) if diagnosis.patterns_detected else 'None detected'}

### Error Logs
```
{diagnosis.error_logs[:500]}...
```

### Recommended Action
{diagnosis.recommended_action}

### Next Steps
1. Investigate the issue manually
2. Determine if this requires infrastructure changes, deployment, or ops action
3. Execute appropriate remediation
4. Update this issue with resolution details

---
*Generated by Remediation Agent on {datetime.now().isoformat()}*
*Incident ID: {diagnosis.incident_id}*
"""


__all__ = ["RemediationAgent"]
