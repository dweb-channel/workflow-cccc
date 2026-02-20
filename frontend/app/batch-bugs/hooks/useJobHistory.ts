import { useState, useEffect, useCallback, useRef } from "react";
import { getBatchJobHistory, getBatchJobStatus, deleteBatchJob, type BatchJobHistoryItem } from "@/lib/api";
import { useToast } from "@/components/hooks/use-toast";
import type { BatchJob } from "../types";

export function useJobHistory() {
  const { toast } = useToast();
  const [historyJobs, setHistoryJobs] = useState<BatchJobHistoryItem[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [expandedJobDetails, setExpandedJobDetails] = useState<BatchJob | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadHistory = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoadingHistory(true);
    try {
      const data = await getBatchJobHistory(historyPage, 10);
      if (controller.signal.aborted) return;
      setHistoryJobs(data.jobs);
      setHistoryTotal(data.total);
    } catch (err) {
      if (controller.signal.aborted) return;
      console.error("Failed to load history:", err);
      toast({
        title: "加载历史失败",
        description: err instanceof Error ? err.message : "请稍后重试",
        variant: "destructive",
      });
    } finally {
      if (!controller.signal.aborted) {
        setLoadingHistory(false);
      }
    }
  }, [historyPage, toast]);

  // Load history on mount and when page changes
  useEffect(() => {
    loadHistory();
    return () => { abortRef.current?.abort(); };
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
        const status = await getBatchJobStatus(jobId);
        setExpandedJobDetails({
          job_id: status.job_id,
          bugs: status.bugs.map((b, idx) => ({
            bug_id: `BUG-${idx + 1}`,
            url: b.url,
            status: b.status,
            error: b.error,
          })),
          started_at: status.created_at,
          job_status: status.status,
        });
      } catch (err) {
        console.error("Failed to load job details:", err);
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

  const deleteJob = useCallback(
    async (jobId: string) => {
      try {
        await deleteBatchJob(jobId);
        setHistoryJobs((prev) => prev.filter((j) => j.job_id !== jobId));
        setHistoryTotal((prev) => Math.max(0, prev - 1));
        if (expandedJobId === jobId) {
          setExpandedJobId(null);
          setExpandedJobDetails(null);
        }
        toast({ title: "已删除", description: jobId });
      } catch (err) {
        toast({
          title: "删除失败",
          description: err instanceof Error ? err.message : "请稍后重试",
          variant: "destructive",
        });
      }
    },
    [expandedJobId, toast]
  );

  return {
    historyJobs,
    historyPage,
    historyTotal,
    loadingHistory,
    expandedJobId,
    expandedJobDetails,
    setHistoryPage,
    loadHistory,
    toggleJobDetails,
    deleteJob,
  };
}
