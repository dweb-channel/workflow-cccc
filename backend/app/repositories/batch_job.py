"""Repository layer for batch bug fix job persistence.

Provides async CRUD operations for BatchJobModel and BugResultModel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.db import BatchJobModel, BugResultModel


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

    async def get_job_metrics(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed metrics for a single job.

        Computes per-bug timing, success rates, retry stats, and
        step-level performance from existing BugResultModel fields.

        Returns:
            Dict with bug_metrics, step_metrics, retry_stats, summary
            or None if job not found.
        """
        job = await self.get(job_id)
        if not job:
            return None

        bugs = sorted(job.bugs, key=lambda b: b.bug_index)
        total = len(bugs)
        if total == 0:
            return {
                "job_id": job_id,
                "status": job.status,
                "summary": {"total": 0, "completed": 0, "failed": 0, "skipped": 0, "success_rate": 0.0},
                "timing": {"avg_ms": 0, "min_ms": 0, "max_ms": 0, "total_ms": 0},
                "retry_stats": {"total_retries": 0, "bugs_with_retries": 0, "max_retries_single_bug": 0},
                "step_metrics": [],
            }

        # --- Bug-level timing ---
        durations_ms: List[float] = []
        completed_count = 0
        failed_count = 0
        skipped_count = 0
        total_retries = 0
        bugs_with_retries = 0
        max_retries_single = 0

        # Accumulate step-level data: step_label -> {count, total_ms, failures}
        step_data: Dict[str, Dict[str, Any]] = {}

        for bug in bugs:
            if bug.status == "completed":
                completed_count += 1
            elif bug.status == "failed":
                failed_count += 1
            elif bug.status == "skipped":
                skipped_count += 1

            # Bug duration
            if bug.started_at and bug.completed_at:
                delta = (bug.completed_at - bug.started_at).total_seconds() * 1000
                durations_ms.append(delta)

            # Step-level metrics + retry counting
            if bug.steps:
                bug_max_attempt = 0
                for step in bug.steps:
                    label = step.get("label", step.get("step", "unknown"))
                    dur = step.get("duration_ms")
                    status = step.get("status", "")
                    attempt = step.get("attempt")

                    if attempt is not None and attempt > bug_max_attempt:
                        bug_max_attempt = attempt

                    if label not in step_data:
                        step_data[label] = {"count": 0, "total_ms": 0.0, "failures": 0}
                    step_data[label]["count"] += 1
                    if dur is not None:
                        step_data[label]["total_ms"] += dur
                    if status == "failed":
                        step_data[label]["failures"] += 1

                retries = max(0, bug_max_attempt - 1)
                total_retries += retries
                if retries > 0:
                    bugs_with_retries += 1
                if retries > max_retries_single:
                    max_retries_single = retries

        # Compute summary timing
        avg_ms = sum(durations_ms) / len(durations_ms) if durations_ms else 0
        min_ms = min(durations_ms) if durations_ms else 0
        max_ms = max(durations_ms) if durations_ms else 0
        total_ms = sum(durations_ms)

        finished = completed_count + failed_count + skipped_count
        success_rate = (completed_count / finished * 100) if finished > 0 else 0.0

        # Build step_metrics list sorted by occurrence order
        step_metrics = []
        for label, data in step_data.items():
            avg_step = data["total_ms"] / data["count"] if data["count"] > 0 else 0
            fail_rate = data["failures"] / data["count"] * 100 if data["count"] > 0 else 0
            step_metrics.append({
                "label": label,
                "count": data["count"],
                "avg_duration_ms": round(avg_step, 1),
                "total_duration_ms": round(data["total_ms"], 1),
                "failures": data["failures"],
                "failure_rate": round(fail_rate, 1),
            })

        return {
            "job_id": job_id,
            "status": job.status,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "summary": {
                "total": total,
                "completed": completed_count,
                "failed": failed_count,
                "skipped": skipped_count,
                "success_rate": round(success_rate, 1),
            },
            "timing": {
                "avg_ms": round(avg_ms, 1),
                "min_ms": round(min_ms, 1),
                "max_ms": round(max_ms, 1),
                "total_ms": round(total_ms, 1),
            },
            "retry_stats": {
                "total_retries": total_retries,
                "bugs_with_retries": bugs_with_retries,
                "max_retries_single_bug": max_retries_single,
            },
            "step_metrics": step_metrics,
        }

    async def get_global_metrics(self) -> Dict[str, Any]:
        """Get aggregated metrics across all completed/failed jobs.

        Returns:
            Dict with totals, success rates, average timing, and
            most-failed steps ranking.
        """
        # Get all jobs with terminal status
        result = await self.session.execute(
            select(BatchJobModel)
            .options(selectinload(BatchJobModel.bugs))
            .where(BatchJobModel.status.in_(["completed", "failed", "cancelled"]))
            .order_by(BatchJobModel.created_at.desc())
        )
        jobs = list(result.scalars().all())

        total_jobs = len(jobs)
        total_bugs = 0
        completed_bugs = 0
        failed_bugs = 0
        skipped_bugs = 0
        job_durations_ms: List[float] = []
        bug_durations_ms: List[float] = []
        step_failures: Dict[str, int] = {}
        step_counts: Dict[str, int] = {}
        total_retries = 0

        for job in jobs:
            # Job-level duration
            if job.created_at and job.updated_at:
                delta = (job.updated_at - job.created_at).total_seconds() * 1000
                job_durations_ms.append(delta)

            for bug in job.bugs:
                total_bugs += 1
                if bug.status == "completed":
                    completed_bugs += 1
                elif bug.status == "failed":
                    failed_bugs += 1
                elif bug.status == "skipped":
                    skipped_bugs += 1

                # Bug duration
                if bug.started_at and bug.completed_at:
                    delta = (bug.completed_at - bug.started_at).total_seconds() * 1000
                    bug_durations_ms.append(delta)

                # Step-level failure tracking
                if bug.steps:
                    bug_max_attempt = 0
                    for step in bug.steps:
                        label = step.get("label", step.get("step", "unknown"))
                        status = step.get("status", "")
                        attempt = step.get("attempt")
                        if attempt is not None and attempt > bug_max_attempt:
                            bug_max_attempt = attempt
                        step_counts[label] = step_counts.get(label, 0) + 1
                        if status == "failed":
                            step_failures[label] = step_failures.get(label, 0) + 1
                    total_retries += max(0, bug_max_attempt - 1)

        finished_bugs = completed_bugs + failed_bugs + skipped_bugs
        bug_success_rate = (completed_bugs / finished_bugs * 100) if finished_bugs > 0 else 0.0

        jobs_succeeded = sum(1 for j in jobs if j.status == "completed")
        job_success_rate = (jobs_succeeded / total_jobs * 100) if total_jobs > 0 else 0.0

        # Most-failed steps ranking
        most_failed_steps = sorted(
            [
                {
                    "label": label,
                    "failures": step_failures.get(label, 0),
                    "total": count,
                    "failure_rate": round(step_failures.get(label, 0) / count * 100, 1) if count > 0 else 0,
                }
                for label, count in step_counts.items()
            ],
            key=lambda x: x["failures"],
            reverse=True,
        )[:5]

        return {
            "jobs": {
                "total": total_jobs,
                "completed": jobs_succeeded,
                "failed": total_jobs - jobs_succeeded,
                "success_rate": round(job_success_rate, 1),
            },
            "bugs": {
                "total": total_bugs,
                "completed": completed_bugs,
                "failed": failed_bugs,
                "skipped": skipped_bugs,
                "success_rate": round(bug_success_rate, 1),
            },
            "timing": {
                "avg_job_ms": round(sum(job_durations_ms) / len(job_durations_ms), 1) if job_durations_ms else 0,
                "avg_bug_ms": round(sum(bug_durations_ms) / len(bug_durations_ms), 1) if bug_durations_ms else 0,
                "min_bug_ms": round(min(bug_durations_ms), 1) if bug_durations_ms else 0,
                "max_bug_ms": round(max(bug_durations_ms), 1) if bug_durations_ms else 0,
            },
            "retries": {
                "total": total_retries,
            },
            "most_failed_steps": most_failed_steps,
        }

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
