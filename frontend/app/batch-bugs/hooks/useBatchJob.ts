import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  submitBatchBugFix,
  getBatchJobStreamUrl,
  getBatchJobStatus,
  cancelBatchJob,
  retryBug as retryBugApi,
  getActiveJob,
  type BatchBugFixRequest,
} from "@/lib/api";
import { useToast } from "@/components/hooks/use-toast";
import { useSSEStream } from "@/lib/useSSEStream";
import type { BatchJob, BugStatus, BugStep, BatchJobStats, AIThinkingEvent, AIThinkingStats, DbSyncWarning } from "../types";

const TERMINAL_STATUSES = ["completed", "failed", "cancelled"];

export function useBatchJob() {
  const { toast } = useToast();
  const [currentJob, setCurrentJob] = useState<BatchJob | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // AI Thinking state
  const [aiThinkingEvents, setAiThinkingEvents] = useState<AIThinkingEvent[]>([]);
  const [aiThinkingStats, setAiThinkingStats] = useState<AIThinkingStats>({
    streaming: false,
    tokens_in: 0,
    tokens_out: 0,
    cost: 0,
  });

  // DB sync warnings
  const [dbSyncWarnings, setDbSyncWarnings] = useState<DbSyncWarning[]>([]);

  // Refs for toast (used in SSE callbacks without causing re-renders)
  const toastRef = useRef(toast);
  toastRef.current = toast;

  // Recovery: on mount, check for active (non-terminal) job in DB
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const activeJob = await getActiveJob();
        if (cancelled || !activeJob) return;
        const bugs: BugStatus[] = activeJob.bugs.map((b, idx) => ({
          bug_id: `BUG-${idx + 1}`,
          url: b.url,
          status: b.status,
          error: b.error,
          steps: b.steps,
          retry_count: b.retry_count,
        }));
        setCurrentJob({
          job_id: activeJob.job_id,
          bugs,
          started_at: activeJob.created_at,
          job_status: activeJob.status,
        });
      } catch {
        console.warn("Failed to recover active job on mount");
      }
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // --- SSE URL: non-null only when job is active ---
  const sseUrl = useMemo(() => {
    if (!currentJob || TERMINAL_STATUSES.includes(currentJob.job_status)) {
      return null;
    }
    return getBatchJobStreamUrl(currentJob.job_id);
  }, [currentJob?.job_id, currentJob?.job_status]); // eslint-disable-line react-hooks/exhaustive-deps

  // --- Helper to update a specific bug by index ---
  const updateBug = useCallback(
    (bugIndex: number, updater: (bug: BugStatus) => BugStatus) => {
      setCurrentJob((prev) =>
        prev
          ? {
              ...prev,
              bugs: prev.bugs.map((bug, idx) =>
                idx === bugIndex ? updater(bug) : bug
              ),
            }
          : prev
      );
    },
    []
  );

  // --- SSE event handlers ---
  const jobIdRef = useRef(currentJob?.job_id);
  jobIdRef.current = currentJob?.job_id;

  const sseHandlers = useMemo<Record<string, (data: Record<string, unknown>) => void>>(() => ({
    job_state: (data) => {
      setCurrentJob((prev) =>
        prev
          ? {
              ...prev,
              job_status: (data.status as string) ?? prev.job_status,
              bugs: prev.bugs.map((bug, idx) => {
                const bugData = (data.bugs as Record<string, unknown>[] | undefined)?.[idx];
                return {
                  ...bug,
                  status: (bugData?.status as BugStatus["status"]) ?? bug.status,
                  error: bugData?.error as string | undefined,
                  steps: (bugData?.steps as BugStep[]) ?? bug.steps,
                  retry_count: (bugData?.retry_count as number) ?? bug.retry_count,
                };
              }),
            }
          : prev
      );
    },

    bug_started: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "in_progress" as const,
        steps: [],
      }));
    },

    bug_completed: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "completed" as const,
        retry_count: (data.retry_count as number) ?? bug.retry_count,
      }));
    },

    bug_failed: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "failed" as const,
        error: (data.error as string) ?? bug.error,
        retry_count: (data.retry_count as number) ?? bug.retry_count,
      }));
    },

    bug_skipped: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "skipped" as const,
        error: (data.reason as string) ?? bug.error,
      }));
    },

    bug_step_started: (data) => {
      if (typeof data.bug_index !== "number") return;
      const newStep: BugStep = {
        step: data.step as string,
        label: data.label as string,
        status: "in_progress",
        started_at: data.timestamp as string,
        attempt: data.attempt as number | undefined,
      };
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        steps: [...(bug.steps ?? []), newStep],
      }));
    },

    bug_step_completed: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => {
        const steps = [...(bug.steps ?? [])];
        let found = false;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].step === data.step && steps[i].status === "in_progress") {
            steps[i] = {
              ...steps[i],
              status: "completed",
              completed_at: data.timestamp as string,
              duration_ms: data.duration_ms as number | undefined,
              output_preview: data.output_preview as string | undefined,
            };
            found = true;
            break;
          }
        }
        if (!found) {
          steps.push({
            step: data.step as string,
            label: (data.label as string) || (data.step as string),
            status: "completed",
            completed_at: data.timestamp as string,
            duration_ms: data.duration_ms as number | undefined,
            output_preview: data.output_preview as string | undefined,
            attempt: data.attempt as number | undefined,
          });
        }
        return { ...bug, steps };
      });
    },

    bug_step_failed: (data) => {
      if (typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => {
        const steps = [...(bug.steps ?? [])];
        let found = false;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].step === data.step && steps[i].status === "in_progress") {
            steps[i] = {
              ...steps[i],
              status: "failed",
              completed_at: data.timestamp as string,
              error: data.error as string | undefined,
            };
            found = true;
            break;
          }
        }
        if (!found) {
          steps.push({
            step: data.step as string,
            label: (data.label as string) || (data.step as string),
            status: "failed",
            completed_at: data.timestamp as string,
            error: data.error as string | undefined,
            attempt: data.attempt as number | undefined,
          });
        }
        return { ...bug, steps };
      });
    },

    ai_thinking: (data) => {
      if (!data.type) return;
      const event = data as unknown as AIThinkingEvent;
      setAiThinkingEvents((prev) => {
        const next = [...prev, event];
        return next.length > 2000 ? next.slice(-1500) : next;
      });
      setAiThinkingStats((prev) => ({ ...prev, streaming: true }));
    },

    ai_thinking_stats: (data) => {
      setAiThinkingStats((prev) => ({
        ...prev,
        tokens_in: (data.tokens_in as number) ?? prev.tokens_in,
        tokens_out: (data.tokens_out as number) ?? prev.tokens_out,
        cost: (data.cost as number) ?? prev.cost,
      }));
    },

    db_sync_warning: (data) => {
      setDbSyncWarnings((prev) => [
        ...prev,
        {
          bug_index: (data.bug_index as number) ?? -1,
          message: (data.message as string) ?? "数据库同步失败",
          timestamp: (data.timestamp as string) ?? new Date().toISOString(),
        },
      ]);
    },

    preflight_failed: (data) => {
      const errors = (data.errors as string[]) ?? [];
      toastRef.current({
        title: "环境检查失败",
        description: errors.join("\n") || "Pre-flight 检查未通过",
        variant: "destructive",
      });
    },

    job_done: (data) => {
      setCurrentJob((prev) =>
        prev ? { ...prev, job_status: (data.status as string) ?? prev.job_status } : prev
      );
      setAiThinkingStats((prev) => ({ ...prev, streaming: false }));
    },
  }), [updateBug]);

  // --- Fallback poll function ---
  const pollFn = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId) return;
    const status = await getBatchJobStatus(jobId);
    setCurrentJob((prev) => {
      if (!prev || prev.job_id !== jobId) return prev;
      return {
        ...prev,
        job_status: status.status,
        bugs: prev.bugs.map((bug, idx) => {
          const apiBug = status.bugs?.[idx];
          if (!apiBug) return bug;
          return {
            ...bug,
            status: apiBug.status ?? bug.status,
            error: apiBug.error ?? bug.error,
            steps: bug.steps && bug.steps.length > 0 ? bug.steps : undefined,
            retry_count: bug.retry_count,
          };
        }),
      };
    });
  }, []);

  // --- SSE connection via shared hook ---
  const { connected: sseConnected, stale: sseStale } = useSSEStream({
    url: sseUrl,
    handlers: sseHandlers,
    terminalEvents: ["job_done"],
    pollFn,
    onError: () => {
      toastRef.current({
        title: "连接中断",
        description: "实时更新暂时不可用，正在尝试重连…",
        variant: "destructive",
      });
    },
    onReconnect: () => {
      toastRef.current({
        title: "连接恢复",
        description: "实时更新已恢复",
      });
    },
  });

  // Submit a new batch job — also resets AI thinking state
  const submit = useCallback(
    async (request: BatchBugFixRequest) => {
      setSubmitting(true);
      setAiThinkingEvents([]);
      setAiThinkingStats({ streaming: false, tokens_in: 0, tokens_out: 0, cost: 0 });
      setDbSyncWarnings([]);
      try {
        const data = await submitBatchBugFix(request);

        const bugs: BugStatus[] = request.jira_urls.map((url, index) => ({
          bug_id: `BUG-${index + 1}`,
          url,
          status: "pending",
        }));

        setCurrentJob({
          job_id: data.job_id,
          bugs,
          started_at: data.created_at,
          job_status: data.status,
        });

        toast({
          title: "任务已提交",
          description: `开始修复 ${data.total_bugs} 个 Bug (Job: ${data.job_id})`,
        });

        return data;
      } catch (err) {
        toast({
          title: "提交失败",
          description: err instanceof Error ? err.message : "未知错误",
          variant: "destructive",
        });
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [toast]
  );

  // Cancel the current job
  const cancel = useCallback(async () => {
    if (!currentJob) return;
    try {
      await cancelBatchJob(currentJob.job_id);
      setCurrentJob((prev) =>
        prev ? { ...prev, job_status: "cancelled" } : prev
      );
      toast({
        title: "任务已取消",
        description: `Job ${currentJob.job_id} 已取消`,
      });
    } catch (err) {
      toast({
        title: "取消失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    }
  }, [currentJob, toast]);

  // Retry a single failed bug
  const retryBug = useCallback(async (bugIndex: number) => {
    if (!currentJob) return;
    // Guard: don't allow retry if job is terminal or bug is not failed
    if (TERMINAL_STATUSES.includes(currentJob.job_status)) {
      toast({
        title: "无法重试",
        description: `任务已${currentJob.job_status === "completed" ? "完成" : currentJob.job_status === "cancelled" ? "取消" : "结束"}，无法重试单个 Bug`,
        variant: "destructive",
      });
      return;
    }
    const targetBug = currentJob.bugs[bugIndex];
    if (!targetBug || targetBug.status !== "failed") {
      return;
    }
    try {
      await retryBugApi(currentJob.job_id, bugIndex);
      setCurrentJob((prev) => {
        if (!prev) return prev;
        // Double-check: don't overwrite terminal job_status
        const nextJobStatus = TERMINAL_STATUSES.includes(prev.job_status)
          ? prev.job_status
          : "running";
        return {
          ...prev,
          job_status: nextJobStatus,
          bugs: prev.bugs.map((bug, idx) =>
            idx === bugIndex
              ? { ...bug, status: "pending" as const, error: undefined, steps: [] }
              : bug
          ),
        };
      });
      setAiThinkingEvents((prev) => prev.filter((e) => e.bug_index === undefined || e.bug_index !== bugIndex));
      toast({
        title: "重试已启动",
        description: `Bug ${bugIndex + 1} 正在重新修复`,
      });
    } catch (err) {
      toast({
        title: "重试失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    }
  }, [currentJob, toast]);

  // Calculate stats
  const stats: BatchJobStats = currentJob
    ? {
        completed: currentJob.bugs.filter((b) => b.status === "completed").length,
        in_progress: currentJob.bugs.filter((b) => b.status === "in_progress").length,
        pending: currentJob.bugs.filter((b) => b.status === "pending").length,
        failed: currentJob.bugs.filter((b) => b.status === "failed").length,
        skipped: currentJob.bugs.filter((b) => b.status === "skipped").length,
      }
    : { completed: 0, in_progress: 0, pending: 0, failed: 0, skipped: 0 };

  return {
    currentJob,
    submitting,
    stats,
    submit,
    cancel,
    retryBug,
    sseConnected,
    sseStale,
    aiThinkingEvents,
    aiThinkingStats,
    dbSyncWarnings,
  };
}
