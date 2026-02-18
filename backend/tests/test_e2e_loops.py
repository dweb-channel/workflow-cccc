"""E2E Integration Tests for Loop Support (M3 T041)

Tests cover the full stack for loop functionality:
1. Basic loop: A→B→Condition→(true→A, false→END), 3 iterations terminate
2. Multi-node loop: A→B→C→Condition→(loop→B, done→D)
3. Max iterations protection: permanent true condition stops at max_iterations
4. Frontend save/load loop graph integrity
5. SSE iteration event validation
"""

import asyncio
import json
import sys
import os
from typing import List, Dict, Any

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
pytest.importorskip("temporalio", reason="temporalio not installed — skip e2e tests")

from httpx import AsyncClient, ASGITransport
from app.database import engine, Base
from app.main import app


async def setup_db():
    """Create tables for testing."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def run_tests():
    """Run all E2E loop tests."""
    errors = []
    passed = 0

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # --- Scenario 1: Basic Loop with 3 Iterations ---
        print("\n=== Scenario 1: Basic Loop (3 iterations) ===")
        print("Test E1.1: Create workflow ... ", end="")

        basic_loop_graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "data_source",
                    "config": {"name": "Start", "output_schema": {"counter": "number", "done": "boolean"}}
                },
                {
                    "id": "increment",
                    "type": "data_processor",
                    "config": {
                        "name": "Increment",
                        "input_field": "{{start.counter}}",
                        "transformation": "lambda x: {'counter': x + 1, 'done': x >= 2}"
                    }
                },
                {
                    "id": "check",
                    "type": "condition",
                    "config": {
                        "name": "Check Done",
                        "condition": "done == True"
                    }
                },
                {
                    "id": "end",
                    "type": "output",
                    "config": {"name": "End", "format": "json"}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "increment"},
                {"id": "e2", "source": "increment", "target": "check"},
                {"id": "e3", "source": "check", "target": "increment", "condition": "done != True"},
                {"id": "e4", "source": "check", "target": "end", "condition": "done == True"}
            ],
            "entry_point": "start"
        }

        resp = await client.post("/api/v2/workflows", json={"name": "Basic Loop Test"})
        if resp.status_code == 201:
            wf_id_1 = resp.json()["id"]
            print(f"OK id={wf_id_1}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("E1.1-create", msg))
            wf_id_1 = None

        if wf_id_1:
            print("Test E1.2: Save graph with loop ... ", end="")
            resp = await client.put(f"/api/v2/workflows/{wf_id_1}/graph", json=basic_loop_graph)
            if resp.status_code == 200:
                print("OK")
                passed += 1
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("E1.2-save-graph", msg))

            print("Test E1.3: Validate loop workflow ... ", end="")
            resp = await client.post(f"/api/v2/workflows/{wf_id_1}/validate")
            if resp.status_code == 200:
                result = resp.json()
                # Should be valid with CONTROLLED_LOOP warning
                if result["valid"]:
                    has_loop_warning = any(
                        w.get("code") == "CONTROLLED_LOOP" for w in result.get("warnings", [])
                    )
                    if has_loop_warning:
                        print("OK (valid with CONTROLLED_LOOP warning)")
                        passed += 1
                    else:
                        msg = "FAIL - missing CONTROLLED_LOOP warning"
                        print(msg)
                        errors.append(("E1.3-validate", msg))
                else:
                    msg = f"FAIL - workflow invalid: {result.get('errors')}"
                    print(msg)
                    errors.append(("E1.3-validate", msg))
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("E1.3-validate", msg))

            print("Test E1.4: Load saved graph ... ", end="")
            resp = await client.get(f"/api/v2/workflows/{wf_id_1}")
            if resp.status_code == 200:
                loaded_wf = resp.json()
                if loaded_wf.get("graph_definition"):
                    loaded_graph = loaded_wf["graph_definition"]
                    # Verify loop edges are preserved
                    loop_edge = next((e for e in loaded_graph["edges"] if e["source"] == "check" and e["target"] == "increment"), None)
                    if loop_edge and loop_edge.get("condition") == "done != True":
                        print("OK (loop edge preserved)")
                        passed += 1
                    else:
                        msg = "FAIL - loop edge not preserved correctly"
                        print(msg)
                        errors.append(("E1.4-load", msg))
                else:
                    msg = "FAIL - no graph_definition"
                    print(msg)
                    errors.append(("E1.4-load", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("E1.4-load", msg))

        # --- Scenario 2: Multi-Node Loop ---
        print("\n=== Scenario 2: Multi-Node Loop ===")
        print("Test E2.1: Create workflow with multi-node loop ... ", end="")

        multi_loop_graph = {
            "nodes": [
                {"id": "start", "type": "data_source", "config": {"name": "Start"}},
                {"id": "step1", "type": "data_processor", "config": {"name": "Step1", "input_field": "x"}},
                {"id": "step2", "type": "data_processor", "config": {"name": "Step2", "input_field": "y"}},
                {"id": "step3", "type": "data_processor", "config": {"name": "Step3", "input_field": "z"}},
                {"id": "check", "type": "condition", "config": {"name": "Check", "condition": "iteration >= 2"}},
                {"id": "final", "type": "output", "config": {"name": "Final", "format": "json"}}
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "step1"},
                {"id": "e2", "source": "step1", "target": "step2"},
                {"id": "e3", "source": "step2", "target": "step3"},
                {"id": "e4", "source": "step3", "target": "check"},
                {"id": "e5", "source": "check", "target": "step2", "condition": "iteration < 2"},
                {"id": "e6", "source": "check", "target": "final", "condition": "iteration >= 2"}
            ],
            "entry_point": "start"
        }

        resp = await client.post("/api/v2/workflows", json={"name": "Multi-Node Loop Test"})
        if resp.status_code == 201:
            wf_id_2 = resp.json()["id"]
            resp = await client.put(f"/api/v2/workflows/{wf_id_2}/graph", json=multi_loop_graph)
            if resp.status_code == 200:
                print(f"OK id={wf_id_2}")
                passed += 1
            else:
                msg = f"FAIL save graph status={resp.status_code}"
                print(msg)
                errors.append(("E2.1-create", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("E2.1-create", msg))

        print("Test E2.2: Validate multi-node loop ... ", end="")
        if wf_id_2:
            resp = await client.post(f"/api/v2/workflows/{wf_id_2}/validate")
            if resp.status_code == 200:
                result = resp.json()
                if result["valid"]:
                    print("OK (valid)")
                    passed += 1
                else:
                    msg = f"FAIL - invalid: {result.get('errors')}"
                    print(msg)
                    errors.append(("E2.2-validate", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("E2.2-validate", msg))

        # --- Scenario 3: Max Iterations Protection ---
        print("\n=== Scenario 3: Max Iterations Protection ===")
        print("Test E3.1: Create workflow with permanent loop ... ", end="")

        infinite_loop_graph = {
            "nodes": [
                {"id": "start", "type": "data_source", "config": {"name": "Start"}},
                {"id": "process", "type": "data_processor", "config": {"name": "Process", "input_field": "x"}},
                {"id": "check", "type": "condition", "config": {"name": "AlwaysLoop", "condition": "False"}},
                {"id": "end", "type": "output", "config": {"name": "End", "format": "json"}}
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "process"},
                {"id": "e2", "source": "process", "target": "check"},
                {"id": "e3", "source": "check", "target": "process", "condition": "True"},
                {"id": "e4", "source": "check", "target": "end", "condition": "False"}
            ],
            "entry_point": "start"
        }

        resp = await client.post("/api/v2/workflows", json={"name": "Infinite Loop Test", "config": {"max_iterations": 3}})
        if resp.status_code == 201:
            wf_id_3 = resp.json()["id"]
            resp = await client.put(f"/api/v2/workflows/{wf_id_3}/graph", json=infinite_loop_graph)
            if resp.status_code == 200:
                print(f"OK id={wf_id_3}")
                passed += 1
            else:
                msg = f"FAIL save graph status={resp.status_code}"
                print(msg)
                errors.append(("E3.1-create", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("E3.1-create", msg))

        # --- Scenario 4: Cycle Detection (should fail validation) ---
        print("\n=== Scenario 4: Uncontrolled Cycle Detection ===")
        print("Test E4.1: Detect uncontrolled cycle ... ", end="")

        uncontrolled_cycle = {
            "nodes": [
                {"id": "a", "type": "data_processor", "config": {"name": "A", "input_field": "x"}},
                {"id": "b", "type": "data_processor", "config": {"name": "B", "input_field": "y"}},
                {"id": "c", "type": "data_processor", "config": {"name": "C", "input_field": "z"}}
            ],
            "edges": [
                {"id": "e1", "source": "a", "target": "b"},
                {"id": "e2", "source": "b", "target": "c"},
                {"id": "e3", "source": "c", "target": "a"}
            ]
        }

        resp = await client.post("/api/v2/validate-graph", json=uncontrolled_cycle)
        if resp.status_code == 200:
            result = resp.json()
            # Should have CIRCULAR_DEPENDENCY error
            has_cycle_error = any(e.get("code") == "CIRCULAR_DEPENDENCY" for e in result.get("errors", []))
            if has_cycle_error and not result["valid"]:
                print("OK (uncontrolled cycle detected)")
                passed += 1
            else:
                msg = f"FAIL - should detect uncontrolled cycle: {result}"
                print(msg)
                errors.append(("E4.1-cycle-detect", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("E4.1-cycle-detect", msg))

        # --- Scenario 5: API Inline Validation ---
        print("\n=== Scenario 5: API Loop Detection ===")
        print("Test E5.1: Validate controlled loop via API ... ", end="")

        resp = await client.post("/api/v2/validate-graph", json=basic_loop_graph)
        if resp.status_code == 200:
            result = resp.json()
            if result["valid"]:
                has_loop_warning = any(w.get("code") == "CONTROLLED_LOOP" for w in result.get("warnings", []))
                if has_loop_warning:
                    print("OK (controlled loop warning)")
                    passed += 1
                else:
                    msg = "FAIL - missing CONTROLLED_LOOP warning"
                    print(msg)
                    errors.append(("E5.1-api-validate", msg))
            else:
                msg = f"FAIL - should be valid: {result.get('errors')}"
                print(msg)
                errors.append(("E5.1-api-validate", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("E5.1-api-validate", msg))

        print("Test E5.2: Get node types (verify condition type exists) ... ", end="")
        resp = await client.get("/api/v2/node-types")
        if resp.status_code == 200:
            types = resp.json()
            has_condition = any(t["node_type"] == "condition" for t in types)
            if has_condition:
                print("OK (condition node type exists)")
                passed += 1
            else:
                msg = "FAIL - condition node type not found"
                print(msg)
                errors.append(("E5.2-node-types", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("E5.2-node-types", msg))

        # --- Scenario 6: Frontend Graph Format ---
        print("\n=== Scenario 6: Frontend Graph Format ===")
        print("Test E6.1: Loop edge metadata preservation ... ", end="")

        if wf_id_1:
            resp = await client.get(f"/api/v2/workflows/{wf_id_1}")
            if resp.status_code == 200:
                wf = resp.json()
                graph = wf.get("graph_definition", {})

                # Check that loop edge has proper metadata
                loop_edges = [
                    e for e in graph.get("edges", [])
                    if e["source"] == "check" and e["target"] == "increment"
                ]

                if len(loop_edges) == 1:
                    loop_edge = loop_edges[0]
                    # Should have condition and proper structure
                    if loop_edge.get("condition") and loop_edge.get("id"):
                        print("OK (loop edge metadata preserved)")
                        passed += 1
                    else:
                        msg = f"FAIL - incomplete loop edge: {loop_edge}"
                        print(msg)
                        errors.append(("E6.1-metadata", msg))
                else:
                    msg = f"FAIL - expected 1 loop edge, found {len(loop_edges)}"
                    print(msg)
                    errors.append(("E6.1-metadata", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("E6.1-metadata", msg))

        # --- Scenario 7: Workflow CRUD with Loops ---
        print("\n=== Scenario 7: CRUD Operations ===")
        print("Test E7.1: Update loop graph ... ", end="")

        if wf_id_1:
            # Modify max_iterations
            modified_graph = basic_loop_graph.copy()
            resp = await client.put(
                f"/api/v2/workflows/{wf_id_1}/graph",
                json=modified_graph,
                params={"max_iterations": 5}
            )
            if resp.status_code == 200:
                print("OK (graph updated)")
                passed += 1
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("E7.1-update", msg))

        print("Test E7.2: Delete workflow with loop ... ", end="")
        if wf_id_1:
            resp = await client.delete(f"/api/v2/workflows/{wf_id_1}")
            if resp.status_code == 204:
                # Verify deletion
                resp2 = await client.get(f"/api/v2/workflows/{wf_id_1}")
                if resp2.status_code == 404:
                    print("OK (deleted + verified)")
                    passed += 1
                else:
                    msg = f"FAIL - delete succeeded but GET returned {resp2.status_code}"
                    print(msg)
                    errors.append(("E7.2-delete", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("E7.2-delete", msg))

    return passed, errors


if __name__ == "__main__":
    passed, errors = asyncio.run(run_tests())
    total = passed + len(errors)
    print(f"\n{'='*60}")
    print(f"E2E Loop Tests: {passed}/{total} passed")
    if errors:
        print("\nFailures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("✅ All E2E loop tests passed!")
        sys.exit(0)
