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

    @patch("workflow.temporal.batch_activities.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_db_failure_pushes_job_done_with_warning(self, mock_ctx, mock_push, mock_sleep):
        """DB sync failure → job_done event has db_sync_failed flag."""
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
        data = job_done_calls[0][0][2]
        assert data["db_sync_failed"] is True
        assert "db_sync_message" in data


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

        result = await _update_job_status("job_1", "running")

        assert result is True
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

        result = await _update_job_status("job_1", "failed", error="boom")

        assert result is True
        mock_repo.update_status.assert_awaited_once_with(
            "job_1", "failed", error="boom"
        )

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_db_error_returns_false_and_pushes_warning(self, mock_ctx, mock_push):
        from workflow.temporal.batch_activities import _update_job_status

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB unreachable")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _update_job_status("job_1", "running")

        assert result is False
        # Should push db_sync_warning SSE event
        mock_push.assert_awaited_once()
        call_args = mock_push.call_args
        assert call_args[0][0] == "job_1"
        assert call_args[0][1] == "db_sync_warning"


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

        result = await _persist_bug_steps("job_1", 0, steps)

        assert result is True
        mock_repo.update_bug_steps.assert_awaited_once_with(
            job_id="job_1",
            bug_index=0,
            steps=steps,
        )

    @patch("app.database.get_session_ctx")
    async def test_db_error_returns_false(self, mock_ctx):
        from workflow.temporal.batch_activities import _persist_bug_steps

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB down")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _persist_bug_steps("job_1", 0, [{"step": "fix"}])
        assert result is False


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

        result = await _update_bug_status_db(
            "job_1", 2, "in_progress", started_at=now
        )

        assert result is True
        mock_repo.update_bug_status.assert_awaited_once_with(
            job_id="job_1",
            bug_index=2,
            status="in_progress",
            error=None,
            started_at=now,
            completed_at=None,
        )

    @patch("app.database.get_session_ctx")
    async def test_db_error_returns_false(self, mock_ctx):
        from workflow.temporal.batch_activities import _update_bug_status_db

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("timeout")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _update_bug_status_db("job_1", 0, "completed")
        assert result is False


# ---------------------------------------------------------------------------
# 11. _sync_incremental_results with bug_index_offset (S2)
# ---------------------------------------------------------------------------


class TestSyncIncrementalResultsWithOffset:
    """Test _sync_incremental_results with bug_index_offset for retry scenarios."""

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_offset_3_sse_uses_db_bug_index(self, mock_push, mock_db):
        """5-bug job, retry bug[3]: SSE bug_index should be 3, not 0."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = ["https://jira.example.com/browse/TEST-3"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0, bug_index_offset=3)

        # bug_completed SSE event should have bug_index=3
        bug_completed_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_completed"
        ]
        assert len(bug_completed_calls) == 1
        assert bug_completed_calls[0][0][2]["bug_index"] == 3

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_offset_3_db_update_uses_db_bug_index(self, mock_push, mock_db):
        """DB update should use offset bug_index (3), not array index (0)."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = ["https://jira.example.com/browse/TEST-3"]
        results = [{"status": "failed", "error": "compilation error"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0, bug_index_offset=3)

        # DB update should be called with bug_index=3
        db_calls = [c for c in mock_db.call_args_list if c[0][2] in ("failed", "completed")]
        assert len(db_calls) == 1
        assert db_calls[0][0][1] == 3  # db_i = 0 + 3

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_offset_with_next_bug_started(self, mock_push, mock_db):
        """With offset=2 and 2 bugs, next bug_started should have bug_index=3."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = [
            "https://jira.example.com/browse/TEST-2",
            "https://jira.example.com/browse/TEST-3",
        ]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0, bug_index_offset=2)

        bug_started_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_started"
        ]
        assert len(bug_started_calls) == 1
        assert bug_started_calls[0][0][2]["bug_index"] == 3  # next_index(1) + offset(2)

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_offset_db_failure_pushes_warning_with_correct_index(self, mock_push, mock_db):
        """DB failure with offset should push warning with correct bug_index."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = False  # DB failure
        jira_urls = ["https://jira.example.com/browse/TEST-3"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0, bug_index_offset=3)

        warning_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "db_sync_warning"
        ]
        assert len(warning_calls) == 1
        assert warning_calls[0][0][2]["bug_index"] == 3


# ---------------------------------------------------------------------------
# 12. _sync_final_results retry mode (S2 + S4)
# ---------------------------------------------------------------------------


class TestSyncFinalResultsRetryMode:
    """Test _sync_final_results with bug_index_offset > 0 (retry mode)."""

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_recomputes_overall_from_all_bugs(self, mock_ctx, mock_repo_cls, mock_push):
        """5-bug job: 4 done + bug[3] retry completed → overall = completed."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # After retry, all 5 bugs are completed
        mock_repo.get.return_value = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "completed"),
                _make_bug_model(2, "completed"),
                _make_bug_model(3, "completed"),  # just retried successfully
                _make_bug_model(4, "completed"),
            ]
        )

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url3"], bug_index_offset=3)

        # Overall status should be "completed" (all 5 bugs done)
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert job_done_calls[0][0][2]["status"] == "completed"

        # update_status should be called with "completed"
        mock_repo.update_status.assert_awaited_once_with("job_1", "completed")

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_partial_still_failed(self, mock_ctx, mock_repo_cls, mock_push):
        """5-bug job: bug[3] retry succeeded, but bug[4] still failed → overall = failed."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # bug[3] retried OK but bug[4] still failed
        mock_repo.get.return_value = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "completed"),
                _make_bug_model(2, "completed"),
                _make_bug_model(3, "completed"),  # just retried
                _make_bug_model(4, "failed"),      # still failed
            ]
        )

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url3"], bug_index_offset=3)

        # Overall should be "failed" because bug[4] is still failed
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert job_done_calls[0][0][2]["status"] == "failed"
        mock_repo.update_status.assert_awaited_once_with("job_1", "failed")

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_skipped_bug_means_failed_overall(self, mock_ctx, mock_repo_cls, mock_push):
        """A skipped bug counts as failure for overall status."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo.get.return_value = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "skipped"),   # skipped = failed
                _make_bug_model(2, "completed"),
            ]
        )

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url2"], bug_index_offset=2)

        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert job_done_calls[0][0][2]["status"] == "failed"

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_non_retry_ignores_db_requery(self, mock_ctx, mock_repo_cls, mock_push):
        """Without offset (normal run), should NOT requery DB for overall status."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        final_state = {"results": [
            {"status": "completed"},
            {"status": "failed", "error": "oops"},
        ]}

        await _sync_final_results("job_1", final_state, ["url1", "url2"], bug_index_offset=0)

        # repo.get should NOT be called (no retry requery)
        mock_repo.get.assert_not_awaited()

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_bug_status_written_with_offset(self, mock_ctx, mock_repo_cls, mock_push):
        """Retry run writes bug status at correct offset index in DB."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo.get.return_value = _make_job_model(
            bugs=[_make_bug_model(i, "completed") for i in range(5)]
        )

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url3"], bug_index_offset=3)

        # update_bug_status should be called with bug_index=3 (0 + offset 3)
        bug_status_calls = mock_repo.update_bug_status.call_args_list
        assert len(bug_status_calls) == 1
        assert bug_status_calls[0].kwargs["bug_index"] == 3


# ---------------------------------------------------------------------------
# 13. DB sync retry in _sync_final_results (S1)
# ---------------------------------------------------------------------------


class TestSyncFinalResultsDbRetry:
    """Test that _sync_final_results retries once on transient DB failure."""

    @patch("workflow.temporal.batch_activities.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_succeeds_on_second_attempt(self, mock_ctx, mock_repo_cls, mock_push, mock_sleep):
        """First DB attempt fails, second succeeds → db_sync_failed absent."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()

        # First call fails, second succeeds
        call_count = 0

        async def session_enter(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("transient DB error")
            return mock_session

        mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=session_enter)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url1"])

        # Should have slept between retries
        mock_sleep.assert_awaited_once_with(1)

        # job_done should NOT have db_sync_failed
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1
        assert "db_sync_failed" not in job_done_calls[0][0][2]

    @patch("workflow.temporal.batch_activities.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_both_attempts_fail_sets_warning(self, mock_ctx, mock_push, mock_sleep):
        """Both DB attempts fail → db_sync_failed in job_done event."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("persistent DB error")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url1"])

        mock_sleep.assert_awaited_once_with(1)

        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        data = job_done_calls[0][0][2]
        assert data["db_sync_failed"] is True
        assert "db_sync_message" in data


# ---------------------------------------------------------------------------
# 14. _sync_incremental_results DB failure + SSE warning (S1)
# ---------------------------------------------------------------------------


class TestSyncIncrementalDbWarning:
    """Test that _sync_incremental_results pushes SSE warning on DB failure."""

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_db_failure_pushes_warning(self, mock_push, mock_db):
        """When DB update fails, a db_sync_warning SSE event is pushed."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = False  # DB failure
        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        warning_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "db_sync_warning"
        ]
        assert len(warning_calls) == 1
        assert warning_calls[0][0][2]["bug_index"] == 0

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_db_success_no_warning(self, mock_push, mock_db):
        """When DB update succeeds, no warning event is pushed."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        warning_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "db_sync_warning"
        ]
        assert len(warning_calls) == 0

    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    async def test_multiple_bugs_partial_failure(self, mock_push, mock_db):
        """2 bugs: first DB update fails, second succeeds → 1 warning."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        # First call fails, subsequent calls succeed
        mock_db.side_effect = [False, True, True]
        jira_urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
        ]
        results = [
            {"status": "completed"},
            {"status": "failed", "error": "oops"},
        ]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        warning_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "db_sync_warning"
        ]
        assert len(warning_calls) == 1
        assert warning_calls[0][0][2]["bug_index"] == 0


