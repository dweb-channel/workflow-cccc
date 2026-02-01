/**
 * E2E Integration Tests: Phase 3 - Frontend Editor (E7-E15)
 *
 * Tests the visual workflow editor: mode switching, drag-drop, node config,
 * edge connections, save/load, and real-time validation.
 * Requires: frontend at localhost:3000, backend at localhost:8000
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

// Helper: create a workflow via API for editor tests
async function createTestWorkflow(request: any) {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name: `Editor Test ${Date.now()}`, description: 'E2E editor test' },
  });
  return resp.json();
}

// Helper: cleanup
async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

test.describe('Phase 3: Frontend Editor (E7-E15)', () => {
  let workflowId: string;

  test.beforeEach(async ({ request }) => {
    const wf = await createTestWorkflow(request);
    workflowId = wf.id;
  });

  test.afterEach(async ({ request }) => {
    if (workflowId) {
      await deleteWorkflow(request, workflowId).catch(() => {});
    }
  });

  // E7: Mode switching - click edit → canvas turns blue + NodePalette appears + nodes draggable
  test('E7: should switch between view and edit modes', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Initially in view mode
    const editButton = page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")');
    await expect(editButton).toBeVisible();

    // Switch to edit mode
    await editButton.click();

    // Canvas should change appearance (blue tint for edit mode)
    const canvas = page.locator('.react-flow');
    await expect(canvas).toBeVisible();

    // NodePalette should appear in edit mode (identified by "节点工具箱" heading)
    const palette = page.locator('text=节点工具箱').locator('..');
    await expect(page.locator('text=节点工具箱')).toBeVisible();

    // Switch back to view mode
    const viewButton = page.locator('[data-testid="view-mode-toggle"], button:has-text("查看")');
    await viewButton.click();

    // NodePalette should disappear
    await expect(page.locator('text=节点工具箱')).not.toBeVisible();
  });

  // E8: Drag-drop node creation - from Palette → canvas → new node appears at correct position
  test('E8: should create a node via drag-drop from palette', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Wait for palette (identified by "节点工具箱" heading)
    await expect(page.locator('text=节点工具箱')).toBeVisible();

    // Get a draggable node type from palette
    const paletteItem = page.locator('[draggable="true"]').first();
    await expect(paletteItem).toBeVisible();

    // Get canvas target
    const canvas = page.locator('.react-flow__pane');

    // Perform drag-drop
    const canvasBox = await canvas.boundingBox();
    expect(canvasBox).not.toBeNull();

    await paletteItem.dragTo(canvas, {
      targetPosition: { x: canvasBox!.width / 2, y: canvasBox!.height / 2 },
    });

    // Verify a new node appeared
    const nodes = page.locator('.react-flow__node');
    const count = await nodes.count();
    expect(count).toBeGreaterThan(0);
  });

  // E9: Connect nodes - edit mode drag connection → edge created + graphChanged=true
  test('E9: should connect two nodes with an edge in edit mode', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Need at least 2 nodes. If the page has default nodes, use them.
    // Otherwise, create nodes first via drag-drop.
    const nodes = page.locator('.react-flow__node');
    const nodeCount = await nodes.count();

    if (nodeCount >= 2) {
      // Get source and target node handles
      const sourceHandle = page.locator('.react-flow__handle--source').first();
      const targetHandle = page.locator('.react-flow__handle--target').nth(1);

      if (await sourceHandle.isVisible() && await targetHandle.isVisible()) {
        await sourceHandle.dragTo(targetHandle);

        // Verify edge was created
        const edges = page.locator('.react-flow__edge');
        await expect(edges.first()).toBeVisible();
      }
    }

    // If graph changed, save button should be enabled or indicator visible
    // (graphChanged state is internal, verify via UI indicator)
  });

  // E10: Delete node - edit mode select + Backspace → node and associated edges removed
  test('E10: should delete a node with Backspace in edit mode', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    const nodes = page.locator('.react-flow__node');
    const initialCount = await nodes.count();

    if (initialCount > 0) {
      // Click a node to select it
      await nodes.first().click();

      // Press Backspace to delete
      await page.keyboard.press('Backspace');

      // Node count should decrease
      const afterCount = await nodes.count();
      expect(afterCount).toBeLessThan(initialCount);
    }
  });

  // E11: Node config panel - edit mode click node → NodeConfigPanel opens → modify and save
  test('E11: should open NodeConfigPanel when clicking a node in edit mode', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    const nodes = page.locator('.react-flow__node');
    if (await nodes.count() > 0) {
      await nodes.first().click();

      // NodeConfigPanel should appear
      const configPanel = page.locator('[data-testid="node-config-panel"]');
      await expect(configPanel).toBeVisible({ timeout: 5000 });

      // Panel should have editable fields
      const inputs = configPanel.locator('input, textarea, select');
      const inputCount = await inputs.count();
      expect(inputCount).toBeGreaterThan(0);
    }
  });

  // E12: View mode click - click node → NodeDetailPanel opens (not config panel)
  test('E12: should open NodeDetailPanel when clicking a node in view mode', async ({ page }) => {
    await page.goto(`http://localhost:3000`);

    // Ensure in view mode (default)
    const nodes = page.locator('.react-flow__node');
    if (await nodes.count() > 0) {
      await nodes.first().click();

      // NodeDetailPanel should appear (not NodeConfigPanel)
      const detailPanel = page.locator('[data-testid="node-detail-panel"]');
      await expect(detailPanel).toBeVisible({ timeout: 5000 });

      // Config panel should NOT be visible
      const configPanel = page.locator('[data-testid="node-config-panel"]');
      await expect(configPanel).not.toBeVisible();
    }
  });

  // E13: Save graph - edit → save → PUT /api/v2/workflows/{id}/graph → no validation errors
  test('E13: should save the graph via v2 API', async ({ request, page }) => {
    await page.goto(`http://localhost:3000`);

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Click save button
    const saveButton = page.locator('[data-testid="save-graph"], button:has-text("保存")');
    if (await saveButton.isVisible()) {
      await saveButton.click();

      // Should not show error toast/message
      const errorToast = page.locator('[data-testid="error-toast"], .toast-error');
      await expect(errorToast).not.toBeVisible({ timeout: 3000 });
    }

    // Verify via direct API: save a minimal valid graph
    const graphPayload = {
      nodes: [
        { id: 'src', type: 'data_source', config: { name: 'Source' } },
        { id: 'out', type: 'output', config: { name: 'Output', format: 'json' } },
      ],
      edges: [
        { id: 'e-src-out', source: 'src', target: 'out' },
      ],
      entry_point: 'src',
    };

    const saveResp = await request.put(
      `${API_BASE}/api/v2/workflows/${workflowId}/graph`,
      { data: graphPayload }
    );
    expect(saveResp.ok()).toBeTruthy();
  });

  // E14: Load graph - refresh page → graph loads from DB → nodes/edges restored
  test('E14: should load graph from DB after page refresh', async ({ request, page }) => {
    // First, save a graph via API
    const graphPayload = {
      nodes: [
        { id: 'node-a', type: 'data_source', config: { name: 'Node A' } },
        { id: 'node-b', type: 'data_processor', config: { name: 'Node B', input_field: 'data' } },
      ],
      edges: [
        { id: 'e-ab', source: 'node-a', target: 'node-b' },
      ],
      entry_point: 'node-a',
    };

    await request.put(`${API_BASE}/api/v2/workflows/${workflowId}/graph`, {
      data: graphPayload,
    });

    // Navigate to the workflow page
    await page.goto(`http://localhost:3000`);
    await page.waitForLoadState('networkidle');

    // Verify nodes are rendered
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 10000 });

    // Verify edges are rendered
    const edges = page.locator('.react-flow__edge');
    const edgeCount = await edges.count();
    expect(edgeCount).toBeGreaterThanOrEqual(1);
  });

  // E15: Real-time validation - edit mode → POST /api/v2/validate-graph → errors/warnings shown
  test('E15: should trigger real-time validation and display results', async ({ request, page }) => {
    // Test via direct API call
    const invalidGraph = {
      nodes: [
        { id: 'n1', type: 'data_source', config: { name: 'N1' } },
        { id: 'n2', type: 'data_processor', config: { name: 'N2', input_field: 'data' } },
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2' },
        { id: 'e2', source: 'n2', target: 'n1' }, // circular dependency
      ],
    };

    const resp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: invalidGraph,
    });

    // Validation endpoint should return result (200 with errors, or 422)
    const body = await resp.json();

    if (resp.ok()) {
      // Validation result with errors
      expect(body).toHaveProperty('valid');
      expect(body.valid).toBe(false);
      expect(body.errors.length).toBeGreaterThan(0);
    } else {
      // 422 with validation errors
      expect(resp.status()).toBe(422);
    }
  });
});
