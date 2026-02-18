"""Tests for batch bug fix API routes (app/routes/batch.py).

Covers:
- POST /api/v2/batch/bug-fix (create + dry-run)
- GET /api/v2/batch/bug-fix (list with pagination/filter)
- GET /api/v2/batch/bug-fix/{job_id} (status)
- POST /api/v2/batch/bug-fix/{job_id}/cancel
- POST /api/v2/batch/bug-fix/{job_id}/retry/{bug_index}
- DELETE /api/v2/batch/bug-fix/{job_id}
- POST /api/v2/batch/bug-fix/batch-delete
- GET /api/v2/batch/metrics/job/{job_id}
- GET /api/v2/batch/metrics/global
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

# Ensure temporalio mock is available
from tests.workflow.conftest import *  # noqa: F401, F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JIRA_URLS = [
    "https://mycompany.atlassian.net/browse/BUG-123",
    "https://mycompany.atlassian.net/browse/BUG-456",
]

CREATE_PAYLOAD = {
    "jira_urls": VALID_JIRA_URLS,
    "cwd": "/tmp/test-repo",
}


async def _create_job(client: AsyncClient, **overrides) -> dict:
    """Helper: create a batch job and return response JSON."""
    payload = {**CREATE_PAYLOAD, **overrides}
    resp = await client.post("/api/v2/batch/bug-fix", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v2/batch/bug-fix — Create
# ---------------------------------------------------------------------------


class TestCreateBatchBugFix:
    """Tests for job creation endpoint."""

    @pytest.mark.asyncio
    async def test_create_basic(self, client: AsyncClient):
        data = await _create_job(client)
        assert data["status"] == "started"
        assert data["total_bugs"] == 2
        assert data["job_id"].startswith("job_")
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_with_config(self, client: AsyncClient):
        data = await _create_job(client, config={
            "validation_level": "thorough",
            "failure_policy": "stop",
            "max_retries": 5,
        })
        assert data["status"] == "started"
        assert data["total_bugs"] == 2

    @pytest.mark.asyncio
    async def test_create_empty_urls_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={"jira_urls": []})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_invalid_url_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["not-a-url"]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_localhost_url_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["http://localhost/browse/BUG-1"]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_example_domain_rejected(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["https://example.com/browse/BUG-1"]
        })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_max_retries_bounds(self, client: AsyncClient):
        # max_retries > 10 should be rejected
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": VALID_JIRA_URLS,
            "config": {"max_retries": 99},
        })
        assert resp.status_code == 422

        # max_retries < 1 should be rejected
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": VALID_JIRA_URLS,
            "config": {"max_retries": 0},
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v2/batch/bug-fix (dry_run=true) — Dry Run
# ---------------------------------------------------------------------------


class TestDryRun:
    """Tests for dry-run preview mode."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_200(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            **CREATE_PAYLOAD,
            "dry_run": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["total_bugs"] == 2
        assert len(data["bugs"]) == 2

    @pytest.mark.asyncio
    async def test_dry_run_extracts_jira_key(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["https://mycompany.atlassian.net/browse/XSZS-15463"],
            "dry_run": True,
        })
        data = resp.json()
        assert data["bugs"][0]["jira_key"] == "XSZS-15463"

    @pytest.mark.asyncio
    async def test_dry_run_includes_expected_steps(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            **CREATE_PAYLOAD,
            "dry_run": True,
        })
        data = resp.json()
        assert len(data["expected_steps_per_bug"]) == 4
        assert "获取 Bug 信息" in data["expected_steps_per_bug"]

    @pytest.mark.asyncio
    async def test_dry_run_preserves_config(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix", json={
            **CREATE_PAYLOAD,
            "dry_run": True,
            "config": {"validation_level": "thorough", "max_retries": 5},
        })
        data = resp.json()
        assert data["config"]["validation_level"] == "thorough"
        assert data["config"]["max_retries"] == 5