# ---------------------------------------------------------------------------
# 15. Retry endpoint (routes/batch.py) tests (S3)
# ---------------------------------------------------------------------------


class TestRetryEndpointValidation:
    """Test retry_single_bug endpoint validation logic.

    Tests the route validation conditions without HTTP server.
    Exercises the core logic: job existence, bug existence, state checks.
    """

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_retry_failed_bug_starts_workflow(self, mock_ctx, mock_client):
        """Retrying a failed bug should reset it and start a workflow."""
        from app.routes.batch import retry_single_bug

        mock_session = AsyncMock()
        mock_repo = AsyncMock()

        # First session: get job for validation
        db_job = _make_job_model(
            job_id="job_1",
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "failed"),
            ],
        )
        db_job.config = {"cwd": "/tmp/project", "validation_level": "strict"}
        mock_repo.get.return_value = db_job

        # Second session: get_bug for reset
        mock_bug = _make_bug_model(1, "failed")
        mock_repo.get_bug = AsyncMock(return_value=mock_bug)

        # Patch get_session_ctx to return our mock
        from unittest.mock import MagicMock as SyncMock
        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        # Patch BatchJobRepository at import site
        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            mock_temporal = AsyncMock()
            mock_client.return_value = mock_temporal

            response = await retry_single_bug("job_1", 1)

        assert response.success is True
        assert response.status == "running"

    @patch("app.database.get_session_ctx")
    async def test_retry_nonexistent_job_raises_404(self, mock_ctx):
        """Retrying a bug in a non-existent job → 404."""
        from app.routes.batch import retry_single_bug
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_repo.get.return_value = None

        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await retry_single_bug("nonexistent", 0)
            assert exc_info.value.status_code == 404

    @patch("app.database.get_session_ctx")
    async def test_retry_nonexistent_bug_raises_404(self, mock_ctx):
        """Retrying a bug_index that doesn't exist → 404."""
        from app.routes.batch import retry_single_bug
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        db_job = _make_job_model(bugs=[_make_bug_model(0, "completed")])
        mock_repo.get.return_value = db_job

        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await retry_single_bug("job_1", 5)  # index 5 doesn't exist
            assert exc_info.value.status_code == 404

    @patch("app.database.get_session_ctx")
    async def test_retry_completed_bug_raises_400(self, mock_ctx):
        """Retrying a completed (non-failed) bug → 400."""
        from app.routes.batch import retry_single_bug
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        db_job = _make_job_model(bugs=[_make_bug_model(0, "completed")])
        mock_repo.get.return_value = db_job

        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await retry_single_bug("job_1", 0)
            assert exc_info.value.status_code == 400
            assert "completed" in str(exc_info.value.detail)

    @patch("app.database.get_session_ctx")
    async def test_retry_in_progress_bug_raises_400(self, mock_ctx):
        """Retrying an in_progress bug → 400 (concurrent protection)."""
        from app.routes.batch import retry_single_bug
        from fastapi import HTTPException

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        db_job = _make_job_model(bugs=[_make_bug_model(0, "in_progress")])
        mock_repo.get.return_value = db_job

        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await retry_single_bug("job_1", 0)
            assert exc_info.value.status_code == 400

    @patch("app.database.get_session_ctx")
    async def test_retry_skipped_bug_allowed(self, mock_ctx):
        """Retrying a skipped bug should be allowed (skipped is retryable)."""
        from app.routes.batch import retry_single_bug

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        db_job = _make_job_model(
            bugs=[_make_bug_model(0, "skipped")],
        )
        db_job.config = {"cwd": "/tmp"}
        mock_repo.get.return_value = db_job

        mock_bug = _make_bug_model(0, "skipped")
        mock_repo.get_bug = AsyncMock(return_value=mock_bug)

        ctx_mock = AsyncMock()
        ctx_mock.__aenter__ = AsyncMock(return_value=mock_session)
        ctx_mock.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.return_value = ctx_mock

        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            with patch("app.routes.batch.get_client", new_callable=AsyncMock) as mock_client:
                mock_temporal = AsyncMock()
                mock_client.return_value = mock_temporal

                response = await retry_single_bug("job_1", 0)

        assert response.success is True


