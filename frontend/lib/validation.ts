/**
 * Validation types and utilities shared between components.
 */

// ============ Types ============

export interface ValidationError {
  code: string;
  message: string;
  severity: "error" | "warning";
  node_ids: string[];
  context: Record<string, unknown>;
}

export type ValidationWarning = ValidationError;

export interface CircularDependencyContext {
  cycle_path: string[];
  has_condition_exit?: boolean;
  condition_node_id?: string;
  max_iterations?: number;
}

export interface MissingFieldReferenceContext {
  field: string;
  available_fields: string[];
  source_node_id: string;
  upstream_node_ids?: string[];
  referenced_field?: string;
  fix_suggestions?: Array<{ label: string; value: string }>;
}

export interface DanglingNodeContext {
  node_id: string;
  connected_nodes: string[];
  connection_suggestions?: string[];
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationWarning[];
}

export type ValidationResponse = ValidationResult;

// ============ Type Guards ============

export function isCircularDependencyError(
  error: ValidationError
): error is ValidationError & { context: CircularDependencyContext } {
  return error.code === "CIRCULAR_DEPENDENCY" || error.code === "CONTROLLED_LOOP";
}

export function isMissingFieldReferenceError(
  error: ValidationError
): error is ValidationError & { context: MissingFieldReferenceContext } {
  return error.code === "MISSING_FIELD_REFERENCE";
}

export function isDanglingNodeWarning(
  warning: ValidationError
): warning is ValidationError & { context: DanglingNodeContext } {
  return warning.code === "DANGLING_NODE";
}

// ============ Client-side Validation ============

interface WorkflowForValidation {
  nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>;
  edges: Array<{ id: string; source: string; target: string; condition?: string }>;
  entry_point?: string;
}

/**
 * Client-side workflow validation (basic structural checks).
 * For full validation, use the backend /api/v2/validate-graph endpoint.
 */
export function validateWorkflowClient(workflow: WorkflowForValidation): ValidationResult {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];

  if (!workflow.nodes || workflow.nodes.length === 0) {
    errors.push({
      code: "EMPTY_GRAPH",
      message: "工作流不包含任何节点",
      severity: "error",
      node_ids: [],
      context: {},
    });
    return { valid: false, errors, warnings };
  }

  // Check for dangling nodes (no incoming or outgoing edges)
  const sources = new Set(workflow.edges.map((e) => e.source));
  const targets = new Set(workflow.edges.map((e) => e.target));
  for (const node of workflow.nodes) {
    if (!sources.has(node.id) && !targets.has(node.id) && workflow.nodes.length > 1) {
      warnings.push({
        code: "DANGLING_NODE",
        message: `节点 "${node.id}" 未连接到任何其他节点`,
        severity: "warning",
        node_ids: [node.id],
        context: { node_id: node.id, connected_nodes: [] },
      });
    }
  }

  // Detect cycles using DFS
  const adj = new Map<string, string[]>();
  for (const edge of workflow.edges) {
    if (!adj.has(edge.source)) adj.set(edge.source, []);
    adj.get(edge.source)!.push(edge.target);
  }

  const visited = new Set<string>();
  const inStack = new Set<string>();
  const cyclePaths: string[][] = [];

  function dfs(node: string, path: string[]) {
    visited.add(node);
    inStack.add(node);
    path.push(node);

    for (const neighbor of adj.get(node) || []) {
      if (inStack.has(neighbor)) {
        const cycleStart = path.indexOf(neighbor);
        cyclePaths.push([...path.slice(cycleStart), neighbor]);
      } else if (!visited.has(neighbor)) {
        dfs(neighbor, path);
      }
    }

    path.pop();
    inStack.delete(node);
  }

  for (const node of workflow.nodes) {
    if (!visited.has(node.id)) {
      dfs(node.id, []);
    }
  }

  for (const cyclePath of cyclePaths) {
    // Check if cycle has a condition node with an exit
    const cycleNodeIds = new Set(cyclePath.slice(0, -1));
    const conditionNode = workflow.nodes.find(
      (n) => cycleNodeIds.has(n.id) && n.type === "condition"
    );
    const hasConditionExit =
      conditionNode != null &&
      workflow.edges.some(
        (e) => e.source === conditionNode.id && !cycleNodeIds.has(e.target)
      );

    if (hasConditionExit) {
      warnings.push({
        code: "CONTROLLED_LOOP",
        message: `检测到受控循环：${cyclePath.join(" → ")}`,
        severity: "warning",
        node_ids: [...cycleNodeIds],
        context: {
          cycle_path: cyclePath,
          has_condition_exit: true,
          condition_node_id: conditionNode!.id,
        },
      });
    } else {
      errors.push({
        code: "CIRCULAR_DEPENDENCY",
        message: `检测到无出口环路：${cyclePath.join(" → ")}`,
        severity: "error",
        node_ids: [...cycleNodeIds],
        context: { cycle_path: cyclePath },
      });
    }
  }

  return {
    valid: errors.length === 0,
    errors,
    warnings,
  };
}

/**
 * Adapt a fixture workflow format to the validation input format.
 */
export function adaptFixtureWorkflow(fixtureWorkflow: {
  nodes?: Array<{ id: string; type?: string; config?: Record<string, unknown> }>;
  edges?: Array<{ id?: string; source: string; target: string; condition?: string }>;
  entry_point?: string;
}): WorkflowForValidation {
  return {
    nodes: (fixtureWorkflow.nodes || []).map((n) => ({
      id: n.id,
      type: n.type || "llm_agent",
      config: n.config || {},
    })),
    edges: (fixtureWorkflow.edges || []).map((e, idx) => ({
      id: e.id || `edge-${idx}`,
      source: e.source,
      target: e.target,
      condition: e.condition,
    })),
    entry_point: fixtureWorkflow.entry_point,
  };
}
