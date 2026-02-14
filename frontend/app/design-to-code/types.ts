// ============ Design-to-Code Types ============

export type ComponentStatus = "pending" | "in_progress" | "completed" | "failed";

export interface DesignJob {
  job_id: string;
  job_status: string;
  design_file: string;
  output_dir: string;
  created_at: string;
  completed_at?: string;
  error?: string;
  components_total: number;
  components_completed: number;
  components_failed: number;
  result?: Record<string, unknown>;
}

export interface DesignJobStats {
  completed: number;
  in_progress: number;
  pending: number;
  failed: number;
  total: number;
}

// ============ SSE Pipeline Event Types ============

/** Events received from the SSE stream during pipeline execution */
export interface PipelineEvent {
  event_type: string;
  node_id?: string;
  timestamp: string;
  data?: Record<string, unknown>;
  message?: string;
}