# ===========================================================================
# T101: PR/Jira Integration Tests
# ===========================================================================


class TestGitBranchHelpers:
    """Test per-bug branch creation, switching, and cleanup."""

    @pytest.mark.asyncio
    async def test_git_get_current_branch(self):
        from workflow.temporal.batch_activities import _git_get_current_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, "main"),
        ) as mock_run:
            result = await _git_get_current_branch("/tmp/repo")
            assert result == "main"
            mock_run.assert_called_once_with(
                "/tmp/repo", "rev-parse", "--abbrev-ref", "HEAD"
            )

    @pytest.mark.asyncio
    async def test_git_get_current_branch_fails(self):
        from workflow.temporal.batch_activities import _git_get_current_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(1, ""),
        ):
            result = await _git_get_current_branch("/tmp/repo")
            assert result is None

    @pytest.mark.asyncio
    async def test_git_create_fix_branch(self):
        from workflow.temporal.batch_activities import _git_create_fix_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ) as mock_run:
            result = await _git_create_fix_branch(
                "/tmp/repo",
                "https://jira.example.com/browse/XSZS-123",
                "job_1",
            )
            assert result == "fix/xszs-123"
            mock_run.assert_called_once_with(
                "/tmp/repo", "checkout", "-b", "fix/xszs-123"
            )

    @pytest.mark.asyncio
    async def test_git_create_fix_branch_fails(self):
        from workflow.temporal.batch_activities import _git_create_fix_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(1, "branch already exists"),
        ):
            result = await _git_create_fix_branch(
                "/tmp/repo",
                "https://jira.example.com/browse/XSZS-123",
                "job_1",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_git_switch_branch(self):
        from workflow.temporal.batch_activities import _git_switch_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ):
            result = await _git_switch_branch("/tmp/repo", "main", "job_1")
            assert result is True

    @pytest.mark.asyncio
    async def test_git_switch_branch_fails(self):
        from workflow.temporal.batch_activities import _git_switch_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(1, "error"),
        ):
            result = await _git_switch_branch("/tmp/repo", "main", "job_1")
            assert result is False

    @pytest.mark.asyncio
    async def test_git_delete_branch(self):
        from workflow.temporal.batch_activities import _git_delete_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ):
            result = await _git_delete_branch("/tmp/repo", "fix/xszs-123", "job_1")
            assert result is True

    @pytest.mark.asyncio
    async def test_git_delete_branch_fails(self):
        from workflow.temporal.batch_activities import _git_delete_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(1, "error"),
        ):
            result = await _git_delete_branch("/tmp/repo", "fix/xszs-123", "job_1")
            assert result is False


