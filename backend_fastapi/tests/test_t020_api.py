"""Integration tests for T020: Repository layer & API endpoints.

Tests the v2 dynamic workflow API endpoints using httpx + FastAPI TestClient.
"""

import asyncio
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from httpx import AsyncClient, ASGITransport
from app.database import engine, Base
from app.main import app


async def setup_db():
    """Create tables for testing."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def run_tests():
    errors = []
    passed = 0

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:

        # --- Test 1: GET /api/v2/node-types ---
        print("Test 1: GET /api/v2/node-types ... ", end="")
        resp = await client.get("/api/v2/node-types")
        if resp.status_code == 200 and isinstance(resp.json(), list):
            print(f"OK ({len(resp.json())} types)")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("node-types", msg))

        # --- Test 2: POST /api/v2/workflows (create) ---
        print("Test 2: POST /api/v2/workflows ... ", end="")
        create_payload = {
            "name": "测试工作流",
            "description": "集成测试用",
        }
        resp = await client.post("/api/v2/workflows", json=create_payload)
        if resp.status_code == 201:
            wf = resp.json()
            wf_id = wf["id"]
            assert wf["name"] == "测试工作流"
            assert wf["status"] == "draft"
            print(f"OK id={wf_id}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("create", msg))
            wf_id = None

        if not wf_id:
            print("Skipping remaining tests (create failed)")
            return passed, errors

        # --- Test 3: GET /api/v2/workflows (list) ---
        print("Test 3: GET /api/v2/workflows ... ", end="")
        resp = await client.get("/api/v2/workflows")
        if resp.status_code == 200 and resp.json()["total"] >= 1:
            print(f"OK total={resp.json()['total']}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("list", msg))

        # --- Test 4: GET /api/v2/workflows/{id} ---
        print("Test 4: GET /api/v2/workflows/{id} ... ", end="")
        resp = await client.get(f"/api/v2/workflows/{wf_id}")
        if resp.status_code == 200 and resp.json()["id"] == wf_id:
            print("OK")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("get", msg))

        # --- Test 5: PATCH /api/v2/workflows/{id} ---
        print("Test 5: PATCH /api/v2/workflows/{id} ... ", end="")
        resp = await client.patch(
            f"/api/v2/workflows/{wf_id}",
            json={"name": "更新后的名称", "status": "published"},
        )
        if resp.status_code == 200 and resp.json()["name"] == "更新后的名称":
            print("OK")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("patch", msg))

        # --- Test 6: PUT /api/v2/workflows/{id}/graph (with valid graph) ---
        print("Test 6: PUT /api/v2/workflows/{id}/graph ... ", end="")
        graph_payload = {
            "nodes": [
                {"id": "node-1", "type": "claude_agent", "config": {"prompt": "test"}},
                {"id": "node-2", "type": "claude_agent", "config": {"prompt": "test2"}},
            ],
            "edges": [
                {"id": "e1", "source": "node-1", "target": "node-2"},
            ],
            "entry_point": "node-1",
        }
        resp = await client.put(
            f"/api/v2/workflows/{wf_id}/graph",
            json=graph_payload,
        )
        if resp.status_code == 200 and resp.json()["graph_definition"] is not None:
            print("OK")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("put-graph", msg))

        # --- Test 7: POST /api/v2/workflows/{id}/validate ---
        print("Test 7: POST /api/v2/workflows/{id}/validate ... ", end="")
        resp = await client.post(f"/api/v2/workflows/{wf_id}/validate")
        if resp.status_code == 200 and "valid" in resp.json():
            v = resp.json()
            print(f"OK valid={v['valid']} errors={len(v['errors'])} warnings={len(v['warnings'])}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("validate", msg))

        # --- Test 8: POST /api/v2/validate-graph (inline, with cycle) ---
        print("Test 8: POST /api/v2/validate-graph (cycle detection) ... ", end="")
        cyclic_graph = {
            "nodes": [
                {"id": "a", "type": "claude_agent", "config": {}},
                {"id": "b", "type": "claude_agent", "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "b"},
                {"id": "e2", "source": "b", "target": "a"},
            ],
        }
        resp = await client.post("/api/v2/validate-graph", json=cyclic_graph)
        if resp.status_code == 200:
            v = resp.json()
            has_cycle_error = any(e["code"] == "CIRCULAR_DEPENDENCY" for e in v["errors"])
            if has_cycle_error:
                print("OK (cycle detected)")
                passed += 1
            else:
                msg = f"FAIL - no cycle error in {v['errors']}"
                print(msg)
                errors.append(("validate-cycle", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("validate-cycle", msg))

        # --- Test 9: GET /api/v2/workflows/nonexistent (404) ---
        print("Test 9: GET /api/v2/workflows/nonexistent ... ", end="")
        resp = await client.get("/api/v2/workflows/nonexistent-id")
        if resp.status_code == 404:
            print("OK (404)")
            passed += 1
        else:
            msg = f"FAIL expected 404, got {resp.status_code}"
            print(msg)
            errors.append(("404", msg))

        # --- Test 10: DELETE /api/v2/workflows/{id} ---
        print("Test 10: DELETE /api/v2/workflows/{id} ... ", end="")
        resp = await client.delete(f"/api/v2/workflows/{wf_id}")
        if resp.status_code == 204:
            # Verify it's gone
            resp2 = await client.get(f"/api/v2/workflows/{wf_id}")
            if resp2.status_code == 404:
                print("OK (deleted + 404 confirmed)")
                passed += 1
            else:
                msg = f"FAIL - delete returned 204 but GET returned {resp2.status_code}"
                print(msg)
                errors.append(("delete-verify", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("delete", msg))

    return passed, errors


if __name__ == "__main__":
    passed, errors = asyncio.run(run_tests())
    total = passed + len(errors)
    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed")
    if errors:
        print("Failures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("All tests passed!")
        sys.exit(0)
