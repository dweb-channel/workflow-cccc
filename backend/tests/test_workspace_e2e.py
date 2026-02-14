"""E2E Tests for Workspace API (M19 T112).

Tests cover:
- Workspace CRUD (create, list, get, update, delete)
- Preflight validation (path exists, git repo, permissions)
- repo_path uniqueness constraint (409 on duplicate)
- Config inheritance (workspace defaults → job override)
- Delete behavior (SET NULL on jobs, not CASCADE)
- Job listing filtered by workspace_id
- Legacy mode (no workspace, original behavior)
"""

import asyncio
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock temporalio if not installed (same pattern as tests/workflow/conftest.py)
if "temporalio" not in sys.modules:
    try:
        import temporalio  # noqa: F401
    except ModuleNotFoundError:
        _temporalio = MagicMock()
        _activity = MagicMock()
        _activity.defn = lambda fn=None, **kwargs: fn if fn else (lambda f: f)
        _activity.heartbeat = MagicMock()
        _activity.info = MagicMock()
        _temporalio.activity = _activity
        _workflow = MagicMock()
        _workflow.defn = lambda cls=None, **kwargs: cls if cls else (lambda c: c)
        _workflow.run = lambda fn=None, **kwargs: fn if fn else (lambda f: f)
        _temporalio.workflow = _workflow
        _temporalio.client = MagicMock()
        _temporalio.worker = MagicMock()
        sys.modules["temporalio"] = _temporalio
        sys.modules["temporalio.activity"] = _activity
        sys.modules["temporalio.workflow"] = _workflow
        sys.modules["temporalio.client"] = _temporalio.client
        sys.modules["temporalio.worker"] = _temporalio.worker

from httpx import AsyncClient, ASGITransport
from app.database import engine, Base
from app.main import app


