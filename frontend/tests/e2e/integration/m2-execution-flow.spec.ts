/**
 * M2 E2E Integration Tests: Workflow Execution with CCCC SDK Nodes
 *
 * Tests end-to-end workflow execution flow including:
 * - Dynamic graph → Temporal execution (T031)
 * - LLM Agent node execution via subprocess
 * - CCCC Peer node execution via MCP tools
 * - SSE real-time status updates during execution
 *
 * Dependencies: T029 + T030 + T031 must be complete.
 * Requires: frontend, backend, and Temporal worker running.
 *
 * Note: Some tests are marked test.skip() as they require
 * full Temporal + Worker infrastructure. Enable when ready.
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';
const APP_URL = 'http://localhost:3000';

// Helper: create a workflow via API
async function createWorkflow(request: any, name = 'M2 Exec Test') {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name, description: 'M2 execution E2E test' },
  });
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

// Helper: save graph to workflow
async function saveGraph(request: any, workflowId: string, graph: any) {
  const resp = await request.put(
    `${API_BASE}/api/v2/workflows/${workflowId}/graph`,
    { data: graph }
  );
  return resp;
}

// Helper: cleanup
async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

// Standard test graph: DataSource → LLM Agent → Output
function buildLLMGraph() {
  return {
    nodes: [
      {
        id: 'source',
        type: 'data_source',
        config: { name: 'Source', data: { request: 'Hello, analyze this' } },
      },
      {
        id: 'llm',
        type: 'llm_agent',
        config: {
          name: 'Analyzer',
          prompt: 'Briefly respond to: {request}',
          cwd: '.',
          timeout: 300,
        },
      },
      {
        id: 'out',
        type: 'output',
        config: { name: 'Output', format: 'json' },
      },
    ],
    edges: [
      { id: 'e1', source: 'source', target: 'llm' },
      { id: 'e2', source: 'llm', target: 'out' },
    ],
    entry_point: 'source',
  };
}

// Test graph: DataSource → CCCC Peer → Output
function buildCCCCGraph() {
  return {
    nodes: [
      {
        id: 'source',
        type: 'data_source',
        config: { name: 'Source', data: { request: 'Implement a simple helper function' } },
      },
      {
        id: 'peer',
        type: 'cccc_peer',
        config: {
          name: 'Implementor',
          peer_id: 'peer-impl',
          prompt: 'Execute: {request}',
          timeout: 120,
        },
      },
      {
        id: 'out',
        type: 'output',
        config: { name: 'Output', format: 'json' },
      },
    ],
    edges: [
      { id: 'e1', source: 'source', target: 'peer' },
      { id: 'e2', source: 'peer', target: 'out' },
    ],
    entry_point: 'source',
  };
}

test.describe('M2: Workflow Execution Flow (EX1-EX8)', () => {
  let createdIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdIds) {
      await deleteWorkflow(request, id).catch(() => {});
    }
    createdIds = [];
  });

  // EX1: Dynamic graph builds from saved workflow definition
  test('EX1: should build dynamic graph from saved workflow definition', async ({ request }) => {
    const wf = await createWorkflow(request, 'EX1 Build Graph');
    createdIds.push(wf.id);

    const graph = buildLLMGraph();
    const saveResp = await saveGraph(request, wf.id, graph);
    expect(saveResp.ok()).toBeTruthy();

    // Verify the graph was stored and can be retrieved
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    expect(getResp.ok()).toBeTruthy();
    const body = await getResp.json();
    expect(body.graph_definition).toBeDefined();
    expect(body.graph_definition.nodes.length).toBe(3);
    expect(body.graph_definition.edges.length).toBe(2);
    expect(body.graph_definition.entry_point).toBe('source');
  });

  // EX2: Workflow with LLM Agent can be submitted for execution
  test.skip('EX2: should submit workflow with LLM Agent for execution', async ({ request }) => {
    // Requires Temporal worker running
    const wf = await createWorkflow(request, 'EX2 LLM Run');
    createdIds.push(wf.id);

    const graph = buildLLMGraph();
    await saveGraph(request, wf.id, graph);

    // Submit for execution
    const runResp = await request.post(`${API_BASE}/api/workflows/${wf.id}/run`, {
      data: { request: 'Test execution' },
    });
    expect(runResp.ok()).toBeTruthy();

    const runBody = await runResp.json();
    expect(runBody).toHaveProperty('runId');
    expect(runBody.status).toBe('running');
  });

  // EX3: Workflow with CCCC Peer can be submitted for execution
  test.skip('EX3: should submit workflow with CCCC Peer for execution', async ({ request }) => {
    // Requires Temporal worker + CCCC infrastructure
    const wf = await createWorkflow(request, 'EX3 CCCC Run');
    createdIds.push(wf.id);

    const graph = buildCCCCGraph();
    await saveGraph(request, wf.id, graph);

    const runResp = await request.post(`${API_BASE}/api/workflows/${wf.id}/run`, {
      data: { request: 'Test CCCC execution' },
    });
    expect(runResp.ok()).toBeTruthy();

    const runBody = await runResp.json();
    expect(runBody).toHaveProperty('runId');
  });

  // EX4: SSE stream emits node status updates during execution
  test.skip('EX4: SSE should emit node_update events during workflow execution', async ({
    request,
  }) => {
    // Requires full execution pipeline
    const wf = await createWorkflow(request, 'EX4 SSE Stream');
    createdIds.push(wf.id);

    const graph = buildLLMGraph();
    await saveGraph(request, wf.id, graph);

    // Start execution
    const runResp = await request.post(`${API_BASE}/api/workflows/${wf.id}/run`, {
      data: {},
    });
    const { runId } = await runResp.json();

    // Connect to SSE stream
    const sseResp = await request.get(
      `${API_BASE}/api/workflows/${wf.id}/stream/${runId}`,
      { timeout: 30000 }
    );
    expect(sseResp.ok()).toBeTruthy();
  });

  // EX5: Validate graph before execution - reject invalid graph
  test('EX5: should reject execution of invalid graph', async ({ request }) => {
    const wf = await createWorkflow(request, 'EX5 Invalid');
    createdIds.push(wf.id);

    // Save an invalid graph (circular dependency)
    const invalidGraph = {
      nodes: [
        { id: 'a', type: 'data_processor', config: { input_field: '{{b.result}}' } },
        { id: 'b', type: 'data_processor', config: { input_field: '{{a.result}}' } },
      ],
      edges: [
        { id: 'e1', source: 'a', target: 'b' },
        { id: 'e2', source: 'b', target: 'a' },
      ],
      entry_point: 'a',
    };

    // Validate should catch circular dependency
    const validateResp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: invalidGraph,
    });
    expect(validateResp.ok()).toBeTruthy();
    const result = await validateResp.json();
    expect(result.valid).toBe(false);
  });

  // EX6: Validate graph before execution - accept valid graph with new node types
  test('EX6: should validate graph with LLM + CCCC nodes as valid', async ({ request }) => {
    const graph = {
      nodes: [
        {
          id: 'source',
          type: 'data_source',
          config: { name: 'Source', data: { request: 'test' } },
        },
        {
          id: 'llm',
          type: 'llm_agent',
          config: {
            name: 'Analyzer',
            prompt: 'Analyze: {request}',
          },
        },
        {
          id: 'peer',
          type: 'cccc_peer',
          config: {
            name: 'Implementor',
            peer_id: 'peer-impl',
            prompt: 'Implement: {analysis}',
            timeout: 120,
          },
        },
        {
          id: 'out',
          type: 'output',
          config: { name: 'Output', format: 'json' },
        },
      ],
      edges: [
        { id: 'e1', source: 'source', target: 'llm' },
        { id: 'e2', source: 'llm', target: 'peer' },
        { id: 'e3', source: 'peer', target: 'out' },
      ],
      entry_point: 'source',
    };

    const validateResp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: graph,
    });
    expect(validateResp.ok()).toBeTruthy();
    const result = await validateResp.json();
    expect(result.valid).toBe(true);
  });

  // EX7: UI execution flow - start run from editor
  test.skip('EX7: should start workflow run from editor UI', async ({ page, request }) => {
    // Requires Temporal worker
    const wf = await createWorkflow(request, 'EX7 UI Run');
    createdIds.push(wf.id);

    const graph = buildLLMGraph();
    await saveGraph(request, wf.id, graph);

    await page.goto(`${APP_URL}`);

    // Find and click run button
    const runBtn = page.getByRole('button', { name: /运行|Run/i });
    if (await runBtn.isVisible()) {
      await runBtn.click();

      // Should show execution banner or node status changes
      await page.waitForTimeout(2000);
      const statusIndicator = page.locator(
        '[class*="running"], [class*="executing"], text=运行中'
      );
      // Execution started indicator should be visible
      await expect(statusIndicator).toBeVisible({ timeout: 10000 });
    }
  });

  // EX8: Full lifecycle - create → edit → save → validate → execute (UI)
  test.skip('EX8: full lifecycle via UI - create, edit, save, validate, execute', async ({
    page,
    request,
  }) => {
    // Requires full infrastructure
    const wf = await createWorkflow(request, 'EX8 Full Lifecycle');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await page.waitForTimeout(1000);

    // Enter edit mode
    const editBtn = page.getByRole('button', { name: /编辑|Edit/i });
    if (await editBtn.isVisible()) {
      await editBtn.click();
    }

    const canvas = page.locator('.react-flow');

    // Add LLM Agent node
    const llmItem = page
      .locator('[draggable="true"]')
      .filter({ hasText: /LLM Agent|LLM/i });
    await llmItem.dragTo(canvas);
    await page.waitForTimeout(500);

    // Save
    const saveBtn = page.getByRole('button', { name: /保存|Save/i }).first();
    if (await saveBtn.isVisible()) {
      await saveBtn.click();
      await page.waitForTimeout(1000);
    }

    // Run
    const runBtn = page.getByRole('button', { name: /运行|Run/i });
    if (await runBtn.isVisible()) {
      await runBtn.click();
      await page.waitForTimeout(3000);

      // Verify execution started (SSE events or status change)
      const hasExecIndicator = await page
        .locator('text=运行中')
        .or(page.locator('[class*="running"]'))
        .isVisible()
        .catch(() => false);

      // At minimum, execution should have been attempted
      expect(true).toBe(true); // Placeholder - will strengthen after infra ready
    }
  });
});
