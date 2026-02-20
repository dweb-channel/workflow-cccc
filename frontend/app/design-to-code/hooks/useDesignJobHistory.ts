import { useState, useEffect, useCallback } from "react";
import { getDesignJobHistory, getDesignJobStatus, type DesignJobStatusResponse } from "@/lib/api";
import { useToast } from "@/components/hooks/use-toast";
import type { DesignJob } from "../types";

export interface DesignJobHistoryItem {
  job_id: string;
  status: string;
  created_at: string;
  completed_at?: string;
  components_total: number;
  components_completed: number;
  components_failed: number;
}

export function useDesignJobHistory() {
  const { toast } = useToast();
  const [historyJobs, setHistoryJobs] = useState<DesignJobHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [expandedJobDetails, setExpandedJobDetails] = useState<DesignJob | null>(null);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const jobs = await getDesignJobHistory();
      setHistoryJobs(
        jobs.map((j) => ({
          job_id: j.job_id,
          status: j.status,
          created_at: j.created_at,
          completed_at: j.completed_at,
          components_total: j.components_total,
          components_completed: j.components_completed,
          components_failed: j.components_failed,
        }))
      );
    } catch (err) {
      console.error("Failed to load design job history:", err);
      toast({
        title: "加载历史失败",
        description: err instanceof Error ? err.message : "请稍后重试",
        variant: "destructive",
      });
    } finally {
      setLoadingHistory(false);
    }
  }, [toast]);

  // Load history on mount
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const toggleJobDetails = useCallback(
    async (jobId: string) => {
      if (expandedJobId === jobId) {
        setExpandedJobId(null);
        setExpandedJobDetails(null);
        return;
      }

      setExpandedJobId(jobId);
      try {
        const status = await getDesignJobStatus(jobId);
        setExpandedJobDetails({
          job_id: status.job_id,
          job_status: status.status,
          design_file: status.design_file || "",
          output_dir: status.output_dir,
          created_at: status.created_at,
          completed_at: status.completed_at,
          error: status.error,
          components_total: status.components_total,
          components_completed: status.components_completed,
          components_failed: status.components_failed,
          result: status.result,
        });
      } catch (err) {
        console.error("Failed to load design job details:", err);
        setExpandedJobId(null);
        toast({
          title: "加载详情失败",
          description: err instanceof Error ? err.message : "请稍后重试",
          variant: "destructive",
        });
      }
    },
    [expandedJobId, toast]
  );

  return {
    historyJobs,
    loadingHistory,
    expandedJobId,
    expandedJobDetails,
    loadHistory,
    toggleJobDetails,
  };
}
