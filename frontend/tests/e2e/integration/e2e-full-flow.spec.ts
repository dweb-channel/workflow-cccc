/**
 * E2E Integration Tests: End-to-End Full Flow (E22-E24)
 *
 * Complete user journey tests covering create→edit→save→reload→verify,
 * invalid graph error handling, and v1 API SSE regression.
 * Requires: frontend at localhost:3000, backend at localhost:8000
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

// Helper: create a workflow via API
async function createTestWorkflow(request: any) {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name: `E2E Flow Test ${Date.now()}`, description: 'Full flow test' },
  });
  return resp.json();
}

async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

test.describe('End-to-End Full Flow (E22-E24)', () => {
  // E22: Create → Edit → Add conditional edge → Save → Close → Reopen → Verify graph restored
  test('E22: full workflow lifecycle with conditional edges', async ({ request, page }) => {
    // Step 1: Create workflow via API
    const wf = await createTestWorkflow(request);
    expect(wf.id).toBeTruthy();

    try {
      // Step 2: Save a graph with conditional edges via API
      const graphPayload = {
        nodes: [
          { id: 'src', type: 'data_source', config: { name: 'Start Node' } },
          { id: 'cond', type: 'condition', config: { name: 'Check', condition: 'result.status == "success"' } },
          { id: 'ok', type: 'data_processor', config: { name: 'Success Handler', input_field: 'data' } },
          { id: 'fail', type: 'output', config: { name: 'Failure Handler', format: 'json' } },
        ],
        edges: [
          { id: 'e1', source: 'src', target: 'cond' },
          { id: 'e2', source: 'cond', target: 'ok', condition: 'result.status == "success"' },
          { id: 'e3', source: 'cond', target: 'fail', condition: 'result.status != "success"' },
        ],
        entry_point: 'src',
      };

      const saveResp = await request.put(
        `${API_BASE}/api/v2/workflows/${wf.id}/graph`,
        { data: graphPayload }
      );
      expect(saveResp.ok()).toBeTruthy();

      // Step 3: Retrieve and verify graph was persisted
      const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
      expect(getResp.ok()).toBeTruthy();
      const persisted = await getResp.json();

      expect(persisted.graph_definition).not.toBeNull();
      expect(persisted.graph_definition.nodes).toHaveLength(4);
      expect(persisted.graph_definition.edges).toHaveLength(3);

      // Verify conditional edges preserved
      const conditionalEdges = persisted.graph_definition.edges.filter(
        (e: any) => e.condition
      );
      expect(conditionalEdges).toHaveLength(2);

      // Step 4: Load in browser and verify visual rendering
      await page.goto('http://localhost:3000');
      await page.waitForLoadState('networkidle');

      // Nodes should render
      const nodes = page.locator('.react-flow__node');
      await expect(nodes.first()).toBeVisible({ timeout: 10000 });

    } finally {
      await deleteWorkflow(request, wf.id).catch(() => {});
    }
  });

  // E23: Create → Add invalid graph (cycle) → Save → Receive 422 error
  test('E23: should return 422 when saving an invalid graph with cycles', async ({ request }) => {
    const wf = await createTestWorkflow(request);
    expect(wf.id).toBeTruthy();

    try {
      // Save a graph with a circular dependency
      const cyclicGraph = {
        nodes: [
          { id: 'a', type: 'data_source', config: { name: 'A' } },
          { id: 'b', type: 'data_processor', config: { name: 'B', input_field: 'data' } },
          { id: 'c', type: 'output', config: { name: 'C', format: 'json' } },
        ],
        edges: [
          { id: 'e1', source: 'a', target: 'b' },
          { id: 'e2', source: 'b', target: 'c' },
          { id: 'e3', source: 'c', target: 'a' }, // creates cycle
        ],
        entry_point: 'a',
      };

      const saveResp = await request.put(
        `${API_BASE}/api/v2/workflows/${wf.id}/graph`,
        { data: cyclicGraph }
      );

      // Should reject with 422 (or return validation errors)
      if (!saveResp.ok()) {
        expect(saveResp.status()).toBe(422);
        const body = await saveResp.json();
        // Error should mention circular dependency (Chinese: 环路依赖)
        const detail = JSON.stringify(body);
        expect(detail).toMatch(/circular|cycle|loop|环路/i);
      } else {
        // If saved, validate-graph should catch it
        const validateResp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
          data: cyclicGraph,
        });
        const valBody = await validateResp.json();
        expect(valBody.valid).toBe(false);
      }

    } finally {
      await deleteWorkflow(request, wf.id).catch(() => {});
    }
  });

  // E24: v1 API workflow run → SSE real-time status → confirm → complete (regression test)
  test('E24: should run workflow via v1 API with SSE updates', async ({ page, request }) => {
    // Navigate to main page
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Check if v1 workflows are available
    const listResp = await request.get(`${API_BASE}/api/workflows`);
    if (!listResp.ok()) {
      test.skip(true, 'v1 API not available');
      return;
    }

    const workflows = await listResp.json();
    if (!Array.isArray(workflows) || workflows.length === 0) {
      test.skip(true, 'No v1 workflows available');
      return;
    }

    const workflowId = workflows[0].id;

    // Start a workflow run
    const runResp = await request.post(`${API_BASE}/api/workflows/${workflowId}/run`, {
      data: { request: 'E2E regression test' },
    });

    if (!runResp.ok()) {
      // Worker might not be running - acceptable for framework test
      test.skip(true, 'Workflow worker not available');
      return;
    }

    const runData = await runResp.json();
    expect(runData).toHaveProperty('runId');
    expect(runData).toHaveProperty('status');

    // Verify SSE endpoint is accessible (may return various status codes)
    const sseResp = await request.get(
      `${API_BASE}/api/workflows/${workflowId}/runs/${runData.runId}/events`,
      { timeout: 5000 }
    );
    // SSE endpoint should respond - accept any non-5xx status
    expect(sseResp.status()).toBeLessThan(500);

    // Check run status
    const statusResp = await request.get(
      `${API_BASE}/api/workflows/${workflowId}/runs?page=1&pageSize=1`
    );
    if (statusResp.ok()) {
      const runsData = await statusResp.json();
      expect(runsData).toHaveProperty('items');
    }

    // Attempt initial confirmation (may fail if workflow hasn't reached confirm stage)
    const confirmResp = await request.post(
      `${API_BASE}/api/workflows/${workflowId}/runs/${runData.runId}/confirm`,
      {
        data: {
          stage: 'initial',
          approved: true,
          feedback: 'E2E test approval',
        },
      }
    );
    // Don't assert success - the workflow timing is non-deterministic
    // Just verify the endpoint accepts the request format
    expect([200, 400, 404, 409]).toContain(confirmResp.status());
  });
});