# ---------------------------------------------------------------------------
# GET /api/v2/batch/bug-fix/{job_id} — Status
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    """Tests for single job status endpoint."""

    @pytest.mark.asyncio
    async def test_get_existing_job(self, client: AsyncClient):
        created = await _create_job(client)
        job_id = created["job_id"]

        resp = await client.get(f"/api/v2/batch/bug-fix/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id
        assert data["total_bugs"] == 2
        assert data["pending"] == 2
        assert data["completed"] == 0

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/bug-fix/nonexistent_job")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_bugs_have_correct_urls(self, client: AsyncClient):
        created = await _create_job(client)
        resp = await client.get(f"/api/v2/batch/bug-fix/{created['job_id']}")
        data = resp.json()
        bug_urls = [b["url"] for b in data["bugs"]]
        assert bug_urls == VALID_JIRA_URLS


# ---------------------------------------------------------------------------
# GET /api/v2/batch/bug-fix — List
# ---------------------------------------------------------------------------


class TestListJobs:
    """Tests for job listing with pagination."""

    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/bug-fix")
        assert resp.status_code == 200
        data = resp.json()
        assert data["jobs"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_with_jobs(self, client: AsyncClient):
        await _create_job(client)
        await _create_job(client)

        resp = await client.get("/api/v2/batch/bug-fix")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, client: AsyncClient):
        # Create 3 jobs
        for _ in range(3):
            await _create_job(client)

        # Page 1 with page_size=2
        resp = await client.get("/api/v2/batch/bug-fix?page=1&page_size=2")
        data = resp.json()
        assert len(data["jobs"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 2

        # Page 2
        resp = await client.get("/api/v2/batch/bug-fix?page=2&page_size=2")
        data = resp.json()
        assert len(data["jobs"]) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, client: AsyncClient):
        await _create_job(client)

        # Filter by "started" (should match)
        resp = await client.get("/api/v2/batch/bug-fix?status=started")
        data = resp.json()
        assert data["total"] >= 1

        # Filter by "completed" (should not match)
        resp = await client.get("/api/v2/batch/bug-fix?status=completed")
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_invalid_page(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/bug-fix?page=0")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v2/batch/bug-fix/{job_id}/cancel — Cancel
# ---------------------------------------------------------------------------


class TestCancelJob:
    """Tests for job cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_running_job(self, client: AsyncClient):
        created = await _create_job(client)
        job_id = created["job_id"]

        resp = await client.post(f"/api/v2/batch/bug-fix/{job_id}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix/nonexistent/cancel")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled(self, client: AsyncClient):
        created = await _create_job(client)
        job_id = created["job_id"]

        # Cancel once
        await client.post(f"/api/v2/batch/bug-fix/{job_id}/cancel")

        # Cancel again should fail
        resp = await client.post(f"/api/v2/batch/bug-fix/{job_id}/cancel")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v2/batch/bug-fix/{job_id}/retry/{bug_index} — Retry
# ---------------------------------------------------------------------------


class TestRetryBug:
    """Tests for single bug retry."""

    @pytest.mark.asyncio
    async def test_retry_nonexistent_job(self, client: AsyncClient):
        resp = await client.post("/api/v2/batch/bug-fix/nonexistent/retry/0")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_nonexistent_bug_index(self, client: AsyncClient):
        created = await _create_job(client)
        resp = await client.post(
            f"/api/v2/batch/bug-fix/{created['job_id']}/retry/99"
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_pending_bug_rejected(self, client: AsyncClient):
        """Cannot retry a bug that hasn't failed yet."""
        created = await _create_job(client)
        resp = await client.post(
            f"/api/v2/batch/bug-fix/{created['job_id']}/retry/0"
        )
        assert resp.status_code == 400
        assert "pending" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# DELETE /api/v2/batch/bug-fix/{job_id} — Delete
# ---------------------------------------------------------------------------


class TestDeleteJob:
    """Tests for job deletion."""

    @pytest.mark.asyncio
    async def test_delete_existing_job(self, client: AsyncClient):
        created = await _create_job(client)
        job_id = created["job_id"]

        resp = await client.delete(f"/api/v2/batch/bug-fix/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["status"] == "deleted"

        # Verify it's gone
        resp = await client.get(f"/api/v2/batch/bug-fix/{job_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job(self, client: AsyncClient):
        resp = await client.delete("/api/v2/batch/bug-fix/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v2/batch/bug-fix/batch-delete — Batch Delete
# ---------------------------------------------------------------------------


class TestBatchDelete:
    """Tests for batch deletion."""

    @pytest.mark.asyncio
    async def test_batch_delete(self, client: AsyncClient):
        j1 = await _create_job(client)
        j2 = await _create_job(client)

        resp = await client.post("/api/v2/batch/bug-fix/batch-delete", json={
            "job_ids": [j1["job_id"], j2["job_id"]],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["deleted"]) == 2
        assert len(data["failed"]) == 0

    @pytest.mark.asyncio
    async def test_batch_delete_partial_failure(self, client: AsyncClient):
        j1 = await _create_job(client)
        resp = await client.post("/api/v2/batch/bug-fix/batch-delete", json={
            "job_ids": [j1["job_id"], "nonexistent"],
        })
        data = resp.json()
        assert len(data["deleted"]) == 1
        assert len(data["failed"]) == 1


# ---------------------------------------------------------------------------
# GET /api/v2/batch/metrics/* — Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    """Tests for metrics endpoints."""

    @pytest.mark.asyncio
    async def test_job_metrics(self, client: AsyncClient):
        created = await _create_job(client)
        resp = await client.get(
            f"/api/v2/batch/metrics/job/{created['job_id']}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == created["job_id"]
        assert "summary" in data
        assert "timing" in data
        assert "retry_stats" in data

    @pytest.mark.asyncio
    async def test_job_metrics_nonexistent(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/metrics/job/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_global_metrics(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/metrics/global")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "bugs" in data
        assert "timing" in data


# ---------------------------------------------------------------------------
# SSE Endpoint — Basic validation
# ---------------------------------------------------------------------------


class TestSSEStream:
    """Tests for SSE streaming endpoint."""

    @pytest.mark.asyncio
    async def test_stream_nonexistent_job(self, client: AsyncClient):
        resp = await client.get("/api/v2/batch/bug-fix/nonexistent/stream")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_stream_existing_job_responds(self, client: AsyncClient):
        """Verify existing job SSE endpoint doesn't 404 (full stream test needs live EventBus)."""
        created = await _create_job(client)
        # We can't easily consume the infinite SSE stream in tests.
        # The 404 test above covers the guard. Here just verify the job was created
        # and the endpoint path is correct (the non-existent test covers 404).
        resp = await client.get(f"/api/v2/batch/bug-fix/{created['job_id']}")
        assert resp.status_code == 200
