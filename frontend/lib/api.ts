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

// ============ Batch Bug Fix Types ============

export interface BatchBugFixRequest {
  jira_urls: string[];
  cwd?: string;
  workspace_id?: string;
  config?: {
    validation_level?: "minimal" | "standard" | "thorough";
    failure_policy?: "stop" | "skip" | "retry";
    max_retries?: number;
  };
  dry_run?: boolean;
}

export interface DryRunBugPreview {
  url: string;
  jira_key: string;
  expected_steps: string[];
}

export interface DryRunResponse {
  dry_run: true;
  total_bugs: number;
  cwd: string;
  config: {
    validation_level: string;
    failure_policy: string;
    max_retries: number;
  };
  bugs: DryRunBugPreview[];
  expected_steps_per_bug: string[];
}

export interface BatchBugFixResponse {
  job_id: string;
  status: string;
  total_bugs: number;
  created_at: string;
}

export interface BugStepDetail {
  step: string;
  label: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  output_preview?: string;
  error?: string;
  attempt?: number;
}

export interface BugStatusDetail {
  url: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped";
  error?: string;
  started_at?: string;
  completed_at?: string;
  steps?: BugStepDetail[];
  retry_count?: number;
}

export interface BatchJobStatusResponse {
  job_id: string;
  status: string;
  total_bugs: number;
  bugs: BugStatusDetail[];
  completed: number;
  failed: number;
  skipped: number;
  in_progress: number;
  pending: number;
  created_at: string;
  updated_at?: string;
}

export interface BatchJobHistoryItem {
  job_id: string;
  status: string;
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

// ============ Batch Bug Fix API ============

export async function submitBatchBugFix(payload: BatchBugFixRequest): Promise<BatchBugFixResponse> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<BatchBugFixResponse>(response);
}

export async function submitDryRun(payload: BatchBugFixRequest): Promise<DryRunResponse> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, dry_run: true }),
  });
  return handleResponse<DryRunResponse>(response);
}

export async function getBatchJobStatus(jobId: string): Promise<BatchJobStatusResponse> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix/${jobId}`);
  return handleResponse<BatchJobStatusResponse>(response);
}

export async function cancelBatchJob(jobId: string): Promise<{ success: boolean; job_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix/${jobId}/cancel`, {
    method: "POST",
  });
  return handleResponse<{ success: boolean; job_id: string; status: string }>(response);
}

