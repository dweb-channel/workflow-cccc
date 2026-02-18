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

        with patch("workflow.temporal.sse_events.asyncio") as mock_asyncio:
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

        with patch("workflow.temporal.sse_events.asyncio") as mock_asyncio:
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

        with patch("workflow.temporal.sse_events.asyncio") as mock_asyncio:
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

        with patch("workflow.temporal.sse_events.asyncio") as mock_asyncio:
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

        with patch("workflow.temporal.sse_events.asyncio") as mock_asyncio:
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    async def test_sync_failed_bug(self, mock_push, mock_db):
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "failed", "error": "Compilation error"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        push_calls = mock_push.call_args_list
        event_types = [c[0][1] for c in push_calls]
        assert "bug_failed" in event_types

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    async def test_sync_last_bug_no_next_started(self, mock_push, mock_db):
        """When last bug completes, no bug_started event for next."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        jira_urls = ["https://jira.example.com/browse/TEST-1"]
        results = [{"status": "completed"}]

        await _sync_incremental_results("job_1", jira_urls, results, 0)

        push_calls = mock_push.call_args_list
        bug_started_calls = [c for c in push_calls if c[0][1] == "bug_started"]
        assert len(bug_started_calls) == 0

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events.activity")
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

    @patch("workflow.temporal.sse_events.activity")
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_skipped_bug_means_failed_overall(self, mock_ctx, mock_repo_cls, mock_push):
        """In retry mode (no index_map), a skipped bug counts as failure."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo.get.return_value = _make_job_model(
            bugs=[
                _make_bug_model(0, "completed"),
                _make_bug_model(1, "skipped"),   # skipped = failed in retry mode
                _make_bug_model(2, "completed"),
            ]
        )

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url2"], bug_index_offset=2)

        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert job_done_calls[0][0][2]["status"] == "failed"

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_non_retry_preserves_incremental_timestamps(self, mock_ctx, mock_repo_cls, mock_push):
        """Normal run fetches existing bugs to preserve incremental completed_at timestamps."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_repo = AsyncMock()
        mock_repo_cls.return_value = mock_repo
        mock_session = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Simulate bug 0 already has completed_at from incremental sync
        mock_bug_0 = MagicMock(bug_index=0, completed_at="2026-02-14T04:00:00")
        mock_bug_1 = MagicMock(bug_index=1, completed_at=None)
        mock_db_job = MagicMock(bugs=[mock_bug_0, mock_bug_1])
        mock_repo.get.return_value = mock_db_job

        final_state = {"results": [
            {"status": "completed"},
            {"status": "failed", "error": "oops"},
        ]}

        await _sync_final_results("job_1", final_state, ["url1", "url2"], bug_index_offset=0)

        # repo.get IS called to fetch existing bugs for timestamp preservation
        mock_repo.get.assert_awaited_once_with("job_1")
        # Bug 0: completed_at=None (preserved, already set by incremental sync)
        # Bug 1: completed_at=<now> (set by final sync since it was None)
        calls = mock_repo.update_bug_status.call_args_list
        assert calls[0].kwargs.get("completed_at") is None  # bug 0 preserved
        assert calls[1].kwargs.get("completed_at") is not None  # bug 1 set

    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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
    """Test that _sync_final_results retries with exponential backoff on DB failure."""

    @patch("workflow.temporal.state_sync.random.uniform", return_value=0.0)
    @patch("workflow.temporal.sse_events.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    @patch("app.repositories.batch_job.BatchJobRepository")
    @patch("app.database.get_session_ctx")
    async def test_retry_succeeds_on_second_attempt(self, mock_ctx, mock_repo_cls, mock_push, mock_sleep, mock_uniform):
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

        # Should have slept with exponential backoff (2^0 * 1.0 = 1.0 with jitter=0)
        mock_sleep.assert_awaited_once_with(1.0)

        # job_done should NOT have db_sync_failed
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1
        assert "db_sync_failed" not in job_done_calls[0][0][2]

    @patch("workflow.temporal.state_sync.random.uniform", return_value=0.0)
    @patch("workflow.temporal.sse_events.asyncio.sleep", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_all_attempts_fail_sets_warning(self, mock_ctx, mock_push, mock_sleep, mock_uniform):
        """All 4 DB attempts fail → db_sync_failed in job_done event."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("persistent DB error")
        )
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        final_state = {"results": [{"status": "completed"}]}

        await _sync_final_results("job_1", final_state, ["url1"])

        # Should have slept 3 times (between attempts 1-2, 2-3, 3-4)
        # Backoff: 2^0=1.0, 2^1=2.0, 2^2=4.0 (with jitter=0)
        assert mock_sleep.await_count == 3
        mock_sleep.assert_any_await(1.0)
        mock_sleep.assert_any_await(2.0)
        mock_sleep.assert_any_await(4.0)

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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
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
# ===========================================================================
# T104: Pre-flight Check Tests
# ===========================================================================


