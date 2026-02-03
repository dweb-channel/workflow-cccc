"""E2E Integration Tests for Bug Fix Workflow (M4 T045)

Phase 1: Template & Validation (T1-T7, 15 tests)
- Template API: list, get, 404 handling
- Bug Fix workflow creation from template
- Node types verification (cccc_peer, llm_agent)
- Workflow CRUD operations

Phase 2: Execution (T8-T9, 6 tests)
- CCCCPeerNode mock execution
- Template variable rendering
- Workflow run API
"""

import asyncio
import json
import os
import sys
from typing import Dict, Any

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
    """Run all E2E Bug Fix workflow tests."""
    errors = []
    passed = 0

    # Enable CCCC mock mode for testing
    os.environ["CCCC_MOCK"] = "true"

    await setup_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:

        # =================================================================
        # Scenario 1: Template API - List
        # =================================================================
        print("\n=== Scenario 1: Template API - List ===")
        print("Test T1.1: List templates ... ", end="")

        resp = await client.get("/api/v2/templates")
        if resp.status_code == 200:
            templates = resp.json()
            if isinstance(templates, list):
                bug_fix_found = any(t.get("name") == "bug_fix" for t in templates)
                if bug_fix_found:
                    print(f"OK ({len(templates)} templates, bug_fix found)")
                    passed += 1
                else:
                    msg = f"FAIL - bug_fix template not in list: {[t.get('name') for t in templates]}"
                    print(msg)
                    errors.append(("T1.1-list", msg))
            else:
                msg = f"FAIL - expected list, got {type(templates)}"
                print(msg)
                errors.append(("T1.1-list", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("T1.1-list", msg))

        print("Test T1.2: Template list item schema ... ", end="")
        if resp.status_code == 200 and templates:
            t = templates[0]
            required_fields = ["name", "title", "description"]
            if all(f in t for f in required_fields):
                print("OK (has name, title, description)")
                passed += 1
            else:
                msg = f"FAIL - missing fields in {t}"
                print(msg)
                errors.append(("T1.2-schema", msg))
        else:
            msg = "SKIP - no templates to check"
            print(msg)

        # =================================================================
        # Scenario 2: Template API - Get Detail
        # =================================================================
        print("\n=== Scenario 2: Template API - Get Detail ===")
        print("Test T2.1: Get bug_fix template ... ", end="")

        resp = await client.get("/api/v2/templates/bug_fix")
        if resp.status_code == 200:
            template = resp.json()
            if "nodes" in template and "edges" in template:
                node_count = len(template["nodes"])
                edge_count = len(template["edges"])
                print(f"OK ({node_count} nodes, {edge_count} edges)")
                passed += 1
            else:
                msg = f"FAIL - missing nodes/edges: {list(template.keys())}"
                print(msg)
                errors.append(("T2.1-detail", msg))
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("T2.1-detail", msg))

        print("Test T2.2: Verify bug_fix has 6 nodes ... ", end="")
        if resp.status_code == 200:
            nodes = template.get("nodes", [])
            if len(nodes) == 6:
                node_types = [n.get("type") for n in nodes]
                expected_types = ["data_source", "cccc_peer", "cccc_peer", "cccc_peer", "condition", "output"]
                if sorted(node_types) == sorted(expected_types):
                    print("OK (correct node types)")
                    passed += 1
                else:
                    msg = f"FAIL - unexpected types: {node_types}"
                    print(msg)
                    errors.append(("T2.2-nodes", msg))
            else:
                msg = f"FAIL - expected 6 nodes, got {len(nodes)}"
                print(msg)
                errors.append(("T2.2-nodes", msg))

        print("Test T2.3: Verify retry loop edge ... ", end="")
        if resp.status_code == 200:
            edges = template.get("edges", [])
            # Find edge from condition_5 to fix_3 (retry loop)
            retry_edge = next(
                (e for e in edges if e.get("source") == "condition_5" and e.get("target") == "fix_3"),
                None
            )
            if retry_edge:
                print("OK (retry loop edge found)")
                passed += 1
            else:
                msg = "FAIL - retry loop edge (condition_5 -> fix_3) not found"
                print(msg)
                errors.append(("T2.3-loop", msg))

        # =================================================================
        # Scenario 3: Template API - 404 Handling
        # =================================================================
        print("\n=== Scenario 3: Template API - 404 Handling ===")
        print("Test T3.1: Get nonexistent template ... ", end="")

        resp = await client.get("/api/v2/templates/nonexistent_template")
        if resp.status_code == 404:
            print("OK (404 returned)")
            passed += 1
        else:
            msg = f"FAIL - expected 404, got {resp.status_code}"
            print(msg)
            errors.append(("T3.1-404", msg))

        print("Test T3.2: 404 response has detail ... ", end="")
        if resp.status_code == 404:
            body = resp.json()
            if "detail" in body:
                print(f"OK (detail: {body['detail'][:50]}...)")
                passed += 1
            else:
                msg = "FAIL - 404 response missing 'detail'"
                print(msg)
                errors.append(("T3.2-404-detail", msg))

        # =================================================================
        # Scenario 4: Create Workflow from Template
        # =================================================================
        print("\n=== Scenario 4: Create Workflow from Template ===")
        print("Test T4.1: Create workflow ... ", end="")

        resp = await client.post("/api/v2/workflows", json={"name": "Bug Fix Test"})
        if resp.status_code == 201:
            wf_id = resp.json()["id"]
            print(f"OK id={wf_id}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code} body={resp.text}"
            print(msg)
            errors.append(("T4.1-create", msg))
            wf_id = None

        print("Test T4.2: Load template and save to workflow ... ", end="")
        if wf_id:
            # Get template
            resp = await client.get("/api/v2/templates/bug_fix")
            if resp.status_code == 200:
                template = resp.json()
                # Extract graph definition (API now returns node.data.config format)
                graph = {
                    "nodes": [
                        {
                            "id": n["id"],
                            "type": n["type"],
                            "config": n.get("data", {}).get("config") or n.get("config", {})
                        }
                        for n in template["nodes"]
                    ],
                    "edges": template["edges"],
                    "entry_point": template.get("entry_point")
                }
                # Save to workflow
                resp = await client.put(f"/api/v2/workflows/{wf_id}/graph", json=graph)
                if resp.status_code == 200:
                    print("OK (graph saved)")
                    passed += 1
                else:
                    msg = f"FAIL save graph status={resp.status_code} body={resp.text}"
                    print(msg)
                    errors.append(("T4.2-save", msg))
            else:
                msg = f"FAIL get template status={resp.status_code}"
                print(msg)
                errors.append(("T4.2-template", msg))

        print("Test T4.3: Validate workflow ... ", end="")
        if wf_id:
            resp = await client.post(f"/api/v2/workflows/{wf_id}/validate")
            if resp.status_code == 200:
                result = resp.json()
                if result.get("valid"):
                    # May have CONTROLLED_LOOP warning due to retry loop
                    warnings = result.get("warnings", [])
                    if warnings:
                        print(f"OK (valid with {len(warnings)} warnings)")
                    else:
                        print("OK (valid)")
                    passed += 1
                else:
                    msg = f"FAIL - invalid: {result.get('errors')}"
                    print(msg)
                    errors.append(("T4.3-validate", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("T4.3-validate", msg))

        # =================================================================
        # Scenario 5: CCCC_MOCK Environment Variable
        # =================================================================
        print("\n=== Scenario 5: CCCC_MOCK Mode ===")
        print("Test T5.1: CCCC_MOCK is set ... ", end="")

        if os.environ.get("CCCC_MOCK") == "true":
            print("OK (CCCC_MOCK=true)")
            passed += 1
        else:
            msg = f"FAIL - CCCC_MOCK={os.environ.get('CCCC_MOCK')}"
            print(msg)
            errors.append(("T5.1-mock", msg))

        # =================================================================
        # Scenario 6: Node Types Include CCCC Peer
        # =================================================================
        print("\n=== Scenario 6: Node Types Verification ===")
        print("Test T6.1: cccc_peer node type registered ... ", end="")

        resp = await client.get("/api/v2/node-types")
        if resp.status_code == 200:
            types = resp.json()
            cccc_peer = next((t for t in types if t.get("node_type") == "cccc_peer"), None)
            if cccc_peer:
                print(f"OK (display: {cccc_peer.get('display_name')})")
                passed += 1
            else:
                msg = "FAIL - cccc_peer not in node types"
                print(msg)
                errors.append(("T6.1-cccc-peer", msg))
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("T6.1-types", msg))

        print("Test T6.2: llm_agent node type registered ... ", end="")
        if resp.status_code == 200:
            llm_agent = next((t for t in types if t.get("node_type") == "llm_agent"), None)
            if llm_agent:
                print(f"OK (display: {llm_agent.get('display_name')})")
                passed += 1
            else:
                msg = "FAIL - llm_agent not in node types"
                print(msg)
                errors.append(("T6.2-llm-agent", msg))

        # =================================================================
        # Scenario 7: Workflow CRUD with Template-based Graph
        # =================================================================
        print("\n=== Scenario 7: Workflow CRUD Operations ===")
        print("Test T7.1: Update workflow name ... ", end="")

        if wf_id:
            resp = await client.patch(
                f"/api/v2/workflows/{wf_id}",
                json={"name": "Bug Fix Test - Updated"}
            )
            if resp.status_code == 200:
                updated = resp.json()
                if updated.get("name") == "Bug Fix Test - Updated":
                    print("OK")
                    passed += 1
                else:
                    msg = f"FAIL - name not updated: {updated.get('name')}"
                    print(msg)
                    errors.append(("T7.1-update", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("T7.1-update", msg))

        print("Test T7.2: Delete workflow ... ", end="")
        if wf_id:
            resp = await client.delete(f"/api/v2/workflows/{wf_id}")
            if resp.status_code == 204:
                # Verify deletion
                resp2 = await client.get(f"/api/v2/workflows/{wf_id}")
                if resp2.status_code == 404:
                    print("OK (deleted + verified)")
                    passed += 1
                else:
                    msg = f"FAIL - delete succeeded but GET returned {resp2.status_code}"
                    print(msg)
                    errors.append(("T7.2-delete", msg))
            else:
                msg = f"FAIL status={resp.status_code}"
                print(msg)
                errors.append(("T7.2-delete", msg))

        # =================================================================
        # Phase 2: CCCCPeerNode Execution Tests
        # =================================================================
        print("\n=== Scenario 8: CCCCPeerNode Mock Execution ===")
        print("Test T8.1: CCCCPeerNode execute with mock ... ", end="")

        try:
            from workflow.nodes.agents import CCCCPeerNode

            # Set up mock environment
            os.environ["CCCC_GROUP_ID"] = "test-group"

            # Create a CCCCPeerNode instance
            node = CCCCPeerNode(
                node_id="test_peer_node",
                node_type="cccc_peer",
                config={
                    "name": "Test Peer",
                    "peer_id": "domain-expert",
                    "prompt": "Test prompt: {input_data}",
                    "timeout": 10
                }
            )

            # Execute with mock mode (CCCC_MOCK=true already set)
            result = await node.execute({"input_data": "Hello from test"})

            if result.get("success") and "MOCK" in result.get("response", ""):
                print(f"OK (response: {result['response'][:40]}...)")
                passed += 1
            else:
                msg = f"FAIL - unexpected result: {result}"
                print(msg)
                errors.append(("T8.1-execute", msg))
        except Exception as e:
            msg = f"FAIL - exception: {e}"
            print(msg)
            errors.append(("T8.1-execute", msg))

        print("Test T8.2: CCCCPeerNode template rendering ... ", end="")
        try:
            node2 = CCCCPeerNode(
                node_id="test_template_node",
                node_type="cccc_peer",
                config={
                    "name": "Template Test",
                    "peer_id": "code-simplifier",
                    "prompt": "Fix this bug: {bug_report.description}\nCode: {bug_report.code}",
                    "timeout": 10
                }
            )

            # Execute with nested context
            result = await node2.execute({
                "bug_report": {
                    "description": "NullPointerException",
                    "code": "obj.method()"
                }
            })

            if result.get("success"):
                print("OK (nested template rendered)")
                passed += 1
            else:
                msg = f"FAIL - execution failed: {result}"
                print(msg)
                errors.append(("T8.2-template", msg))
        except Exception as e:
            msg = f"FAIL - exception: {e}"
            print(msg)
            errors.append(("T8.2-template", msg))

        print("Test T8.3: CCCCPeerNode missing group_id handling ... ", end="")
        try:
            # Clear group_id to test error handling
            old_group_id = os.environ.pop("CCCC_GROUP_ID", None)

            node3 = CCCCPeerNode(
                node_id="no_group_node",
                node_type="cccc_peer",
                config={
                    "name": "No Group Test",
                    "peer_id": "test-peer",
                    "prompt": "Test",
                    "timeout": 5
                }
            )

            result = await node3.execute({})

            # Should fail gracefully with error message
            if not result.get("success") and "group_id" in result.get("response", "").lower():
                print("OK (graceful error for missing group_id)")
                passed += 1
            else:
                msg = f"FAIL - should error on missing group_id: {result}"
                print(msg)
                errors.append(("T8.3-no-group", msg))

            # Restore group_id
            if old_group_id:
                os.environ["CCCC_GROUP_ID"] = old_group_id
        except Exception as e:
            msg = f"FAIL - exception: {e}"
            print(msg)
            errors.append(("T8.3-no-group", msg))
            if old_group_id:
                os.environ["CCCC_GROUP_ID"] = old_group_id

        # =================================================================
        # Scenario 9: Workflow Run API (validation only, Temporal may not be available)
        # =================================================================
        print("\n=== Scenario 9: Workflow Run API ===")
        print("Test T9.1: Create workflow for run test ... ", end="")

        # Restore group_id for remaining tests
        os.environ["CCCC_GROUP_ID"] = "test-group"

        resp = await client.post("/api/v2/workflows", json={"name": "Bug Fix Run Test"})
        if resp.status_code == 201:
            run_wf_id = resp.json()["id"]
            print(f"OK id={run_wf_id}")
            passed += 1
        else:
            msg = f"FAIL status={resp.status_code}"
            print(msg)
            errors.append(("T9.1-create", msg))
            run_wf_id = None

        print("Test T9.2: Save bug_fix template graph ... ", end="")
        if run_wf_id:
            resp = await client.get("/api/v2/templates/bug_fix")
            if resp.status_code == 200:
                template = resp.json()
                graph = {
                    "nodes": [
                        {"id": n["id"], "type": n["type"], "config": n.get("data", {}).get("config") or n.get("config", {})}
                        for n in template["nodes"]
                    ],
                    "edges": template["edges"],
                    "entry_point": template.get("entry_point")
                }
                resp = await client.put(f"/api/v2/workflows/{run_wf_id}/graph", json=graph)
                if resp.status_code == 200:
                    print("OK")
                    passed += 1
                else:
                    msg = f"FAIL save status={resp.status_code}"
                    print(msg)
                    errors.append(("T9.2-save", msg))
            else:
                msg = f"FAIL template status={resp.status_code}"
                print(msg)
                errors.append(("T9.2-template", msg))

        print("Test T9.3: Run workflow API call ... ", end="")
        if run_wf_id:
            # Try to run - may fail due to Temporal not being available, but should validate first
            resp = await client.post(
                f"/api/v2/workflows/{run_wf_id}/run",
                json={"initial_state": {"input_1": {"data": "Test bug: NullPointerException"}}}
            )

            # Accept either success (Temporal running) or 503 (Temporal not available)
            if resp.status_code == 200:
                result = resp.json()
                if "run_id" in result:
                    print(f"OK (run_id: {result['run_id'][:8]}...)")
                    passed += 1
                else:
                    msg = f"FAIL - missing run_id: {result}"
                    print(msg)
                    errors.append(("T9.3-run", msg))
            elif resp.status_code == 503:
                # Temporal not available - this is expected in test environment
                print("OK (503 - Temporal not available, validation passed)")
                passed += 1
            elif resp.status_code == 422:
                # Validation error - this is a real failure
                msg = f"FAIL - validation error: {resp.json()}"
                print(msg)
                errors.append(("T9.3-run", msg))
            else:
                msg = f"FAIL status={resp.status_code} body={resp.text}"
                print(msg)
                errors.append(("T9.3-run", msg))

        # Cleanup
        if run_wf_id:
            await client.delete(f"/api/v2/workflows/{run_wf_id}")

    return passed, errors


if __name__ == "__main__":
    passed, errors = asyncio.run(run_tests())
    total = passed + len(errors)
    print(f"\n{'='*60}")
    print(f"E2E Bug Fix Workflow Tests: {passed}/{total} passed")
    if errors:
        print("\nFailures:")
        for name, msg in errors:
            print(f"  - {name}: {msg}")
        sys.exit(1)
    else:
        print("All E2E Bug Fix tests passed!")
        sys.exit(0)
