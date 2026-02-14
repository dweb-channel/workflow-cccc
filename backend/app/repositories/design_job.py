"""Repository layer for design-to-code job persistence.

Provides async CRUD operations for DesignJobModel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import DesignJobModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DesignJobRepository:
    """Data access layer for design-to-code jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        job_id: str,
        design_file: str,
        output_dir: str,
        cwd: str,
        max_retries: int = 2,
    ) -> DesignJobModel:
        """Create a new design-to-code job.

        Args:
            job_id: Unique job identifier (e.g., design_xxx)
            design_file: Absolute path to design_export.json
            output_dir: Target directory for generated code
            cwd: Working directory for Claude CLI
            max_retries: Max retries per component

        Returns:
            Created DesignJobModel
        """
        job = DesignJobModel(
            id=job_id,
            status="started",
            design_file=design_file,
            output_dir=output_dir,
            cwd=cwd,
            max_retries=max_retries,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> Optional[DesignJobModel]:
        """Get a design job by ID."""
        result = await self.session.execute(
            select(DesignJobModel).where(DesignJobModel.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[DesignJobModel], int]:
        """List design jobs with optional filtering and pagination.

        Args:
            status: Filter by job status
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (jobs, total_count)
        """
        query = select(DesignJobModel)
        count_query = select(func.count()).select_from(DesignJobModel)

        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                query = query.where(DesignJobModel.status == statuses[0])
                count_query = count_query.where(DesignJobModel.status == statuses[0])
            else:
                query = query.where(DesignJobModel.status.in_(statuses))
                count_query = count_query.where(DesignJobModel.status.in_(statuses))

        query = query.order_by(DesignJobModel.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(query)
        jobs = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return jobs, total

    async def update(
        self,
        job_id: str,
        **kwargs: Any,
    ) -> Optional[DesignJobModel]:
        """Update a design job with arbitrary fields.

        Args:
            job_id: Job identifier
            **kwargs: Fields to update (status, error, components_total, etc.)

        Returns:
            Updated DesignJobModel or None if not found
        """
        job = await self.get(job_id)
        if not job:
            return None

        for key, value in kwargs.items():
            if hasattr(job, key):
                setattr(job, key, value)

        await self.session.flush()
        return job

    async def update_status(
        self,
        job_id: str,
        status: str,
        error: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[DesignJobModel]:
        """Update job status with optional error and completion timestamp.

        Args:
            job_id: Job identifier
            status: New status
            error: Error message if failed
            completed_at: Completion timestamp

        Returns:
            Updated DesignJobModel or None if not found
        """
        job = await self.get(job_id)
        if not job:
            return None

        job.status = status
        if error is not None:
            job.error = error
        if completed_at is not None:
            job.completed_at = completed_at

        await self.session.flush()
        return job

    async def update_component_counts(
        self,
        job_id: str,
        total: Optional[int] = None,
        completed: Optional[int] = None,
        failed: Optional[int] = None,
    ) -> Optional[DesignJobModel]:
        """Update component progress counters.

        Args:
            job_id: Job identifier
            total: Total components count
            completed: Completed components count
            failed: Failed components count

        Returns:
            Updated DesignJobModel or None if not found
        """
        job = await self.get(job_id)
        if not job:
            return None

        if total is not None:
            job.components_total = total
        if completed is not None:
            job.components_completed = completed
        if failed is not None:
            job.components_failed = failed

        await self.session.flush()
        return job

    async def delete(self, job_id: str) -> bool:
        """Delete a design job."""
        job = await self.get(job_id)
        if not job:
            return False
        await self.session.delete(job)
        await self.session.flush()
        return True