class TestPreflightCheck:
    """Test _preflight_check environment validation."""

    @pytest.mark.asyncio
    async def test_all_checks_pass(self):
        from workflow.temporal.batch_activities import _preflight_check

        with patch("workflow.temporal.git_operations.os.path.isdir", return_value=True):
            with patch(
                "workflow.temporal.git_operations._git_is_repo",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
                    ok, issues = await _preflight_check("/tmp/repo", {}, "job_1")
                    assert ok is True
                    assert issues == []

    @pytest.mark.asyncio
    async def test_cwd_not_exists(self):
        from workflow.temporal.batch_activities import _preflight_check

        with patch("workflow.temporal.git_operations.os.path.isdir", return_value=False):
            with patch("shutil.which", return_value=None):
                with patch.dict("os.environ", {}, clear=True):
                    ok, issues = await _preflight_check("/nonexistent", {}, "job_1")
                    assert ok is False
                    assert any("工作目录不存在" in e for e in issues)

    @pytest.mark.asyncio
    async def test_not_git_repo(self):
        from workflow.temporal.batch_activities import _preflight_check

        with patch("workflow.temporal.git_operations.os.path.isdir", return_value=True):
            with patch(
                "workflow.temporal.git_operations._git_is_repo",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with patch("shutil.which", return_value=None):
                    with patch.dict("os.environ", {}, clear=True):
                        ok, issues = await _preflight_check("/tmp/repo", {}, "job_1")
                        assert ok is False
                        assert any("不是 Git 仓库" in e for e in issues)

    @pytest.mark.asyncio
    async def test_claude_cli_missing(self):
        from workflow.temporal.batch_activities import _preflight_check

        def mock_which(name):
            if name == "claude":
                return None
            return f"/usr/bin/{name}"

        with patch("workflow.temporal.git_operations.os.path.isdir", return_value=True):
            with patch(
                "workflow.temporal.git_operations._git_is_repo",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch("shutil.which", side_effect=mock_which):
                    ok, issues = await _preflight_check("/tmp/repo", {}, "job_1")
                    assert ok is False
                    assert any("Claude CLI" in e for e in issues)

    @pytest.mark.asyncio
    async def test_multiple_errors(self):
        """cwd not exists + claude missing = 2 errors."""
        from workflow.temporal.batch_activities import _preflight_check

        with patch("workflow.temporal.git_operations.os.path.isdir", return_value=False):
            with patch("shutil.which", return_value=None):
                with patch.dict("os.environ", {}, clear=True):
                    ok, issues = await _preflight_check("/nonexistent", {}, "job_1")
                    assert ok is False
                    assert len([e for e in issues if "不存在" in e or "CLI" in e]) >= 2


# ===========================================================================
# T107: Dry-Run Preview Mode Tests
# ===========================================================================


class TestDryRunRoute:
    """Test dry_run=true returns preview without starting Temporal."""

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_dry_run_returns_preview(self, mock_ctx, mock_client):
        """dry_run=true should return preview without DB/Temporal."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        payload = BatchBugFixRequest(
            jira_urls=[
                "https://tssoft.atlassian.net/browse/XSZS-100",
                "https://tssoft.atlassian.net/browse/XSZS-200",
            ],
            cwd="/tmp/project",
            dry_run=True,
        )
        resp = await create_batch_bug_fix(payload)

        # Should be a JSONResponse, not BatchBugFixResponse
        import json
        body = json.loads(resp.body.decode())
        assert body["dry_run"] is True
        assert body["total_bugs"] == 2
        assert body["cwd"] == "/tmp/project"
        assert len(body["bugs"]) == 2
        assert body["bugs"][0]["jira_key"] == "XSZS-100"
        assert body["bugs"][1]["jira_key"] == "XSZS-200"
        assert len(body["expected_steps_per_bug"]) > 0

        # DB and Temporal should NOT be called
        mock_ctx.assert_not_called()
        mock_client.assert_not_called()

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_dry_run_default_config(self, mock_ctx, mock_client):
        """dry_run with no config should use defaults."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        payload = BatchBugFixRequest(
            jira_urls=["https://tssoft.atlassian.net/browse/PROJ-1"],
            dry_run=True,
        )
        resp = await create_batch_bug_fix(payload)

        import json
        body = json.loads(resp.body.decode())
        assert body["dry_run"] is True
        assert body["cwd"] == "."
        assert body["config"]["validation_level"] == "standard"
        assert body["config"]["failure_policy"] == "skip"
        assert body["config"]["max_retries"] == 3

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_dry_run_status_code_200(self, mock_ctx, mock_client):
        """dry_run should return HTTP 200, not 201."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        payload = BatchBugFixRequest(
            jira_urls=["https://tssoft.atlassian.net/browse/PROJ-1"],
            dry_run=True,
        )
        resp = await create_batch_bug_fix(payload)
        assert resp.status_code == 200

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_dry_run_extracts_jira_key(self, mock_ctx, mock_client):
        """Should extract Jira key from various URL formats."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        payload = BatchBugFixRequest(
            jira_urls=[
                "https://tssoft.atlassian.net/browse/XSZS-15463",
                "https://tssoft.atlassian.net/browse/PROJ-42",
                "https://tssoft.atlassian.net/browse/ABC-1",
            ],
            dry_run=True,
        )
        resp = await create_batch_bug_fix(payload)

        import json
        body = json.loads(resp.body.decode())
        keys = [b["jira_key"] for b in body["bugs"]]
        assert keys == ["XSZS-15463", "PROJ-42", "ABC-1"]

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_dry_run_bug_has_expected_steps(self, mock_ctx, mock_client):
        """Each bug should have expected_steps list."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        payload = BatchBugFixRequest(
            jira_urls=["https://tssoft.atlassian.net/browse/PROJ-1"],
            dry_run=True,
        )
        resp = await create_batch_bug_fix(payload)

        import json
        body = json.loads(resp.body.decode())
        bug_steps = body["bugs"][0]["expected_steps"]
        assert len(bug_steps) >= 3
        assert "修复 Bug" in bug_steps

    @patch("app.routes.batch.get_client", new_callable=AsyncMock)
    @patch("app.database.get_session_ctx")
    async def test_non_dry_run_starts_workflow(self, mock_ctx, mock_client):
        """dry_run=false (default) should proceed normally."""
        from app.routes.batch import create_batch_bug_fix, BatchBugFixRequest

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # Mock BatchJobRepository constructor
        with patch("app.routes.batch.BatchJobRepository", return_value=mock_repo):
            mock_temporal = AsyncMock()
            mock_client.return_value = mock_temporal

            payload = BatchBugFixRequest(
                jira_urls=["https://tssoft.atlassian.net/browse/PROJ-1"],
                cwd="/tmp",
            )
            resp = await create_batch_bug_fix(payload)

            # Should return BatchBugFixResponse (not JSONResponse)
            assert hasattr(resp, "job_id")
            assert resp.status == "started"
            assert resp.total_bugs == 1

            # Temporal should have been called
            mock_temporal.start_workflow.assert_called_once()

    async def test_extract_jira_key_helper(self):
        """Verify _extract_jira_key_from_url helper."""
        from app.routes.batch import _extract_jira_key_from_url

        assert _extract_jira_key_from_url("https://tssoft.atlassian.net/browse/XSZS-100") == "XSZS-100"
        assert _extract_jira_key_from_url("https://tssoft.atlassian.net/browse/ABC-1") == "ABC-1"
        assert _extract_jira_key_from_url("https://tssoft.atlassian.net/PROJ-42") == "PROJ-42"


# ---------------------------------------------------------------------------
# 22. T105: _db_index helper
# ---------------------------------------------------------------------------


class TestDbIndex:
    """Test _db_index mapping helper."""

    def test_offset_only_no_index_map(self):
        from workflow.temporal.batch_activities import _db_index

        assert _db_index(0, 3) == 3
        assert _db_index(1, 3) == 4
        assert _db_index(0, 0) == 0

    def test_index_map_overrides_offset(self):
        from workflow.temporal.batch_activities import _db_index

        # index_map=[1, 3, 4] means workflow bug 0 → DB 1, 1 → 3, 2 → 4
        index_map = [1, 3, 4]
        assert _db_index(0, 0, index_map) == 1
        assert _db_index(1, 0, index_map) == 3
        assert _db_index(2, 0, index_map) == 4

    def test_index_map_with_offset(self):
        """index_map already includes offset, so offset param is ignored."""
        from workflow.temporal.batch_activities import _db_index

        # index_map=[5, 7] (already offset-adjusted)
        index_map = [5, 7]
        assert _db_index(0, 5, index_map) == 5
        assert _db_index(1, 5, index_map) == 7

    def test_index_map_out_of_range_fallback(self):
        from workflow.temporal.batch_activities import _db_index

        index_map = [2, 4]
        # Index beyond map falls back to raw bug_index
        assert _db_index(5, 0, index_map) == 5

    def test_none_index_map_uses_offset(self):
        from workflow.temporal.batch_activities import _db_index

        assert _db_index(2, 10, None) == 12


# ---------------------------------------------------------------------------
# 23. T105: _jira_get_status
# ---------------------------------------------------------------------------


class TestJiraGetStatus:
    """Test _jira_get_status helper."""

    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    @patch("httpx.AsyncClient")
    async def test_returns_done_for_resolved_issue(self, mock_client_cls):
        from workflow.temporal.batch_activities import _jira_get_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "fields": {
                "status": {
                    "statusCategory": {"key": "Done"}
                }
            }
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _jira_get_status(
            "https://jira.example.com/browse/TEST-1", "job_1"
        )
        assert result == "done"

    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    @patch("httpx.AsyncClient")
    async def test_returns_indeterminate_for_in_progress(self, mock_client_cls):
        from workflow.temporal.batch_activities import _jira_get_status

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "fields": {
                "status": {
                    "statusCategory": {"key": "indeterminate"}
                }
            }
        }
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _jira_get_status(
            "https://jira.example.com/browse/TEST-2", "job_1"
        )
        assert result == "indeterminate"

    @patch.dict("os.environ", {"JIRA_URL": "", "JIRA_EMAIL": "", "JIRA_API_TOKEN": ""})
    async def test_returns_none_without_credentials(self):
        from workflow.temporal.batch_activities import _jira_get_status

        result = await _jira_get_status(
            "https://jira.example.com/browse/TEST-1", "job_1"
        )
        assert result is None

    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    @patch("httpx.AsyncClient")
    async def test_returns_none_on_http_error(self, mock_client_cls):
        from workflow.temporal.batch_activities import _jira_get_status

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _jira_get_status(
            "https://jira.example.com/browse/MISSING-1", "job_1"
        )
        assert result is None

    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    @patch("httpx.AsyncClient")
    async def test_returns_none_on_exception(self, mock_client_cls):
        from workflow.temporal.batch_activities import _jira_get_status

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("connection refused")
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _jira_get_status(
            "https://jira.example.com/browse/TEST-1", "job_1"
        )
        assert result is None


# ---------------------------------------------------------------------------
# 24. T105: _prescan_closed_bugs
# ---------------------------------------------------------------------------


class TestPrescanClosedBugs:
    """Test _prescan_closed_bugs helper."""

    @patch.dict("os.environ", {"JIRA_URL": "", "JIRA_EMAIL": "", "JIRA_API_TOKEN": ""})
    async def test_no_credentials_returns_empty(self):
        from workflow.temporal.batch_activities import _prescan_closed_bugs

        result = await _prescan_closed_bugs(
            ["https://jira.example.com/browse/TEST-1"], "job_1"
        )
        assert result == set()

    @patch("workflow.temporal.git_operations._jira_get_status", new_callable=AsyncMock)
    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    async def test_all_open_returns_empty(self, mock_status):
        from workflow.temporal.batch_activities import _prescan_closed_bugs

        mock_status.return_value = "indeterminate"
        urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
        ]
        result = await _prescan_closed_bugs(urls, "job_1")
        assert result == set()
        assert mock_status.call_count == 2

    @patch("workflow.temporal.git_operations._jira_get_status", new_callable=AsyncMock)
    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    async def test_some_closed_returns_indices(self, mock_status):
        from workflow.temporal.batch_activities import _prescan_closed_bugs

        # Bug 0: open, Bug 1: done, Bug 2: open, Bug 3: done
        mock_status.side_effect = ["indeterminate", "done", "new", "done"]
        urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
            "https://jira.example.com/browse/TEST-3",
            "https://jira.example.com/browse/TEST-4",
        ]
        result = await _prescan_closed_bugs(urls, "job_1")
        assert result == {1, 3}

    @patch("workflow.temporal.git_operations._jira_get_status", new_callable=AsyncMock)
    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    async def test_all_closed_returns_all_indices(self, mock_status):
        from workflow.temporal.batch_activities import _prescan_closed_bugs

        mock_status.return_value = "done"
        urls = [
            "https://jira.example.com/browse/TEST-1",
            "https://jira.example.com/browse/TEST-2",
        ]
        result = await _prescan_closed_bugs(urls, "job_1")
        assert result == {0, 1}

    @patch("workflow.temporal.git_operations._jira_get_status", new_callable=AsyncMock)
    @patch.dict("os.environ", {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_API_TOKEN": "token123",
    })
    async def test_api_failure_returns_empty(self, mock_status):
        """If Jira API returns None, bugs are NOT skipped (best-effort)."""
        from workflow.temporal.batch_activities import _prescan_closed_bugs

        mock_status.return_value = None
        urls = ["https://jira.example.com/browse/TEST-1"]
        result = await _prescan_closed_bugs(urls, "job_1")
        assert result == set()


# ---------------------------------------------------------------------------
# 25. T105: _sync_incremental_results with index_map
# ---------------------------------------------------------------------------


class TestSyncIncrementalResultsWithIndexMap:
    """Test _sync_incremental_results with index_map for skip scenarios."""

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    async def test_index_map_sse_uses_mapped_index(self, mock_push, mock_db):
        """5-bug job, bugs 1,3 skipped → active bugs are 0,2,4.
        index_map=[0, 2, 4]. Workflow bug 1 → DB bug 2."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = [
            "https://jira.example.com/browse/TEST-0",
            "https://jira.example.com/browse/TEST-2",
            "https://jira.example.com/browse/TEST-4",
        ]
        results = [{"status": "completed"}, {"status": "failed", "error": "oops"}]
        index_map = [0, 2, 4]

        await _sync_incremental_results(
            "job_1", jira_urls, results, 0,
            bug_index_offset=0, index_map=index_map,
        )

        # Bug completed event for workflow bug 0 → DB bug 0
        bug_completed_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_completed"
        ]
        assert len(bug_completed_calls) == 1
        assert bug_completed_calls[0][0][2]["bug_index"] == 0

        # Bug failed event for workflow bug 1 → DB bug 2
        bug_failed_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_failed"
        ]
        assert len(bug_failed_calls) == 1
        assert bug_failed_calls[0][0][2]["bug_index"] == 2

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    async def test_index_map_db_update_uses_mapped_index(self, mock_push, mock_db):
        """DB update should use mapped index, not array index."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = ["https://jira.example.com/browse/TEST-2"]
        results = [{"status": "completed"}]
        index_map = [2]  # workflow bug 0 → DB bug 2

        await _sync_incremental_results(
            "job_1", jira_urls, results, 0,
            bug_index_offset=0, index_map=index_map,
        )

        # DB update for status should use bug_index=2
        status_calls = [
            c for c in mock_db.call_args_list
            if len(c[0]) >= 3 and c[0][2] in ("completed", "failed")
        ]
        assert len(status_calls) == 1
        assert status_calls[0][0][1] == 2  # db_i = index_map[0] = 2

    @patch("workflow.temporal.state_sync._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock)
    async def test_index_map_next_bug_started_uses_mapped_index(self, mock_push, mock_db):
        """Next bug_started should use mapped index for the next active bug."""
        from workflow.temporal.batch_activities import _sync_incremental_results

        mock_db.return_value = True
        jira_urls = [
            "https://jira.example.com/browse/TEST-0",
            "https://jira.example.com/browse/TEST-3",
        ]
        results = [{"status": "completed"}]
        index_map = [0, 3]  # workflow bug 0 → DB 0, workflow bug 1 → DB 3

        await _sync_incremental_results(
            "job_1", jira_urls, results, 0,
            bug_index_offset=0, index_map=index_map,
        )

        bug_started_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_started"
        ]
        assert len(bug_started_calls) == 1
        assert bug_started_calls[0][0][2]["bug_index"] == 3  # index_map[1] = 3


# ---------------------------------------------------------------------------
# 26. T105: _sync_final_results with index_map and pre_skipped
# ---------------------------------------------------------------------------


class TestSyncFinalResultsWithSkip:
    """Test _sync_final_results with index_map and pre_skipped."""

    @patch("app.database.get_session_ctx")
    async def test_skipped_bugs_not_counted_as_failure(self, mock_ctx):
        """Pre-scan skipped bugs (already resolved) should not make job 'failed'."""
        from workflow.temporal.batch_activities import _sync_final_results
        from workflow.temporal.batch_activities import _push_event

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        # 5-bug job: 2 pre-scan skipped (done), 3 active (all completed)
        bugs = [
            _make_bug_model(0, "completed"),
            _make_bug_model(1, "skipped"),    # pre-scan
            _make_bug_model(2, "completed"),
            _make_bug_model(3, "skipped"),    # pre-scan
            _make_bug_model(4, "completed"),
        ]
        mock_repo.get.return_value = _make_job_model(bugs=bugs)
        mock_repo.update_bug_status = AsyncMock()
        mock_repo.update_status = AsyncMock()

        with patch("app.repositories.batch_job.BatchJobRepository", return_value=mock_repo):
            with patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock) as mock_push:
                final_state = {
                    "results": [
                        {"status": "completed"},
                        {"status": "completed"},
                        {"status": "completed"},
                    ]
                }
                index_map = [0, 2, 4]

                await _sync_final_results(
                    "job_1", final_state,
                    [
                        "https://jira.example.com/browse/TEST-0",
                        "https://jira.example.com/browse/TEST-2",
                        "https://jira.example.com/browse/TEST-4",
                    ],
                    bug_index_offset=0,
                    index_map=index_map,
                    pre_skipped=2,
                )

                # Overall status should be "completed" (no failed bugs in DB)
                mock_repo.update_status.assert_called_with("job_1", "completed")

                # job_done event should include correct totals
                job_done_calls = [
                    c for c in mock_push.call_args_list if c[0][1] == "job_done"
                ]
                assert len(job_done_calls) == 1
                event = job_done_calls[0][0][2]
                assert event["status"] == "completed"
                assert event["total"] == 5  # 3 active + 2 pre-skipped
                assert event["skipped"] == 2  # pre-skipped only

    @patch("app.database.get_session_ctx")
    async def test_mixed_results_with_skip(self, mock_ctx):
        """Some active bugs failed + pre-skipped → overall 'failed'."""
        from workflow.temporal.batch_activities import _sync_final_results

        mock_session = AsyncMock()
        mock_repo = AsyncMock()
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        bugs = [
            _make_bug_model(0, "completed"),
            _make_bug_model(1, "skipped"),    # pre-scan
            _make_bug_model(2, "failed"),      # active bug failed
        ]
        mock_repo.get.return_value = _make_job_model(bugs=bugs)
        mock_repo.update_bug_status = AsyncMock()
        mock_repo.update_status = AsyncMock()

        with patch("app.repositories.batch_job.BatchJobRepository", return_value=mock_repo):
            with patch("workflow.temporal.sse_events._push_event", new_callable=AsyncMock):
                final_state = {
                    "results": [
                        {"status": "completed"},
                        {"status": "failed", "error": "compile error"},
                    ]
                }
                index_map = [0, 2]

                await _sync_final_results(
                    "job_1", final_state,
                    [
                        "https://jira.example.com/browse/TEST-0",
                        "https://jira.example.com/browse/TEST-2",
                    ],
                    bug_index_offset=0,
                    index_map=index_map,
                    pre_skipped=1,
                )

                # Overall should be "failed" because bug 2 failed
                mock_repo.update_status.assert_called_with("job_1", "failed")


# ---------------------------------------------------------------------------
# 27. T105: Integration — pre-scan in execute_batch_bugfix_activity
# ---------------------------------------------------------------------------


class TestPrescanIntegration:
    """Test pre-scan integration in execute_batch_bugfix_activity."""

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._preflight_check", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._prescan_closed_bugs", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities.activity")
    async def test_all_bugs_closed_returns_early(
        self, mock_activity, mock_prescan, mock_preflight,
        mock_update_job, mock_update_bug, mock_push,
    ):
        """When all bugs are resolved, activity should return early with success."""
        from workflow.temporal.batch_activities import execute_batch_bugfix_activity

        mock_preflight.return_value = (True, [])
        mock_prescan.return_value = {0, 1, 2}  # All 3 bugs closed
        mock_activity.info.return_value.attempt = 1
        mock_update_job.return_value = True
        mock_update_bug.return_value = True

        params = {
            "job_id": "job_all_skip",
            "jira_urls": [
                "https://jira.example.com/browse/TEST-1",
                "https://jira.example.com/browse/TEST-2",
                "https://jira.example.com/browse/TEST-3",
            ],
            "cwd": "/tmp/test",
            "config": {},
        }

        result = await execute_batch_bugfix_activity(params)

        assert result["success"] is True
        assert result.get("all_skipped") is True

        # Should have pushed bug_skipped events for all 3 bugs
        bug_skipped_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "bug_skipped"
        ]
        assert len(bug_skipped_calls) == 3

        # Should have pushed job_done with all skipped
        job_done_calls = [
            c for c in mock_push.call_args_list if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1
        assert job_done_calls[0][0][2]["skipped"] == 3
        assert job_done_calls[0][0][2]["status"] == "completed"

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._preflight_check", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._prescan_closed_bugs", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._execute_workflow", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._sync_final_results", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities.activity")
    async def test_some_bugs_closed_passes_index_map(
        self, mock_activity, mock_final_sync, mock_execute,
        mock_prescan, mock_preflight, mock_update_job,
        mock_update_bug, mock_push,
    ):
        """When some bugs are closed, index_map is built and passed correctly."""
        from workflow.temporal.batch_activities import execute_batch_bugfix_activity

        mock_preflight.return_value = (True, [])
        mock_prescan.return_value = {1}  # Bug 1 closed
        mock_activity.info.return_value.attempt = 1
        mock_activity.heartbeat = MagicMock()
        mock_update_job.return_value = True
        mock_update_bug.return_value = True
        mock_execute.return_value = {"results": [{"status": "completed"}, {"status": "completed"}]}

        params = {
            "job_id": "job_partial_skip",
            "jira_urls": [
                "https://jira.example.com/browse/TEST-0",
                "https://jira.example.com/browse/TEST-1",  # closed
                "https://jira.example.com/browse/TEST-2",
            ],
            "cwd": "/tmp/test",
            "config": {},
        }

        result = await execute_batch_bugfix_activity(params)

        assert result["success"] is True

        # _execute_workflow should receive only active URLs
        execute_call = mock_execute.call_args
        active_urls = execute_call[0][1]  # second positional arg
        assert len(active_urls) == 2
        assert "TEST-1" not in str(active_urls)

        # index_map should be [0, 2] (skip bug 1)
        index_map = execute_call[0][5]  # sixth positional arg
        assert index_map == [0, 2]

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._preflight_check", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._prescan_closed_bugs", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._execute_workflow", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._sync_final_results", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities.activity")
    async def test_no_bugs_closed_no_index_map(
        self, mock_activity, mock_final_sync, mock_execute,
        mock_prescan, mock_preflight, mock_update_job,
        mock_update_bug, mock_push,
    ):
        """When no bugs are closed, index_map is None and all URLs pass through."""
        from workflow.temporal.batch_activities import execute_batch_bugfix_activity

        mock_preflight.return_value = (True, [])
        mock_prescan.return_value = set()  # No bugs closed
        mock_activity.info.return_value.attempt = 1
        mock_activity.heartbeat = MagicMock()
        mock_update_job.return_value = True
        mock_update_bug.return_value = True
        mock_execute.return_value = {"results": [{"status": "completed"}]}

        params = {
            "job_id": "job_no_skip",
            "jira_urls": ["https://jira.example.com/browse/TEST-0"],
            "cwd": "/tmp/test",
            "config": {},
        }

        result = await execute_batch_bugfix_activity(params)
        assert result["success"] is True

        # _execute_workflow should receive original URLs and None index_map
        execute_call = mock_execute.call_args
        active_urls = execute_call[0][1]
        assert len(active_urls) == 1
        index_map = execute_call[0][5]
        assert index_map is None

    @patch("workflow.temporal.batch_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_bug_status_db", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._preflight_check", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities._prescan_closed_bugs", new_callable=AsyncMock)
    @patch("workflow.temporal.batch_activities.activity")
    async def test_skipped_bugs_marked_in_db(
        self, mock_activity, mock_prescan, mock_preflight,
        mock_update_job, mock_update_bug, mock_push,
    ):
        """Pre-scan skipped bugs should be marked as 'skipped' in DB."""
        from workflow.temporal.batch_activities import execute_batch_bugfix_activity

        mock_preflight.return_value = (True, [])
        mock_prescan.return_value = {0, 1, 2}  # All closed
        mock_activity.info.return_value.attempt = 1
        mock_update_job.return_value = True
        mock_update_bug.return_value = True

        params = {
            "job_id": "job_db_skip",
            "jira_urls": [
                "https://jira.example.com/browse/TEST-1",
                "https://jira.example.com/browse/TEST-2",
                "https://jira.example.com/browse/TEST-3",
            ],
            "cwd": "/tmp/test",
            "config": {},
        }

        await execute_batch_bugfix_activity(params)

        # DB should have been called with "skipped" for all 3 bugs
        skip_calls = [
            c for c in mock_update_bug.call_args_list
            if len(c[0]) >= 3 and c[0][2] == "skipped"
        ]
        assert len(skip_calls) == 3
        # Verify indices 0, 1, 2
        skip_indices = sorted(c[0][1] for c in skip_calls)
        assert skip_indices == [0, 1, 2]
