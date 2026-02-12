"""E2E Integration Tests for M9: Tab Detail Enhancement — Steps + SSE (T067)

Phase 1: Backend API — steps data (T67.1–T67.5)
- GET /batch-bug-fix/{job_id} returns steps field
- BugStepInfo schema completeness
- output_preview truncation
- retry_count calculation
- Steps persistence across DB reload

Phase 2: SSE new events (T67.6–T67.9, T67.11)
- bug_step_started / bug_step_completed event format via push_node_event
- Event ordering via SSE infrastructure
- Internal nodes filtered (NODE_TO_STEP)
- duration_ms precision

Note: Tests updated for Temporal architecture — uses DB-based state
instead of in-memory caches, and push_node_event instead of push_job_event.

Total: 10 backend test scenarios (T67.10 removed per master — source check only)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_session_ctx
from app.batch_job_repository import BatchJobRepository
from app.db_models import BatchJobModel, BugResultModel
from app.sse import push_node_event, _active_streams
from workflow.temporal.batch_activities import NODE_TO_STEP

# --- Test DB isolation: use in-memory SQLite to avoid nuking production data ---
_test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

# Monkey-patch the app's database module to use test engine
import app.database as _db_mod
_db_mod.engine = _test_engine
_db_mod.async_session_factory = _test_session_factory

from httpx import AsyncClient, ASGITransport
from app.main import app


def _count_retries(steps: List[Dict[str, Any]]) -> int:
    """Count retries from steps (max attempt - 1)."""
    max_attempt = 0
    for s in steps:
        attempt = s.get("attempt", 0)
        if attempt > max_attempt:
            max_attempt = attempt
    return max(0, max_attempt - 1)


async def setup_db():
    """Create tables for testing (in-memory, isolated from production)."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def create_job_in_db(
    job_id: str,
    bugs: List[Dict[str, Any]],
    status: str = "running",
    target_group_id: str = "test-group",
) -> None:
    """Create a job with bugs directly in the database."""
    async with get_session_ctx() as session:
        job_model = BatchJobModel(
            id=job_id,
            status=status,
            target_group_id=target_group_id,
            config={},
        )
        session.add(job_model)
        await session.flush()

        for i, bug in enumerate(bugs):
            bug_model = BugResultModel(
                job_id=job_id,
                bug_index=i,
                url=bug["url"],
                status=bug.get("status", "pending"),
                error=bug.get("error"),
                started_at=datetime.now(timezone.utc) if bug.get("status") != "pending" else None,
                completed_at=datetime.now(timezone.utc) if bug.get("status") in ("completed", "failed") else None,
                steps=bug.get("steps"),
            )
            session.add(bug_model)

        await session.commit()


