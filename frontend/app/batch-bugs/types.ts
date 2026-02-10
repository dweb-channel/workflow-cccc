import type {
  CCCCGroup,
  CCCCPeer,
  BatchJobHistoryItem,
  JiraBug,
} from "@/lib/api";

// Re-export API types used by components
export type { CCCCGroup, CCCCPeer, BatchJobHistoryItem, JiraBug };

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
