"""Git isolation and Jira status helpers for batch bug fix activities.

Provides git commit/revert operations for per-bug isolation,
Jira pre-scan for smart skip, and pre-flight environment checks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

from ..settings import GIT_COMMAND_TIMEOUT as _GIT_TIMEOUT

logger = logging.getLogger("workflow.temporal.git_operations")


# --- Git Helpers ---


def _extract_jira_key(url: str) -> str:
    """Extract Jira issue key from URL.

    Examples:
        https://tssoft.atlassian.net/browse/XSZS-15463 → XSZS-15463
        XSZS-15463 → XSZS-15463
    """
    match = re.search(r"([A-Z][A-Z0-9]+-\d+)", url)
    return match.group(1) if match else url.rsplit("/", 1)[-1]


async def _git_run(cwd: str, *args: str) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout).

    Non-blocking async subprocess. Captures stderr into stdout.
    Timeout configurable via GIT_COMMAND_TIMEOUT env var (default 60s).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT)
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        logger.warning(f"Git command timed out ({_GIT_TIMEOUT}s): git {' '.join(args)}")
        return 1, f"timeout ({_GIT_TIMEOUT}s)"
    except Exception as e:
        logger.warning(f"Git command failed: git {' '.join(args)}: {e}")
        return 1, str(e)


async def _git_is_repo(cwd: str) -> bool:
    """Check if cwd is inside a git repository."""
    code, _ = await _git_run(cwd, "rev-parse", "--is-inside-work-tree")
    return code == 0


async def _git_has_changes(cwd: str) -> bool:
    """Check if there are uncommitted changes (staged or unstaged)."""
    code, output = await _git_run(cwd, "status", "--porcelain")
    return code == 0 and len(output.strip()) > 0


async def _git_commit_bug_fix(cwd: str, jira_url: str, job_id: str) -> bool:
    """Stage all changes and commit with a descriptive message.

    Returns True if commit succeeded, False otherwise.
    """
    jira_key = _extract_jira_key(jira_url)

    if not await _git_has_changes(cwd):
        logger.info(f"Job {job_id}: No changes to commit for {jira_key}")
        return True  # No changes is not an error

    # Stage all changes in the working directory
    code, output = await _git_run(cwd, "add", ".")
    if code != 0:
        logger.error(f"Job {job_id}: git add failed for {jira_key}: {output}")
        return False

    # Commit with conventional commit format
    commit_msg = f"fix: {jira_key}\n\nAutomated fix by batch-bug-fix workflow\nJob: {job_id}"
    code, output = await _git_run(cwd, "commit", "-m", commit_msg)
    if code != 0:
        logger.error(f"Job {job_id}: git commit failed for {jira_key}: {output}")
        return False

    logger.info(f"Job {job_id}: Committed fix for {jira_key}")
    return True


async def _git_revert_changes(cwd: str, job_id: str, jira_key: str) -> bool:
    """Revert all uncommitted changes (tracked and untracked).

    Used when a bug fix fails after max retries.
    Returns True if revert succeeded.
    """
    if not await _git_has_changes(cwd):
        return True  # Nothing to revert

    # Revert tracked file changes
    code1, out1 = await _git_run(cwd, "checkout", ".")
    # Remove untracked files created during the fix attempt
    code2, out2 = await _git_run(cwd, "clean", "-fd")

    if code1 != 0:
        logger.error(f"Job {job_id}: git checkout failed for {jira_key}: {out1}")
    if code2 != 0:
        logger.error(f"Job {job_id}: git clean failed for {jira_key}: {out2}")

    success = code1 == 0 and code2 == 0
    if success:
        logger.info(f"Job {job_id}: Reverted changes for failed {jira_key}")
    return success


async def _git_change_summary(cwd: str, job_id: str) -> Optional[Dict[str, Any]]:
    """Collect code change summary before commit.

    Runs git diff --stat (tracked) and counts untracked files.
    Returns None if no changes.
    """
    if not await _git_has_changes(cwd):
        return None

    # Tracked file changes
    code, stat_output = await _git_run(cwd, "diff", "--stat")

    # Untracked (new) files
    code2, untracked_output = await _git_run(
        cwd, "ls-files", "--others", "--exclude-standard",
    )

    tracked_lines = (
        stat_output.strip().split("\n") if stat_output.strip() else []
    )
    untracked_files = [
        f for f in untracked_output.strip().split("\n") if f.strip()
    ] if untracked_output.strip() else []

    # Parse tracked file list from stat output (all lines except summary)
    tracked_files: List[str] = []
    insertions = 0
    deletions = 0

    if len(tracked_lines) > 1:
        for line in tracked_lines[:-1]:
            fname = line.strip().split("|")[0].strip()
            if fname:
                tracked_files.append(fname)

        summary_line = tracked_lines[-1]
        ins_match = re.search(r"(\d+) insertion", summary_line)
        del_match = re.search(r"(\d+) deletion", summary_line)
        if ins_match:
            insertions = int(ins_match.group(1))
        if del_match:
            deletions = int(del_match.group(1))

    all_files = tracked_files + untracked_files
    if not all_files:
        return None

    return {
        "files_changed": len(all_files),
        "insertions": insertions,
        "deletions": deletions,
        "new_files": len(untracked_files),
        "file_list": all_files[:10],
    }


# --- Jira Status Helpers ---


_JIRA_RESOLVED_CATEGORIES = frozenset({"done"})


async def _jira_get_status(jira_url: str, job_id: str) -> Optional[str]:
    """Get the status category of a Jira issue. Best-effort.

    Returns the statusCategory.key (e.g., 'done', 'indeterminate', 'new')
    or None if the check fails.
    """
    jira_base = os.environ.get("JIRA_URL", "")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")

    if not all([jira_base, email, token]):
        return None

    jira_key = _extract_jira_key(jira_url)

    try:
        import httpx
        import base64

        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        url = (
            f"{jira_base.rstrip('/')}/rest/api/3/issue/{jira_key}"
            f"?fields=status"
        )
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                category = (
                    data.get("fields", {})
                    .get("status", {})
                    .get("statusCategory", {})
                    .get("key", "")
                    .lower()
                )
                return category
            else:
                logger.debug(
                    f"Job {job_id}: Jira status check failed for {jira_key}: "
                    f"HTTP {resp.status_code}"
                )
                return None

    except Exception as e:
        logger.debug(
            f"Job {job_id}: Jira status check failed for {jira_key}: {e}"
        )
        return None


async def _prescan_closed_bugs(
    jira_urls: List[str], job_id: str,
) -> set:
    """Pre-scan Jira URLs and return indices of closed/resolved issues.

    Best-effort: if Jira API is unavailable, returns empty set (no skips).
    """
    from .sse_events import _push_event

    # Skip pre-scan entirely if no Jira credentials
    if not all([
        os.environ.get("JIRA_URL", ""),
        os.environ.get("JIRA_EMAIL", ""),
        os.environ.get("JIRA_API_TOKEN", ""),
    ]):
        logger.info(f"Job {job_id}: Jira credentials not configured, skipping pre-scan")
        await _push_event(job_id, "warning", {
            "source": "jira_prescan",
            "message": "Jira 凭证未配置，跳过预扫描（已关闭的 Bug 不会自动跳过）",
        })
        return set()

    closed = set()
    failed_checks: List[str] = []
    for i, url in enumerate(jira_urls):
        category = await _jira_get_status(url, job_id)
        if category is None:
            failed_checks.append(_extract_jira_key(url))
        elif category in _JIRA_RESOLVED_CATEGORIES:
            closed.add(i)
            jira_key = _extract_jira_key(url)
            logger.info(
                f"Job {job_id}: Bug {i} ({jira_key}) is resolved, will skip"
            )

    if failed_checks:
        await _push_event(job_id, "warning", {
            "source": "jira_prescan",
            "message": f"Jira 状态检查失败: {', '.join(failed_checks)}（将正常处理这些 Bug）",
            "failed_keys": failed_checks,
        })

    if closed:
        logger.info(
            f"Job {job_id}: Pre-scan found {len(closed)}/{len(jira_urls)} "
            f"resolved bugs to skip"
        )

    return closed


# --- Pre-flight Check ---


async def _preflight_check(
    cwd: str, config: Dict[str, Any], job_id: str,
) -> tuple[bool, List[str]]:
    """Validate environment before starting the batch workflow.

    Checks:
    1. cwd exists and is a git repository
    2. claude CLI is available

    Returns (ok, errors) — ok=True means all checks passed.
    """
    import shutil

    errors: List[str] = []
    warnings: List[str] = []

    # 1. Working directory exists
    if not os.path.isdir(cwd):
        errors.append(f"工作目录不存在: {cwd}")
    else:
        # 2. Git repository check
        if not await _git_is_repo(cwd):
            errors.append(f"工作目录不是 Git 仓库: {cwd}")

    # 3. Claude CLI available
    claude_path = shutil.which("claude")
    if not claude_path:
        errors.append("Claude CLI 未安装或不在 PATH 中")

    # Log results
    all_issues = errors + warnings
    if all_issues:
        logger.info(
            f"Job {job_id}: Preflight check — "
            f"{len(errors)} error(s), {len(warnings)} warning(s)"
        )
        for issue in all_issues:
            logger.info(f"  - {issue}")
    else:
        logger.info(f"Job {job_id}: Preflight check passed")

    return len(errors) == 0, all_issues
