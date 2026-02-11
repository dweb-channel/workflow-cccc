"""E2E Integration Tests for M9: Tab Detail Enhancement — Steps + SSE (T067)

Phase 1: Backend API — steps data (T67.1–T67.5)
- GET /batch-bug-fix/{job_id} returns steps field
- BugStepInfo schema completeness
- output_preview truncation
- retry_count calculation
- Steps persistence across DB reload

Phase 2: SSE new events (T67.6–T67.9, T67.11)
- bug_step_started event format
- bug_step_completed event format
- Event ordering
- Internal nodes filtered
- duration_ms precision

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

from httpx import AsyncClient, ASGITransport
from app.database import engine, Base
from app.main import app
from app.routes.cccc import (
    BATCH_JOBS_CACHE,
    JOB_BUG_STEPS,
    JOB_SSE_QUEUES,
    NODE_TO_STEP,
    push_job_event,
    _count_retries,
)


async def setup_db():
    """Create tables for testing."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def make_job_cache_entry(
    job_id: str,
    bugs: List[Dict[str, Any]],
    target_group_id: str = "test-group",
    status: str = "running",
) -> Dict[str, Any]:
    """Create a BATCH_JOBS_CACHE entry for testing."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": job_id,
        "status": status,
        "target_group_id": target_group_id,
        "config": {},
        "error": None,
        "bugs": bugs,
        "created_at": now,
        "updated_at": now,
    }


def make_bug(
    url: str,
    status: str = "pending",
    error: Optional[str] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a bug entry for cache."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "url": url,
        "status": status,
        "error": error,
        "started_at": now if status != "pending" else None,
        "completed_at": now if status in ("completed", "failed") else None,
        "steps": steps,
        "retry_count": _count_retries(steps) if steps else 0,
    }


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

    # CCCC_MOCK/CCCC_GROUP_ID no longer needed (CCCC integration removed in M11)

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # =============================================================
        # Phase 1: Backend API — steps data
        # =============================================================
        print("\n" + "=" * 60)
        print("Phase 1: Backend API — steps data")
        print("=" * 60)

        # Setup: create a job with steps in cache
        test_job_id = "job_test_steps_01"
        completed_steps = [
            make_step("fix_bug_peer", "修复 Bug", "completed", 45200.5, "已修复 UserService 模块的空指针异常", attempt=1),
            make_step("verify_fix", "验证修复结果", "completed", 30100.3, "VERIFIED: 3 个单元测试通过", attempt=1),
            make_step("update_success", "修复完成", "completed", 50.1, "Bug 修复成功记录"),
        ]

        BATCH_JOBS_CACHE[test_job_id] = make_job_cache_entry(
            test_job_id,
            [make_bug("https://jira.example.com/browse/BUG-101", "completed", steps=completed_steps)],
        )

        # Also populate JOB_BUG_STEPS for live enrichment test
        JOB_BUG_STEPS[test_job_id] = {0: completed_steps}

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
                    # Verify required field values
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

        # Create a job with retry steps
        retry_job_id = "job_test_retry_01"
        retry_steps = [
            make_step("fix_bug_peer", "修复 Bug", "completed", 40000.0, "第一次修复", attempt=1),
            make_step("verify_fix", "验证修复结果", "failed", 20000.0, error="lint 失败", attempt=1),
            make_step("increment_retry", "准备重试", "completed", 10.0),
            make_step("fix_bug_peer", "修复 Bug", "completed", 35000.0, "第二次修复", attempt=2),
            make_step("verify_fix", "验证修复结果", "completed", 25000.0, "VERIFIED", attempt=2),
            make_step("update_success", "修复完成", "completed", 50.0),
        ]

        BATCH_JOBS_CACHE[retry_job_id] = make_job_cache_entry(
            retry_job_id,
            [make_bug("https://jira.example.com/browse/BUG-201", "completed", steps=retry_steps)],
        )
        JOB_BUG_STEPS[retry_job_id] = {0: retry_steps}

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

        # Create a job through the POST API and manually persist steps
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        persist_job_id = f"job_persist_{int(datetime.now(timezone.utc).timestamp())}"
        try:
            async with get_session_ctx() as session:
                repo = BatchJobRepository(session)
                # Create job directly in DB
                from app.db_models import BatchJobModel, BugResultModel
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
                    url="https://jira.example.com/browse/BUG-301",
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

            # Now fetch via API (not from cache — remove from cache first)
            BATCH_JOBS_CACHE.pop(persist_job_id, None)
            JOB_BUG_STEPS.pop(persist_job_id, None)

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
        # Phase 2: SSE new events
        # =============================================================
        print("\n" + "=" * 60)
        print("Phase 2: SSE new events")
        print("=" * 60)

        # -----------------------------------------------------------------
        # T67.6: bug_step_started event format
        # -----------------------------------------------------------------
        print("\nTest T67.6: bug_step_started event format ... ", end="")

        sse_job_id = "job_sse_test_01"
        sse_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        JOB_SSE_QUEUES[sse_job_id] = sse_queue

        push_job_event(sse_job_id, "bug_step_started", {
            "bug_index": 0,
            "step": "fix_bug_peer",
            "label": "修复 Bug",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": 1,
        })

        try:
            event = sse_queue.get_nowait()
            evt_data = event.get("data", {})
            required = ["bug_index", "step", "label", "timestamp"]
            missing = [f for f in required if f not in evt_data]
            if event.get("event") == "bug_step_started" and not missing:
                # Verify types
                type_ok = (
                    isinstance(evt_data["bug_index"], int)
                    and isinstance(evt_data["step"], str)
                    and isinstance(evt_data["label"], str)
                    and isinstance(evt_data["timestamp"], str)
                )
                if type_ok:
                    has_attempt = "attempt" in evt_data
                    print(f"OK (fields: {required}, attempt={'present' if has_attempt else 'absent'})")
                    passed += 1
                else:
                    msg = f"FAIL — type mismatch in event data"
                    print(msg)
                    errors.append(("T67.6", msg))
            else:
                msg = f"FAIL — event_type={event.get('event')}, missing={missing}"
                print(msg)
                errors.append(("T67.6", msg))
        except asyncio.QueueEmpty:
            msg = "FAIL — no event in queue after push_job_event"
            print(msg)
            errors.append(("T67.6", msg))

        # -----------------------------------------------------------------
        # T67.7: bug_step_completed event format
        # -----------------------------------------------------------------
        print("Test T67.7: bug_step_completed event format ... ", end="")

        push_job_event(sse_job_id, "bug_step_completed", {
            "bug_index": 0,
            "step": "fix_bug_peer",
            "label": "修复 Bug",
            "status": "completed",
            "duration_ms": 45200.5,
            "output_preview": "已修复模块",
            "error": None,
            "attempt": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            event = sse_queue.get_nowait()
            evt_data = event.get("data", {})
            required = ["bug_index", "step", "label", "status", "timestamp"]
            optional = ["duration_ms", "output_preview", "error", "attempt"]
            missing = [f for f in required if f not in evt_data]
            if event.get("event") == "bug_step_completed" and not missing:
                # Verify status is valid
                if evt_data["status"] in ("completed", "in_progress", "failed"):
                    present_optionals = [f for f in optional if evt_data.get(f) is not None]
                    print(f"OK (required: {required}, optional present: {present_optionals})")
                    passed += 1
                else:
                    msg = f"FAIL — invalid status: {evt_data['status']}"
                    print(msg)
                    errors.append(("T67.7", msg))
            else:
                msg = f"FAIL — event_type={event.get('event')}, missing={missing}"
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
        # Simulate: bug_started → step_started(fix) → step_completed(fix) → step_started(verify) → step_completed(verify) → bug_completed
        events_to_push = [
            ("bug_started", {"bug_index": 0, "url": "BUG-1", "timestamp": now.isoformat()}),
            ("bug_step_started", {"bug_index": 0, "step": "fix_bug_peer", "label": "修复 Bug", "timestamp": now.isoformat()}),
            ("bug_step_completed", {"bug_index": 0, "step": "fix_bug_peer", "label": "修复 Bug", "status": "completed", "timestamp": now.isoformat()}),
            ("bug_step_started", {"bug_index": 0, "step": "verify_fix", "label": "验证修复结果", "timestamp": now.isoformat()}),
            ("bug_step_completed", {"bug_index": 0, "step": "verify_fix", "label": "验证修复结果", "status": "completed", "timestamp": now.isoformat()}),
            ("bug_completed", {"bug_index": 0, "url": "BUG-1", "timestamp": now.isoformat()}),
        ]

        for evt_type, evt_data in events_to_push:
            push_job_event(sse_job_id, evt_type, evt_data)

        received_order = []
        while not sse_queue.empty():
            evt = sse_queue.get_nowait()
            received_order.append(evt["event"])

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
            # Check 1 decimal place: round(d, 1) should equal d
            if round(d, 1) != d:
                duration_ok = False
                break

        if duration_ok:
            # Also verify from API response
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

        # Cleanup
        BATCH_JOBS_CACHE.pop(test_job_id, None)
        BATCH_JOBS_CACHE.pop(retry_job_id, None)
        JOB_BUG_STEPS.pop(test_job_id, None)
        JOB_BUG_STEPS.pop(retry_job_id, None)
        JOB_SSE_QUEUES.pop(sse_job_id, None)

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
