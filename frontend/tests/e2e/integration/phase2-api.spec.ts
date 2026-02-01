/**
 * E2E Integration Tests: Phase 2 - Database Persistence API (E1-E6)
 *
 * Tests v2 API CRUD operations for workflow management.
 * Requires: backend running at localhost:8000
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

// Helper: create a workflow via API
async function createWorkflow(request: any, name = 'Test Workflow') {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name, description: 'Created by E2E test' },
  });
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

// Helper: cleanup a workflow
async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

test.describe('Phase 2: Database Persistence API (E1-E6)', () => {
  // Track created workflow IDs for cleanup
  let createdIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdIds) {
      await deleteWorkflow(request, id).catch(() => {});
    }
    createdIds = [];
  });

  // E1: Create workflow - POST 201 + returns ID + DB persistence
  test('E1: should create a workflow via POST /api/v2/workflows', async ({ request }) => {
    const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
      data: {
        name: 'E1 Test Workflow',
        description: 'Integration test - create workflow',
      },
    });

    expect(resp.status()).toBe(201);
    const body = await resp.json();

    // Must return an ID
    expect(body).toHaveProperty('id');
    expect(typeof body.id).toBe('string');
    expect(body.id.length).toBeGreaterThan(0);

    // Must echo back name and description
    expect(body.name).toBe('E1 Test Workflow');
    expect(body.description).toBe('Integration test - create workflow');

    // Must have timestamps
    expect(body).toHaveProperty('created_at');
    expect(body).toHaveProperty('updated_at');

    // Verify persistence: GET should return the same workflow
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${body.id}`);
    expect(getResp.ok()).toBeTruthy();
    const persisted = await getResp.json();
    expect(persisted.id).toBe(body.id);
    expect(persisted.name).toBe('E1 Test Workflow');

    createdIds.push(body.id);
  });

  // E2: List workflows - pagination + sorted by updated_at DESC
  test('E2: should list workflows with pagination sorted by updated_at DESC', async ({ request }) => {
    // Create 3 workflows with distinct names
    const names = ['E2-Alpha', 'E2-Beta', 'E2-Gamma'];
    for (const name of names) {
      const wf = await createWorkflow(request, name);
      createdIds.push(wf.id);
    }

    // List with page=1, page_size=2
    const resp = await request.get(`${API_BASE}/api/v2/workflows?page=1&page_size=2`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();

    // Paged response structure
    expect(body).toHaveProperty('items');
    expect(body).toHaveProperty('page');
    expect(body).toHaveProperty('page_size');
    expect(body).toHaveProperty('total');

    expect(Array.isArray(body.items)).toBe(true);
    expect(body.items.length).toBeLessThanOrEqual(2);
    expect(body.page).toBe(1);
    expect(body.total).toBeGreaterThanOrEqual(3);

    // Verify sorting: updated_at DESC (most recent first)
    if (body.items.length >= 2) {
      const t0 = new Date(body.items[0].updated_at).getTime();
      const t1 = new Date(body.items[1].updated_at).getTime();
      expect(t0).toBeGreaterThanOrEqual(t1);
    }
  });

  // E3: Get single workflow - 404 for invalid ID + correct return
  test('E3: should get a single workflow and return 404 for invalid ID', async ({ request }) => {
    // Create a workflow to fetch
    const wf = await createWorkflow(request, 'E3 Fetch Test');
    createdIds.push(wf.id);

    // Successful fetch
    const resp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.id).toBe(wf.id);
    expect(body.name).toBe('E3 Fetch Test');

    // 404 for non-existent ID
    const notFoundResp = await request.get(`${API_BASE}/api/v2/workflows/non-existent-id-12345`);
    expect(notFoundResp.status()).toBe(404);
  });

  // E4: Update workflow metadata - PATCH name/description/status
  test('E4: should update workflow metadata via PATCH', async ({ request }) => {
    const wf = await createWorkflow(request, 'E4 Original Name');
    createdIds.push(wf.id);

    const patchResp = await request.patch(`${API_BASE}/api/v2/workflows/${wf.id}`, {
      data: {
        name: 'E4 Updated Name',
        description: 'Updated description',
        status: 'published',
      },
    });
    expect(patchResp.ok()).toBeTruthy();
    const updated = await patchResp.json();

    expect(updated.name).toBe('E4 Updated Name');
    expect(updated.description).toBe('Updated description');
    expect(updated.status).toBe('published');

    // Verify persistence
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    const persisted = await getResp.json();
    expect(persisted.name).toBe('E4 Updated Name');
  });

  // E5: Delete workflow - 204 + confirm deleted
  test('E5: should delete a workflow and confirm deletion', async ({ request }) => {
    const wf = await createWorkflow(request, 'E5 Delete Me');
    // Don't add to createdIds since we're deleting manually

    const delResp = await request.delete(`${API_BASE}/api/v2/workflows/${wf.id}`);
    expect(delResp.status()).toBe(204);

    // Confirm deleted: GET should return 404
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    expect(getResp.status()).toBe(404);
  });

  // E6: Node types list - returns all registered types
  test('E6: should list all registered node types', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v2/node-types`);
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();

    // Should return an array of node type definitions
    expect(Array.isArray(body)).toBe(true);
    expect(body.length).toBeGreaterThan(0);

    // Each node type should have at minimum: type, label
    const nodeType = body[0];
    expect(nodeType).toHaveProperty('node_type');
    expect(typeof nodeType.node_type).toBe('string');
  });
});
