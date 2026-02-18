"""Tests for design-to-spec API routes (app/routes/design.py).

Covers:
- POST /api/v2/design/scan-figma (Figma scan + classification)
- POST /api/v2/design/run-spec (start spec pipeline)
- GET /api/v2/design/{job_id} (job status)
- GET /api/v2/design (list jobs)
- POST /api/v2/design/{job_id}/cancel (cancel job)
- GET /api/v2/design/{job_id}/files (generated files)
- GET /api/v2/design/{job_id}/screenshots/{filename} (screenshots)
- GET /api/v2/design/{job_id}/stream (SSE — basic 404 check)
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient

# Ensure temporalio mock is available
from tests.workflow.conftest import *  # noqa: F401, F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_FIGMA_URL = (
    "https://www.figma.com/design/6kGd851qaAX4TiL44vpIrO/"
    "PixelCheese?node-id=5574-3309"
)

SPEC_PAYLOAD = {
    "figma_url": VALID_FIGMA_URL,
    "output_dir": "/tmp/test-spec-output",
}


async def _create_design_job(client: AsyncClient, **overrides) -> dict:
    """Helper: create a design job via run-spec endpoint and return response JSON."""
    payload = {**SPEC_PAYLOAD, **overrides}
    with patch("app.routes.design.FIGMA_TOKEN", "fake-token", create=True):
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/run-spec", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v2/design/scan-figma — Scan Figma Page
# ---------------------------------------------------------------------------


class TestScanFigma:
    """Tests for Figma scan endpoint."""

    @pytest.mark.asyncio
    async def test_scan_requires_figma_token(self, client: AsyncClient):
        """Without FIGMA_TOKEN, endpoint returns 400."""
        with patch("workflow.config.FIGMA_TOKEN", ""):
            resp = await client.post("/api/v2/design/scan-figma", json={
                "figma_url": VALID_FIGMA_URL,
            })
        assert resp.status_code == 400
        assert "FIGMA_TOKEN" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_scan_invalid_figma_url(self, client: AsyncClient):
        """Invalid Figma URL format returns 400."""
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/scan-figma", json={
                "figma_url": "https://example.com/not-figma",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_scan_missing_node_id(self, client: AsyncClient):
        """Figma URL without node-id returns 400."""
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/scan-figma", json={
                "figma_url": "https://www.figma.com/design/abc123/MyFile",
            })
        assert resp.status_code == 400
        assert "node-id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v2/design/run-spec — Start Spec Pipeline
# ---------------------------------------------------------------------------


class TestRunSpec:
    """Tests for spec pipeline start endpoint."""

    @pytest.mark.asyncio
    async def test_run_spec_requires_figma_token(self, client: AsyncClient):
        with patch("workflow.config.FIGMA_TOKEN", ""):
            resp = await client.post("/api/v2/design/run-spec", json=SPEC_PAYLOAD)
        assert resp.status_code == 400
        assert "FIGMA_TOKEN" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_run_spec_creates_job(self, client: AsyncClient):
        data = await _create_design_job(client)
        assert data["status"] == "started"
        assert data["job_id"].startswith("spec_")
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_run_spec_invalid_url(self, client: AsyncClient):
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/run-spec", json={
                "figma_url": "not-a-figma-url",
                "output_dir": "/tmp/test",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_run_spec_temporal_failure(self, client: AsyncClient):
        """When Temporal is unavailable, job is marked failed and returns 503."""
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            with patch(
                "app.temporal_adapter.start_spec_pipeline",
                AsyncMock(side_effect=RuntimeError("Temporal down")),
            ):
                resp = await client.post("/api/v2/design/run-spec", json=SPEC_PAYLOAD)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/v2/design/{job_id} — Job Status
# ---------------------------------------------------------------------------


class TestGetDesignJobStatus:
    """Tests for design job status endpoint."""

    @pytest.mark.asyncio
    async def test_get_existing_job(self, client: AsyncClient):
        created = await _create_design_job(client)
        resp = await client.get(f"/api/v2/design/{created['job_id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == created["job_id"]
        assert data["status"] == "started"

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/design/nonexistent_job")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v2/design — List Jobs
# ---------------------------------------------------------------------------


class TestListDesignJobs:
    """Tests for design job listing."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/v2/design")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_with_jobs(self, client: AsyncClient):
        await _create_design_job(client)
        await _create_design_job(client)
        resp = await client.get("/api/v2/design")
        data = resp.json()
        assert len(data) == 2


