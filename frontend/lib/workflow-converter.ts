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
  max_iterations?: number;
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
  data?: { condition?: string; branches?: Record<string, string>; isLoop?: boolean };
}

// ============ Loop Detection ============

/**
 * Detect back edges (edges that create cycles) using DFS.
 * Returns a Set of edge IDs that are loop/back edges.
 */
export function detectLoopEdges(
  nodes: FlowNode[],
  edges: FlowEdge[]
): Set<string> {
  const adj = new Map<string, Array<{ target: string; edgeId: string }>>();
  for (const edge of edges) {
    if (!adj.has(edge.source)) adj.set(edge.source, []);
    adj.get(edge.source)!.push({ target: edge.target, edgeId: edge.id });
  }

  const backEdgeIds = new Set<string>();
  const visited = new Set<string>();
  const inStack = new Set<string>();

  function dfs(node: string) {
    visited.add(node);
    inStack.add(node);

    for (const { target, edgeId } of adj.get(node) || []) {
      if (inStack.has(target)) {
        backEdgeIds.add(edgeId);
      } else if (!visited.has(target)) {
        dfs(target);
      }
    }

    inStack.delete(node);
  }

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      dfs(node.id);
    }
  }

  return backEdgeIds;
}

// ============ Edge Styling ============

const EDGE_STYLE_NORMAL = { stroke: "#94a3b8", strokeWidth: 2 };
const EDGE_STYLE_CONDITION = { stroke: "#9333ea", strokeWidth: 2, strokeDasharray: "6 3" };
const EDGE_STYLE_LOOP = { stroke: "#f97316", strokeWidth: 2, strokeDasharray: "5 4" };

export function getEdgeStyle(edge: FlowEdge, isLoop: boolean) {
  if (isLoop) return EDGE_STYLE_LOOP;
  if (edge.data?.condition) return EDGE_STYLE_CONDITION;
  return EDGE_STYLE_NORMAL;
}

/**
 * Apply loop detection and styling to all edges.
 * Returns new edges array with updated styles and data.isLoop flags.
 */
export function applyLoopStyles(nodes: FlowNode[], edges: FlowEdge[]): FlowEdge[] {
  const loopEdgeIds = detectLoopEdges(nodes, edges);

  return edges.map((e) => {
    const isLoop = loopEdgeIds.has(e.id);
    return {
      ...e,
      style: getEdgeStyle(e, isLoop),
      data: { ...e.data, isLoop },
    };
  });
}

// ============ Converters ============

/**
 * Convert React Flow nodes/edges to a WorkflowDefinition for saving to backend.
 */
export function toWorkflowDefinition(
  nodes: FlowNode[],
  edges: FlowEdge[],
  workflowName: string,
  maxIterations?: number
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

  // Detect entry point: node with no incoming non-loop edges
  // In cyclic graphs, exclude back edges when finding the entry point
  const loopEdgeIds = detectLoopEdges(nodes, edges);
  const nonLoopTargets = new Set(
    edges.filter((e) => !loopEdgeIds.has(e.id)).map((e) => e.target)
  );
  const entryNode = nodes.find((n) => !nonLoopTargets.has(n.id));

  return {
    name: workflowName,
    nodes: wfNodes,
    edges: wfEdges,
    entry_point: entryNode?.id,
    max_iterations: maxIterations,
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
      ? EDGE_STYLE_CONDITION
      : EDGE_STYLE_NORMAL,
    data: e.condition ? { condition: e.condition } : undefined,
  }));

  // Apply loop detection and styling after initial conversion
  return { nodes, edges: applyLoopStyles(nodes, edges) };
}
