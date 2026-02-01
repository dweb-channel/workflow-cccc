/**
 * M2 E2E Integration Tests: CCCC SDK Node Types - API Layer
 *
 * Tests LLMAgentNode and CCCCPeerNode registration, configuration,
 * and graph integration via v2 API endpoints.
 *
 * Dependencies: T029 (backend node types) must be complete.
 * Requires: backend running at localhost:8000
 *
 * Aligned with actual implementation:
 * - agent_nodes.py: category="agent", required fields: name+prompt (LLM), name+peer_id+prompt (CCCC)
 * - Config field is "prompt" not "prompt_template"
 *
 * Author: browser-tester
 * Date: 2026-02-01
 */

import { test, expect } from '@playwright/test';

const API_BASE = 'http://localhost:8000';

// Helper: create a workflow via API
async function createWorkflow(request: any, name = 'M2 Test Workflow') {
  const resp = await request.post(`${API_BASE}/api/v2/workflows`, {
    data: { name, description: 'M2 E2E test' },
  });
  expect(resp.ok()).toBeTruthy();
  return resp.json();
}

// Helper: cleanup a workflow
async function deleteWorkflow(request: any, id: string) {
  await request.delete(`${API_BASE}/api/v2/workflows/${id}`);
}

test.describe('M2: CCCC SDK Node Types - API (NT1-NT8)', () => {
  let createdIds: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of createdIds) {
      await deleteWorkflow(request, id).catch(() => {});
    }
    createdIds = [];
  });

  // NT1: LLMAgentNode registered in node type registry
  test('NT1: LLMAgentNode should be registered in node-types API', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v2/node-types`);
    expect(resp.ok()).toBeTruthy();
    const nodeTypes = await resp.json();

    const llmAgent = nodeTypes.find(
      (nt: any) => nt.node_type === 'llm_agent'
    );
    expect(llmAgent).toBeDefined();
    expect(llmAgent.display_name).toBe('LLM Agent');
    expect(llmAgent.category).toBe('agent');
    expect(llmAgent.icon).toBe('bot');
    expect(llmAgent.color).toBe('#6366F1');

    // Should have input/output schema with required fields
    expect(llmAgent).toHaveProperty('input_schema');
    expect(llmAgent).toHaveProperty('output_schema');
    expect(llmAgent.input_schema.required).toContain('name');
    expect(llmAgent.input_schema.required).toContain('prompt');
  });

  // NT2: CCCCPeerNode registered in node type registry
  test('NT2: CCCCPeerNode should be registered in node-types API', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v2/node-types`);
    expect(resp.ok()).toBeTruthy();
    const nodeTypes = await resp.json();

    const ccccPeer = nodeTypes.find(
      (nt: any) => nt.node_type === 'cccc_peer'
    );
    expect(ccccPeer).toBeDefined();
    expect(ccccPeer.display_name).toBe('CCCC Peer');
    expect(ccccPeer.category).toBe('agent');
    expect(ccccPeer.icon).toBe('message-circle');
    expect(ccccPeer.color).toBe('#F59E0B');

    expect(ccccPeer).toHaveProperty('input_schema');
    expect(ccccPeer).toHaveProperty('output_schema');
    expect(ccccPeer.input_schema.required).toContain('name');
    expect(ccccPeer.input_schema.required).toContain('peer_id');
    expect(ccccPeer.input_schema.required).toContain('prompt');
  });

  // NT3: Save graph with LLMAgentNode - valid config
  test('NT3: should save a graph containing LLMAgentNode with valid config', async ({ request }) => {
    const wf = await createWorkflow(request, 'NT3 LLM Graph');
    createdIds.push(wf.id);

    const graphPayload = {
      nodes: [
        {
          id: 'node-1',
          type: 'data_source',
          config: { name: 'Source', data: { request: 'test input' } },
        },
        {
          id: 'node-2',
          type: 'llm_agent',
          config: {
            name: 'Analyzer',
            prompt: 'Analyze: {request}',
            cwd: '.',
            timeout: 300,
          },
        },
        {
          id: 'node-3',
          type: 'output',
          config: { name: 'Output', format: 'json' },
        },
      ],
      edges: [
        { id: 'e1', source: 'node-1', target: 'node-2' },
        { id: 'e2', source: 'node-2', target: 'node-3' },
      ],
      entry_point: 'node-1',
    };

    const saveResp = await request.put(
      `${API_BASE}/api/v2/workflows/${wf.id}/graph`,
      { data: graphPayload }
    );
    expect(saveResp.ok()).toBeTruthy();

    // Verify persistence
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    const persisted = await getResp.json();
    expect(persisted.graph_definition).toBeDefined();

    const llmNode = persisted.graph_definition.nodes.find(
      (n: any) => n.type === 'llm_agent'
    );
    expect(llmNode).toBeDefined();
    expect(llmNode.config.prompt).toBe('Analyze: {request}');
    expect(llmNode.config.name).toBe('Analyzer');
  });

  // NT4: Save graph with CCCCPeerNode - valid config
  test('NT4: should save a graph containing CCCCPeerNode with valid config', async ({ request }) => {
    const wf = await createWorkflow(request, 'NT4 CCCC Graph');
    createdIds.push(wf.id);

    const graphPayload = {
      nodes: [
        {
          id: 'node-1',
          type: 'data_source',
          config: { name: 'Source', data: { request: 'implement feature' } },
        },
        {
          id: 'node-2',
          type: 'cccc_peer',
          config: {
            name: 'Implementor',
            peer_id: 'peer-impl',
            prompt: 'Implement: {request}',
            timeout: 120,
          },
        },
        {
          id: 'node-3',
          type: 'output',
          config: { name: 'Output', format: 'json' },
        },
      ],
      edges: [
        { id: 'e1', source: 'node-1', target: 'node-2' },
        { id: 'e2', source: 'node-2', target: 'node-3' },
      ],
      entry_point: 'node-1',
    };

    const saveResp = await request.put(
      `${API_BASE}/api/v2/workflows/${wf.id}/graph`,
      { data: graphPayload }
    );
    expect(saveResp.ok()).toBeTruthy();

    // Verify persistence
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    const persisted = await getResp.json();
    const ccccNode = persisted.graph_definition.nodes.find(
      (n: any) => n.type === 'cccc_peer'
    );
    expect(ccccNode).toBeDefined();
    expect(ccccNode.config.peer_id).toBe('peer-impl');
    expect(ccccNode.config.prompt).toBe('Implement: {request}');
  });

  // NT5: Validate graph rejects LLMAgentNode with missing prompt
  test('NT5: should reject LLMAgentNode with empty prompt', async ({ request }) => {
    const graphPayload = {
      nodes: [
        {
          id: 'node-1',
          type: 'data_source',
          config: { data: {} },
        },
        {
          id: 'node-2',
          type: 'llm_agent',
          config: {
            name: 'Empty Prompt Agent',
            prompt: '',  // Empty prompt should fail validation
          },
        },
      ],
      edges: [{ id: 'e1', source: 'node-1', target: 'node-2' }],
      entry_point: 'node-1',
    };

    const validateResp = await request.post(
      `${API_BASE}/api/v2/validate-graph`,
      { data: graphPayload }
    );
    expect(validateResp.ok()).toBeTruthy();
    const result = await validateResp.json();

    // Should have validation error for empty prompt
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  // NT6: Validate graph rejects CCCCPeerNode with missing peer_id
  test('NT6: should reject CCCCPeerNode with empty peer_id', async ({ request }) => {
    const graphPayload = {
      nodes: [
        {
          id: 'node-1',
          type: 'data_source',
          config: { data: {} },
        },
        {
          id: 'node-2',
          type: 'cccc_peer',
          config: {
            name: 'Missing Peer',
            peer_id: '',  // Empty peer_id should fail validation
            prompt: 'Do something',
            timeout: 120,
          },
        },
      ],
      edges: [{ id: 'e1', source: 'node-1', target: 'node-2' }],
      entry_point: 'node-1',
    };

    const validateResp = await request.post(
      `${API_BASE}/api/v2/validate-graph`,
      { data: graphPayload }
    );
    expect(validateResp.ok()).toBeTruthy();
    const result = await validateResp.json();

    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  // NT7: Mixed graph with both LLM and CCCC nodes
  test('NT7: should save mixed graph with LLMAgent + CCCCPeer + Condition nodes', async ({ request }) => {
    const wf = await createWorkflow(request, 'NT7 Mixed Graph');
    createdIds.push(wf.id);

    const graphPayload = {
      nodes: [
        {
          id: 'node-1',
          type: 'data_source',
          config: { name: 'Source', data: { request: 'analyze and implement' } },
        },
        {
          id: 'node-2',
          type: 'llm_agent',
          config: {
            name: 'Analyzer',
            prompt: 'Analyze: {request}',
          },
        },
        {
          id: 'node-3',
          type: 'condition',
          config: {
            name: 'Branch',
            condition: 'result.analysis != ""',
            true_branch: 'node-4',
            false_branch: 'node-5',
          },
        },
        {
          id: 'node-4',
          type: 'cccc_peer',
          config: {
            name: 'Implementor',
            peer_id: 'peer-impl',
            prompt: 'Implement based on: {analysis}',
            timeout: 120,
          },
        },
        {
          id: 'node-5',
          type: 'output',
          config: { name: 'Output', format: 'json' },
        },
      ],
      edges: [
        { id: 'e1', source: 'node-1', target: 'node-2' },
        { id: 'e2', source: 'node-2', target: 'node-3' },
        { id: 'e3', source: 'node-3', target: 'node-4', condition: 'result.analysis != ""' },
        { id: 'e4', source: 'node-3', target: 'node-5' },
        { id: 'e5', source: 'node-4', target: 'node-5' },
      ],
      entry_point: 'node-1',
    };

    const saveResp = await request.put(
      `${API_BASE}/api/v2/workflows/${wf.id}/graph`,
      { data: graphPayload }
    );
    expect(saveResp.ok()).toBeTruthy();

    // Verify all node types persisted
    const getResp = await request.get(`${API_BASE}/api/v2/workflows/${wf.id}`);
    const persisted = await getResp.json();
    const nodeTypes = persisted.graph_definition.nodes.map((n: any) => n.type);
    expect(nodeTypes).toContain('llm_agent');
    expect(nodeTypes).toContain('cccc_peer');
    expect(nodeTypes).toContain('condition');
  });

  // NT8: Agent category includes both LLM and CCCC node types
  test('NT8: agent category should include both LLM and CCCC node types', async ({ request }) => {
    const resp = await request.get(`${API_BASE}/api/v2/node-types`);
    const nodeTypes = await resp.json();

    const agents = nodeTypes.filter(
      (nt: any) => nt.category === 'agent'
    );
    expect(agents.length).toBeGreaterThanOrEqual(2);

    const agentTypes = agents.map((nt: any) => nt.node_type);
    expect(agentTypes).toContain('llm_agent');
    expect(agentTypes).toContain('cccc_peer');
  });
});
