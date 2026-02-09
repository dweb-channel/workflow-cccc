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
          ? (() => {
              const d = detail as { message?: string; errors?: string[] };
              const base = d.message ?? "";
              if (d.errors?.length) {
                return base ? `${base}\n\n${d.errors.join("\n")}` : d.errors.join("\n");
              }
              return base || JSON.stringify(detail);
            })()
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
          ? (() => {
              const d = detail as { message?: string; errors?: string[] };
              const base = d.message ?? "";
              if (d.errors?.length) {
                return base ? `${base}\n\n${d.errors.join("\n")}` : d.errors.join("\n");
              }
              return base || JSON.stringify(detail);
            })()
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

// ============ CCCC Types ============

export interface CCCCPeer {
  id: string;
  title: string;
  role: string;
  enabled?: boolean;
  running?: boolean;
}

export interface CCCCGroup {
  group_id: string;
  title: string;
  state: "active" | "idle" | "paused";
  running: boolean;
  actor_count: number;
  scope: string;
  ready: boolean;
  enabled_peers: number;
  peers?: CCCCPeer[];
}

export interface CCCCGroupsResponse {
  groups: CCCCGroup[];
}

export interface BatchBugFixRequest {
  target_group_id: string;
  jira_urls: string[];
  verification_level?: "quick" | "standard" | "full";
  on_failure?: "continue" | "stop";
  fixer_peer_id?: string;
  verifier_peer_id?: string;
}

export interface BatchBugFixResponse {
  job_id: string;
  status: string;
  total_bugs: number;
  target_group_id: string;
  created_at: string;
}

export interface BugStatusDetail {
  bug_id: string;
  url: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  error?: string;
}

export interface BatchJobStatusResponse {
  job_id: string;
  status: string;
  target_group_id: string;
  bugs: BugStatusDetail[];
  completed: number;
  failed: number;
  skipped: number;
  in_progress: number;
  pending: number;
  created_at: string;
}

export interface BatchJobHistoryItem {
  job_id: string;
  status: string;
  target_group_id: string;
  total_bugs: number;
  completed: number;
  failed: number;
  created_at: string;
  updated_at: string;
}

export interface BatchJobHistoryResponse {
  jobs: BatchJobHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

// ============ CCCC API ============

export async function getCCCCGroups(filter?: "running" | "ready"): Promise<CCCCGroupsResponse> {
  const params = new URLSearchParams();
  if (filter) params.set("filter", filter);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/api/v2/cccc/groups${query ? `?${query}` : ""}`);
  return handleResponse<CCCCGroupsResponse>(response);
}

export async function submitBatchBugFix(payload: BatchBugFixRequest): Promise<BatchBugFixResponse> {
  const response = await fetch(`${API_BASE}/api/v2/cccc/batch-bug-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<BatchBugFixResponse>(response);
}

export async function getBatchJobStatus(jobId: string): Promise<BatchJobStatusResponse> {
  const response = await fetch(`${API_BASE}/api/v2/cccc/batch-bug-fix/${jobId}`);
  return handleResponse<BatchJobStatusResponse>(response);
}

export async function cancelBatchJob(jobId: string): Promise<{ success: boolean; job_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/v2/cccc/batch-bug-fix/${jobId}/cancel`, {
    method: "POST",
  });
  return handleResponse<{ success: boolean; job_id: string; status: string }>(response);
}

// --- Jira JQL Query API ---

export interface JiraBug {
  key: string;
  summary: string;
  status: string;
  url: string;
  priority?: string;
  assignee?: string;
}

export interface JiraQueryRequest {
  jql: string;
  jira_url?: string;
  email?: string;
  api_token?: string;
  max_results?: number;
}

export interface JiraQueryResponse {
  bugs: JiraBug[];
  total: number;
  jql: string;
}

export async function queryJiraBugs(payload: JiraQueryRequest): Promise<JiraQueryResponse> {
  const response = await fetch(`${API_BASE}/api/v2/cccc/jira/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<JiraQueryResponse>(response);
}

export async function getBatchJobHistory(
  page = 1,
  pageSize = 20,
  status?: string
): Promise<BatchJobHistoryResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (status) params.set("status", status);
  const response = await fetch(`${API_BASE}/api/v2/cccc/batch-bug-fix?${params}`);
  return handleResponse<BatchJobHistoryResponse>(response);
}

// --- Task Polling API (for target groups) ---

export interface BatchBugFixConfig {
  validation_level: "minimal" | "standard" | "thorough";
  failure_policy: "stop" | "skip" | "retry";
  max_retries: number;
}

export interface TaskForGroup {
  job_id: string;
  bug_index: number;
  url: string;
  status: string;
  config: BatchBugFixConfig;
}

export interface TasksForGroupResponse {
  tasks: TaskForGroup[];
  total: number;
}

export interface BugStatusUpdateResponse {
  success: boolean;
  job_id: string;
  bug_index: number;
  new_status: string;
  job_status: string;
}

/**
 * Get tasks assigned to a specific group.
 * Target groups should poll this endpoint to get tasks assigned to them.
 */
export async function getTasksForGroup(
  groupId: string,
  status?: "pending" | "in_progress" | "all"
): Promise<TasksForGroupResponse> {
  const params = new URLSearchParams({ group_id: groupId });
  if (status) params.set("status", status);
  const response = await fetch(`${API_BASE}/api/v2/cccc/tasks?${params}`);
  return handleResponse<TasksForGroupResponse>(response);
}

/**
 * Update the status of a specific bug in a job.
 * Target groups should call this to report progress on bug fixes.
 */
export async function updateBugStatus(
  jobId: string,
  bugIndex: number,
  status: "in_progress" | "completed" | "failed" | "skipped",
  error?: string
): Promise<BugStatusUpdateResponse> {
  const response = await fetch(`${API_BASE}/api/v2/cccc/tasks/${jobId}/bugs/${bugIndex}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status, error }),
  });
  return handleResponse<BugStatusUpdateResponse>(response);
}

/**
 * Get the SSE stream URL for a batch job.
 * Use with EventSource to receive real-time progress updates.
 */
export function getBatchJobStreamUrl(jobId: string): string {
  return `${API_BASE}/api/v2/cccc/batch-bug-fix/${jobId}/stream`;
}
