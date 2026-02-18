"""Tests for workflow.temporal.spec_activities — Design-to-Spec pipeline activity.

Covers:
- Checkpoint helpers (_checkpoint_dir, _save_checkpoint, _load_checkpoints)
- DB helpers (_update_job_status, _update_component_counts)
- Heartbeat (_periodic_heartbeat)
- Main activity (execute_spec_pipeline_activity) — happy path, 0-components, Figma error,
  cancellation, checkpoint resume, SpecAnalyzer failures
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.temporal.spec_activities import (
    _checkpoint_dir,
    _load_checkpoints,
    _periodic_heartbeat,
    _save_checkpoint,
    _update_component_counts,
    _update_job_status,
    execute_spec_pipeline_activity,
)


# ─── Checkpoint helpers ───────────────────────────────────────────────


class TestCheckpointDir:
    def test_returns_checkpoint_subdir(self):
        result = _checkpoint_dir("/some/output")
        assert result == "/some/output/.spec_checkpoints"

    def test_works_with_trailing_slash(self):
        result = _checkpoint_dir("/some/output/")
        assert result.endswith(".spec_checkpoints")


class TestSaveCheckpoint:
    def test_saves_json_file(self, tmp_path):
        data = {"id": "comp-1", "role": "button", "description": "A button"}
        _save_checkpoint(str(tmp_path), "comp-1", data)

        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        assert os.path.isdir(cp_dir)

        path = os.path.join(cp_dir, "comp-1.json")
        assert os.path.isfile(path)

        with open(path) as f:
            loaded = json.load(f)
        assert loaded["id"] == "comp-1"
        assert loaded["role"] == "button"

    def test_sanitizes_id_with_special_chars(self, tmp_path):
        data = {"id": "1:23/abc", "role": "text"}
        _save_checkpoint(str(tmp_path), "1:23/abc", data)

        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        path = os.path.join(cp_dir, "1_23_abc.json")
        assert os.path.isfile(path)

    def test_handles_write_failure_gracefully(self, tmp_path):
        """Save should not raise on json.dump failure — just log a warning."""
        # Create checkpoint dir so makedirs succeeds, but mock open to fail
        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        os.makedirs(cp_dir, exist_ok=True)
        with patch("builtins.open", side_effect=PermissionError("denied")):
            _save_checkpoint(str(tmp_path), "comp-1", {"id": "comp-1"})
        # No exception raised


class TestLoadCheckpoints:
    def test_returns_empty_dict_for_missing_dir(self, tmp_path):
        result = _load_checkpoints(str(tmp_path))
        assert result == {}

    def test_loads_saved_checkpoints(self, tmp_path):
        data1 = {"id": "comp-1", "role": "button"}
        data2 = {"id": "comp-2", "role": "text"}
        _save_checkpoint(str(tmp_path), "comp-1", data1)
        _save_checkpoint(str(tmp_path), "comp-2", data2)

        result = _load_checkpoints(str(tmp_path))
        assert len(result) == 2
        assert result["comp-1"]["role"] == "button"
        assert result["comp-2"]["role"] == "text"

    def test_skips_non_json_files(self, tmp_path):
        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        os.makedirs(cp_dir)
        with open(os.path.join(cp_dir, "readme.txt"), "w") as f:
            f.write("not json")
        _save_checkpoint(str(tmp_path), "comp-1", {"id": "comp-1", "role": "nav"})

        result = _load_checkpoints(str(tmp_path))
        assert len(result) == 1
        assert "comp-1" in result

    def test_skips_entries_without_id(self, tmp_path):
        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        os.makedirs(cp_dir)
        with open(os.path.join(cp_dir, "bad.json"), "w") as f:
            json.dump({"role": "button"}, f)  # no 'id' key

        result = _load_checkpoints(str(tmp_path))
        assert len(result) == 0

    def test_handles_corrupt_json_gracefully(self, tmp_path):
        cp_dir = os.path.join(str(tmp_path), ".spec_checkpoints")
        os.makedirs(cp_dir)
        with open(os.path.join(cp_dir, "bad.json"), "w") as f:
            f.write("{invalid json")

        result = _load_checkpoints(str(tmp_path))
        assert result == {}


# ─── DB helpers ───────────────────────────────────────────────────────


class TestUpdateJobStatus:
    @pytest.mark.asyncio
    @patch("app.database.get_session_ctx")
    @patch("app.repositories.design_job.DesignJobRepository")
    async def test_success(self, MockRepo, mock_session_ctx):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo_instance = MockRepo.return_value
        mock_repo_instance.update = AsyncMock()

        result = await _update_job_status("job-1", "running")

        assert result is True
        mock_repo_instance.update.assert_called_once()
        call_kwargs = mock_repo_instance.update.call_args
        assert call_kwargs[0][0] == "job-1"
        assert call_kwargs[1]["status"] == "running"

    @pytest.mark.asyncio
    @patch("app.database.get_session_ctx")
    @patch("app.repositories.design_job.DesignJobRepository")
    async def test_with_error_and_completed_at(self, MockRepo, mock_session_ctx):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo_instance = MockRepo.return_value
        mock_repo_instance.update = AsyncMock()

        now = datetime.now(timezone.utc)
        result = await _update_job_status(
            "job-1", "failed", error="Something broke", completed_at=now,
        )

        assert result is True
        call_kwargs = mock_repo_instance.update.call_args[1]
        assert call_kwargs["error"] == "Something broke"
        assert call_kwargs["completed_at"] == now

    @pytest.mark.asyncio
    @patch("app.database.get_session_ctx", side_effect=Exception("DB down"))
    async def test_returns_false_on_db_error(self, _):
        result = await _update_job_status("job-1", "running")
        assert result is False


class TestUpdateComponentCounts:
    @pytest.mark.asyncio
    @patch("app.database.get_session_ctx")
    @patch("app.repositories.design_job.DesignJobRepository")
    async def test_success(self, MockRepo, mock_session_ctx):
        mock_session = AsyncMock()
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo_instance = MockRepo.return_value
        mock_repo_instance.update_component_counts = AsyncMock()

        result = await _update_component_counts("job-1", total=5, completed=3, failed=1)

        assert result is True
        mock_repo_instance.update_component_counts.assert_called_once_with(
            "job-1", total=5, completed=3, failed=1,
        )

    @pytest.mark.asyncio
    @patch("app.database.get_session_ctx", side_effect=Exception("DB down"))
    async def test_returns_false_on_db_error(self, _):
        result = await _update_component_counts("job-1", total=5)
        assert result is False


# ─── Heartbeat ────────────────────────────────────────────────────────


class TestPeriodicHeartbeat:
    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    async def test_sends_heartbeats(self, mock_activity):
        """Heartbeat should call activity.heartbeat periodically."""
        call_count = 0

        def track_heartbeat(msg):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise Exception("Stop")  # break the loop

        mock_activity.heartbeat = track_heartbeat

        task = asyncio.create_task(_periodic_heartbeat("job-1", interval_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count >= 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    async def test_stops_on_exception(self, mock_activity):
        """Heartbeat should stop when activity.heartbeat raises."""
        mock_activity.heartbeat = MagicMock(side_effect=Exception("cancelled"))

        task = asyncio.create_task(_periodic_heartbeat("job-1", interval_seconds=0.01))
        await asyncio.sleep(0.05)
        assert task.done()


# ─── Main activity ────────────────────────────────────────────────────


def _make_params(tmp_path, **overrides):
    """Helper to build minimal valid params for execute_spec_pipeline_activity."""
    params = {
        "job_id": "test-job-1",
        "file_key": "abc123",
        "node_id": "0:1",
        "output_dir": str(tmp_path),
        "model": "",
    }
    params.update(overrides)
    return params


def _mock_figma_client(children=None, screenshots=None, tokens=None):
    """Create a mock FigmaClient with configurable responses."""
    if children is None:
        children = [
            {"id": "1:1", "name": "Header", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 80}},
            {"id": "1:2", "name": "Body", "type": "FRAME",
             "absoluteBoundingBox": {"x": 0, "y": 80, "width": 393, "height": 700}},
        ]

    client = AsyncMock()
    client.get_file_nodes = AsyncMock(return_value={
        "name": "Test File",
        "lastModified": "2026-01-01T00:00:00Z",
        "nodes": {
            "0:1": {
                "document": {
                    "name": "Test Page",
                    "children": children,
                },
            },
        },
    })
    client.download_screenshots = AsyncMock(
        return_value=screenshots or {"0:1": "/tmp/screenshot.png"},
    )
    client.get_design_tokens = AsyncMock(return_value=tokens or {})
    client.close = AsyncMock()
    return client


def _mock_decomposer_result(components=None):
    """Build FrameDecomposerNode result."""
    if components is None:
        components = [
            {"id": "1:1", "name": "Header", "role": "other", "bounds": {"x": 0, "y": 0, "width": 393, "height": 80}},
            {"id": "1:2", "name": "Body", "role": "other", "bounds": {"x": 0, "y": 80, "width": 393, "height": 700}},
        ]
    return {
        "components": components,
        "page": {"device": {"type": "mobile", "width": 393, "height": 852}},
        "design_tokens": {},
        "source": {"file_key": "abc123"},
    }


def _mock_analyzer_result(components=None, stats=None):
    """Build SpecAnalyzerNode result."""
    if components is None:
        components = [
            {"id": "1:1", "name": "Header", "role": "navigation", "description": "Top nav bar"},
            {"id": "1:2", "name": "Body", "role": "section", "description": "Main content"},
        ]
    if stats is None:
        stats = {"total": len(components), "succeeded": len(components), "failed": 0}
    return {
        "components": components,
        "analysis_stats": stats,
        "token_usage": {"input_tokens": 1000, "output_tokens": 500},
    }


def _mock_assembler_result(spec_path="/tmp/spec.json"):
    """Build SpecAssemblerNode result."""
    return {
        "spec_path": spec_path,
        "validation": {"warnings": [], "errors": []},
    }


class TestExecuteSpecPipelineActivity:
    """Tests for the main activity function.

    Note: FigmaClient, FrameDecomposerNode, SpecAnalyzerNode, SpecAssemblerNode
    are lazy-imported inside execute_spec_pipeline_activity, so we must patch them
    at their SOURCE modules, not at workflow.temporal.spec_activities.
    """

    # Patch paths for lazy imports
    _FIGMA_CLIENT = "workflow.integrations.figma_client.FigmaClient"
    _FIGMA_ERROR = "workflow.integrations.figma_client.FigmaClientError"
    _DECOMPOSER = "workflow.nodes.spec_nodes.FrameDecomposerNode"
    _ANALYZER = "workflow.nodes.spec_nodes.SpecAnalyzerNode"
    _ASSEMBLER = "workflow.nodes.spec_nodes.SpecAssemblerNode"

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_happy_path(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Full pipeline success: Figma fetch → Decompose → Analyze → Assemble."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True
        mock_counts.return_value = True

        figma_client = _mock_figma_client()
        decomposer_result = _mock_decomposer_result()
        analyzer_result = _mock_analyzer_result()
        spec_path = str(tmp_path / "spec.json")
        assembler_result = _mock_assembler_result(spec_path=spec_path)

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
            patch(self._ANALYZER) as MockAnalyzer,
            patch(self._ASSEMBLER) as MockAssembler,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)
            MockAnalyzer.return_value.execute = AsyncMock(return_value=analyzer_result)
            MockAssembler.return_value.execute = AsyncMock(return_value=assembler_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is True
        assert result["job_id"] == "test-job-1"
        assert result["components_total"] == 2
        assert result["components_completed"] == 2
        assert result["components_failed"] == 0

        # Verify job_done event was pushed
        job_done_calls = [
            c for c in mock_push.call_args_list
            if c[0][1] == "job_done"
        ]
        assert len(job_done_calls) == 1
        assert job_done_calls[0][0][2]["status"] == "completed"

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_figma_client_not_configured(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Should fail gracefully when FIGMA_TOKEN is not set."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True

        from workflow.integrations.figma_client import FigmaClientError

        with patch(
            self._FIGMA_CLIENT,
            side_effect=FigmaClientError("No FIGMA_TOKEN"),
        ):
            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is False
        assert "FIGMA_TOKEN" in result.get("error", "") or "Figma API" in result.get("error", "")

        # Verify status set to failed
        failed_calls = [
            c for c in mock_status.call_args_list
            if len(c[0]) >= 2 and c[0][1] == "failed"
        ]
        assert len(failed_calls) >= 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_zero_components_aborts(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Should abort early when FrameDecomposer returns 0 components (T139)."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True
        mock_counts.return_value = True

        figma_client = _mock_figma_client()
        decomposer_result = _mock_decomposer_result(components=[])

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is False
        assert "0" in result.get("error", "") or "组件" in result.get("error", "")

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_checkpoint_resume_skips_completed(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Checkpoint resume: previously completed components should be skipped."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True
        mock_counts.return_value = True

        # Pre-save checkpoint for comp-1
        checkpoint_data = {
            "id": "1:1", "name": "Header", "role": "navigation",
            "description": "Top nav", "_token_usage": {"input_tokens": 100, "output_tokens": 50},
        }
        _save_checkpoint(str(tmp_path), "1:1", checkpoint_data)

        figma_client = _mock_figma_client()
        decomposer_result = _mock_decomposer_result()

        # Analyzer should only receive 1 component (comp-2), not both
        analyzer_result = _mock_analyzer_result(
            components=[{"id": "1:2", "name": "Body", "role": "section", "description": "Content"}],
            stats={"total": 1, "succeeded": 1, "failed": 0},
        )
        assembler_result = _mock_assembler_result(spec_path=str(tmp_path / "spec.json"))

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
            patch(self._ANALYZER) as MockAnalyzer,
            patch(self._ASSEMBLER) as MockAssembler,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)
            MockAnalyzer.return_value.execute = AsyncMock(return_value=analyzer_result)
            MockAssembler.return_value.execute = AsyncMock(return_value=assembler_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is True
        assert result["components_completed"] == 2  # 1 from checkpoint + 1 newly analyzed

        # Verify analyzer was called with only the pending component
        analyzer_call = MockAnalyzer.return_value.execute.call_args[0][0]
        assert len(analyzer_call["components"]) == 1
        assert analyzer_call["components"][0]["id"] == "1:2"

        # Verify checkpoint_resume event was pushed
        resume_calls = [
            c for c in mock_push.call_args_list
            if c[0][1] == "checkpoint_resume"
        ]
        assert len(resume_calls) == 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_analyzer_error_surfaces(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """SpecAnalyzer errors should be surfaced via SSE and status update."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True
        mock_counts.return_value = True

        figma_client = _mock_figma_client()
        decomposer_result = _mock_decomposer_result()
        analyzer_result = _mock_analyzer_result(
            components=[],
            stats={"total": 2, "succeeded": 0, "failed": 2, "error": "api_key invalid"},
        )
        assembler_result = _mock_assembler_result(spec_path=str(tmp_path / "spec.json"))

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
            patch(self._ANALYZER) as MockAnalyzer,
            patch(self._ASSEMBLER) as MockAssembler,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)
            MockAnalyzer.return_value.execute = AsyncMock(return_value=analyzer_result)
            MockAssembler.return_value.execute = AsyncMock(return_value=assembler_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        # Pipeline should still "complete" (assembler ran) but report failures
        assert result["components_failed"] == 2

        # Should push workflow_error with API key related message
        error_calls = [
            c for c in mock_push.call_args_list
            if c[0][1] == "workflow_error"
        ]
        assert len(error_calls) >= 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_cancellation_sets_status(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """CancelledError should be handled gracefully — status set to cancelled."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True

        figma_client = _mock_figma_client()

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
        ):
            MockDecomp.return_value.execute = AsyncMock(
                side_effect=asyncio.CancelledError(),
            )

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is False
        assert result.get("cancelled") is True

        # Verify cancelled status in DB
        cancelled_calls = [
            c for c in mock_status.call_args_list
            if len(c[0]) >= 2 and c[0][1] == "cancelled"
        ]
        assert len(cancelled_calls) >= 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_unexpected_exception_sets_failed(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Unexpected exceptions should be caught and set status to failed."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True

        figma_client = _mock_figma_client()

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
        ):
            MockDecomp.return_value.execute = AsyncMock(
                side_effect=RuntimeError("Unexpected crash"),
            )

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is False
        assert "Unexpected crash" in result.get("error", "")

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_screenshot_failure_non_fatal(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Screenshot download failure should not crash the pipeline."""
        mock_activity.heartbeat = MagicMock()
        mock_status.return_value = True
        mock_counts.return_value = True

        from workflow.integrations.figma_client import FigmaClientError

        figma_client = _mock_figma_client()
        figma_client.download_screenshots = AsyncMock(
            side_effect=FigmaClientError("Download failed"),
        )

        decomposer_result = _mock_decomposer_result()
        analyzer_result = _mock_analyzer_result()
        assembler_result = _mock_assembler_result(spec_path=str(tmp_path / "spec.json"))

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
            patch(self._ANALYZER) as MockAnalyzer,
            patch(self._ASSEMBLER) as MockAssembler,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)
            MockAnalyzer.return_value.execute = AsyncMock(return_value=analyzer_result)
            MockAssembler.return_value.execute = AsyncMock(return_value=assembler_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        # Pipeline should succeed despite screenshot failure
        assert result["success"] is True

        # Warning event should be pushed
        warning_calls = [
            c for c in mock_push.call_args_list
            if c[0][1] == "warning"
        ]
        assert len(warning_calls) >= 1

    @pytest.mark.asyncio
    @patch("workflow.temporal.spec_activities.activity")
    @patch("workflow.temporal.spec_activities._push_event", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_job_status", new_callable=AsyncMock)
    @patch("workflow.temporal.spec_activities._update_component_counts", new_callable=AsyncMock)
    async def test_heartbeat_started_and_cancelled(
        self, mock_counts, mock_status, mock_push, mock_activity, tmp_path,
    ):
        """Heartbeat task should be started and properly cancelled."""
        heartbeat_calls = []
        mock_activity.heartbeat = lambda msg: heartbeat_calls.append(msg)
        mock_status.return_value = True
        mock_counts.return_value = True

        figma_client = _mock_figma_client()
        decomposer_result = _mock_decomposer_result()
        analyzer_result = _mock_analyzer_result()
        assembler_result = _mock_assembler_result(spec_path=str(tmp_path / "spec.json"))

        with (
            patch(self._FIGMA_CLIENT, return_value=figma_client),
            patch(self._DECOMPOSER) as MockDecomp,
            patch(self._ANALYZER) as MockAnalyzer,
            patch(self._ASSEMBLER) as MockAssembler,
        ):
            MockDecomp.return_value.execute = AsyncMock(return_value=decomposer_result)
            MockAnalyzer.return_value.execute = AsyncMock(return_value=analyzer_result)
            MockAssembler.return_value.execute = AsyncMock(return_value=assembler_result)

            result = await execute_spec_pipeline_activity(_make_params(tmp_path))

        assert result["success"] is True
        # Direct heartbeat calls should have been made (phase markers)
        assert any("init" in str(c) for c in heartbeat_calls)
        assert any("complete" in str(c) for c in heartbeat_calls)
