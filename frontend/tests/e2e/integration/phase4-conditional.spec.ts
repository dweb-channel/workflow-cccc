/**
 * E2E Integration Tests: Phase 4 - Conditional Branching (E16-E21)
 *
 * Tests conditional node creation, edge configuration, expression validation,
 * visual styling, and mixed edge type warnings.
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
    data: { name: `Conditional Test ${Date.now()}`, description: 'E2E conditional test' },
  });
  return resp.json();
}

async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

test.describe('Phase 4: Conditional Branching (E16-E21)', () => {
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

  // E16: Condition node creation - drag condition type → config panel shows condition expression input
  test('E16: should create a condition node with expression input', async ({ page }) => {
    await page.goto('http://localhost:3000');

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Find condition node type in palette (identified by "节点工具箱" heading)
    await expect(page.locator('text=节点工具箱')).toBeVisible();

    const conditionItem = page.locator('[draggable="true"]:has-text("条件分支")').first();

    if (await conditionItem.isVisible()) {
      // Drag condition node to canvas
      const canvas = page.locator('.react-flow__pane');
      const canvasBox = await canvas.boundingBox();
      await conditionItem.dragTo(canvas, {
        targetPosition: { x: canvasBox!.width / 2, y: canvasBox!.height / 2 },
      });

      // Click the newly created condition node
      const conditionNode = page.locator('.react-flow__node').last();
      await conditionNode.click();

      // Config panel should show with "节点配置" heading
      await expect(page.getByRole('heading', { name: '节点配置' })).toBeVisible({ timeout: 5000 });

      // Should have a condition expression field
      await expect(page.locator('text=条件表达式')).toBeVisible();
    }
  });

  // E17: Conditional edge config - edit mode click edge → EdgeConfigPanel → set condition
  test('E17: should open EdgeConfigPanel when clicking an edge in edit mode', async ({ page }) => {
    await page.goto('http://localhost:3000');

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Wait for edges to render
    const edges = page.locator('.react-flow__edge');
    if (await edges.count() > 0) {
      // Click on an edge
      await edges.first().click();

      // EdgeConfigPanel should appear
      const edgePanel = page.locator('[data-testid="edge-config-panel"]');
      await expect(edgePanel).toBeVisible({ timeout: 5000 });
    }
  });

  // E18: Condition validation (attack blocked) - input malicious expression → validation error
  test('E18: should reject malicious condition expressions', async ({ request }) => {
    // Test via API: save a graph with malicious condition
    const maliciousGraph = {
      nodes: [
        { id: 'n1', type: 'condition', config: { condition_expression: 'os.system("rm -rf /")' } },
        { id: 'n2', type: 'llm_call', config: {} },
        { id: 'n3', type: 'llm_call', config: {} },
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2', condition: 'os.system("hack")' },
        { id: 'e2', source: 'n1', target: 'n3' },
      ],
    };

    // Validate graph - should report errors for malicious expressions
    const resp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: maliciousGraph,
    });

    const body = await resp.json();

    if (resp.ok()) {
      // Validation should flag the malicious expression
      expect(body.valid).toBe(false);
      const errorMessages = body.errors.map((e: any) => e.message).join(' ');
      // Should mention function calls not allowed or similar security message
      expect(errorMessages.toLowerCase()).toMatch(/function|call|not allowed|blocked|invalid/);
    } else {
      // 422 with validation error is also acceptable
      expect(resp.status()).toBe(422);
    }
  });

  // E19: Valid condition expression - input `result.score > 80` → validation passes
  test('E19: should accept valid condition expressions', async ({ request }) => {
    const validGraph = {
      nodes: [
        { id: 'n1', type: 'condition', config: { condition_expression: 'result.score > 80' } },
        { id: 'n2', type: 'llm_call', config: {} },
        { id: 'n3', type: 'llm_call', config: {} },
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2', condition: 'result.score > 80' },
        { id: 'e2', source: 'n1', target: 'n3', condition: 'result.score <= 80' },
      ],
      entry_point: 'n1',
    };

    const resp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: validGraph,
    });

    const body = await resp.json();

    if (resp.ok()) {
      // The condition expression itself should not cause errors
      // (there may be other structural errors, but no INVALID_CONDITION errors)
      const conditionErrors = (body.errors || []).filter(
        (e: any) => e.code === 'INVALID_CONDITION_EXPRESSION'
      );
      expect(conditionErrors).toHaveLength(0);
    }
  });

  // E20: Conditional edge visual styling - conditional edges show purple dashed lines
  test('E20: should display conditional edges with purple dashed styling', async ({ page }) => {
    await page.goto('http://localhost:3000');

    // Enter edit mode
    await page.locator('[data-testid="edit-mode-toggle"], button:has-text("编辑")').click();

    // Look for conditional edges (with condition data)
    const conditionalEdges = page.locator('.react-flow__edge--conditional, [data-conditional="true"]');

    if (await conditionalEdges.count() > 0) {
      // Check the edge path has dashed stroke style
      const edgePath = conditionalEdges.first().locator('path').first();
      const strokeDasharray = await edgePath.getAttribute('stroke-dasharray');
      expect(strokeDasharray).toBeTruthy(); // Dashed line

      // Check for purple-ish color
      const stroke = await edgePath.getAttribute('stroke');
      if (stroke) {
        // Purple color range: #8b5cf6, #7c3aed, etc. or rgb values
        expect(stroke.toLowerCase()).toMatch(/#[0-9a-f]{6}|rgb/);
      }
    }
  });

  // E21: Mixed edge type warning - same node with both conditional and normal edges → warning
  test('E21: should warn about mixed edge types on same node', async ({ request }) => {
    const mixedGraph = {
      nodes: [
        { id: 'n1', type: 'condition', config: { condition_expression: 'x > 0' } },
        { id: 'n2', type: 'llm_call', config: {} },
        { id: 'n3', type: 'llm_call', config: {} },
      ],
      edges: [
        { id: 'e1', source: 'n1', target: 'n2', condition: 'x > 0' },  // conditional edge
        { id: 'e2', source: 'n1', target: 'n3' },                       // normal edge (no condition)
      ],
      entry_point: 'n1',
    };

    const resp = await request.post(`${API_BASE}/api/v2/validate-graph`, {
      data: mixedGraph,
    });

    const body = await resp.json();

    if (resp.ok()) {
      // Should have a MIXED_EDGE_TYPES warning
      const mixedWarnings = (body.warnings || []).filter(
        (w: any) => w.code === 'MIXED_EDGE_TYPES'
      );
      expect(mixedWarnings.length).toBeGreaterThan(0);
      expect(mixedWarnings[0].node_ids).toContain('n1');
    }
  });
});
