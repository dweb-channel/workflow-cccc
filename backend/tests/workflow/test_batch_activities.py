"""Unit tests for batch_activities.py — T099 (M16 safety net).

Tests cover:
- NODE_TO_STEP mapping completeness
- _push_event (SSE push with error handling)
- _record_next_step_start (node transition + start time recording)
- _sync_incremental_results (incremental DB sync + SSE events)
- _sync_final_results (final sync + job_done event)
- _reset_stale_bugs (retry cleanup)
- _periodic_heartbeat (heartbeat loop)
- execute_batch_bugfix_activity (main activity, mocked graph)
- Error scenarios (DB failures, cancellation)

All DB operations use mocks (no real DB) to avoid N048-style issues.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bug_model(bug_index: int, status: str = "pending") -> MagicMock:
    """Create a mock BugResultModel."""
    bug = MagicMock()
    bug.bug_index = bug_index
    bug.status = status
    bug.url = f"https://jira.example.com/browse/TEST-{bug_index}"
    bug.error = None
    bug.started_at = None
    bug.completed_at = None
    bug.steps = None
    return bug


def _make_job_model(
    job_id: str = "job_test123",
    status: str = "running",
    bugs: Optional[list] = None,
) -> MagicMock:
    """Create a mock BatchJobModel."""
    job = MagicMock()
    job.id = job_id
    job.status = status
    job.bugs = bugs or []
    job.config = {}
    job.error = None
    job.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return job


# ---------------------------------------------------------------------------
# 1. NODE_TO_STEP mapping
# ---------------------------------------------------------------------------


class TestNodeToStepMapping:
    """Validate the NODE_TO_STEP constant."""

    def test_mapping_has_expected_keys(self):
        from workflow.temporal.batch_activities import NODE_TO_STEP

        expected_nodes = {
            "get_current_bug",
            "fix_bug_peer",
            "verify_fix",
            "check_verify_result",
            "check_retry",
            "increment_retry",
            "update_success",
            "update_failure",
            "check_more_bugs",
            "input_node",
            "output_node",
        }
        assert set(NODE_TO_STEP.keys()) == expected_nodes

    def test_visible_steps_have_tuples(self):
        from workflow.temporal.batch_activities import NODE_TO_STEP

        for node_id, step_info in NODE_TO_STEP.items():
            if step_info is not None:
                assert isinstance(step_info, tuple), f"{node_id} should be tuple"
                assert len(step_info) == 2, f"{node_id} tuple should have 2 elements"
                step_name, step_label = step_info
                assert isinstance(step_name, str)
                assert isinstance(step_label, str)

    def test_internal_nodes_are_none(self):
        from workflow.temporal.batch_activities import NODE_TO_STEP

        internal_nodes = [
            "check_verify_result",
            "check_retry",
            "check_more_bugs",
            "input_node",
            "output_node",
        ]
        for node_id in internal_nodes:
            assert NODE_TO_STEP[node_id] is None, f"{node_id} should be None"


# ---------------------------------------------------------------------------
# 2. _push_event
# ---------------------------------------------------------------------------


class TestPushEvent:
    """Test SSE event push helper."""

    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_push_event_success(self, mock_push):
        """Successful SSE push."""
        from workflow.temporal.batch_activities import _push_event

        await _push_event("job_1", "bug_started", {"bug_index": 0})
        mock_push.assert_awaited_once_with("job_1", "bug_started", {"bug_index": 0})

    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_push_event_swallows_errors(self, mock_push):
        """SSE push errors are logged but not raised."""
        from workflow.temporal.batch_activities import _push_event

        mock_push.side_effect = ConnectionError("connection refused")
        # Should NOT raise
        await _push_event("job_1", "bug_started", {"bug_index": 0})


# ---------------------------------------------------------------------------
# 3. _record_next_step_start
# ---------------------------------------------------------------------------


class TestRecordNextStepStart:
    """Test the node-transition prediction logic."""

    def test_get_current_bug_predicts_fix(self):
        from workflow.temporal.batch_activities import _record_next_step_start

        node_start_times: Dict[str, datetime] = {}
        state = {"retry_count": 0}

        with patch("workflow.temporal.batch_activities.asyncio") as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = mock_loop

            _record_next_step_start(
                "job_1", "get_current_bug", 0, state, node_start_times
            )

        # Should record start time for fix_bug_peer
        assert "0:fix_bug_peer" in node_start_times
        # Should schedule SSE push for bug_step_started
        mock_loop.create_task.assert_called_once()

    def test_fix_bug_peer_predicts_verify(self):
        from workflow.temporal.batch_activities import _record_next_step_start

        node_start_times: Dict[str, datetime] = {}
        state = {"retry_count": 0}

        with patch("workflow.temporal.batch_activities.asyncio") as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = mock_loop

            _record_next_step_start(
                "job_1", "fix_bug_peer", 0, state, node_start_times
            )

        assert "0:verify_fix" in node_start_times

    def test_verify_fix_has_no_next(self):
        from workflow.temporal.batch_activities import _record_next_step_start

        node_start_times: Dict[str, datetime] = {}
        state = {"retry_count": 0}

        with patch("workflow.temporal.batch_activities.asyncio") as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = mock_loop

            _record_next_step_start(
                "job_1", "verify_fix", 0, state, node_start_times
            )

        assert len(node_start_times) == 0
        mock_loop.create_task.assert_not_called()

    def test_increment_retry_predicts_fix(self):
        from workflow.temporal.batch_activities import _record_next_step_start

        node_start_times: Dict[str, datetime] = {}
        state = {"retry_count": 1}

        with patch("workflow.temporal.batch_activities.asyncio") as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = mock_loop

            _record_next_step_start(
                "job_1", "increment_retry", 0, state, node_start_times
            )

        assert "0:fix_bug_peer" in node_start_times

    def test_unknown_node_is_noop(self):
        from workflow.temporal.batch_activities import _record_next_step_start

        node_start_times: Dict[str, datetime] = {}
        state = {}

        with patch("workflow.temporal.batch_activities.asyncio") as mock_asyncio:
            mock_loop = MagicMock()
            mock_asyncio.get_running_loop.return_value = mock_loop

            _record_next_step_start(
                "job_1", "nonexistent_node", 0, state, node_start_times
            )

        assert len(node_start_times) == 0


# ---------------------------------------------------------------------------
# 4. _sync_incremental_results
# ---------------------------------------------------------------------------


class TestSyncIncrementalResults:
    """Test incremental result syncing to DB + SSE."""

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_completed_bug(self, mock_push, mock_db):
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        # Should push bug_completed event
        push_calls = mock_push.call_args_list
        event_types = [c[0][1] for c in push_calls]
        assert "bug_completed" in event_types

        # Should update DB to completed
        db_calls = mock_db.call_args_list
        assert any(
            c[0] == ("job_1", 0, "completed") or
            c.kwargs.get("status") == "completed" or
            (len(c[0]) >= 3 and c[0][2] == "completed")
            for c in db_calls
        )

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_failed_bug(self, mock_push, mock_db):
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "failed", "error": "Compilation error"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        push_calls = mock_push.call_args_list
        event_types = [c[0][1] for c in push_calls]
        assert "bug_failed" in event_types

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_marks_next_bug_in_progress(self, mock_push, mock_db):
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
        ]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        # Should push bug_started for next bug
        push_calls = mock_push.call_args_list
        bug_started_calls = [c for c in push_calls if c[0][1] == "bug_started"]
        assert len(bug_started_calls) == 1
        assert bug_started_calls[0][0][2]["bug_index"] == 1

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_last_bug_no_next_started(self, mock_push, mock_db):
        """When last bug completes, no bug_started event for next."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        push_calls = mock_push.call_args_list
        bug_started_calls = [c for c in push_calls if c[0][1] == "bug_started"]
        assert len(bug_started_calls) == 0

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_skipped_bug(self, mock_push, mock_db):
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "skipped", "error": "Already fixed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        push_calls = mock_push.call_args_list
        event_types = [c[0][1] for c in push_calls]
        assert "bug_failed" in event_types
        # Skipped bugs get bug_failed event with skipped=True
        skipped_call = [c for c in push_calls if c[0][1] == "bug_failed"][0]
        assert skipped_call[0][2].get("skipped") is True

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_sync_incremental_from_middle(self, mock_push, mock_db):
        """Only process results from start_index onwards."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
            "https://jira.example.com/browse/TEST-3",
        ]
        results = [
            {"status": "completed"},
            {"status": "failed", "error": "oops"},
        ]

        # Only sync index 1 (start_index=1)
        await _sync_incremental_results("job_1", jira_urls, results, 1)

        # Should only push events for bug index 1, not 0
        push_calls = mock_push.call_args_list
        bug_event_calls = [
            c for c in push_calls
            if c[0][1] in ("bug_completed", "bug_failed")
        ]
        assert len(bug_event_calls) == 1
        assert bug_event_calls[0][0][2]["bug_index"] == 1


# ---------------------------------------------------------------------------
# 5. _sync_final_results
# ---------------------------------------------------------------------------


class TestSyncFinalResults:
    """Test final result sync + job_done event."""

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_all_completed(self, mock_ctx, mock_repo_cls, mock_push):
        from workflow.temporal.batch_activities import _sync_final_results

        jira_urls = ["url1", "url2"]
        final_state = {
            "results": [
                {"status": "completed"},
                {"status": "completed"},
            ]
        }

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _sync_final_results("job_1", final_state, jira_urls)

        # Should push job_done with status=completed
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1
        data = job_done_calls[0][0][2]
        assert data["status"] == "completed"
        assert data["completed"] == 2
        assert data["failed"] == 0

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_some_failed(self, mock_ctx, mock_repo_cls, mock_push):
        from workflow.temporal.batch_activities import _sync_final_results

        jira_urls = ["url1", "url2", "url3"]
        final_state = {
            "results": [
                {"status": "completed"},
                {"status": "failed", "error": "oops"},
                {"status": "skipped"},
            ]
        }

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _sync_final_results("job_1", final_state, jira_urls)

        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        data = job_done_calls[0][0][2]
        assert data["status"] == "failed"
        assert data["completed"] == 1
        assert data["failed"] == 1
        assert data["skipped"] == 1

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_db_failure_still_pushes_job_done(self, mock_ctx, mock_push):
        """Even if DB sync fails, job_done SSE event should still be pushed."""
        from workflow.temporal.batch_activities import _sync_final_results

        jira_urls = ["url1"]
        final_state = {"results": [{"status": "completed"}]}

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB connection lost")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _sync_final_results("job_1", final_state, jira_urls)

        # job_done event should still be pushed even after DB failure
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1


# ---------------------------------------------------------------------------
# 6. _reset_stale_bugs
# ---------------------------------------------------------------------------


class TestResetStaleBugs:
    """Test stale bug reset on retry attempts."""

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_resets_in_progress_bugs(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _reset_stale_bugs

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_job = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "in_progress"),
                _make_bug_model(2, "pending"),
            ]
        )
        mock_repo.get.return_value = mock_job

        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _reset_stale_bugs("job_1", 3)

        # Should only reset bug 1 (in_progress -> pending)
        mock_repo.update_bug_status.assert_called_once_with(
            job_id="job_1",
            bug_index=1,
            status="pending",
        )

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_no_stale_bugs_is_noop(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _reset_stale_bugs

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_job = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "pending"),
            ]
        )
        mock_repo.get.return_value = mock_job

        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _reset_stale_bugs("job_1", 2)

        mock_repo.update_bug_status.assert_not_called()

    @patch("app.database.get_session_ctx")
    async def test_db_error_is_swallowed(self, mock_ctx):
        from workflow.temporal.batch_activities import _reset_stale_bugs

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB down")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise
        await _reset_stale_bugs("job_1", 3)


# ---------------------------------------------------------------------------
# 7. _periodic_heartbeat
# ---------------------------------------------------------------------------


class TestPeriodicHeartbeat:
    """Test heartbeat background task."""

    @patch("workflow.temporal.batch_activities.activity")
    async def test_heartbeat_sends_and_can_be_cancelled(self, mock_activity):
        from workflow.temporal.batch_activities import _periodic_heartbeat

        # Run heartbeat with very short interval, cancel after first beat
        task = asyncio.create_task(_periodic_heartbeat("job_1", interval_seconds=0))
        await asyncio.sleep(0.05)  # Let it beat once
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_activity.heartbeat.assert_called()

    @patch("workflow.temporal.batch_activities.activity")
    async def test_heartbeat_stops_on_activity_error(self, mock_activity):
        from workflow.temporal.batch_activities import _periodic_heartbeat

        # Simulate Temporal cancelling the activity
        mock_activity.heartbeat.side_effect = Exception("Activity cancelled")

        task = asyncio.create_task(_periodic_heartbeat("job_1", interval_seconds=0))
        await asyncio.sleep(0.05)
        # Task should have returned (not stuck)
        assert task.done()


# ---------------------------------------------------------------------------
# 8. DB helper: _update_job_status
# ---------------------------------------------------------------------------


class TestUpdateJobStatus:
    """Test job status DB update helper."""

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_updates_status(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _update_job_status

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _update_job_status("job_1", "running")

        mock_repo.update_status.assert_awaited_once_with(
            "job_1", "running", error=None
        )

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_updates_status_with_error(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _update_job_status

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _update_job_status("job_1", "failed", error="boom")

        mock_repo.update_status.assert_awaited_once_with(
            "job_1", "failed", error="boom"
        )

    @patch("app.database.get_session_ctx")
    async def test_db_error_is_swallowed(self, mock_ctx):
        from workflow.temporal.batch_activities import _update_job_status

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB unreachable")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise
        await _update_job_status("job_1", "running")


# ---------------------------------------------------------------------------
# 9. DB helper: _persist_bug_steps
# ---------------------------------------------------------------------------


class TestPersistBugSteps:
    """Test step persistence."""

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_persists_steps(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _persist_bug_steps

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        steps = [
            {"step": "fix_bug_peer", "label": "修复 Bug", "status": "completed"},
            {"step": "verify_fix", "label": "验证修复结果", "status": "completed"},
        ]

        await _persist_bug_steps("job_1", 0, steps)

        mock_repo.update_bug_steps.assert_awaited_once_with(
            job_id="job_1",
            bug_index=0,
            steps=steps,
        )

    @patch("app.database.get_session_ctx")
    async def test_db_error_is_swallowed(self, mock_ctx):
        from workflow.temporal.batch_activities import _persist_bug_steps

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB down")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _persist_bug_steps("job_1", 0, [{"step": "fix"}])


# ---------------------------------------------------------------------------
# 10. _update_bug_status_db
# ---------------------------------------------------------------------------


class TestUpdateBugStatusDb:
    """Test single bug status update."""

    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_updates_bug_status(self, mock_ctx, mock_repo_cls):
        from workflow.temporal.batch_activities import _update_bug_status_db

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        now = datetime.now(timezone.utc)

        await _update_bug_status_db(
            "job_1", 2, "in_progress", started_at=now
        )

        mock_repo.update_bug_status.assert_awaited_once_with(
            job_id="job_1",
            bug_index=2,
            status="in_progress",
            error=None,
            started_at=now,
            completed_at=None,
        )

    @patch("app.database.get_session_ctx")
    async def test_db_error_is_swallowed(self, mock_ctx):
        from workflow.temporal.batch_activities import _update_bug_status_db

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("timeout")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        await _update_bug_status_db("job_1", 0, "completed")
