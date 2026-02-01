const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ============ Types ============

export interface WorkflowParameters {
  trigger: string;
  priority: "low" | "normal" | "high";
  schedule: string;
  notifyBot: boolean;
}

export interface ApiError {
  detail: string | { message?: string; errors?: string[] };
}

// ============ V2 Types ============

export interface V2WorkflowResponse {
  id: string;
  name: string;
  description: string | null;
  status: string;
  version: string;
  graph_definition: {
    nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>;
    edges: Array<{ id: string; source: string; target: string; condition?: string }>;
    entry_point?: string;
  } | null;
  parameters: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface V2PagedWorkflowsResponse {
  items: V2WorkflowResponse[];
  page: number;
  page_size: number;
  total: number;
}

export interface V2RunRequest {
  initial_state: Record<string, unknown>;
}

export interface V2RunResponse {
  run_id: string;
  workflow_id: string;
  status: string;
}

export interface V2CreateWorkflowRequest {
  name: string;
  description?: string;
  graph_definition?: {
    nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>;
    edges: Array<{ id: string; source: string; target: string; condition?: string }>;
    entry_point?: string;
  };
  parameters?: Record<string, unknown>;
}

export interface V2UpdateWorkflowRequest {
  name?: string;
  description?: string;
  status?: string;
  parameters?: Record<string, unknown>;
}

export interface NodeTypeInfo {
  node_type: string;
  display_name: string;
  description: string;
  category: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  icon?: string;
  color?: string;
}

export interface ValidationError {
  code: string;
  message: string;
  severity: string;
  node_ids: string[];
  context: Record<string, unknown>;
}

export interface ValidationResponse {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationError[];
}

// ============ API Client ============

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      detail: `HTTP ${response.status}: ${response.statusText}`,
    }));
    const detail = error.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null
          ? (detail as { message?: string }).message ?? JSON.stringify(detail)
          : `HTTP ${response.status}: ${response.statusText}`;
    throw new Error(message);
  }
  return response.json();
}

// --- Workflow CRUD ---

export async function listWorkflows(
  status?: string,
  page = 1,
  pageSize = 20
): Promise<V2PagedWorkflowsResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (status) params.set("status", status);
  const response = await fetch(`${API_BASE}/api/v2/workflows?${params}`);
  return handleResponse<V2PagedWorkflowsResponse>(response);
}

export async function getWorkflow(id: string): Promise<V2WorkflowResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}`);
  return handleResponse<V2WorkflowResponse>(response);
}

export async function createWorkflow(
  payload: V2CreateWorkflowRequest
): Promise<V2WorkflowResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<V2WorkflowResponse>(response);
}

export async function updateWorkflow(
  id: string,
  payload: V2UpdateWorkflowRequest
): Promise<V2WorkflowResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<V2WorkflowResponse>(response);
}

export async function deleteWorkflow(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      detail: `HTTP ${response.status}: ${response.statusText}`,
    }));
    const detail = error.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail !== null
          ? (detail as { message?: string }).message ?? JSON.stringify(detail)
          : `HTTP ${response.status}: ${response.statusText}`;
    throw new Error(message);
  }
}

// --- Graph ---

export async function saveWorkflowGraph(
  id: string,
  payload: {
    nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>;
    edges: Array<{ id: string; source: string; target: string; condition?: string }>;
    entry_point?: string;
  }
): Promise<V2WorkflowResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}/graph`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<V2WorkflowResponse>(response);
}

// --- Run ---

export async function runWorkflow(
  id: string,
  initialState: Record<string, unknown> = {}
): Promise<V2RunResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ initial_state: initialState }),
  });
  return handleResponse<V2RunResponse>(response);
}

// --- Validation ---

export async function validateWorkflow(id: string): Promise<ValidationResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workflows/${id}/validate`, {
    method: "POST",
  });
  return handleResponse<ValidationResponse>(response);
}

export async function validateGraphInline(
  payload: {
    nodes: Array<{ id: string; type: string; config: Record<string, unknown> }>;
    edges: Array<{ id: string; source: string; target: string; condition?: string }>;
    entry_point?: string;
  }
): Promise<ValidationResponse> {
  const response = await fetch(`${API_BASE}/api/v2/validate-graph`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<ValidationResponse>(response);
}

// --- Node Types ---

export async function getNodeTypes(): Promise<NodeTypeInfo[]> {
  const response = await fetch(`${API_BASE}/api/v2/node-types`);
  return handleResponse<NodeTypeInfo[]>(response);
}
