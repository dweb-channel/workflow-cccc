"""Tests for DesignJobRepository (app/repositories/design_job.py).

Covers CRUD operations, filtering, pagination, and component count updates.
Uses in-memory SQLite via conftest fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.design_job import DesignJobRepository

# Ensure temporalio mock is available
from tests.workflow.conftest import *  # noqa: F401, F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_job(
    session: AsyncSession,
    job_id: str = "spec_test001",
    design_file: str = "/tmp/out/design_spec.json",
    output_dir: str = "/tmp/out",
    cwd: str = "/tmp",
    max_retries: int = 2,
) -> "DesignJobModel":  # noqa: F821
    """Helper: create a design job via repository."""
    repo = DesignJobRepository(session)
    return await repo.create(
        job_id=job_id,
        design_file=design_file,
        output_dir=output_dir,
        cwd=cwd,
        max_retries=max_retries,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:

    @pytest.mark.asyncio
    async def test_create_job(self, test_session: AsyncSession):
        job = await _create_job(test_session)
        assert job.id == "spec_test001"
        assert job.status == "started"
        assert job.design_file == "/tmp/out/design_spec.json"
        assert job.output_dir == "/tmp/out"
        assert job.cwd == "/tmp"
        assert job.max_retries == 2

    @pytest.mark.asyncio
    async def test_create_sets_defaults(self, test_session: AsyncSession):
        job = await _create_job(test_session)
        assert job.components_total == 0
        assert job.components_completed == 0
        assert job.components_failed == 0
        assert job.error is None
        assert job.result is None


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


class TestGet:

    @pytest.mark.asyncio
    async def test_get_existing(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        job = await repo.get("spec_test001")
        assert job is not None
        assert job.id == "spec_test001"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        job = await repo.get("does_not_exist")
        assert job is None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:

    @pytest.mark.asyncio
    async def test_list_empty(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        jobs, total = await repo.list()
        assert jobs == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_returns_jobs(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        await _create_job(test_session, job_id="j2")
        repo = DesignJobRepository(test_session)
        jobs, total = await repo.list()
        assert total == 2
        assert len(jobs) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, test_session: AsyncSession):
        for i in range(5):
            await _create_job(test_session, job_id=f"j{i}")
        repo = DesignJobRepository(test_session)

        jobs, total = await repo.list(page=1, page_size=2)
        assert len(jobs) == 2
        assert total == 5

        jobs, total = await repo.list(page=3, page_size=2)
        assert len(jobs) == 1

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        repo = DesignJobRepository(test_session)
        await repo.update_status("j1", "completed")

        jobs, total = await repo.list(status="completed")
        assert total == 1
        assert jobs[0].status == "completed"

        jobs, total = await repo.list(status="started")
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_comma_separated_status(self, test_session: AsyncSession):
        await _create_job(test_session, job_id="j1")
        repo = DesignJobRepository(test_session)
        await repo.update_status("j1", "completed")
        await _create_job(test_session, job_id="j2")

        jobs, total = await repo.list(status="started,completed")
        assert total == 2


# ---------------------------------------------------------------------------
# Update Status
# ---------------------------------------------------------------------------


class TestUpdateStatus:

    @pytest.mark.asyncio
    async def test_update_status(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        job = await repo.update_status("spec_test001", "running")
        assert job.status == "running"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        result = await repo.update_status("nope", "failed")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_with_error(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        now = datetime.now(timezone.utc)
        job = await repo.update_status(
            "spec_test001", "failed", error="Pipeline crashed", completed_at=now,
        )
        assert job.status == "failed"
        assert job.error == "Pipeline crashed"
        assert job.completed_at == now


# ---------------------------------------------------------------------------
# Update (generic)
# ---------------------------------------------------------------------------


class TestUpdate:

    @pytest.mark.asyncio
    async def test_update_arbitrary_fields(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        job = await repo.update("spec_test001", status="completed", result={"components": 3})
        assert job.status == "completed"
        assert job.result == {"components": 3}

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        result = await repo.update("nope", status="failed")
        assert result is None


# ---------------------------------------------------------------------------
# Update Component Counts
# ---------------------------------------------------------------------------


class TestUpdateComponentCounts:

    @pytest.mark.asyncio
    async def test_update_counts(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        job = await repo.update_component_counts(
            "spec_test001", total=10, completed=7, failed=2,
        )
        assert job.components_total == 10
        assert job.components_completed == 7
        assert job.components_failed == 2

    @pytest.mark.asyncio
    async def test_update_partial_counts(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        job = await repo.update_component_counts("spec_test001", total=5)
        assert job.components_total == 5
        assert job.components_completed == 0  # unchanged

    @pytest.mark.asyncio
    async def test_update_counts_nonexistent(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        result = await repo.update_component_counts("nope", total=5)
        assert result is None


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDelete:

    @pytest.mark.asyncio
    async def test_delete_job(self, test_session: AsyncSession):
        await _create_job(test_session)
        repo = DesignJobRepository(test_session)
        result = await repo.delete("spec_test001")
        assert result is True
        job = await repo.get("spec_test001")
        assert job is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, test_session: AsyncSession):
        repo = DesignJobRepository(test_session)
        result = await repo.delete("nope")
        assert result is False
