"""Unit tests for Git Isolation in batch_activities.py — T097.

Tests cover:
- _extract_jira_key: Jira key extraction from URLs
- _git_run: Async git command execution
- _git_is_repo: Git repository detection
- _git_has_changes: Uncommitted change detection
- _git_commit_bug_fix: Per-bug commit after successful fix
- _git_revert_changes: Revert on failed bug fix

All git operations use mocks (no real git repo).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. _extract_jira_key
# ---------------------------------------------------------------------------


class TestExtractJiraKey:
    """Test Jira key extraction from URLs."""

    def test_full_url(self):
        from workflow.temporal.batch_activities import _extract_jira_key

        assert _extract_jira_key("https://tssoft.atlassian.net/browse/XSZS-15463") == "XSZS-15463"

    def test_bare_key(self):
        from workflow.temporal.batch_activities import _extract_jira_key

        assert _extract_jira_key("XSZS-15463") == "XSZS-15463"

    def test_key_with_numbers_in_project(self):
        from workflow.temporal.batch_activities import _extract_jira_key

        assert _extract_jira_key("https://jira.example.com/browse/AB2C-99") == "AB2C-99"

    def test_no_match_returns_last_segment(self):
        from workflow.temporal.batch_activities import _extract_jira_key

        assert _extract_jira_key("https://example.com/some/path") == "path"

    def test_empty_string(self):
        from workflow.temporal.batch_activities import _extract_jira_key

        result = _extract_jira_key("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 2. _git_run
# ---------------------------------------------------------------------------


class TestGitRun:
    """Test the async git command runner."""

    async def test_successful_command(self):
        from workflow.temporal.batch_activities import _git_run

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"true\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            code, output = await _git_run("/tmp", "rev-parse", "--is-inside-work-tree")

        assert code == 0
        assert output == "true"

    async def test_failed_command(self):
        from workflow.temporal.batch_activities import _git_run

        mock_proc = AsyncMock()
        mock_proc.returncode = 128
        mock_proc.communicate = AsyncMock(return_value=(b"fatal: not a git repo\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            code, output = await _git_run("/tmp", "status")

        assert code == 128
        assert "not a git repo" in output

    async def test_timeout_returns_error(self):
        from workflow.temporal.batch_activities import _git_run

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            code, output = await _git_run("/tmp", "status")

        assert code == 1

    async def test_exception_returns_error(self):
        from workflow.temporal.batch_activities import _git_run

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("git not found"),
        ):
            code, output = await _git_run("/tmp", "status")

        assert code == 1
        assert "git not found" in output


# ---------------------------------------------------------------------------
# 3. _git_is_repo
# ---------------------------------------------------------------------------


class TestGitIsRepo:
    """Test git repo detection."""

    async def test_is_repo(self):
        from workflow.temporal.batch_activities import _git_is_repo

        with patch(
            "workflow.temporal.git_operations._git_run",
            new_callable=AsyncMock,
            return_value=(0, "true"),
        ):
            assert await _git_is_repo("/tmp") is True

    async def test_not_repo(self):
        from workflow.temporal.batch_activities import _git_is_repo

        with patch(
            "workflow.temporal.git_operations._git_run",
            new_callable=AsyncMock,
            return_value=(128, "fatal: not a git repo"),
        ):
            assert await _git_is_repo("/tmp") is False


# ---------------------------------------------------------------------------
# 4. _git_has_changes
# ---------------------------------------------------------------------------


class TestGitHasChanges:
    """Test uncommitted change detection."""

    async def test_has_changes(self):
        from workflow.temporal.batch_activities import _git_has_changes

        with patch(
            "workflow.temporal.git_operations._git_run",
            new_callable=AsyncMock,
            return_value=(0, " M src/main.py\n?? newfile.txt"),
        ):
            assert await _git_has_changes("/tmp") is True

    async def test_no_changes(self):
        from workflow.temporal.batch_activities import _git_has_changes

        with patch(
            "workflow.temporal.git_operations._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ):
            assert await _git_has_changes("/tmp") is False

    async def test_git_error_returns_false(self):
        from workflow.temporal.batch_activities import _git_has_changes

        with patch(
            "workflow.temporal.git_operations._git_run",
            new_callable=AsyncMock,
            return_value=(128, "fatal"),
        ):
            assert await _git_has_changes("/tmp") is False


# ---------------------------------------------------------------------------
# 5. _git_commit_bug_fix
# ---------------------------------------------------------------------------


class TestGitCommitBugFix:
    """Test per-bug git commit."""

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_commit_success(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_commit_bug_fix

        mock_has_changes.return_value = True
        mock_run.return_value = (0, "")

        result = await _git_commit_bug_fix(
            "/tmp", "https://jira.example.com/browse/XSZS-15463", "job_1"
        )

        assert result is True
        # Should call git add then git commit
        assert mock_run.call_count == 2
        add_call = mock_run.call_args_list[0]
        assert add_call[0] == ("/tmp", "add", ".")
        commit_call = mock_run.call_args_list[1]
        assert commit_call[0][0] == "/tmp"
        assert commit_call[0][1] == "commit"
        # Commit message should contain the Jira key
        assert "XSZS-15463" in commit_call[0][3]

    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_no_changes_skips_commit(self, mock_has_changes):
        from workflow.temporal.batch_activities import _git_commit_bug_fix

        mock_has_changes.return_value = False

        result = await _git_commit_bug_fix("/tmp", "XSZS-100", "job_1")
        assert result is True  # No changes is not an error

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_add_failure_returns_false(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_commit_bug_fix

        mock_has_changes.return_value = True
        mock_run.return_value = (1, "error: unable to create")

        result = await _git_commit_bug_fix("/tmp", "XSZS-100", "job_1")
        assert result is False

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_commit_failure_returns_false(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_commit_bug_fix

        mock_has_changes.return_value = True
        # git add succeeds, git commit fails
        mock_run.side_effect = [(0, ""), (1, "error: commit failed")]

        result = await _git_commit_bug_fix("/tmp", "XSZS-100", "job_1")
        assert result is False

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_commit_message_format(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_commit_bug_fix

        mock_has_changes.return_value = True
        mock_run.return_value = (0, "")

        await _git_commit_bug_fix("/tmp", "https://jira.example.com/browse/TEST-42", "job_abc")

        commit_call = mock_run.call_args_list[1]
        commit_msg = commit_call[0][3]
        assert commit_msg.startswith("fix: TEST-42")
        assert "job_abc" in commit_msg


# ---------------------------------------------------------------------------
# 6. _git_revert_changes
# ---------------------------------------------------------------------------


class TestGitRevertChanges:
    """Test git revert on failed bug fix."""

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_revert_success(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_revert_changes

        mock_has_changes.return_value = True
        mock_run.return_value = (0, "")

        result = await _git_revert_changes("/tmp", "job_1", "XSZS-100")

        assert result is True
        # Should call git checkout . and git clean -fd
        assert mock_run.call_count == 2
        checkout_call = mock_run.call_args_list[0]
        assert checkout_call[0] == ("/tmp", "checkout", ".")
        clean_call = mock_run.call_args_list[1]
        assert clean_call[0] == ("/tmp", "clean", "-fd")

    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_no_changes_skips_revert(self, mock_has_changes):
        from workflow.temporal.batch_activities import _git_revert_changes

        mock_has_changes.return_value = False

        result = await _git_revert_changes("/tmp", "job_1", "XSZS-100")
        assert result is True

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_checkout_failure(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_revert_changes

        mock_has_changes.return_value = True
        # checkout fails, clean succeeds
        mock_run.side_effect = [(1, "error: checkout failed"), (0, "")]

        result = await _git_revert_changes("/tmp", "job_1", "XSZS-100")
        assert result is False

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_clean_failure(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_revert_changes

        mock_has_changes.return_value = True
        # checkout succeeds, clean fails
        mock_run.side_effect = [(0, ""), (1, "error: clean failed")]

        result = await _git_revert_changes("/tmp", "job_1", "XSZS-100")
        assert result is False

    @patch("workflow.temporal.git_operations._git_run", new_callable=AsyncMock)
    @patch("workflow.temporal.git_operations._git_has_changes", new_callable=AsyncMock)
    async def test_both_fail(self, mock_has_changes, mock_run):
        from workflow.temporal.batch_activities import _git_revert_changes

        mock_has_changes.return_value = True
        mock_run.side_effect = [(1, "error"), (1, "error")]

        result = await _git_revert_changes("/tmp", "job_1", "XSZS-100")
        assert result is False
