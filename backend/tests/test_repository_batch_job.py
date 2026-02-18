"""Tests for BatchJobRepository (app/repositories/batch_job.py).

Covers CRUD operations, filtering, pagination, metrics, and edge cases.
Uses in-memory SQLite via conftest fixtures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import BatchJobModel, BugResultModel
from app.repositories.batch_job import BatchJobRepository

# Ensure temporalio mock is available
from tests.workflow.conftest import *  # noqa: F401, F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

JIRA_URLS = [
    "https://myco.atlassian.net/browse/BUG-1",
    "https://myco.atlassian.net/browse/BUG-2",
    "https://myco.atlassian.net/browse/BUG-3",
]


async def _create_job(
    session: AsyncSession,
    job_id: str = "test_job_001",
    urls: list | None = None,
    config: dict | None = None,
    workspace_id: str | None = None,
) -> BatchJobModel:
    """Helper: create a job via repository."""
    repo = BatchJobRepository(session)
    return await repo.create(
        job_id=job_id,
        target_group_id="test-group",
        jira_urls=urls or JIRA_URLS[:2],
        config=config or {"validation_level": "standard"},
        workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:

    @pytest.mark.asyncio
    async def test_create_job_with_bugs(self, test_session: AsyncSession):
        job = await _create_job(test_session)
        assert job.id == "test_job_001"
        assert job.status == "started"
        assert len(job.bugs) == 2
        assert job.bugs[0].url == JIRA_URLS[0]
        assert job.bugs[0].status == "pending"
        assert job.bugs[0].bug_index == 0
        assert job.bugs[1].bug_index == 1

    @pytest.mark.asyncio
    async def test_create_stores_config(self, test_session: AsyncSession):
        job = await _create_job(
            test_session,
            config={"validation_level": "thorough", "max_retries": 5},
        )
        assert job.config["validation_level"] == "thorough"
        assert job.config["max_retries"] == 5

    @pytest.mark.asyncio
    async def test_create_with_workspace(self, test_session: AsyncSession):
        # Note: we can't FK to a real workspace without creating one first,
        # but SQLite won't enforce FK by default. Test the field stores.
        job = await _create_job(test_session, workspace_id="ws-123")
        assert job.workspace_id == "ws-123"

    @pytest.mark.asyncio
    async def test_create_three_bugs(self, test_session: AsyncSession):
        job = await _create_job(test_session, urls=JIRA_URLS)
        assert len(job.bugs) == 3


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


class TestGet:

    @pytest.mark.asyncio
    async def test_get_existing(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        job = await repo.get("test_job_001")
        assert job is not None
        assert job.id == "test_job_001"
        assert len(job.bugs) == 2

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, test_session: AsyncSession):
        repo = BatchJobRepository(test_session)
        job = await repo.get("does_not_exist")
        assert job is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:

    @pytest.mark.asyncio
    async def test_list_empty(self, test_session: AsyncSession):
        repo = BatchJobRepository(test_session)
        jobs, total = await repo.list()
        assert jobs == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_returns_jobs(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        await _create_job(test_session, job_id="j2")
        repo = BatchJobRepository(test_session)
        jobs, total = await repo.list()
        assert total == 2
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, test_session: AsyncSession):
        for i in range(5):
            await _create_job(test_session, job_id=f"j{i}")
        repo = BatchJobRepository(test_session)

        jobs, total = await repo.list(page=1, page_size=2)
        assert len(jobs) == 2
        assert total == 5

        jobs, total = await repo.list(page=3, page_size=2)
        assert len(jobs) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        repo = BatchJobRepository(test_session)
        await repo.update_status("j1", "completed")

        jobs, total = await repo.list(status="completed")
        assert total == 1
        assert jobs[0].status == "completed"

        jobs, total = await repo.list(status="started")
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_filter_by_workspace(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1", workspace_id="ws-a")
        await _create_job(test_session, job_id="j2", workspace_id="ws-b")

        repo = BatchJobRepository(test_session)
        jobs, total = await repo.list(workspace_id="ws-a")
        assert total == 1
        assert jobs[0].id == "j1"

    @pytest.mark.asyncio
    async def test_list_comma_separated_status(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        repo = BatchJobRepository(test_session)
        await repo.update_status("j1", "completed")
        await _create_job(test_session, job_id="j2")

        jobs, total = await repo.list(status="started,completed")
        assert total == 2


# ---------------------------------------------------------------------------
# Update Status
# ---------------------------------------------------------------------------


class TestUpdateStatus:

    @pytest.mark.asyncio
    async def test_update_job_status(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        job = await repo.update_status("test_job_001", "running")
        assert job.status == "running"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, test_session: AsyncSession):
        repo = BatchJobRepository(test_session)
        result = await repo.update_status("nope", "failed")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_with_error(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        job = await repo.update_status("test_job_001", "failed", error="boom")
        assert job.status == "failed"
        assert job.error == "boom"


# ---------------------------------------------------------------------------
# Update Bug Status
# ---------------------------------------------------------------------------


class TestUpdateBugStatus:

    @pytest.mark.asyncio
    async def test_update_bug_status(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        now = datetime.now(timezone.utc)
        bug = await repo.update_bug_status(
            "test_job_001", 0, "in_progress", started_at=now,
        )
        assert bug.status == "in_progress"
        assert bug.started_at == now

    @pytest.mark.asyncio
    async def test_update_bug_nonexistent(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        result = await repo.update_bug_status("test_job_001", 99, "failed")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_bug_with_error(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        bug = await repo.update_bug_status(
            "test_job_001", 0, "failed", error="Claude timeout",
        )
        assert bug.error == "Claude timeout"


# ---------------------------------------------------------------------------
# Get Bug
# ---------------------------------------------------------------------------


class TestGetBug:

    @pytest.mark.asyncio
    async def test_get_bug(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        bug = await repo.get_bug("test_job_001", 0)
        assert bug is not None
        assert bug.url == JIRA_URLS[0]

    @pytest.mark.asyncio
    async def test_get_bug_nonexistent(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        bug = await repo.get_bug("test_job_001", 99)
        assert bug is None


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:

    @pytest.mark.asyncio
    async def test_delete_job(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        result = await repo.delete("test_job_001")
        assert result is True

        # Verify gone
        job = await repo.get("test_job_001")
        assert job is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, test_session: AsyncSession):
        repo = BatchJobRepository(test_session)
        result = await repo.delete("nope")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_cascades_bugs(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        await repo.delete("test_job_001")

        # Bug should also be gone
        bug = await repo.get_bug("test_job_001", 0)
        assert bug is None


# ---------------------------------------------------------------------------
# Update Bug Steps
# ---------------------------------------------------------------------------


class TestUpdateBugSteps:

    @pytest.mark.asyncio
    async def test_update_steps(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)

        steps = [
            {"step": "fetch", "label": "获取 Bug 信息", "status": "completed"},
            {"step": "fix", "label": "修复 Bug", "status": "in_progress"},
        ]
        bug = await repo.update_bug_steps("test_job_001", 0, steps)
        assert bug is not None
        assert len(bug.steps) == 2
        assert bug.steps[0]["label"] == "获取 Bug 信息"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:

    @pytest.mark.asyncio
    async def test_job_metrics_empty_bugs(self, test_session: AsyncSession):
        """Job with no bugs should return zero metrics."""
        # Create a job with empty urls (edge case)
        repo = BatchJobRepository(test_session)
        job = BatchJobModel(
            id="empty_job", status="completed", target_group_id="g"
        )
        test_session.add(job)
        await test_session.flush()

        metrics = await repo.get_job_metrics("empty_job")
        assert metrics is not None
        assert metrics["summary"]["total"] == 0

    @pytest.mark.asyncio
    async def test_job_metrics_with_completed_bugs(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        now = datetime.now(timezone.utc)

        # Complete bug 0
        await repo.update_bug_status(
            "test_job_001", 0, "completed",
            started_at=now - timedelta(seconds=10),
            completed_at=now,
        )
        # Fail bug 1
        await repo.update_bug_status(
            "test_job_001", 1, "failed", error="timeout",
        )

        metrics = await repo.get_job_metrics("test_job_001")
        assert metrics["summary"]["completed"] == 1
        assert metrics["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_global_metrics_empty(self, test_session: AsyncSession):
        repo = BatchJobRepository(test_session)
        metrics = await repo.get_global_metrics()
        assert metrics["jobs"]["total"] == 0

    @pytest.mark.asyncio
    async def test_get_stats(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = BatchJobRepository(test_session)
        stats = await repo.get_stats("test_job_001")
        assert stats["total"] == 2
        assert stats["pending"] == 2
        assert stats["completed"] == 0
