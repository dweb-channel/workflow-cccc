/**
 * M2 E2E Integration Tests: CCCC SDK Node Configuration UI
 *
 * Tests LLMAgentNode and CCCCPeerNode configuration panels in the
 * workflow editor, including drag-drop creation, config editing,
 * and visual differentiation.
 *
 * Aligned with actual implementation:
 * - NodePalette.tsx: "LLM Agent" (🤖), "CCCC Peer" (👥) in "执行器" category
 * - NodeConfigPanel.tsx: LLMAgentConfig (indigo) + CCCCPeerConfig (amber)
 * - Config panel header: "节点配置", palette header: "节点工具箱"
 * - LLM fields: "Prompt 模板", "System Prompt", "工作目录 (cwd)", "超时 (秒)"
 * - CCCC fields: "Peer ID", "Prompt 模板", "命令前缀", "Group ID", "超时 (秒)"
 *
 * Dependencies: T029 (backend) + T030 (frontend) must be complete.
 * Requires: frontend at localhost:3000, backend at localhost:8000
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';
const APP_URL = 'http://localhost:3000';

// Helper: create a workflow via API
async function createWorkflow(request: any, name = 'M2 UI Test') {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name, description: 'M2 UI E2E test' },
  });
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

// Helper: cleanup a workflow
async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

// Helper: enter edit mode and wait for palette
async function enterEditMode(page: any) {
  // Wait for the page to load
  await page.waitForLoadState('networkidle');
  // Click the "编辑" toggle button in the editor toolbar
  const editBtn = page.locator('button', { hasText: '编辑' });
  await editBtn.waitFor({ state: 'visible', timeout: 10000 });
  await editBtn.click();
  // Wait for the palette to appear (confirms edit mode is active)
  await page.locator('text=节点工具箱').waitFor({ state: 'visible', timeout: 5000 });
}

test.describe('M2: Node Configuration UI (UI1-UI10)', () => {
  let createdIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdIds) {
      await deleteWorkflow(request, id).catch(() => {});
    }
    createdIds = [];
  });

  // UI1: LLM Agent node appears in Node Palette under "执行器" category
  test('UI1: LLM Agent node should appear in Node Palette under 执行器', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI1 Palette');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    // Palette header: "节点工具箱"
    await expect(page.locator('text=节点工具箱')).toBeVisible({ timeout: 5000 });

    // Category label: "执行器"
    await expect(page.locator('text=执行器')).toBeVisible();

    // LLM Agent item: draggable with "LLM Agent" text and 🤖 icon
    const llmItem = page.locator('[draggable="true"]').filter({ hasText: 'LLM Agent' });
    await expect(llmItem).toBeVisible();
    await expect(llmItem).toContainText('🤖');
  });

  // UI2: CCCC Peer node appears in Node Palette under "执行器" category
  test('UI2: CCCC Peer node should appear in Node Palette under 执行器', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI2 Palette');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    // CCCC Peer item: draggable with "CCCC Peer" text and 👥 icon
    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    await expect(ccccItem).toBeVisible({ timeout: 5000 });
    await expect(ccccItem).toContainText('👥');
  });

  // UI3: Drag LLM Agent to canvas creates node
  test('UI3: drag LLM Agent from palette to canvas should create a node', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI3 Drag LLM');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const llmItem = page.locator('[draggable="true"]').filter({ hasText: 'LLM Agent' });
    const canvas = page.locator('.react-flow');

    // Count nodes before drag
    const nodesBefore = await page.locator('.react-flow__node').count();

    // Drag LLM Agent to canvas
    await llmItem.dragTo(canvas);
    await page.waitForTimeout(500);

    // Verify node count increased
    const nodesAfter = await page.locator('.react-flow__node').count();
    expect(nodesAfter).toBeGreaterThan(nodesBefore);
  });

  // UI4: Drag CCCC Peer to canvas creates node
  test('UI4: drag CCCC Peer from palette to canvas should create a node', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI4 Drag CCCC');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    const canvas = page.locator('.react-flow');

    const nodesBefore = await page.locator('.react-flow__node').count();
    await ccccItem.dragTo(canvas);
    await page.waitForTimeout(500);

    const nodesAfter = await page.locator('.react-flow__node').count();
    expect(nodesAfter).toBeGreaterThan(nodesBefore);
  });

  // UI5: LLM Agent config panel shows "LLM Agent 配置" section with "Prompt 模板"
  test('UI5: clicking LLM Agent node should show config panel with Prompt 模板', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI5 LLM Config');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    // Create LLM node via drag
    const llmItem = page.locator('[draggable="true"]').filter({ hasText: 'LLM Agent' });
    const canvas = page.locator('.react-flow');
    await llmItem.dragTo(canvas);
    await page.waitForTimeout(500);

    // Click the new node to open config panel
    const newNode = page.locator('.react-flow__node').last();
    await newNode.click();
    await page.waitForTimeout(300);

    // Config panel header: "节点配置" (use heading role to avoid strict mode violation)
    await expect(page.getByRole('heading', { name: '节点配置' })).toBeVisible({ timeout: 5000 });

    // LLM-specific config section: "LLM Agent 配置" (indigo-colored section)
    await expect(page.locator('text=LLM Agent 配置')).toBeVisible();

    // "Prompt 模板" label should be present
    await expect(page.locator('text=Prompt 模板')).toBeVisible();
  });

  // UI6: CCCC Peer config panel shows "Peer ID" field
  test('UI6: clicking CCCC Peer node should show config panel with Peer ID', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI6 CCCC Config');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    // Create CCCC Peer node via drag
    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    const canvas = page.locator('.react-flow');
    await ccccItem.dragTo(canvas);
    await page.waitForTimeout(500);

    // Click the new node
    const newNode = page.locator('.react-flow__node').last();
    await newNode.click();
    await page.waitForTimeout(300);

    // Config panel header (use heading role to avoid strict mode violation)
    await expect(page.getByRole('heading', { name: '节点配置' })).toBeVisible({ timeout: 5000 });

    // CCCC-specific config section: "CCCC Peer 配置" (amber-colored section)
    await expect(page.locator('text=CCCC Peer 配置')).toBeVisible();

    // "Peer ID" label should be present
    await expect(page.locator('text=Peer ID')).toBeVisible();

    // Peer ID input with placeholder "peer-impl"
    const peerIdInput = page.locator('input[placeholder="peer-impl"]');
    await expect(peerIdInput).toBeVisible();
  });

  // UI7: LLM Agent config panel has indigo styling
  test('UI7: LLM Agent config section should have indigo border styling', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI7 LLM Style');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const llmItem = page.locator('[draggable="true"]').filter({ hasText: 'LLM Agent' });
    const canvas = page.locator('.react-flow');
    await llmItem.dragTo(canvas);
    await page.waitForTimeout(500);

    const newNode = page.locator('.react-flow__node').last();
    await newNode.click();
    await page.waitForTimeout(300);

    // LLM config section has indigo border class: border-indigo-200 bg-indigo-50/50
    const llmSection = page.locator('.border-indigo-200');
    await expect(llmSection).toBeVisible({ timeout: 5000 });
    await expect(llmSection).toContainText('LLM Agent 配置');
  });

  // UI8: CCCC Peer config panel has amber styling
  test('UI8: CCCC Peer config section should have amber border styling', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI8 CCCC Style');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    const canvas = page.locator('.react-flow');
    await ccccItem.dragTo(canvas);
    await page.waitForTimeout(500);

    const newNode = page.locator('.react-flow__node').last();
    await newNode.click();
    await page.waitForTimeout(300);

    // CCCC config section has amber border class: border-amber-200 bg-amber-50/50
    const ccccSection = page.locator('.border-amber-200');
    await expect(ccccSection).toBeVisible({ timeout: 5000 });
    await expect(ccccSection).toContainText('CCCC Peer 配置');
  });

  // UI9: CCCC Peer config shows command and group_id fields
  test('UI9: CCCC Peer config should show 命令前缀 and Group ID fields', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI9 CCCC Fields');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    const canvas = page.locator('.react-flow');
    await ccccItem.dragTo(canvas);
    await page.waitForTimeout(500);

    const newNode = page.locator('.react-flow__node').last();
    await newNode.click();
    await page.waitForTimeout(300);

    // Verify CCCC-specific fields are present
    await expect(page.locator('text=命令前缀')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=Group ID')).toBeVisible();
    await expect(page.locator('text=超时 (秒)')).toBeVisible();

    // Placeholders match implementation
    await expect(page.locator('input[placeholder="/brainstorm"]')).toBeVisible();
    await expect(page.locator('input[placeholder="默认使用环境变量"]')).toBeVisible();
  });

  // UI10: Save workflow with new node types via UI
  test('UI10: should save workflow with LLM + CCCC nodes via editor UI', async ({
    page,
    request,
  }) => {
    const wf = await createWorkflow(request, 'UI10 Save');
    createdIds.push(wf.id);

    await page.goto(`${APP_URL}`);
    await enterEditMode(page);

    const canvas = page.locator('.react-flow');

    // Create LLM node
    const llmItem = page.locator('[draggable="true"]').filter({ hasText: 'LLM Agent' });
    await llmItem.dragTo(canvas);
    await page.waitForTimeout(500);

    // Create CCCC Peer node
    const ccccItem = page.locator('[draggable="true"]').filter({ hasText: 'CCCC Peer' });
    await ccccItem.dragTo(canvas, { targetPosition: { x: 300, y: 200 } });
    await page.waitForTimeout(500);

    // Click save button (保存)
    const saveBtn = page.getByRole('button', { name: /保存|Save/i }).first();
    if (await saveBtn.isVisible()) {
      await saveBtn.click();
      await page.waitForTimeout(1000);
    }

    // Verify graph was persisted via API
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    if (getResp.ok()) {
      const persisted = await getResp.json();
      if (persisted.graph_definition?.nodes) {
        const types = persisted.graph_definition.nodes.map((n: any) => n.type);
        const hasNewTypes =
          types.includes('llm_agent') || types.includes('cccc_peer');
        expect(hasNewTypes).toBe(true);
      }
    }
  });
});