export async function deleteBatchJob(jobId: string): Promise<{ success: boolean; job_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix/${jobId}`, {
    method: "DELETE",
  });
  return handleResponse<{ success: boolean; job_id: string; status: string }>(response);
}

export async function retryBug(
  jobId: string,
  bugIndex: number
): Promise<{ success: boolean; job_id: string; status: string; message: string }> {
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix/${jobId}/retry/${bugIndex}`, {
    method: "POST",
  });
  return handleResponse<{ success: boolean; job_id: string; status: string; message: string }>(response);
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
  const response = await fetch(`${API_BASE}/api/v2/jira/query`, {
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
  const response = await fetch(`${API_BASE}/api/v2/batch/bug-fix?${params}`);
  return handleResponse<BatchJobHistoryResponse>(response);
}

/**
 * Get the most recent active (non-terminal) batch job, if any.
 * Used for page refresh recovery — restores running job state from DB.
 */
export async function getActiveJob(): Promise<BatchJobStatusResponse | null> {
  // Query for jobs with non-terminal status (started or running)
  const listResp = await getBatchJobHistory(1, 1, "started,running");
  if (listResp.jobs.length === 0) return null;
  // Fetch full status with bug details
  return getBatchJobStatus(listResp.jobs[0].job_id);
}

/**
 * Get the SSE stream URL for a batch job.
 * Use with EventSource to receive real-time progress updates.
 */
export function getBatchJobStreamUrl(jobId: string): string {
  return `${API_BASE}/api/v2/batch/bug-fix/${jobId}/stream`;
}

// ============ Metrics API ============

// Backend nested response structure
interface MetricsRawJobsSection {
  total: number;
  completed: number;
  failed: number;
  cancelled: number;
  success_rate: number;
}

interface MetricsRawBugsSection {
  total: number;
  completed: number;
  failed: number;
  skipped: number;
  success_rate: number;
}

interface MetricsRawTimingSection {
  avg_bug_ms: number;
  avg_job_ms: number;
}

interface MetricsRawStepData {
  step_name: string;
  label: string;
  avg_duration_ms: number;
  success_rate: number;
  total_executions: number;
}

interface MetricsRawResponse {
  jobs: MetricsRawJobsSection;
  bugs: MetricsRawBugsSection;
  timing: MetricsRawTimingSection;
  most_failed_steps: MetricsRawStepData[];
  recent_jobs: MetricsJobSummary[];
}

// Frontend-friendly flat types (mapped from backend)
export interface MetricsStepData {
  step_name: string;
  label: string;
  avg_duration_ms: number;
  success_rate: number;
  total_executions: number;
}

export interface MetricsJobSummary {
  job_id: string;
  status: string;
  total_bugs: number;
  completed: number;
  failed: number;
  success_rate: number;
  avg_bug_duration_ms: number;
  total_duration_ms: number;
  created_at: string;
}

export interface GlobalMetricsResponse {
  total_jobs: number;
  total_bugs: number;
  overall_success_rate: number;
  avg_bug_duration_ms: number;
  avg_job_duration_ms: number;
  step_metrics: MetricsStepData[];
  recent_jobs: MetricsJobSummary[];
}

function mapRawMetrics(raw: MetricsRawResponse): GlobalMetricsResponse {
  return {
    total_jobs: raw.jobs.total,
    total_bugs: raw.bugs.total,
    overall_success_rate: raw.bugs.success_rate,
    avg_bug_duration_ms: raw.timing.avg_bug_ms,
    avg_job_duration_ms: raw.timing.avg_job_ms,
    step_metrics: raw.most_failed_steps ?? [],
    recent_jobs: raw.recent_jobs ?? [],
  };
}

export async function getGlobalMetrics(): Promise<GlobalMetricsResponse> {
  const response = await fetch(`${API_BASE}/api/v2/batch/metrics/global`);
  const raw = await handleResponse<MetricsRawResponse>(response);
  return mapRawMetrics(raw);
}

export async function getJobMetrics(jobId: string): Promise<MetricsJobSummary> {
  const response = await fetch(`${API_BASE}/api/v2/batch/metrics/job/${jobId}`);
  return handleResponse<MetricsJobSummary>(response);
}

// ============ Workspace Types & API ============

export interface Workspace {
  id: string;
  name: string;
  repo_path: string;
  config_defaults?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_used_at?: string;
  job_count: number;
}

export interface WorkspaceListResponse {
  workspaces: Workspace[];
  total: number;
}

export interface CreateWorkspaceRequest {
  name: string;
  repo_path: string;
  config_defaults?: Record<string, unknown>;
}

export interface UpdateWorkspaceRequest {
  name?: string;
  config_defaults?: Record<string, unknown>;
}

export async function listWorkspaces(): Promise<WorkspaceListResponse> {
  const response = await fetch(`${API_BASE}/api/v2/workspaces`);
  return handleResponse<WorkspaceListResponse>(response);
}

export async function createWorkspace(payload: CreateWorkspaceRequest): Promise<Workspace> {
  const response = await fetch(`${API_BASE}/api/v2/workspaces`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<Workspace>(response);
}

export async function updateWorkspace(id: string, payload: UpdateWorkspaceRequest): Promise<Workspace> {
  const response = await fetch(`${API_BASE}/api/v2/workspaces/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return handleResponse<Workspace>(response);
}

export async function deleteWorkspace(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v2/workspaces/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: "删除失败" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "删除失败");
  }
}