class TestGitPushAndCreatePr:
    """Test PR creation via gh CLI."""

    @pytest.mark.asyncio
    async def test_push_and_create_pr_success(self):
        from workflow.temporal.batch_activities import _git_push_and_create_pr

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(b"https://github.com/org/repo/pull/42\n", b"")
        )

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),  # git push succeeds
        ):
            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ):
                result = await _git_push_and_create_pr(
                    "/tmp/repo", "fix/xszs-123", "main",
                    "https://jira.example.com/browse/XSZS-123", "job_1",
                )
                assert result == "https://github.com/org/repo/pull/42"

    @pytest.mark.asyncio
    async def test_push_fails(self):
        from workflow.temporal.batch_activities import _git_push_and_create_pr

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(1, "remote error"),
        ):
            result = await _git_push_and_create_pr(
                "/tmp/repo", "fix/xszs-123", "main",
                "https://jira.example.com/browse/XSZS-123", "job_1",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_gh_cli_not_found(self):
        from workflow.temporal.batch_activities import _git_push_and_create_pr

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ):
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("gh not found"),
            ):
                result = await _git_push_and_create_pr(
                    "/tmp/repo", "fix/xszs-123", "main",
                    "https://jira.example.com/browse/XSZS-123", "job_1",
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_gh_pr_create_fails(self):
        from workflow.temporal.batch_activities import _git_push_and_create_pr

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(b"already exists\n", b"")
        )

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, ""),
        ):
            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ):
                result = await _git_push_and_create_pr(
                    "/tmp/repo", "fix/xszs-123", "main",
                    "https://jira.example.com/browse/XSZS-123", "job_1",
                )
                assert result is None


