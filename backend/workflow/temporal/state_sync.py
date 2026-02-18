"""Database synchronization helpers for batch bug fix activities.

Handles all DB reads/writes for job status, bug status, step persistence,
and incremental/final result synchronization.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..settings import BATCH_DB_SYNC_MAX_ATTEMPTS

logger = logging.getLogger("workflow.temporal.state_sync")


def _db_index(
    bug_index: int,
    bug_index_offset: int,
    index_map: Optional[List[int]] = None,
) -> int:
    """Map workflow-internal bug index to DB/SSE bug index.

    When index_map is provided (skip mode), uses the mapping.
    Otherwise falls back to simple offset (retry mode).
    """
    if index_map is not None:
        return index_map[bug_index] if bug_index < len(index_map) else bug_index
    return bug_index + bug_index_offset


async def _update_job_status(
    job_id: str,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """Update job status in database. Returns True on success."""
    from .sse_events import _push_event

    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, status, error=error)
        logger.info(f"Job {job_id}: DB status -> {status}")
        return True
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to update status in DB: {e}")
        await _push_event(job_id, "db_sync_warning", {
            "message": f"数据库状态更新失败: {status}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return False


async def _reset_stale_bugs(job_id: str, total_bugs: int) -> None:
    """Reset stale in_progress bugs back to pending on retry attempts.

    When a heartbeat timeout kills an attempt, bugs may be left in
    'in_progress' state. This resets them so the retry starts clean.
    """
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            db_job = await repo.get(job_id)
            if db_job:
                for bug in db_job.bugs:
                    if bug.status == "in_progress":
                        await repo.update_bug_status(
                            job_id=job_id,
                            bug_index=bug.bug_index,
                            status="pending",
                        )
                        logger.info(
                            f"Job {job_id}: Reset bug {bug.bug_index} "
                            f"from in_progress to pending"
                        )
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to reset stale bugs: {e}")


async def _update_bug_status_db(
    job_id: str,
    bug_index: int,
    status: str,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> bool:
    """Update a single bug's status in database. Returns True on success."""
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_bug_status(
                job_id=job_id,
                bug_index=bug_index,
                status=status,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )
        return True
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to update bug {bug_index} status: {e}"
        )
        return False


async def _persist_bug_steps(
    job_id: str,
    bug_index: int,
    steps: List[Dict[str, Any]],
) -> bool:
    """Persist step records for a completed bug to the database. Returns True on success."""
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_bug_steps(
                job_id=job_id,
                bug_index=bug_index,
                steps=steps,
            )
        logger.info(
            f"Job {job_id}: Persisted {len(steps)} steps for bug {bug_index}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to persist steps for bug {bug_index}: {e}"
        )
        return False


async def _sync_incremental_results(
    job_id: str,
    jira_urls: List[str],
    results: List[Dict[str, Any]],
    start_index: int,
    bug_index_offset: int = 0,
    index_map: Optional[List[int]] = None,
) -> None:
    """Sync new results to database and push SSE events.

    Only processes results from start_index onwards (incremental).
    Uses index_map (from pre-scan skip) or bug_index_offset (from retry)
    to map workflow indices to DB/SSE bug_index.
    """
    from .sse_events import _push_event

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    for i in range(start_index, len(results)):
        if i >= len(jira_urls):
            break

        db_i = _db_index(i, bug_index_offset, index_map)
        result = results[i]
        result_status = result.get("status", "failed")
        error_msg = None

        if result_status == "completed":
            await _push_event(job_id, "bug_completed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "timestamp": now_iso,
            })
        elif result_status == "failed":
            error_msg = result.get(
                "error", result.get("response", "Unknown error")
            )
            await _push_event(job_id, "bug_failed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "error": error_msg,
                "timestamp": now_iso,
            })
        elif result_status == "skipped":
            error_msg = result.get("error", "Skipped")
            await _push_event(job_id, "bug_failed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "error": error_msg,
                "skipped": True,
                "timestamp": now_iso,
            })

        # Update bug in DB
        db_ok = await _update_bug_status_db(
            job_id, db_i, result_status,
            error=error_msg,
            completed_at=now,
        )
        if not db_ok:
            await _push_event(job_id, "db_sync_warning", {
                "bug_index": db_i,
                "message": f"Bug {db_i} 状态同步失败，刷新页面后状态可能不准确",
                "timestamp": now_iso,
            })

    # Mark next pending bug as in_progress
    next_index = len(results)
    if next_index < len(jira_urls):
        db_next = _db_index(next_index, bug_index_offset, index_map)
        await _update_bug_status_db(
            job_id, db_next, "in_progress",
            started_at=now,
        )
        await _push_event(job_id, "bug_started", {
            "bug_index": db_next,
            "url": jira_urls[next_index],
            "timestamp": now_iso,
        })


