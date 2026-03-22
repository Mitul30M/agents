"""GitHub operations utilities for the remediation agent."""

from __future__ import annotations

import logging
import subprocess
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class GitHubOperations:
    """Wrapper around GitHub CLI and git operations."""

    def __init__(
        self,
        repo_path: str = ".",
        github_token: Optional[str] = None,
    ):
        """Initialize GitHub operations handler.
        
        Args:
            repo_path: Path to the git repository
            github_token: GitHub API token (uses GH_TOKEN env var if not provided)
        """
        self.repo_path = Path(repo_path).resolve()
        self.github_token = github_token

    def _resolve_repo_relative_path(self, file_path: str) -> Path:
        """Resolve a repo-relative path and enforce it stays inside repo root."""
        candidate = (self.repo_path / file_path).resolve()
        try:
            candidate.relative_to(self.repo_path)
        except ValueError as exc:
            raise ValueError(
                f"Path escapes repository root: {file_path}"
            ) from exc
        return candidate

    def _run_git_command(
        self, 
        command: List[str],
        cwd: Optional[Path] = None,
    ) -> tuple[bool, str, str]:
        """Run a git command and return success, stdout, stderr.
        
        Args:
            command: List of command arguments (e.g., ["git", "status"])
            cwd: Working directory for the command
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        try:
            result = subprocess.run(
                command,
                cwd=cwd or self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def _run_gh_command(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
    ) -> tuple[bool, str, str]:
        """Run a GitHub CLI command.
        
        Args:
            command: List of command arguments (e.g., ["gh", "pr", "list"])
            cwd: Working directory for the command
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        return self._run_git_command(command, cwd)

    def is_ignored_path(self, file_path: str) -> bool:
        """Return True if path is ignored by gitignore rules."""
        try:
            safe_rel = str(
                self._resolve_repo_relative_path(file_path).relative_to(self.repo_path)
            )
        except ValueError:
            return True

        result = subprocess.run(
            ["git", "check-ignore", "-q", safe_rel],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0

    def filter_stageable_paths(self, file_paths: list[str]) -> tuple[list[str], list[str]]:
        """Split paths into stageable and ignored lists."""
        stageable: list[str] = []
        ignored: list[str] = []

        for path in file_paths:
            try:
                safe_rel = str(
                    self._resolve_repo_relative_path(path).relative_to(self.repo_path)
                )
            except ValueError:
                ignored.append(path)
                continue

            if self.is_ignored_path(safe_rel):
                ignored.append(safe_rel)
            else:
                stageable.append(safe_rel)

        return stageable, ignored

    def create_branch(self, branch_name: str) -> tuple[bool, str]:
        """Create and checkout a new branch.
        
        Args:
            branch_name: Name of the branch (e.g., "fix/redis-connection")
            
        Returns:
            Tuple of (success, message)
        """
        success, stdout, stderr = self._run_git_command(
            ["git", "checkout", "-b", branch_name],
        )

        if success:
            logger.info(f"✓ Created branch: {branch_name}")
            return True, f"Created branch {branch_name}"
        else:
            logger.error(f"✗ Failed to create branch {branch_name}: {stderr}")
            return False, f"Failed to create branch: {stderr}"

    def push_branch(self, branch_name: str) -> tuple[bool, str]:
        """Push a branch to origin and set upstream.

        Args:
            branch_name: Branch name to push

        Returns:
            Tuple of (success, message)
        """
        success, _, stderr = self._run_git_command(
            ["git", "push", "-u", "origin", branch_name]
        )

        if not success and "could not read username" in stderr.lower():
            token = (
                self.github_token or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
            )
            if token:
                remote_success, remote_url, remote_err = self._run_git_command(
                    ["git", "remote", "get-url", "origin"]
                )
                if remote_success and remote_url.startswith("https://github.com/"):
                    auth_remote = remote_url.replace(
                        "https://", f"https://x-access-token:{token}@", 1
                    )
                    success, _, stderr = self._run_git_command(
                        [
                            "git",
                            "push",
                            "-u",
                            auth_remote,
                            f"{branch_name}:{branch_name}",
                        ]
                    )
                elif not remote_success:
                    logger.warning(
                        "Unable to read origin remote URL for token-based push fallback: %s",
                        remote_err,
                    )

        if success:
            logger.info(f"✓ Pushed branch to origin: {branch_name}")
            return True, f"Pushed branch {branch_name}"

        logger.error(f"✗ Failed to push branch {branch_name}: {stderr}")
        return False, f"Failed to push branch: {stderr}"

    def get_working_tree_status(self) -> str:
        """Return porcelain status for the repository working tree."""
        success, stdout, _ = self._run_git_command(["git", "status", "--porcelain"])
        if not success:
            return ""
        return stdout

    def apply_patch(
        self,
        file_path: str,
        original_content: str,
        patched_content: str,
    ) -> tuple[bool, str]:
        """Apply a patch to a file.
        
        Args:
            file_path: Path to the file relative to repo root
            original_content: Expected original content
            patched_content: New content to write
            
        Returns:
            Tuple of (success, message)
        """
        try:
            file_full_path = self._resolve_repo_relative_path(file_path)
        except ValueError as e:
            logger.error(f"✗ Invalid path {file_path}: {e}")
            return False, str(e)

        # Validate file exists
        if not file_full_path.exists():
            logger.error(f"✗ File does not exist: {file_path}")
            return False, f"File does not exist: {file_path}"

        # Validate original content matches
        try:
            with open(file_full_path, "r", encoding="utf-8") as f:
                current_content = f.read()
        except Exception as e:
            logger.error(f"✗ Failed to read {file_path}: {e}")
            return False, f"Failed to read file: {e}"

        if current_content != original_content:
            logger.warning(
                f"⚠ Content mismatch in {file_path}. "
                f"File may have been modified."
            )
            # Don't fail - proceed with caution

        # Apply patch
        try:
            with open(file_full_path, "w", encoding="utf-8") as f:
                f.write(patched_content)
            logger.info(f"✓ Patched file: {file_path}")
            return True, f"Patched {file_path}"
        except Exception as e:
            logger.error(f"✗ Failed to patch {file_path}: {e}")
            return False, f"Failed to patch file: {e}"

    def stage_changes(self, file_paths: list[str] | None = None) -> tuple[bool, str]:
        """Stage changes for commit.
        
        Args:
            file_paths: List of file paths to stage. If None, stages all changes.
            
        Returns:
            Tuple of (success, message)
        """
        if file_paths:
            safe_paths, ignored_paths = self.filter_stageable_paths(file_paths)

            if ignored_paths:
                logger.warning(
                    "Skipping ignored/non-stageable files during staging: %s",
                    ", ".join(ignored_paths),
                )

            if not safe_paths:
                logger.error("✗ No stageable files after filtering ignored paths")
                return False, "No stageable files after filtering ignored paths"

            cmd = ["git", "add"] + safe_paths
        else:
            cmd = ["git", "add", "-A"]

        success, stdout, stderr = self._run_git_command(cmd)

        if success:
            logger.info(f"✓ Staged changes")
            return True, "Changes staged"
        else:
            logger.error(f"✗ Failed to stage changes: {stderr}")
            return False, f"Failed to stage: {stderr}"

    def commit_changes(
        self,
        message: str,
        file_paths: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Commit changes to the branch.
        
        Args:
            message: Commit message
            file_paths: List of file paths to commit. If None, commits all staged.
            
        Returns:
            Tuple of (success, message)
        """
        cmd = ["git", "commit", "-m", message]
        if file_paths:
            try:
                safe_paths = [
                    str(self._resolve_repo_relative_path(path).relative_to(self.repo_path))
                    for path in file_paths
                ]
            except ValueError as e:
                logger.error(f"✗ Invalid path while committing: {e}")
                return False, str(e)
            cmd.extend(safe_paths)

        success, stdout, stderr = self._run_git_command(cmd)

        if success:
            logger.info(f"✓ Committed with message: {message}")
            return True, f"Committed: {message}"
        else:
            logger.error(f"✗ Failed to commit: {stderr}")
            return False, f"Failed to commit: {stderr}"

    def create_pull_request(
        self,
        title: str,
        body: str,
        base_branch: str = "main",
        head_branch: Optional[str] = None,
    ) -> tuple[bool, Optional[int], str]:
        """Create a GitHub Pull Request using gh CLI.
        
        Args:
            title: PR title
            body: PR description
            base_branch: Target branch (default: "main")
            head_branch: Source branch (if None, uses current branch)
            
        Returns:
            Tuple of (success, pr_number, message)
        """
        if head_branch:
            push_success, push_msg = self.push_branch(head_branch)
            if not push_success:
                return False, None, push_msg

        cmd = [
            "gh",
            "pr",
            "create",
            f"--title={title}",
            f"--body={body}",
            f"--base={base_branch}",
        ]

        if head_branch:
            cmd.append(f"--head={head_branch}")

        success, stdout, stderr = self._run_gh_command(cmd)
        combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()

        if success:
            # Parse PR number from output (format: "https://github.com/owner/repo/pull/123")
            pr_number = None
            try:
                if "pull/" in stdout:
                    pr_number = int(stdout.split("pull/")[-1].strip())
            except (ValueError, IndexError):
                pass

            logger.info(f"✓ Created PR: {stdout}")
            return True, pr_number, f"Created PR: {stdout}"
        else:
            if "uncommitted changes" in combined_output.lower():
                dirty = self.get_working_tree_status()
                dirty_count = len([line for line in dirty.splitlines() if line.strip()])
                message = (
                    "Failed to create PR: repository has uncommitted changes "
                    f"({dirty_count} files)."
                )
                logger.error(f"✗ {message}")
                return False, None, message

            logger.error(f"✗ Failed to create PR: {combined_output}")
            return False, None, f"Failed to create PR: {combined_output}"

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Optional[List[str]] = None,
    ) -> tuple[bool, Optional[int], str]:
        """Create a GitHub Issue using gh CLI.
        
        Args:
            title: Issue title
            body: Issue description
            labels: Optional list of labels to add
            
        Returns:
            Tuple of (success, issue_number, message)
        """
        cmd = [
            "gh",
            "issue",
            "create",
            f"--title={title}",
            f"--body={body}",
        ]

        if labels:
            cmd.extend([f"--label={label}" for label in labels])

        success, stdout, stderr = self._run_gh_command(cmd)
        combined_output = "\n".join(part for part in [stdout, stderr] if part).strip()

        if not success and labels:
            lower_output = combined_output.lower()
            missing_label_error = (
                "label" in lower_output and "not found" in lower_output
            )
            if missing_label_error:
                logger.warning(
                    "Issue labels not found in repo; retrying issue creation without labels: %s",
                    ", ".join(labels),
                )
                retry_cmd = [
                    "gh",
                    "issue",
                    "create",
                    f"--title={title}",
                    f"--body={body}",
                ]
                success, stdout, stderr = self._run_gh_command(retry_cmd)
                combined_output = "\n".join(
                    part for part in [stdout, stderr] if part
                ).strip()

        if success:
            # Parse issue number from output
            issue_number = None
            try:
                if "issues/" in stdout:
                    issue_number = int(stdout.split("issues/")[-1].strip())
            except (ValueError, IndexError):
                pass

            logger.info(f"✓ Created issue: {stdout}")
            return True, issue_number, f"Created issue: {stdout}"
        else:
            logger.error(f"✗ Failed to create issue: {combined_output}")
            return False, None, f"Failed to create issue: {combined_output}"

    def checkout_main(self) -> tuple[bool, str]:
        """Checkout main/master branch.
        
        Returns:
            Tuple of (success, message)
        """
        # Try main first, then master
        for branch in ["main", "master"]:
            success, _, _ = self._run_git_command(["git", "checkout", branch])
            if success:
                logger.info(f"✓ Checked out {branch}")
                return True, f"Checked out {branch}"

        return False, "Failed to checkout main or master branch"

    def get_current_branch(self) -> str:
        """Get the name of the current branch.
        
        Returns:
            Branch name or empty string if unable to determine
        """
        success, stdout, _ = self._run_git_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        )
        return stdout if success else ""


__all__ = ["GitHubOperations"]