# ---------------------------------------------------------------------------
# POST /api/v2/design/{job_id}/cancel — Cancel
# ---------------------------------------------------------------------------


class TestCancelDesignJob:
    """Tests for design job cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, client: AsyncClient):
        created = await _create_design_job(client)
        resp = await client.post(f"/api/v2/design/{created['job_id']}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, client: AsyncClient):
        resp = await client.post("/api/v2/design/nonexistent/cancel")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_already_completed_returns_false(self, client: AsyncClient):
        """Cancelling a job that's already in a terminal state returns success=False."""
        created = await _create_design_job(client)
        job_id = created["job_id"]
        # Manually set job to "completed" via DB to simulate terminal state
        import app.database as db_module
        from app.repositories.design_job import DesignJobRepository
        async with db_module.get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(job_id, "completed")
        # Cancel should return success=False
        resp = await client.post(f"/api/v2/design/{job_id}/cancel")
        data = resp.json()
        assert data["success"] is False
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /api/v2/design/{job_id}/files — Generated Files
# ---------------------------------------------------------------------------


class TestGetDesignFiles:
    """Tests for generated files endpoint."""

    @pytest.mark.asyncio
    async def test_files_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/design/nonexistent/files")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_files_running_job_empty(self, client: AsyncClient):
        """Running job returns empty files list."""
        created = await _create_design_job(client)
        resp = await client.get(f"/api/v2/design/{created['job_id']}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []


# ---------------------------------------------------------------------------
# GET /api/v2/design/{job_id}/screenshots/{filename} — Screenshots
# ---------------------------------------------------------------------------


class TestScreenshots:
    """Tests for screenshot serving endpoint."""

    @pytest.mark.asyncio
    async def test_screenshot_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/design/nonexistent/screenshots/test.png")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_screenshot_path_traversal_rejected(self, client: AsyncClient):
        created = await _create_design_job(client)
        resp = await client.get(
            f"/api/v2/design/{created['job_id']}/screenshots/../../../etc/passwd"
        )
        assert resp.status_code in (400, 404)

    @pytest.mark.asyncio
    async def test_screenshot_invalid_extension(self, client: AsyncClient):
        created = await _create_design_job(client)
        resp = await client.get(
            f"/api/v2/design/{created['job_id']}/screenshots/file.txt"
        )
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/v2/design/{job_id}/stream — SSE (basic 404 check)
# ---------------------------------------------------------------------------


class TestDesignSSE:
    """Basic SSE endpoint validation."""

    @pytest.mark.asyncio
    async def test_stream_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/design/nonexistent/stream")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# URL Parsing (via endpoint validation)
# ---------------------------------------------------------------------------


class TestFigmaUrlParsing:
    """Tests for Figma URL parsing via endpoint error responses."""

    @pytest.mark.asyncio
    async def test_file_url_format_accepted(self, client: AsyncClient):
        """The older /file/ format should also be accepted."""
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/run-spec", json={
                "figma_url": "https://www.figma.com/file/abc123/Design?node-id=123-456",
                "output_dir": "/tmp/test",
            })
        # Should not fail on URL parsing (201 = created, or 503 if Temporal mock fails)
        assert resp.status_code in (201, 503)

    @pytest.mark.asyncio
    async def test_percent_encoded_node_id(self, client: AsyncClient):
        """node-id with %3A encoding should be accepted."""
        with patch("workflow.config.FIGMA_TOKEN", "fake-token"):
            resp = await client.post("/api/v2/design/run-spec", json={
                "figma_url": "https://www.figma.com/design/abc123/File?node-id=123%3A456",
                "output_dir": "/tmp/test",
            })
        assert resp.status_code in (201, 503)