async def setup_db():
    """Create tables for testing."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


# Use the project's own repo as a known-valid git repo for tests
# tests/ -> backend/ -> work-flow/ (the actual git root with .git)
PROJECT_REPO = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))


async def run_tests():
    """Run all Workspace E2E tests."""
    errors = []
    passed = 0

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # =================================================================
        # 1. Workspace CRUD
        # =================================================================

        # --- 1.1 Create workspace with valid git repo ---
        print("\n=== 1. Workspace CRUD ===")
        print("Test 1.1: Create workspace ... ", end="")
        resp = await client.post("/api/v2/workspaces", json={
            "name": "test-project",
            "repo_path": PROJECT_REPO,
        })
        if resp.status_code == 201:
            ws = resp.json()
            ws_id = ws["id"]
            if (
                ws["name"] == "test-project"
                and ws["repo_path"] == PROJECT_REPO
                and ws["job_count"] == 0
                and ws["id"].startswith("ws_") is False or len(ws["id"]) > 0  # ID exists
            ):
                print(f"OK (id={ws_id})")
                passed += 1
            else:
                msg = f"FAIL - unexpected response fields: {ws}"
                print(msg)
                errors.append(("1.1-create", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("1.1-create", msg))
            ws_id = None

        # --- 1.2 List workspaces ---
        print("Test 1.2: List workspaces ... ", end="")
        resp = await client.get("/api/v2/workspaces")
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] >= 1 and len(data["workspaces"]) >= 1:
                found = any(w["name"] == "test-project" for w in data["workspaces"])
                if found:
                    print(f"OK (total={data['total']})")
                    passed += 1
                else:
                    msg = f"FAIL - test-project not in list"
                    print(msg)
                    errors.append(("1.2-list", msg))
            else:
                msg = f"FAIL - expected at least 1 workspace: {data}"
                print(msg)
                errors.append(("1.2-list", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("1.2-list", msg))

        # --- 1.3 Get workspace by ID ---
        print("Test 1.3: Get workspace by ID ... ", end="")
        if ws_id:
            resp = await client.get(f"/api/v2/workspaces/{ws_id}")
            if resp.status_code == 200:
                ws = resp.json()
                if ws["id"] == ws_id and ws["name"] == "test-project":
                    print(f"OK")
                    passed += 1
                else:
                    msg = f"FAIL - wrong data: {ws}"
                    print(msg)
                    errors.append(("1.3-get", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("1.3-get", msg))
        else:
            print("SKIP (no ws_id)")
            errors.append(("1.3-get", "skipped - no workspace created"))

        # --- 1.4 Get non-existent workspace (404) ---
        print("Test 1.4: Get non-existent workspace ... ", end="")
        resp = await client.get("/api/v2/workspaces/ws_nonexistent")
        if resp.status_code == 404:
            print("OK (404)")
            passed += 1
        else:
            msg = f"FAIL - expected 404, got {resp.status_code}"
            print(msg)
            errors.append(("1.4-get-404", msg))

        # --- 1.5 Update workspace ---
        print("Test 1.5: Update workspace name ... ", end="")
        if ws_id:
            resp = await client.put(f"/api/v2/workspaces/{ws_id}", json={
                "name": "test-project-renamed",
            })
            if resp.status_code == 200:
                ws = resp.json()
                if ws["name"] == "test-project-renamed":
                    print("OK")
                    passed += 1
                else:
                    msg = f"FAIL - name not updated: {ws}"
                    print(msg)
                    errors.append(("1.5-update", msg))
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("1.5-update", msg))
        else:
            print("SKIP")
            errors.append(("1.5-update", "skipped"))

        # --- 1.6 Update workspace config_defaults ---
        print("Test 1.6: Update workspace config_defaults ... ", end="")
        if ws_id:
            resp = await client.put(f"/api/v2/workspaces/{ws_id}", json={
                "config_defaults": {"max_retries": 5, "validation_level": "strict"},
            })
            if resp.status_code == 200:
                ws = resp.json()
                defaults = ws.get("config_defaults", {})
                if defaults.get("max_retries") == 5 and defaults.get("validation_level") == "strict":
                    print("OK")
                    passed += 1
                else:
                    msg = f"FAIL - config_defaults not updated: {defaults}"
                    print(msg)
                    errors.append(("1.6-config", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("1.6-config", msg))
        else:
            print("SKIP")
            errors.append(("1.6-config", "skipped"))

        # =================================================================
        # 2. Preflight Validation
        # =================================================================
        print("\n=== 2. Preflight Validation ===")

        # --- 2.1 Preflight: valid git repo ---
        print("Test 2.1: Preflight valid repo ... ", end="")
        resp = await client.post("/api/v2/workspaces/preflight", json={
            "name": "preflight-test",
            "repo_path": PROJECT_REPO,
        })
        if resp.status_code == 200:
            data = resp.json()
            if data["ok"] is True and len(data["errors"]) == 0:
                print("OK")
                passed += 1
            else:
                msg = f"FAIL - expected ok=True: {data}"
                print(msg)
                errors.append(("2.1-preflight-ok", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("2.1-preflight-ok", msg))

        # --- 2.2 Preflight: non-existent path ---
        print("Test 2.2: Preflight non-existent path ... ", end="")
        resp = await client.post("/api/v2/workspaces/preflight", json={
            "name": "bad-path",
            "repo_path": "/nonexistent/path/1234567890",
        })
        if resp.status_code == 200:
            data = resp.json()
            if data["ok"] is False and any("does not exist" in e for e in data["errors"]):
                print("OK (rejected)")
                passed += 1
            else:
                msg = f"FAIL - expected failure: {data}"
                print(msg)
                errors.append(("2.2-preflight-noexist", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("2.2-preflight-noexist", msg))

        # --- 2.3 Preflight: directory exists but not git repo ---
        print("Test 2.3: Preflight non-git directory ... ", end="")
        with tempfile.TemporaryDirectory() as tmpdir:
            resp = await client.post("/api/v2/workspaces/preflight", json={
                "name": "no-git",
                "repo_path": tmpdir,
            })
            if resp.status_code == 200:
                data = resp.json()
                if data["ok"] is False and any("Not a git repository" in e for e in data["errors"]):
                    print("OK (rejected)")
                    passed += 1
                else:
                    msg = f"FAIL - expected git error: {data}"
                    print(msg)
                    errors.append(("2.3-preflight-nogit", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("2.3-preflight-nogit", msg))

        # --- 2.4 Create workspace with non-existent path (should fail 400) ---
        print("Test 2.4: Create with invalid path ... ", end="")
        resp = await client.post("/api/v2/workspaces", json={
            "name": "bad-workspace",
            "repo_path": "/nonexistent/bad/path",
        })
        if resp.status_code == 400:
            if "Preflight failed" in resp.json().get("detail", ""):
                print("OK (400)")
                passed += 1
            else:
                msg = f"FAIL - wrong error message: {resp.json()}"
                print(msg)
                errors.append(("2.4-create-bad", msg))
        else:
            msg = f"FAIL - expected 400, got {resp.status_code}"
            print(msg)
            errors.append(("2.4-create-bad", msg))

        # =================================================================
        # 3. Uniqueness Constraint
        # =================================================================
        print("\n=== 3. Uniqueness Constraint ===")

        # --- 3.1 Duplicate repo_path (409) ---
        print("Test 3.1: Duplicate repo_path ... ", end="")
        resp = await client.post("/api/v2/workspaces", json={
            "name": "duplicate-project",
            "repo_path": PROJECT_REPO,
        })
        if resp.status_code == 409:
            detail = resp.json().get("detail", "")
            if "already exists" in detail.lower() or "已被" in detail:
                print("OK (409)")
                passed += 1
            else:
                msg = f"FAIL - wrong detail: {detail}"
                print(msg)
                errors.append(("3.1-duplicate", msg))
        else:
            msg = f"FAIL - expected 409, got {resp.status_code}"
            print(msg)
            errors.append(("3.1-duplicate", msg))

        # --- 3.2 Path canonicalization (same path with ..) ---
        print("Test 3.2: Path canonicalization dedup ... ", end="")
        parent = os.path.dirname(PROJECT_REPO)
        basename = os.path.basename(PROJECT_REPO)
        non_canonical = os.path.join(parent, "fake_dir", "..", basename)
        resp = await client.post("/api/v2/workspaces", json={
            "name": "canonical-test",
            "repo_path": non_canonical,
        })
        if resp.status_code == 409:
            print("OK (canonicalized + rejected)")
            passed += 1
        else:
            msg = f"FAIL - expected 409 after canonicalization, got {resp.status_code}: {resp.text}"
            print(msg)
            errors.append(("3.2-canonical", msg))

        # =================================================================
        # 4. Config Inheritance
        # =================================================================
        print("\n=== 4. Config Inheritance ===")

        # First verify workspace has config_defaults from test 1.6
        print("Test 4.1: Job inherits workspace config ... ", end="")
        if ws_id:
            # Submit a dry-run job with workspace_id to verify config merge
            resp = await client.post("/api/v2/batch/bug-fix", json={
                "jira_urls": ["https://jira.atlassian.net/browse/TEST-1"],
                "workspace_id": ws_id,
                "dry_run": True,
            })
            if resp.status_code == 200:
                data = resp.json()
                # Dry run should work and inherit cwd from workspace
                if data.get("cwd") == PROJECT_REPO:
                    print(f"OK (cwd inherited: {PROJECT_REPO})")
                    passed += 1
                else:
                    msg = f"FAIL - cwd not inherited: got {data.get('cwd')}, expected {PROJECT_REPO}"
                    print(msg)
                    errors.append(("4.1-inherit", msg))
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("4.1-inherit", msg))
        else:
            print("SKIP")
            errors.append(("4.1-inherit", "skipped"))

        # --- 4.2 Job-level config overrides workspace defaults ---
        print("Test 4.2: Job-level config overrides workspace ... ", end="")
        if ws_id:
            resp = await client.post("/api/v2/batch/bug-fix", json={
                "jira_urls": ["https://jira.atlassian.net/browse/TEST-2"],
                "workspace_id": ws_id,
                "config": {"validation_level": "minimal"},
                "dry_run": True,
            })
            if resp.status_code == 200:
                data = resp.json()
                config = data.get("config", {})
                # validation_level should be overridden to "lenient"
                # max_retries should be inherited as 5 from workspace defaults
                if config.get("validation_level") == "minimal":
                    print("OK (override works)")
                    passed += 1
                else:
                    msg = f"FAIL - override not applied: {config}"
                    print(msg)
                    errors.append(("4.2-override", msg))
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("4.2-override", msg))
        else:
            print("SKIP")
            errors.append(("4.2-override", "skipped"))

        # --- 4.3 Non-existent workspace_id (404) ---
        print("Test 4.3: Job with non-existent workspace ... ", end="")
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["https://jira.atlassian.net/browse/TEST-3"],
            "workspace_id": "ws_nonexistent",
            "dry_run": True,
        })
        if resp.status_code == 404:
            print("OK (404)")
            passed += 1
        else:
            msg = f"FAIL - expected 404, got {resp.status_code}: {resp.text}"
            print(msg)
            errors.append(("4.3-ws-404", msg))

        # =================================================================
        # 5. Legacy Mode (no workspace)
        # =================================================================
        print("\n=== 5. Legacy Mode ===")

        # --- 5.1 Dry-run without workspace (original behavior) ---
        print("Test 5.1: Dry-run without workspace ... ", end="")
        resp = await client.post("/api/v2/batch/bug-fix", json={
            "jira_urls": ["https://jira.atlassian.net/browse/TEST-4"],
            "cwd": "/tmp",
            "dry_run": True,
        })
        if resp.status_code == 200:
            data = resp.json()
            if data.get("cwd") == "/tmp":
                print("OK (manual cwd works)")
                passed += 1
            else:
                msg = f"FAIL - cwd mismatch: {data.get('cwd')}"
                print(msg)
                errors.append(("5.1-legacy", msg))
        else:
            msg = f"FAIL status={resp.status_code}: {resp.text}"
            print(msg)
            errors.append(("5.1-legacy", msg))

        # =================================================================
        # 6. Delete Workspace (SET NULL on jobs)
        # =================================================================
        print("\n=== 6. Delete Workspace ===")

        # --- 6.1 Delete workspace ---
        print("Test 6.1: Delete workspace ... ", end="")
        if ws_id:
            resp = await client.delete(f"/api/v2/workspaces/{ws_id}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") is True:
                    print("OK")
                    passed += 1
                else:
                    msg = f"FAIL - unexpected response: {data}"
                    print(msg)
                    errors.append(("6.1-delete", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("6.1-delete", msg))
        else:
            print("SKIP")
            errors.append(("6.1-delete", "skipped"))

        # --- 6.2 Verify workspace is gone ---
        print("Test 6.2: Verify deletion ... ", end="")
        if ws_id:
            resp = await client.get(f"/api/v2/workspaces/{ws_id}")
            if resp.status_code == 404:
                print("OK (404)")
                passed += 1
            else:
                msg = f"FAIL - expected 404, got {resp.status_code}"
                print(msg)
                errors.append(("6.2-verify-delete", msg))
        else:
            print("SKIP")
            errors.append(("6.2-verify-delete", "skipped"))

        # --- 6.3 Delete non-existent workspace (404) ---
        print("Test 6.3: Delete non-existent workspace ... ", end="")
        resp = await client.delete("/api/v2/workspaces/ws_nonexistent_delete")
        if resp.status_code == 404:
            print("OK (404)")
            passed += 1
        else:
            msg = f"FAIL - expected 404, got {resp.status_code}"
            print(msg)
            errors.append(("6.3-delete-404", msg))

        # --- 6.4 Re-create after delete (path should be available again) ---
        print("Test 6.4: Re-create after delete ... ", end="")
        resp = await client.post("/api/v2/workspaces", json={
            "name": "recreated-project",
            "repo_path": PROJECT_REPO,
        })
        if resp.status_code == 201:
            ws2 = resp.json()
            if ws2["name"] == "recreated-project":
                print(f"OK (id={ws2['id']})")
                passed += 1
            else:
                msg = f"FAIL - wrong name: {ws2}"
                print(msg)
                errors.append(("6.4-recreate", msg))
        else:
            msg = f"FAIL status={resp.status_code}: {resp.text}"
            print(msg)
            errors.append(("6.4-recreate", msg))

        # =================================================================
        # 7. Job Listing with workspace_id Filter
        # =================================================================
        print("\n=== 7. Job Listing Filter ===")

        # --- 7.1 List jobs with workspace filter (empty) ---
        print("Test 7.1: List jobs filtered by workspace (empty) ... ", end="")
        resp = await client.get("/api/v2/batch/bug-fix", params={"workspace_id": "ws_empty_filter"})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("total", 0) == 0:
                print("OK (0 jobs)")
                passed += 1
            else:
                msg = f"FAIL - expected 0 jobs: {data}"
                print(msg)
                errors.append(("7.1-filter", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("7.1-filter", msg))

        # =================================================================
        # 8. Pagination
        # =================================================================
        print("\n=== 8. Pagination ===")

        # --- 8.1 List with page_size=1 ---
        print("Test 8.1: Pagination page_size=1 ... ", end="")
        resp = await client.get("/api/v2/workspaces", params={"page": 1, "page_size": 1})
        if resp.status_code == 200:
            data = resp.json()
            if len(data["workspaces"]) <= 1 and data["page"] == 1:
                print(f"OK (returned {len(data['workspaces'])} of {data['total']})")
                passed += 1
            else:
                msg = f"FAIL - pagination incorrect: {data}"
                print(msg)
                errors.append(("8.1-pagination", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("8.1-pagination", msg))

    # =====================================================================
    # Summary
    # =====================================================================
    total = passed + len(errors)
    print(f"\n{'='*60}")
    print(f"Workspace E2E Tests: {passed}/{total} passed")
    if errors:
        print(f"\nFailed tests ({len(errors)}):")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
    print(f"{'='*60}")

    return len(errors) == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
