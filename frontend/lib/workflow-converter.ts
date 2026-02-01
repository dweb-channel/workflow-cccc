/**
 * Converts between React Flow format and backend WorkflowDefinition format.
 */

import type { AgentNodeData } from "@/components/agent-node";

// ============ Backend Types ============

export interface NodeConfig {
  id: string;
  type: string;
  config: Record<string, unknown>;
}

export interface EdgeDefinition {
  id: string;
  source: string;
  target: string;
  condition?: string;
}

export interface WorkflowDefinition {
  name?: string;
  nodes: NodeConfig[];
  edges: EdgeDefinition[];
  entry_point?: string;
}

// ============ React Flow Types ============

export interface FlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: AgentNodeData;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
  style?: Record<string, unknown>;
  label?: string;
  data?: { condition?: string; branches?: Record<string, string> };
}

// ============ Converters ============

/**
 * Convert React Flow nodes/edges to a WorkflowDefinition for saving to backend.
 */
export function toWorkflowDefinition(
  nodes: FlowNode[],
  edges: FlowEdge[],
  workflowName: string
): WorkflowDefinition {
  const wfNodes: NodeConfig[] = nodes.map((n) => ({
    id: n.id,
    type: n.data.nodeType || "llm_agent",
    config: {
      ...(n.data.config || {}),
      name: n.data.label,
      // Store position for later reconstruction
      _position: n.position,
    },
  }));

  const wfEdges: EdgeDefinition[] = edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    condition: e.data?.condition,
  }));

  // Detect entry point: node with no incoming edges
  const targets = new Set(edges.map((e) => e.target));
  const entryNode = nodes.find((n) => !targets.has(n.id));

  return {
    name: workflowName,
    nodes: wfNodes,
    edges: wfEdges,
    entry_point: entryNode?.id,
  };
}

/**
 * Convert a WorkflowDefinition from backend to React Flow nodes/edges.
 */
export function fromWorkflowDefinition(
  workflow: WorkflowDefinition
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const nodes: FlowNode[] = workflow.nodes.map((n, idx) => {
    const position = (n.config._position as { x: number; y: number }) || {
      x: 100 + idx * 250,
      y: 100,
    };

    return {
      id: n.id,
      type: "agentNode",
      position,
      data: {
        label: (n.config.name as string) || n.id,
        status: "pending",
        nodeType: n.type,
        config: n.config,
      },
    };
  });

  const edges: FlowEdge[] = workflow.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    style: e.condition
      ? { stroke: "#9333ea", strokeWidth: 2, strokeDasharray: "6 3" }
      : { stroke: "#94a3b8", strokeWidth: 2 },
    data: e.condition ? { condition: e.condition } : undefined,
  }));

  return { nodes, edges };
}
