const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ============ Types ============

export interface WorkflowParameters {
  trigger: string;
  priority: "low" | "normal" | "high";
  schedule: string;
  notifyBot: boolean;
}

export interface WorkflowSummary {
  id: string;
  name: string;
  status: string;
  version: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDetail extends WorkflowSummary {
  parameters: WorkflowParameters;
  nodeConfig: string;
}

export interface WorkflowLog {
  id: string;
  runId: string;
  time: string;
  level: string;
  message: string;
  source: string;
}

export interface RunRecord {
  id: string;
  workflowId: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  triggered_by: string;
}

export interface PagedLogs {
  items: WorkflowLog[];
  page: number;
  pageSize: number;
  total: number;
}

export interface PagedRuns {
  items: RunRecord[];
  page: number;
  pageSize: number;
  total: number;
}

export interface RunRequest {
  request?: string;
  parameters?: WorkflowParameters;
  clientRequestId?: string;
}

export interface RunResponse {
  runId: string;
  status: string;
}

export interface SaveRequest {
  parameters: WorkflowParameters;
  nodeConfig?: string;
  clientRequestId?: string;
}

export interface SaveResponse {
  message: string;
  workflow: WorkflowDetail;
}

export interface ApiError {
  detail: string;
}

export interface ConfirmRequest {
  stage: "initial" | "final";
  approved: boolean;
  feedback: string;
}

export interface ConfirmResponse {
  message: string;
  status: string;
}

// ============ API Client ============

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error: ApiError = await response.json().catch(() => ({
      detail: `HTTP ${response.status}: ${response.statusText}`,
    }));
    throw new Error(error.detail);
  }
  return response.json();
}

export async function listWorkflows(): Promise<WorkflowSummary[]> {
  const response = await fetch(`${API_BASE}/api/workflows`);
  return handleResponse<WorkflowSummary[]>(response);
}

export async function getWorkflow(id: string): Promise<WorkflowDetail> {
  const response = await fetch(`${API_BASE}/api/workflows/${id}`);
  return handleResponse<WorkflowDetail>(response);
}

export async function getWorkflowRuns(
  id: string,
  page = 1,
  pageSize = 20
): Promise<PagedRuns> {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  });
  const response = await fetch(`${API_BASE}/api/workflows/${id}/runs?${params}`);
  return handleResponse<PagedRuns>(response);
}

export async function getWorkflowLogs(
  id: string,
  page = 1,
  pageSize = 20
): Promise<PagedLogs> {
  const params = new URLSearchParams({
    page: String(page),
    pageSize: String(pageSize),
  });
  const response = await fetch(`${API_BASE}/api/workflows/${id}/logs?${params}`);
  return handleResponse<PagedLogs>(response);
}

export async function runWorkflow(
  id: string,
  payload?: RunRequest
): Promise<RunResponse> {
  const response = await fetch(`${API_BASE}/api/workflows/${id}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  return handleResponse<RunResponse>(response);
}

export async function saveWorkflow(
  id: string,
  payload: SaveRequest
): Promise<SaveResponse> {
  const response = await fetch(`${API_BASE}/api/workflows/${id}/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<SaveResponse>(response);
}

export async function confirmWorkflow(
  workflowId: string,
  runId: string,
  payload: ConfirmRequest
): Promise<ConfirmResponse> {
  const response = await fetch(
    `${API_BASE}/api/workflows/${workflowId}/runs/${runId}/confirm`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  return handleResponse<ConfirmResponse>(response);
}