class TestJiraAddFixComment:
    """Test Jira comment via REST API."""

    @pytest.mark.asyncio
    async def test_jira_comment_success(self):
        from workflow.temporal.batch_activities import _jira_add_fix_comment

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "JIRA_URL": "https://jira.example.com",
                "JIRA_EMAIL": "test@example.com",
                "JIRA_API_TOKEN": "secret",
            },
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await _jira_add_fix_comment(
                    "https://jira.example.com/browse/XSZS-123",
                    "https://github.com/org/repo/pull/42",
                    "job_1",
                )
                assert result is True
                mock_client.post.assert_called_once()
                # Verify URL contains the Jira key
                pos_args, kwargs = mock_client.post.call_args
                assert "XSZS-123" in pos_args[0]  # URL contains issue key

    @pytest.mark.asyncio
    async def test_jira_comment_no_credentials(self):
        from workflow.temporal.batch_activities import _jira_add_fix_comment

        with patch.dict("os.environ", {}, clear=True):
            result = await _jira_add_fix_comment(
                "https://jira.example.com/browse/XSZS-123",
                None,
                "job_1",
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_jira_comment_api_failure(self):
        from workflow.temporal.batch_activities import _jira_add_fix_comment

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "JIRA_URL": "https://jira.example.com",
                "JIRA_EMAIL": "test@example.com",
                "JIRA_API_TOKEN": "secret",
            },
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await _jira_add_fix_comment(
                    "https://jira.example.com/browse/XSZS-123",
                    None,
                    "job_1",
                )
                assert result is False

    @pytest.mark.asyncio
    async def test_jira_comment_includes_pr_url(self):
        from workflow.temporal.batch_activities import _jira_add_fix_comment

        mock_resp = MagicMock()
        mock_resp.status_code = 201

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(
            "os.environ",
            {
                "JIRA_URL": "https://jira.example.com",
                "JIRA_EMAIL": "test@example.com",
                "JIRA_API_TOKEN": "secret",
            },
        ):
            with patch("httpx.AsyncClient", return_value=mock_client):
                await _jira_add_fix_comment(
                    "https://jira.example.com/browse/XSZS-123",
                    "https://github.com/org/repo/pull/42",
                    "job_1",
                )
                _, kwargs = mock_client.post.call_args
                comment_text = kwargs["json"]["body"]["content"][0]["content"][0]["text"]
                assert "https://github.com/org/repo/pull/42" in comment_text


class TestGitRecoverOriginalBranch:
    """Test branch recovery helper for exception handlers."""

    @pytest.mark.asyncio
    async def test_recover_from_fix_branch(self):
        from workflow.temporal.batch_activities import _git_recover_original_branch

        call_count = {"n": 0}

        async def mock_git_run(cwd, *args):
            call_count["n"] += 1
            cmd = " ".join(args)
            if "rev-parse --abbrev-ref HEAD" in cmd:
                return (0, "fix/xszs-123")
            if "rev-parse --abbrev-ref fix/xszs-123@{upstream}" in cmd:
                return (1, "")  # No upstream
            if "rev-parse --verify main" in cmd:
                return (0, "abc123")
            if "status --porcelain" in cmd:
                return (0, "")  # No changes
            if "checkout main" in cmd:
                return (0, "")
            if "branch -D fix/xszs-123" in cmd:
                return (0, "")
            return (0, "")

        with patch(
            "workflow.temporal.batch_activities._git_run",
            side_effect=mock_git_run,
        ):
            await _git_recover_original_branch("/tmp/repo", "job_1")
            assert call_count["n"] >= 3  # At least: get branch, check base, switch

    @pytest.mark.asyncio
    async def test_no_recovery_needed_on_main(self):
        from workflow.temporal.batch_activities import _git_recover_original_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, "main"),
        ) as mock_run:
            await _git_recover_original_branch("/tmp/repo", "job_1")
            # Only called once (get current branch) — no recovery needed
            assert mock_run.call_count == 1

    @pytest.mark.asyncio
    async def test_no_recovery_on_non_fix_branch(self):
        from workflow.temporal.batch_activities import _git_recover_original_branch

        with patch(
            "workflow.temporal.batch_activities._git_run",
            new_callable=AsyncMock,
            return_value=(0, "feature/my-feature"),
        ) as mock_run:
            await _git_recover_original_branch("/tmp/repo", "job_1")
            assert mock_run.call_count == 1
