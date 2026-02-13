import { useState, useEffect, useCallback, useRef } from "react";
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
import type { BatchJob, BugStatus, BugStep, BatchJobStats, AIThinkingEvent, AIThinkingStats } from "../types";

/** Safe JSON.parse — returns null on failure instead of throwing */
function safeParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Exponential backoff: 3s → 6s → 12s → 24s → 30s cap */
function getBackoffMs(retryCount: number): number {
  return Math.min(3000 * Math.pow(2, retryCount), 30000);
}

const FALLBACK_POLL_INTERVAL = 30_000; // 30s

export function useBatchJob() {
  const { toast } = useToast();
  const [currentJob, setCurrentJob] = useState<BatchJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const sseRetryCount = useRef(0);
  const sseErrorToastShown = useRef(false);
  const [sseConnected, setSseConnected] = useState(true);

  // AI Thinking state
  const [aiThinkingEvents, setAiThinkingEvents] = useState<AIThinkingEvent[]>([]);
  const [aiThinkingStats, setAiThinkingStats] = useState<AIThinkingStats>({
    streaming: false,
    tokens_in: 0,
    tokens_out: 0,
    cost: 0,
  });

  // Recovery: on mount, check for active (non-terminal) job in DB
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const activeJob = await getActiveJob();
        if (cancelled || !activeJob) return;
        // Restore currentJob state from DB response
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
        // Recovery failure is non-critical — user can start a new job
        console.warn("Failed to recover active job on mount");
      }
    })();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // SSE stream for real-time job status updates
  useEffect(() => {
    if (
      !currentJob ||
      currentJob.job_status === "completed" ||
      currentJob.job_status === "failed" ||
      currentJob.job_status === "cancelled"
    ) {
      return;
    }

    const jobId = currentJob.job_id;
    sseRetryCount.current = 0;
    sseErrorToastShown.current = false;

    const streamUrl = getBatchJobStreamUrl(jobId);
    const eventSource = new EventSource(streamUrl);

    // Helper to update a specific bug by index
    const updateBug = (
      bugIndex: number,
      updater: (bug: BugStatus) => BugStatus
    ) => {
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
    };

    eventSource.addEventListener("job_state", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data) return;
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
    });

    eventSource.addEventListener("bug_started", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "in_progress" as const,
        steps: [],
      }));
    });

    eventSource.addEventListener("bug_completed", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "completed" as const,
        retry_count: (data.retry_count as number) ?? bug.retry_count,
      }));
    });

    eventSource.addEventListener("bug_failed", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => ({
        ...bug,
        status: "failed" as const,
        error: (data.error as string) ?? bug.error,
        retry_count: (data.retry_count as number) ?? bug.retry_count,
      }));
    });

    // Step-level SSE events
    eventSource.addEventListener("bug_step_started", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
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
    });

    eventSource.addEventListener("bug_step_completed", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => {
        const steps = [...(bug.steps ?? [])];
        let found = false;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (
            steps[i].step === data.step &&
            steps[i].status === "in_progress"
          ) {
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
        // If no in_progress step found (started event missed), create completed entry
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
    });

    eventSource.addEventListener("bug_step_failed", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || typeof data.bug_index !== "number") return;
      updateBug(data.bug_index, (bug) => {
        const steps = [...(bug.steps ?? [])];
        let found = false;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (
            steps[i].step === data.step &&
            steps[i].status === "in_progress"
          ) {
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
        // If no in_progress step found (started event missed), create failed entry
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
    });

    // AI Thinking events
    eventSource.addEventListener("ai_thinking", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data || !data.type) return;
      const event = data as unknown as AIThinkingEvent;
      setAiThinkingEvents((prev) => [...prev, event]);
      setAiThinkingStats((prev) => ({ ...prev, streaming: true }));
    });

    eventSource.addEventListener("ai_thinking_stats", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data) return;
      setAiThinkingStats((prev) => ({
        ...prev,
        tokens_in: (data.tokens_in as number) ?? prev.tokens_in,
        tokens_out: (data.tokens_out as number) ?? prev.tokens_out,
        cost: (data.cost as number) ?? prev.cost,
      }));
    });

    eventSource.addEventListener("job_done", (e) => {
      const data = safeParse(e.data) as Record<string, unknown> | null;
      if (!data) return;
      setCurrentJob((prev) =>
        prev ? { ...prev, job_status: (data.status as string) ?? prev.job_status } : prev
      );
      setAiThinkingStats((prev) => ({ ...prev, streaming: false }));
      eventSource.close();
    });

    // SSE error handler with backoff awareness
    eventSource.onerror = () => {
      sseRetryCount.current += 1;
      setSseConnected(false);
      const backoff = getBackoffMs(sseRetryCount.current);
      console.warn(
        `SSE connection error (retry #${sseRetryCount.current}, next in ~${backoff / 1000}s)`
      );
      // Show toast once on first error
      if (!sseErrorToastShown.current) {
        sseErrorToastShown.current = true;
        toast({
          title: "连接中断",
          description: "实时更新暂时不可用，正在尝试重连…",
          variant: "destructive",
        });
      }
    };

    eventSource.onopen = () => {
      setSseConnected(true);
      // Connection restored — reset retry state
      if (sseRetryCount.current > 0) {
        sseRetryCount.current = 0;
        sseErrorToastShown.current = false;
        toast({
          title: "连接恢复",
          description: "实时更新已恢复",
        });
      }
    };

    // Fallback polling: GET job status every 30s to catch missed SSE events
    const pollTimer = setInterval(async () => {
      try {
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
                // Keep SSE-derived steps and retry_count (not in BugStatusDetail)
                steps: bug.steps && bug.steps.length > 0 ? bug.steps : undefined,
                retry_count: bug.retry_count,
              };
            }),
          };
        });
      } catch {
        // Polling failure is non-critical — SSE is primary channel
        console.warn("Fallback poll failed, will retry next interval");
      }
    }, FALLBACK_POLL_INTERVAL);

    return () => {
      eventSource.close();
      clearInterval(pollTimer);
    };
  }, [currentJob?.job_id, currentJob?.job_status, toast]);

  // Submit a new batch job — also resets AI thinking state
  const submit = useCallback(
    async (request: BatchBugFixRequest) => {
      setSubmitting(true);
      setAiThinkingEvents([]);
      setAiThinkingStats({ streaming: false, tokens_in: 0, tokens_out: 0, cost: 0 });
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
    try {
      await retryBugApi(currentJob.job_id, bugIndex);
      // Reset local bug state and mark job as running to reconnect SSE
      setCurrentJob((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          job_status: "running",
          bugs: prev.bugs.map((bug, idx) =>
            idx === bugIndex
              ? { ...bug, status: "pending" as const, error: undefined, steps: [] }
              : bug
          ),
        };
      });
      // Clear AI thinking events for the retried bug
      setAiThinkingEvents((prev) => prev.filter((e) => e.bug_index !== bugIndex));
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
        completed: currentJob.bugs.filter((b) => b.status === "completed")
          .length,
        in_progress: currentJob.bugs.filter((b) => b.status === "in_progress")
          .length,
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
    aiThinkingEvents,
    aiThinkingStats,
  };
}
