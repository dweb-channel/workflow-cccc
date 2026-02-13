"""E2E Tests for Phase 3 Fixes — T069 Config + T-REG Regression

Tests cover:
- T069: Config field mapping (frontend→backend alignment)
- T-REG: Regression — M9 API contract intact (DB-based)

Note: T070/T071 (in-memory cache locks, push_job_event SSE) removed
after Temporal migration — those concerns are now handled by the
Temporal worker process and shared SSE infrastructure.

Author: browser-tester (updated for Temporal architecture)
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


async def run_tests():
    """Run all Phase 3 fix verification tests."""
    errors = []
    passed = 0

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    from app.database import Base, get_session_ctx
    from app.repositories.batch_job import BatchJobRepository
    from app.models.db import BatchJobModel, BugResultModel
    from workflow.temporal.batch_activities import NODE_TO_STEP

    # --- Test DB isolation: use in-memory SQLite ---
    _test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    _test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

    import app.database as _db_mod
    _db_mod.engine = _test_engine
    _db_mod.async_session_factory = _test_session_factory

    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.routes.batch import BatchBugFixRequest, BatchBugFixConfig

    # Setup DB (in-memory, isolated from production)
    async with _test_engine.begin() as conn:
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
        try:
            req = BatchBugFixRequest(
                jira_urls=["https://testjira.atlassian.net/browse/CFG-1"],
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
        # Section 2: Regression — M9 API contract intact (DB-based)
        # =============================================================
        print("\n" + "=" * 60)
        print("Section 2: Regression — M9 API contract intact")
        print("=" * 60)

        # T-REG.1: GET job status still returns steps field (M9 regression)
        print("\nTest T-REG.1: GET job status returns steps (M9 regression) ... ", end="")
        reg_job_id = "job_regression_01"
        now = datetime.now(timezone.utc)
        try:
            async with get_session_ctx() as session:
                job_model = BatchJobModel(
                    id=reg_job_id,
                    status="running",
                    target_group_id="test-group",
                    config={"validation_level": "standard", "failure_policy": "skip"},
                )
                session.add(job_model)
                await session.flush()

                bug_model = BugResultModel(
                    job_id=reg_job_id,
                    bug_index=0,
                    url="https://testjira.atlassian.net/browse/REG-1",
                    status="completed",
                    started_at=now,
                    completed_at=now,
                    steps=[
                        {"step": "fix_bug_peer", "label": "修复", "status": "completed",
                         "started_at": now.isoformat(), "completed_at": now.isoformat(),
                         "duration_ms": 100.0, "output_preview": "Fixed"},
                    ],
                )
                session.add(bug_model)
                await session.commit()

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
        except Exception as e:
            msg = f"FAIL — DB error: {e}"
            print(msg)
            errors.append(("T-REG.1", msg))

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