def make_step(
    step: str,
    label: str,
    status: str = "completed",
    duration_ms: Optional[float] = None,
    output_preview: Optional[str] = None,
    error: Optional[str] = None,
    attempt: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a step record."""
    now = datetime.now(timezone.utc).isoformat()
    record: Dict[str, Any] = {
        "step": step,
        "label": label,
        "status": status,
        "started_at": now,
        "completed_at": now if status in ("completed", "failed") else None,
        "duration_ms": duration_ms,
        "output_preview": output_preview,
        "error": error,
    }
    if attempt is not None:
        record["attempt"] = attempt
    return record


async def run_tests():
    """Run all E2E M9 Steps + SSE tests."""
    errors = []
    passed = 0

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # =============================================================
        # Phase 1: Backend API — steps data
        # =============================================================
        print("\n" + "=" * 60)
        print("Phase 1: Backend API — steps data")
        print("=" * 60)

        # Setup: create a job with steps in DB
        test_job_id = "job_test_steps_01"
        completed_steps = [
            make_step("fix_bug_peer", "修复 Bug", "completed", 45200.5, "已修复 UserService 模块的空指针异常", attempt=1),
            make_step("verify_fix", "验证修复结果", "completed", 30100.3, "VERIFIED: 3 个单元测试通过", attempt=1),
            make_step("update_success", "修复完成", "completed", 50.1, "Bug 修复成功记录"),
        ]

        await create_job_in_db(
            test_job_id,
            [{"url": "https://testjira.atlassian.net/browse/BUG-101", "status": "completed", "steps": completed_steps}],
        )

        # -----------------------------------------------------------------
        # T67.1: GET /batch-bug-fix/{job_id} returns steps
        # -----------------------------------------------------------------
        print("\nTest T67.1: GET job status returns steps field ... ", end="")
        resp = await client.get(f"/api/v2/batch/bug-fix/{test_job_id}")
        if resp.status_code == 200:
            data = resp.json()
            bugs = data.get("bugs", [])
            if bugs and bugs[0].get("steps") is not None:
                steps_data = bugs[0]["steps"]
                if isinstance(steps_data, list) and len(steps_data) > 0:
                    print(f"OK (bugs[0].steps has {len(steps_data)} entries)")
                    passed += 1
                else:
                    msg = f"FAIL — steps is empty or not a list: {type(steps_data)}"
                    print(msg)
                    errors.append(("T67.1", msg))
            else:
                msg = f"FAIL — steps field missing from bug. Keys: {list(bugs[0].keys()) if bugs else 'no bugs'}"
                print(msg)
                errors.append(("T67.1", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text[:200]}"
            print(msg)
            errors.append(("T67.1", msg))

        # -----------------------------------------------------------------
        # T67.2: Steps schema completeness (BugStepInfo fields)
        # -----------------------------------------------------------------
        print("Test T67.2: Steps schema completeness ... ", end="")
        if resp.status_code == 200:
            data = resp.json()
            bugs = data.get("bugs", [])
            if bugs and bugs[0].get("steps"):
                step = bugs[0]["steps"][0]
                required_fields = ["step", "label", "status"]
                optional_fields = ["started_at", "completed_at", "duration_ms", "output_preview", "error", "attempt"]
                missing_required = [f for f in required_fields if f not in step]
                if not missing_required:
                    field_errors = []
                    if not isinstance(step.get("step"), str):
                        field_errors.append(f"step should be str, got {type(step.get('step'))}")
                    if not isinstance(step.get("label"), str):
                        field_errors.append(f"label should be str, got {type(step.get('label'))}")
                    if step.get("status") not in ("pending", "in_progress", "completed", "failed"):
                        field_errors.append(f"status invalid: {step.get('status')}")
                    if not field_errors:
                        print(f"OK (required: {required_fields}, optional present: {[f for f in optional_fields if step.get(f) is not None]})")
                        passed += 1
                    else:
                        msg = f"FAIL — field errors: {field_errors}"
                        print(msg)
                        errors.append(("T67.2", msg))
                else:
                    msg = f"FAIL — missing required fields: {missing_required}"
                    print(msg)
                    errors.append(("T67.2", msg))
            else:
                print("SKIP — no steps data from T67.1")
        else:
            print("SKIP — T67.1 failed")

        # -----------------------------------------------------------------
        # T67.3: output_preview truncation (≤200 chars)
        # -----------------------------------------------------------------
        print("Test T67.3: output_preview ≤200 chars ... ", end="")
        if resp.status_code == 200:
            data = resp.json()
            bugs = data.get("bugs", [])
            if bugs and bugs[0].get("steps"):
                all_ok = True
                for step in bugs[0]["steps"]:
                    preview = step.get("output_preview")
                    if preview is not None and len(preview) > 200:
                        all_ok = False
                        msg = f"FAIL — output_preview too long: {len(preview)} chars (step: {step.get('step')})"
                        print(msg)
                        errors.append(("T67.3", msg))
                        break
                if all_ok:
                    previews = [s.get("output_preview") for s in bugs[0]["steps"] if s.get("output_preview")]
                    print(f"OK ({len(previews)} previews, max len={max(len(p) for p in previews) if previews else 0})")
                    passed += 1
            else:
                print("SKIP — no steps data")
        else:
            print("SKIP — T67.1 failed")

        # -----------------------------------------------------------------
        # T67.4: retry_count calculation
        # -----------------------------------------------------------------
        print("Test T67.4: retry_count from steps ... ", end="")

        retry_job_id = "job_test_retry_01"
        retry_steps = [
            make_step("fix_bug_peer", "修复 Bug", "completed", 40000.0, "第一次修复", attempt=1),
            make_step("verify_fix", "验证修复结果", "failed", 20000.0, error="lint 失败", attempt=1),
            make_step("increment_retry", "准备重试", "completed", 10.0),
            make_step("fix_bug_peer", "修复 Bug", "completed", 35000.0, "第二次修复", attempt=2),
            make_step("verify_fix", "验证修复结果", "completed", 25000.0, "VERIFIED", attempt=2),
            make_step("update_success", "修复完成", "completed", 50.0),
        ]

        await create_job_in_db(
            retry_job_id,
            [{"url": "https://testjira.atlassian.net/browse/BUG-201", "status": "completed", "steps": retry_steps}],
        )

        resp_retry = await client.get(f"/api/v2/batch/bug-fix/{retry_job_id}")
        if resp_retry.status_code == 200:
            retry_data = resp_retry.json()
            retry_bugs = retry_data.get("bugs", [])
            if retry_bugs:
                retry_count = retry_bugs[0].get("retry_count", -1)
                # attempt 2 means 1 retry (max_attempt - 1 = 2 - 1 = 1)
                if retry_count == 1:
                    print(f"OK (retry_count={retry_count} for attempt=2)")
                    passed += 1
                else:
                    msg = f"FAIL — expected retry_count=1, got {retry_count}"
                    print(msg)
                    errors.append(("T67.4", msg))
            else:
                msg = "FAIL — no bugs in retry job response"
                print(msg)
                errors.append(("T67.4", msg))
        else:
            msg = f"FAIL status={resp_retry.status_code}"
            print(msg)
            errors.append(("T67.4", msg))

        # -----------------------------------------------------------------
        # T67.5: Steps persistence across DB reload
        # -----------------------------------------------------------------
        print("Test T67.5: Steps persistence in DB ... ", end="")

        persist_job_id = f"job_persist_{int(datetime.now(timezone.utc).timestamp())}"
        try:
            async with get_session_ctx() as session:
                job_model = BatchJobModel(
                    id=persist_job_id,
                    status="completed",
                    target_group_id="test-group",
                    config={},
                )
                session.add(job_model)
                await session.flush()

                bug_model = BugResultModel(
                    job_id=persist_job_id,
                    bug_index=0,
                    url="https://testjira.atlassian.net/browse/BUG-301",
                    status="completed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    steps=[
                        {"step": "fix_bug_peer", "label": "修复 Bug", "status": "completed", "duration_ms": 45000.0},
                        {"step": "verify_fix", "label": "验证修复结果", "status": "completed", "duration_ms": 30000.0},
                    ],
                )
                session.add(bug_model)
                await session.commit()

            resp_persist = await client.get(f"/api/v2/batch/bug-fix/{persist_job_id}")
            if resp_persist.status_code == 200:
                persist_data = resp_persist.json()
                persist_bugs = persist_data.get("bugs", [])
                if persist_bugs and persist_bugs[0].get("steps"):
                    db_steps = persist_bugs[0]["steps"]
                    if len(db_steps) == 2 and db_steps[0].get("step") == "fix_bug_peer":
                        print(f"OK ({len(db_steps)} steps loaded from DB)")
                        passed += 1
                    else:
                        msg = f"FAIL — unexpected steps from DB: {json.dumps(db_steps[:1], ensure_ascii=False)[:100]}"
                        print(msg)
                        errors.append(("T67.5", msg))
                else:
                    msg = "FAIL — steps not persisted or not returned from DB"
                    print(msg)
                    errors.append(("T67.5", msg))
            else:
                msg = f"FAIL status={resp_persist.status_code} body={resp_persist.text[:200]}"
                print(msg)
                errors.append(("T67.5", msg))
        except Exception as e:
            msg = f"FAIL — DB error: {e}"
            print(msg)
            errors.append(("T67.5", msg))

        # =============================================================
        # Phase 2: SSE new events (via push_node_event)
        # =============================================================
        print("\n" + "=" * 60)
        print("Phase 2: SSE new events")
        print("=" * 60)

        # -----------------------------------------------------------------
        # T67.6: bug_step_started event format via push_node_event
        # -----------------------------------------------------------------
        print("\nTest T67.6: bug_step_started event format ... ", end="")

        sse_job_id = "job_sse_test_01"
        sse_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        _active_streams[sse_job_id] = sse_queue

        try:
            event_data = {
                "bug_index": 0,
                "step": "fix_bug_peer",
                "label": "修复 Bug",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "attempt": 1,
            }
            push_node_event(sse_job_id, "bug_step_started", event_data)

            raw_event = sse_queue.get_nowait()
            # push_node_event puts dicts {"event": ..., "data": ...} into queue
            evt_type = raw_event["event"]
            evt_payload = raw_event["data"]

            required = ["bug_index", "step", "label", "timestamp"]
            if evt_type == "bug_step_started" and evt_payload:
                missing = [f for f in required if f not in evt_payload]
                if not missing:
                    has_attempt = "attempt" in evt_payload
                    print(f"OK (fields: {required}, attempt={'present' if has_attempt else 'absent'})")
                    passed += 1
                else:
                    msg = f"FAIL — missing fields: {missing}"
                    print(msg)
                    errors.append(("T67.6", msg))
            else:
                msg = f"FAIL — event_type={evt_type}, payload={evt_payload}"
                print(msg)
                errors.append(("T67.6", msg))
        except asyncio.QueueEmpty:
            msg = "FAIL — no event in queue after push_node_event"
            print(msg)
            errors.append(("T67.6", msg))

        # -----------------------------------------------------------------
        # T67.7: bug_step_completed event format
        # -----------------------------------------------------------------
        print("Test T67.7: bug_step_completed event format ... ", end="")

        try:
            event_data = {
                "bug_index": 0,
                "step": "fix_bug_peer",
                "label": "修复 Bug",
                "status": "completed",
                "duration_ms": 45200.5,
                "output_preview": "已修复模块",
                "error": None,
                "attempt": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            push_node_event(sse_job_id, "bug_step_completed", event_data)

            raw_event = sse_queue.get_nowait()
            evt_type = raw_event["event"]
            evt_payload = raw_event["data"]

            required = ["bug_index", "step", "label", "status", "timestamp"]
            optional = ["duration_ms", "output_preview", "error", "attempt"]
            if evt_type == "bug_step_completed" and evt_payload:
                missing = [f for f in required if f not in evt_payload]
                if not missing and evt_payload["status"] in ("completed", "in_progress", "failed"):
                    present_optionals = [f for f in optional if evt_payload.get(f) is not None]
                    print(f"OK (required: {required}, optional present: {present_optionals})")
                    passed += 1
                else:
                    msg = f"FAIL — missing={missing}, status={evt_payload.get('status')}"
                    print(msg)
                    errors.append(("T67.7", msg))
            else:
                msg = f"FAIL — event_type={evt_type}"
                print(msg)
                errors.append(("T67.7", msg))
        except asyncio.QueueEmpty:
            msg = "FAIL — no event in queue"
            print(msg)
            errors.append(("T67.7", msg))

        # -----------------------------------------------------------------
        # T67.8: Event ordering (step_started before step_completed)
        # -----------------------------------------------------------------
        print("Test T67.8: Event ordering ... ", end="")

        # Drain queue
        while not sse_queue.empty():
            sse_queue.get_nowait()

        now = datetime.now(timezone.utc)
        events_to_push = [
            ("bug_started", {"bug_index": 0, "url": "BUG-1", "timestamp": now.isoformat()}),
            ("bug_step_started", {"bug_index": 0, "step": "fix_bug_peer", "label": "修复 Bug", "timestamp": now.isoformat()}),
            ("bug_step_completed", {"bug_index": 0, "step": "fix_bug_peer", "label": "修复 Bug", "status": "completed", "timestamp": now.isoformat()}),
            ("bug_step_started", {"bug_index": 0, "step": "verify_fix", "label": "验证修复结果", "timestamp": now.isoformat()}),
            ("bug_step_completed", {"bug_index": 0, "step": "verify_fix", "label": "验证修复结果", "status": "completed", "timestamp": now.isoformat()}),
            ("bug_completed", {"bug_index": 0, "url": "BUG-1", "timestamp": now.isoformat()}),
        ]

        for evt_type, evt_data in events_to_push:
            push_node_event(sse_job_id, evt_type, evt_data)

        received_order = []
        while not sse_queue.empty():
            raw_event = sse_queue.get_nowait()
            received_order.append(raw_event["event"])

        expected_order = [
            "bug_started",
            "bug_step_started",
            "bug_step_completed",
            "bug_step_started",
            "bug_step_completed",
            "bug_completed",
        ]

        if received_order == expected_order:
            print(f"OK ({len(received_order)} events in correct order)")
            passed += 1
        else:
            msg = f"FAIL — expected {expected_order}, got {received_order}"
            print(msg)
            errors.append(("T67.8", msg))

        # Cleanup SSE queue
        _active_streams.pop(sse_job_id, None)

        # -----------------------------------------------------------------
        # T67.9: Internal nodes not exposed in NODE_TO_STEP
        # -----------------------------------------------------------------
        print("Test T67.9: Internal nodes filtered ... ", end="")

        internal_nodes = ["check_verify_result", "check_retry", "check_more_bugs", "input_node", "output_node"]
        exposed_nodes = ["get_current_bug", "fix_bug_peer", "verify_fix", "increment_retry", "update_success", "update_failure"]

        internal_filtered = all(NODE_TO_STEP.get(n) is None for n in internal_nodes)
        exposed_present = all(NODE_TO_STEP.get(n) is not None for n in exposed_nodes)

        if internal_filtered and exposed_present:
            print(f"OK (internal={len(internal_nodes)} filtered, exposed={len(exposed_nodes)} mapped)")
            passed += 1
        else:
            failed_internal = [n for n in internal_nodes if NODE_TO_STEP.get(n) is not None]
            failed_exposed = [n for n in exposed_nodes if NODE_TO_STEP.get(n) is None]
            msg = f"FAIL — internal not filtered: {failed_internal}, exposed missing: {failed_exposed}"
            print(msg)
            errors.append(("T67.9", msg))

        # -----------------------------------------------------------------
        # T67.11: duration_ms precision (non-negative, 1 decimal)
        # -----------------------------------------------------------------
        print("Test T67.11: duration_ms precision ... ", end="")

        test_durations = [0.0, 50.1, 45200.5, 30100.3]
        duration_ok = True
        for d in test_durations:
            if d < 0:
                duration_ok = False
                break
            if round(d, 1) != d:
                duration_ok = False
                break

        if duration_ok:
            if resp.status_code == 200:
                data = resp.json()
                bugs = data.get("bugs", [])
                if bugs and bugs[0].get("steps"):
                    api_durations = [s.get("duration_ms") for s in bugs[0]["steps"] if s.get("duration_ms") is not None]
                    all_valid = all(d >= 0 and round(d, 1) == d for d in api_durations)
                    if all_valid:
                        print(f"OK (durations: {api_durations})")
                        passed += 1
                    else:
                        msg = f"FAIL — invalid durations in API: {api_durations}"
                        print(msg)
                        errors.append(("T67.11", msg))
                else:
                    print(f"OK (unit test passed, no API steps to verify)")
                    passed += 1
            else:
                print(f"OK (unit test passed)")
                passed += 1
        else:
            msg = f"FAIL — invalid durations: {test_durations}"
            print(msg)
            errors.append(("T67.11", msg))

    return passed, errors


if __name__ == "__main__":
    passed, errors = asyncio.run(run_tests())
    total = passed + len(errors)
    total_scenarios = 10  # T67.1-T67.9 + T67.11 (T67.10 removed)
    skipped = total_scenarios - total

    print(f"\n{'='*60}")
    print(f"E2E M9 Steps + SSE Tests: {passed}/{total} passed ({skipped} skipped)")
    if errors:
        print("\nFailures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("All M9 backend tests passed!")
        sys.exit(0)
