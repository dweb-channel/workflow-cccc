import type {
  BatchJobHistoryItem,
  JiraBug,
} from "@/lib/api";

// Re-export API types used by components
export type { BatchJobHistoryItem, JiraBug };

// ============ Local Types ============

export type StepStatus = "pending" | "in_progress" | "completed" | "failed";

export interface BugStep {
  step: string;
  label: string;
  status: StepStatus;
  started_at?: string;
  completed_at?: string;
  duration_ms?: number;
  output_preview?: string;
  error?: string;
  attempt?: number;
}

export interface BugStatus {
  bug_id: string;
  url: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped";
  error?: string;
  steps?: BugStep[];
  retry_count?: number;
}

export interface BatchJob {
  job_id: string;
  bugs: BugStatus[];
  started_at: string;
  job_status: string;
}

export type ValidationLevel = "minimal" | "standard" | "thorough";
export type FailurePolicy = "stop" | "skip" | "retry";

export interface BatchJobStats {
  completed: number;
  in_progress: number;
  pending: number;
  failed: number;
  skipped: number;
}

// ============ AI Thinking Events ============

export type AIThinkingEventType = "thinking" | "text" | "read" | "edit" | "bash" | "result";

export interface AIThinkingEventBase {
  type: AIThinkingEventType;
  timestamp: string;
  bug_index?: number;
  node_id?: string;
}

export interface AIThinkingThinkingEvent extends AIThinkingEventBase {
  type: "thinking";
  content: string;
}

export interface AIThinkingReadEvent extends AIThinkingEventBase {
  type: "read";
  file: string;
  lines?: string;
  description?: string;
}

export interface AIThinkingEditEvent extends AIThinkingEventBase {
  type: "edit";
  file: string;
  diff?: string;
  description?: string;
}

export interface AIThinkingBashEvent extends AIThinkingEventBase {
  type: "bash";
  command: string;
  output?: string;
  description?: string;
}

export interface AIThinkingTextEvent extends AIThinkingEventBase {
  type: "text";
  content: string;
}

export interface AIThinkingResultEvent extends AIThinkingEventBase {
  type: "result";
  content: string;
}

export type AIThinkingEvent =
  | AIThinkingThinkingEvent
  | AIThinkingTextEvent
  | AIThinkingReadEvent
  | AIThinkingEditEvent
  | AIThinkingBashEvent
  | AIThinkingResultEvent;

export interface AIThinkingStats {
  streaming: boolean;
  tokens_in: number;
  tokens_out: number;
  cost: number;
}

// ============ DB Sync Warnings ============

export interface DbSyncWarning {
  bug_index: number;
  message: string;
  timestamp: string;
}

// ============ Metrics Types ============

export interface StepMetrics {
  step_name: string;
  label: string;
  avg_duration_ms: number;
  success_rate: number;
  total_executions: number;
}

export interface JobMetricsSummary {
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

export interface GlobalMetrics {
  total_jobs: number;
  total_bugs: number;
  overall_success_rate: number;
  avg_bug_duration_ms: number;
  avg_job_duration_ms: number;
  step_metrics: StepMetrics[];
  recent_jobs: JobMetricsSummary[];
}