async def _sync_final_results(
    job_id: str,
    final_state: Dict[str, Any],
    jira_urls: List[str],
    bug_index_offset: int = 0,
    index_map: Optional[List[int]] = None,
    pre_skipped: int = 0,
) -> None:
    """Final sync — update all statuses and push job_done event.

    For retry runs (bug_index_offset > 0) or skip runs (index_map is set),
    the overall job status is recomputed from ALL bugs in the DB.
    pre_skipped tracks bugs skipped during pre-scan (already resolved).
    """
    from .sse_events import _push_event

    results = final_state.get("results", [])
    now = datetime.now(timezone.utc)

    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    overall = "completed" if failed == 0 and skipped == 0 else "failed"
    db_sync_ok = False

    for attempt in range(BATCH_DB_SYNC_MAX_ATTEMPTS):
        try:
            from app.database import get_session_ctx
            from app.repositories.batch_job import BatchJobRepository

            async with get_session_ctx() as session:
                repo = BatchJobRepository(session)
                # Fetch existing bugs to preserve incremental completed_at timestamps
                db_job = await repo.get(job_id)
                existing_bugs = {b.bug_index: b for b in db_job.bugs} if db_job else {}

                for i, result in enumerate(results):
                    db_i = _db_index(i, bug_index_offset, index_map)
                    existing = existing_bugs.get(db_i)
                    # Only set completed_at if not already set by incremental sync
                    bug_completed_at = None if (existing and existing.completed_at) else now
                    await repo.update_bug_status(
                        job_id=job_id,
                        bug_index=db_i,
                        status=result.get("status", "failed"),
                        error=result.get("error"),
                        completed_at=bug_completed_at,
                    )

                # Recompute overall status from ALL bugs in DB when
                # some bugs were skipped or this is a retry run
                if bug_index_offset > 0 or index_map is not None:
                    db_job = await repo.get(job_id)
                    if db_job:
                        if index_map is not None:
                            # Skip mode: pre-scan skipped bugs are not failures
                            all_failed = sum(
                                1 for b in db_job.bugs
                                if b.status == "failed"
                            )
                        else:
                            # Retry mode: skipped = failure (original behavior)
                            all_failed = sum(
                                1 for b in db_job.bugs
                                if b.status in ("failed", "skipped")
                            )
                        overall = "completed" if all_failed == 0 else "failed"

                await repo.update_status(job_id, overall)
            logger.info(
                f"Job {job_id}: Final sync — {overall} "
                f"(completed={completed}, failed={failed}, skipped={skipped})"
            )
            db_sync_ok = True
            break
        except Exception as e:
            logger.error(f"Job {job_id}: Final DB sync failed (attempt {attempt + 1}/{BATCH_DB_SYNC_MAX_ATTEMPTS}): {e}")
            if attempt < BATCH_DB_SYNC_MAX_ATTEMPTS - 1:
                # Exponential backoff: 1s, 2s, 4s + jitter
                delay = (2 ** attempt) * (1.0 + random.uniform(-0.25, 0.25))
                await asyncio.sleep(delay)

    total_skipped = skipped + pre_skipped
    total_bugs = len(jira_urls) + pre_skipped

    event_data: Dict[str, Any] = {
        "status": overall,
        "completed": completed,
        "failed": failed,
        "skipped": total_skipped,
        "total": total_bugs,
        "timestamp": now.isoformat(),
    }
    if not db_sync_ok:
        event_data["db_sync_failed"] = True
        event_data["db_sync_message"] = "数据库同步失败，刷新页面后状态可能不准确"

    await _push_event(job_id, "job_done", event_data)
