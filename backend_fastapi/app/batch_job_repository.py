"""Repository layer for batch bug fix job persistence.

Provides async CRUD operations for BatchJobModel and BugResultModel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db_models import BatchJobModel, BugResultModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BatchJobRepository:
    """Data access layer for batch bug fix jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        job_id: str,
        target_group_id: str,
        jira_urls: List[str],
        fixer_peer_id: Optional[str] = None,
        verifier_peer_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> BatchJobModel:
        """Create a new batch job with bug records.

        Args:
            job_id: Unique job identifier (e.g., job_xxx)
            target_group_id: (Legacy, nullable) Target group ID
            jira_urls: List of Jira bug URLs
            fixer_peer_id: (Legacy, nullable) Peer ID for bug fixing
            verifier_peer_id: (Legacy, nullable) Peer ID for verification
            config: Job configuration dict

        Returns:
            Created BatchJobModel with bugs relationship loaded
        """
        job = BatchJobModel(
            id=job_id,
            status="started",
            target_group_id=target_group_id,
            fixer_peer_id=fixer_peer_id,
            verifier_peer_id=verifier_peer_id,
            config=config,
        )
        self.session.add(job)

        # Create bug result records
        for idx, url in enumerate(jira_urls):
            bug = BugResultModel(
                job_id=job_id,
                bug_index=idx,
                url=url,
                status="pending",
            )
            self.session.add(bug)

        await self.session.flush()

        # Reload with bugs relationship
        return await self.get(job_id)

    async def get(self, job_id: str) -> Optional[BatchJobModel]:
        """Get a batch job by ID with bugs loaded."""
        result = await self.session.execute(
            select(BatchJobModel)
            .options(selectinload(BatchJobModel.bugs))
            .where(BatchJobModel.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        status: Optional[str] = None,
        target_group_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[BatchJobModel], int]:
        """List batch jobs with optional filtering and pagination.

        Args:
            status: Filter by job status
            target_group_id: Filter by target group
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (jobs, total_count)
        """
        query = select(BatchJobModel).options(selectinload(BatchJobModel.bugs))
        count_query = select(func.count()).select_from(BatchJobModel)

        if status:
            # Support comma-separated status values (e.g., "started,running")
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if len(statuses) == 1:
                query = query.where(BatchJobModel.status == statuses[0])
                count_query = count_query.where(BatchJobModel.status == statuses[0])
            else:
                query = query.where(BatchJobModel.status.in_(statuses))
                count_query = count_query.where(BatchJobModel.status.in_(statuses))

        if target_group_id:
            query = query.where(BatchJobModel.target_group_id == target_group_id)
            count_query = count_query.where(BatchJobModel.target_group_id == target_group_id)

        query = query.order_by(BatchJobModel.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(query)
        jobs = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return jobs, total

    async def update_status(
        self,
        job_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[BatchJobModel]:
        """Update job status."""
        job = await self.get(job_id)
        if not job:
            return None

        job.status = status
        if error:
            job.error = error
        job.updated_at = _utcnow()

        await self.session.flush()
        return job

    async def update_bug_status(
        self,
        job_id: str,
        bug_index: int,
        status: str,
        error: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[BugResultModel]:
        """Update a specific bug's status.

        Args:
            job_id: Job identifier
            bug_index: Index of the bug in the job
            status: New status
            error: Error message if failed
            started_at: When processing started
            completed_at: When processing completed

        Returns:
            Updated BugResultModel or None if not found
        """
        result = await self.session.execute(
            select(BugResultModel).where(
                BugResultModel.job_id == job_id,
                BugResultModel.bug_index == bug_index,
            )
        )
        bug = result.scalar_one_or_none()
        if not bug:
            return None

        bug.status = status
        if error is not None:
            bug.error = error
        if started_at is not None:
            bug.started_at = started_at
        if completed_at is not None:
            bug.completed_at = completed_at

        # Also update job's updated_at
        await self.session.execute(
            update(BatchJobModel)
            .where(BatchJobModel.id == job_id)
            .values(updated_at=_utcnow())
        )

        await self.session.flush()
        return bug

    async def get_bug(
        self,
        job_id: str,
        bug_index: int,
    ) -> Optional[BugResultModel]:
        """Get a specific bug by job_id and index."""
        result = await self.session.execute(
            select(BugResultModel).where(
                BugResultModel.job_id == job_id,
                BugResultModel.bug_index == bug_index,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, job_id: str) -> bool:
        """Delete a batch job and all its bugs."""
        job = await self.get(job_id)
        if not job:
            return False
        await self.session.delete(job)
        await self.session.flush()
        return True

    async def update_bug_steps(
        self,
        job_id: str,
        bug_index: int,
        steps: List[Dict[str, Any]],
    ) -> Optional[BugResultModel]:
        """Update the execution steps for a specific bug.

        Args:
            job_id: Job identifier
            bug_index: Index of the bug in the job
            steps: List of step dicts [{step, label, status, started_at, ...}]

        Returns:
            Updated BugResultModel or None if not found
        """
        result = await self.session.execute(
            select(BugResultModel).where(
                BugResultModel.job_id == job_id,
                BugResultModel.bug_index == bug_index,
            )
        )
        bug = result.scalar_one_or_none()
        if not bug:
            return None

        bug.steps = steps

        await self.session.execute(
            update(BatchJobModel)
            .where(BatchJobModel.id == job_id)
            .values(updated_at=_utcnow())
        )

        await self.session.flush()
        return bug

    async def get_stats(self, job_id: str) -> Dict[str, int]:
        """Get bug status counts for a job.

        Returns:
            Dict with counts: completed, failed, skipped, in_progress, pending, total
        """
        result = await self.session.execute(
            select(
                BugResultModel.status,
                func.count(BugResultModel.id).label("count"),
            )
            .where(BugResultModel.job_id == job_id)
            .group_by(BugResultModel.status)
        )
        rows = result.all()

        stats = {
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "in_progress": 0,
            "pending": 0,
            "total": 0,
        }
        for status, count in rows:
            if status in stats:
                stats[status] = count
            stats["total"] += count

        return stats


# --- Convenience functions for non-FastAPI contexts ---


async def get_batch_job_repository() -> BatchJobRepository:
    """Create a repository instance with a new session.

    Usage:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            job = await repo.get(job_id)
    """
    from .database import get_session_ctx

    async with get_session_ctx() as session:
        return BatchJobRepository(session)
