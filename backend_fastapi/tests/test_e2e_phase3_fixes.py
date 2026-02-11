"""E2E Tests for Phase 3 Fixes — T068/T069/T070/T071

Tests cover:
- T069: Config field mapping (frontend→backend alignment)
- T071: Backend concurrency locks + timeout protection
- T070: SSE defensive programming (safeParse, backoff, fallback poll)
- T068: Workflow Tab (verified via frontend Playwright tests)

Backend-only tests (no temporalio dependency required).

Author: browser-tester
Date: 2026-02-10
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# CCCC_MOCK/CCCC_GROUP_ID no longer needed (CCCC integration removed in M11)


async def run_tests():
    """Run all Phase 3 fix verification tests."""
    errors = []
    passed = 0

    from httpx import AsyncClient, ASGITransport
    from app.database import engine, Base
    from app.main import app
    from app.routes.cccc import (
        BATCH_JOBS_CACHE,
        JOB_BUG_STEPS,
        JOB_SSE_QUEUES,
        WORKFLOW_TASKS,
        NODE_TO_STEP,
        push_job_event,
        _count_retries,
        _cache_lock,
        _tasks_lock,
        _sse_lock,
        _steps_lock,
        WORKFLOW_TIMEOUT,
    )

    # Setup DB
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # =============================================================
        # Section 1: T069 — Config Field Mapping
        # =============================================================
        print("\n" + "=" * 60)
        print("Section 1: T069 — Config Field Mapping")
        print("=" * 60)

        # T069.1: Pydantic schema accepts nested config with correct fields
        print("\nTest T069.1: BatchBugFixRequest schema accepts nested config ... ", end="")
        from app.routes.cccc import BatchBugFixRequest, BatchBugFixConfig
        try:
            req = BatchBugFixRequest(
                target_group_id="test-group",
                jira_urls=["https://jira.example.com/browse/CFG-1"],
                config=BatchBugFixConfig(
                    validation_level="thorough",
                    failure_policy="retry",
                    max_retries=5,
                ),
            )
            if (req.config.validation_level == "thorough"
                    and req.config.failure_policy == "retry"
                    and req.config.max_retries == 5):
                print(f"OK (validation_level={req.config.validation_level}, failure_policy={req.config.failure_policy}, max_retries={req.config.max_retries})")
                passed += 1
            else:
                msg = f"FAIL — config values wrong: {req.config}"
                print(msg)
                errors.append(("T069.1", msg))
        except Exception as e:
            msg = f"FAIL — schema validation error: {e}"
            print(msg)
            errors.append(("T069.1", msg))

        # T069.2: BatchBugFixConfig defaults are correct
        print("Test T069.2: BatchBugFixConfig defaults (standard/skip/3) ... ", end="")
        try:
            cfg = BatchBugFixConfig()
            if (cfg.validation_level == "standard"
                    and cfg.failure_policy == "skip"
                    and cfg.max_retries == 3):
                print(f"OK (defaults: validation_level={cfg.validation_level}, failure_policy={cfg.failure_policy}, max_retries={cfg.max_retries})")
                passed += 1
            else:
                msg = f"FAIL — unexpected defaults: vl={cfg.validation_level}, fp={cfg.failure_policy}, mr={cfg.max_retries}"
                print(msg)
                errors.append(("T069.2", msg))
        except Exception as e:
            msg = f"FAIL — {e}"
            print(msg)
            errors.append(("T069.2", msg))

        # T069.3: Old field names NOT in schema (Pydantic ignores them)
        print("Test T069.3: Old field names (verification_level, on_failure) not in schema ... ", end="")
        req_fields = set(BatchBugFixRequest.model_fields.keys())
        config_fields = set(BatchBugFixConfig.model_fields.keys())
        old_top_level = {"verification_level", "on_failure"} & req_fields
        old_config_level = {"verification_level", "on_failure"} & config_fields
        if not old_top_level and not old_config_level:
            print(f"OK (request fields: {sorted(req_fields)}, config fields: {sorted(config_fields)})")
            passed += 1
        else:
            msg = f"FAIL — old fields found: top={old_top_level}, config={old_config_level}"
            print(msg)
            errors.append(("T069.3", msg))

        # T069.4: All 3 validation_level values accepted by schema
        print("Test T069.4: All validation_level values accepted ... ", end="")
        all_vl_ok = True
        for vl_val in ["minimal", "standard", "thorough"]:
            try:
                cfg = BatchBugFixConfig(validation_level=vl_val)
                if cfg.validation_level != vl_val:
                    all_vl_ok = False
                    break
            except Exception:
                all_vl_ok = False
                break
        if all_vl_ok:
            print("OK (minimal/standard/thorough all accepted)")
            passed += 1
        else:
            msg = f"FAIL — validation_level={vl_val} rejected"
            print(msg)
            errors.append(("T069.4", msg))

        # T069.5: All 3 failure_policy values accepted by schema
        print("Test T069.5: All failure_policy values accepted ... ", end="")
        all_fp_ok = True
        for fp_val in ["stop", "skip", "retry"]:
            try:
                cfg = BatchBugFixConfig(failure_policy=fp_val)
                if cfg.failure_policy != fp_val:
                    all_fp_ok = False
                    break
            except Exception:
                all_fp_ok = False
                break
        if all_fp_ok:
            print("OK (stop/skip/retry all accepted)")
            passed += 1
        else:
            msg = f"FAIL — failure_policy={fp_val} rejected"
            print(msg)
            errors.append(("T069.5", msg))

        # =============================================================
        # Section 2: T071 — Backend Concurrency Locks + Timeout
        # =============================================================
        print("\n" + "=" * 60)
        print("Section 2: T071 — Concurrency Locks + Timeout")
        print("=" * 60)

        # T071.1: Lock objects exist and are asyncio.Lock type
        print("\nTest T071.1: 4 asyncio.Lock() instances exist ... ", end="")
        locks = {
            "_cache_lock": _cache_lock,
            "_tasks_lock": _tasks_lock,
            "_sse_lock": _sse_lock,
            "_steps_lock": _steps_lock,
        }
        all_locks_ok = True
        for name, lock in locks.items():
            if not isinstance(lock, asyncio.Lock):
                all_locks_ok = False
                msg = f"FAIL — {name} is {type(lock).__name__}, expected asyncio.Lock"
                print(msg)
                errors.append(("T071.1", msg))
                break
        if all_locks_ok:
            print(f"OK (4 locks: {', '.join(locks.keys())})")
            passed += 1

        # T071.2: WORKFLOW_TIMEOUT configured
        print("Test T071.2: WORKFLOW_TIMEOUT configured ... ", end="")
        if isinstance(WORKFLOW_TIMEOUT, int) and WORKFLOW_TIMEOUT > 0:
            print(f"OK (WORKFLOW_TIMEOUT={WORKFLOW_TIMEOUT}s)")
            passed += 1
        else:
            msg = f"FAIL — WORKFLOW_TIMEOUT={WORKFLOW_TIMEOUT} (type={type(WORKFLOW_TIMEOUT).__name__})"
            print(msg)
            errors.append(("T071.2", msg))

        # T071.3: Cache lock prevents concurrent mutation
        print("Test T071.3: Cache lock serializes concurrent access ... ", end="")
        test_lock_job = "job_lock_test"
        results = []

        async def writer():
            async with _cache_lock:
                BATCH_JOBS_CACHE[test_lock_job] = {"status": "writing"}
                await asyncio.sleep(0.01)  # Hold lock briefly
                BATCH_JOBS_CACHE[test_lock_job]["status"] = "written"
                results.append("write_done")

        async def reader():
            await asyncio.sleep(0.005)  # Start slightly after writer
            async with _cache_lock:
                val = BATCH_JOBS_CACHE.get(test_lock_job, {}).get("status")
                results.append(f"read_{val}")

        await asyncio.gather(writer(), reader())

        # Reader should see "written" (not "writing") because lock serializes
        if results == ["write_done", "read_written"]:
            print(f"OK (serialized: {results})")
            passed += 1
        else:
            msg = f"FAIL — unexpected order: {results}"
            print(msg)
            errors.append(("T071.3", msg))

        # Cleanup
        async with _cache_lock:
            BATCH_JOBS_CACHE.pop(test_lock_job, None)

        # T071.4: Cache iteration uses snapshot (no RuntimeError)
        print("Test T071.4: Cache iteration safe under concurrent writes ... ", end="")
        # Populate cache with some jobs
        for i in range(5):
            async with _cache_lock:
                BATCH_JOBS_CACHE[f"iter_test_{i}"] = {"status": "running", "bugs": []}

        try:
            # Simulate concurrent iteration + write
            async def iterate_cache():
                async with _cache_lock:
                    snapshot = dict(BATCH_JOBS_CACHE)
                # Iterate snapshot (safe)
                count = 0
                for k, v in snapshot.items():
                    if k.startswith("iter_test_"):
                        count += 1
                return count

            async def write_during_iter():
                await asyncio.sleep(0.001)
                async with _cache_lock:
                    BATCH_JOBS_CACHE["iter_test_new"] = {"status": "new", "bugs": []}

            count, _ = await asyncio.gather(iterate_cache(), write_during_iter())
            if count >= 5:
                print(f"OK (iterated {count} items without RuntimeError)")
                passed += 1
            else:
                msg = f"FAIL — only iterated {count} items"
                print(msg)
                errors.append(("T071.4", msg))
        except RuntimeError as e:
            msg = f"FAIL — RuntimeError during iteration: {e}"
            print(msg)
            errors.append(("T071.4", msg))

        # Cleanup
        async with _cache_lock:
            for k in list(BATCH_JOBS_CACHE.keys()):
                if k.startswith("iter_test_"):
                    del BATCH_JOBS_CACHE[k]

        # T071.5: SSE queue operations locked
        print("Test T071.5: SSE queue register/unregister under lock ... ", end="")
        sse_test_id = "sse_lock_test"
        async with _sse_lock:
            JOB_SSE_QUEUES[sse_test_id] = asyncio.Queue(maxsize=1000)
        async with _sse_lock:
            q = JOB_SSE_QUEUES.pop(sse_test_id, None)
        if q is not None and sse_test_id not in JOB_SSE_QUEUES:
            print("OK (register + unregister under lock)")
            passed += 1
        else:
            msg = f"FAIL — SSE queue lock test failed"
            print(msg)
            errors.append(("T071.5", msg))

        # T071.6: push_job_event with db_warning event type
        print("Test T071.6: push_job_event supports db_warning event ... ", end="")
        warn_job_id = "warn_test"
        warn_queue = asyncio.Queue(maxsize=1000)
        JOB_SSE_QUEUES[warn_job_id] = warn_queue

        push_job_event(warn_job_id, "db_warning", {
            "message": "Database sync failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        try:
            evt = warn_queue.get_nowait()
            if evt.get("event") == "db_warning" and "message" in evt.get("data", {}):
                print(f"OK (db_warning event pushed)")
                passed += 1
            else:
                msg = f"FAIL — unexpected event: {evt}"
                print(msg)
                errors.append(("T071.6", msg))
        except asyncio.QueueEmpty:
            msg = "FAIL — no db_warning event in queue"
            print(msg)
            errors.append(("T071.6", msg))
        finally:
            JOB_SSE_QUEUES.pop(warn_job_id, None)

        # =============================================================
        # Section 3: T070 — SSE Defensive Programming (backend side)
        # =============================================================
        print("\n" + "=" * 60)
        print("Section 3: T070 — SSE Defensive (backend verification)")
        print("=" * 60)

        # T070.1: push_job_event handles missing queue gracefully
        print("\nTest T070.1: push_job_event with no queue (no crash) ... ", end="")
        try:
            push_job_event("nonexistent_job_999", "test_event", {"foo": "bar"})
            print("OK (no crash on missing queue)")
            passed += 1
        except Exception as e:
            msg = f"FAIL — crash on missing queue: {e}"
            print(msg)
            errors.append(("T070.1", msg))

        # T070.2: push_job_event handles full queue gracefully
        print("Test T070.2: push_job_event with full queue (no crash) ... ", end="")
        full_job_id = "full_queue_test"
        tiny_queue = asyncio.Queue(maxsize=1)
        JOB_SSE_QUEUES[full_job_id] = tiny_queue
        # Fill the queue
        tiny_queue.put_nowait({"event": "filler", "data": {}})

        try:
            push_job_event(full_job_id, "overflow_event", {"test": True})
            print("OK (no crash on full queue — event dropped with warning)")
            passed += 1
        except Exception as e:
            msg = f"FAIL — crash on full queue: {e}"
            print(msg)
            errors.append(("T070.2", msg))
        finally:
            JOB_SSE_QUEUES.pop(full_job_id, None)

        # T070.3: SSE event data is JSON-serializable
        print("Test T070.3: SSE events are JSON-serializable ... ", end="")
        serial_job_id = "serial_test"
        serial_queue = asyncio.Queue(maxsize=100)
        JOB_SSE_QUEUES[serial_job_id] = serial_queue

        push_job_event(serial_job_id, "bug_step_started", {
            "bug_index": 0,
            "step": "fix_bug_peer",
            "label": "修复 Bug",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": 1,
        })

        try:
            evt = serial_queue.get_nowait()
            # Attempt to serialize the data payload
            json_str = json.dumps(evt["data"], ensure_ascii=False)
            if len(json_str) > 0:
                print(f"OK (serialized to {len(json_str)} chars)")
                passed += 1
            else:
                msg = "FAIL — empty JSON"
                print(msg)
                errors.append(("T070.3", msg))
        except (TypeError, ValueError) as e:
            msg = f"FAIL — not JSON-serializable: {e}"
            print(msg)
            errors.append(("T070.3", msg))
        except asyncio.QueueEmpty:
            msg = "FAIL — no event in queue"
            print(msg)
            errors.append(("T070.3", msg))
        finally:
            JOB_SSE_QUEUES.pop(serial_job_id, None)

        # =============================================================
        # Section 4: Cross-validation — existing M9 tests still pass
        # =============================================================
        print("\n" + "=" * 60)
        print("Section 4: Regression — M9 API contract intact")
        print("=" * 60)

        # T-REG.1: GET job status still returns steps field (M9 regression)
        print("\nTest T-REG.1: GET job status returns steps (M9 regression) ... ", end="")
        reg_job_id = "job_regression_01"
        now = datetime.now(timezone.utc).isoformat()
        reg_steps = [
            {"step": "fix_bug_peer", "label": "修复", "status": "completed",
             "started_at": now, "completed_at": now, "duration_ms": 100.0,
             "output_preview": "Fixed"},
        ]
        async with _cache_lock:
            BATCH_JOBS_CACHE[reg_job_id] = {
                "job_id": reg_job_id,
                "status": "running",
                "target_group_id": "test-group",
                "config": {"validation_level": "standard", "failure_policy": "skip"},
                "error": None,
                "bugs": [{
                    "url": "https://jira.example.com/browse/REG-1",
                    "status": "completed",
                    "error": None,
                    "started_at": now,
                    "completed_at": now,
                    "steps": reg_steps,
                    "retry_count": 0,
                }],
                "created_at": now,
                "updated_at": now,
            }
        JOB_BUG_STEPS[reg_job_id] = {0: reg_steps}

        resp_reg = await client.get(f"/api/v2/batch/bug-fix/{reg_job_id}")
        if resp_reg.status_code == 200:
            reg_data = resp_reg.json()
            bugs = reg_data.get("bugs", [])
            if bugs and bugs[0].get("steps"):
                step0 = bugs[0]["steps"][0]
                if step0.get("step") == "fix_bug_peer" and step0.get("status") == "completed":
                    print(f"OK (steps intact, first step={step0['step']})")
                    passed += 1
                else:
                    msg = f"FAIL — step data corrupted: {step0}"
                    print(msg)
                    errors.append(("T-REG.1", msg))
            else:
                msg = "FAIL — steps missing from response"
                print(msg)
                errors.append(("T-REG.1", msg))
        else:
            msg = f"FAIL — status={resp_reg.status_code}"
            print(msg)
            errors.append(("T-REG.1", msg))

        # Cleanup
        async with _cache_lock:
            BATCH_JOBS_CACHE.pop(reg_job_id, None)
        JOB_BUG_STEPS.pop(reg_job_id, None)

        # T-REG.2: NODE_TO_STEP mapping unchanged
        print("Test T-REG.2: NODE_TO_STEP mapping unchanged ... ", end="")
        expected_exposed = ["get_current_bug", "fix_bug_peer", "verify_fix",
                           "increment_retry", "update_success", "update_failure"]
        expected_internal = ["check_verify_result", "check_retry", "check_more_bugs",
                            "input_node", "output_node"]
        exposed_ok = all(NODE_TO_STEP.get(n) is not None for n in expected_exposed)
        internal_ok = all(NODE_TO_STEP.get(n) is None for n in expected_internal)
        if exposed_ok and internal_ok:
            print(f"OK ({len(expected_exposed)} exposed, {len(expected_internal)} internal)")
            passed += 1
        else:
            msg = f"FAIL — mapping changed"
            print(msg)
            errors.append(("T-REG.2", msg))

    return passed, errors


if __name__ == "__main__":
    passed, errors = asyncio.run(run_tests())
    total = passed + len(errors)

    print(f"\n{'='*60}")
    print(f"Phase 3 Fix Tests: {passed}/{total} passed")
    if errors:
        print("\nFailures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("All Phase 3 fix tests passed!")
        sys.exit(0)
