"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import {
  submitDesignRun,
  submitFigmaRun,
  getDesignJobStatus,
  getDesignJobStreamUrl,
  type DesignRunRequest,
  type FigmaRunRequest,
  type DesignRunResponse,
} from "@/lib/api";
import type { DesignJob, PipelineEvent } from "../types";

/** Safe JSON.parse — returns null on failure */
function safeParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

const SSE_INITIAL_RETRY_MS = 3000;
const SSE_MAX_RETRY_MS = 30000;
const POLL_INTERVAL_MS = 30000;
const MAX_EVENTS = 500;
const TRIM_TO = 300;

export function useDesignJob() {
  const [currentJob, setCurrentJob] = useState<DesignJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [sseConnected, setSseConnected] = useState(false);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [currentNode, setCurrentNode] = useState<string | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  const retryCountRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- Computed Stats ---
  const stats = currentJob
    ? {
        completed: currentJob.components_completed,
        failed: currentJob.components_failed,
        total: currentJob.components_total,
        in_progress: currentJob.job_status === "running" ? 1 : 0,
        pending: Math.max(
          0,
          currentJob.components_total -
            currentJob.components_completed -
            currentJob.components_failed
        ),
      }
    : { completed: 0, in_progress: 0, pending: 0, failed: 0, total: 0 };

  // --- Add pipeline event to feed ---
  const pushEvent = useCallback(
    (eventType: string, data: Record<string, unknown>) => {
      const evt: PipelineEvent = {
        event_type: eventType,
        node_id: (data.node_id as string) || undefined,
        timestamp:
          (data.timestamp as string) || new Date().toISOString(),
        data,
        message: (data.message as string) || undefined,
      };
      setEvents((prev) => {
        const next = [...prev, evt];
        if (next.length > MAX_EVENTS)
          return next.slice(next.length - TRIM_TO);
        return next;
      });
    },
    []
  );

  // --- SSE Connection ---
  const connectSSE = useCallback(
    (jobId: string) => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      const url = getDesignJobStreamUrl(jobId);
      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.onopen = () => {
        setSseConnected(true);
        retryCountRef.current = 0;
      };

      // Initial job state
      es.addEventListener("job_state", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            job_status: (data.status as string) || prev.job_status,
            components_total:
              (data.components_total as number) ?? prev.components_total,
            components_completed:
              (data.components_completed as number) ??
              prev.components_completed,
            components_failed:
              (data.components_failed as number) ?? prev.components_failed,
          };
        });
      });

      // Job status updates
      es.addEventListener("job_status", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        setCurrentJob((prev) =>
          prev
            ? { ...prev, job_status: (data.status as string) || prev.job_status }
            : prev
        );
        pushEvent("job_status", data);
      });

      // Node lifecycle — backend sends "node_update" with status field.
      // We normalize to node_started/node_completed for the UI.
      // Dedup: track seen events to avoid double-processing if backend
      // ever sends both node_update and node_started/node_completed.
      const seenNodeEvents = new Set<string>();
      const handleNodeEvent = (
        eventType: "node_started" | "node_completed",
        data: Record<string, unknown>
      ) => {
        const nodeId = (data.node_id as string) || (data.node as string) || null;
        const key = `${eventType}:${nodeId}:${data.timestamp || ""}`;
        if (seenNodeEvents.has(key)) return;
        seenNodeEvents.add(key);
        if (eventType === "node_started") {
          setCurrentNode(nodeId);
        }
        pushEvent(eventType, { ...data, node_id: nodeId });
      };

      es.addEventListener("node_update", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        const status = data.status as string;
        if (status === "running") {
          handleNodeEvent("node_started", data);
        } else if (status === "completed") {
          handleNodeEvent("node_completed", data);
        }
      });

      es.addEventListener("node_output", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("node_output", { ...data, node_id: (data.node_id as string) || (data.node as string) });
      });

      es.addEventListener("node_started", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        handleNodeEvent("node_started", data);
      });

      es.addEventListener("node_completed", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        handleNodeEvent("node_completed", data);
      });

      // Component loop events
      es.addEventListener("loop_iteration", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("loop_iteration", data);
      });

      es.addEventListener("loop_terminated", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("loop_terminated", data);
      });

      // Workflow lifecycle
      es.addEventListener("workflow_start", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("workflow_start", data);
      });

      es.addEventListener("workflow_complete", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("workflow_complete", data);
      });

      es.addEventListener("workflow_error", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("workflow_error", data);
      });

      // Figma fetch events (run-figma pipeline)
      es.addEventListener("figma_fetch_start", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("figma_fetch_start", data);
      });

      es.addEventListener("figma_fetch_complete", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("figma_fetch_complete", data);
      });

      // AI thinking events (if nodes push them)
      es.addEventListener("ai_thinking", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        pushEvent("ai_thinking", data);
      });

      // Final event — always sent
      es.addEventListener("job_done", (e) => {
        const data = safeParse(e.data) as Record<string, unknown> | null;
        if (!data) return;
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            job_status: (data.status as string) || "completed",
            components_total:
              (data.components_total as number) ?? prev.components_total,
            components_completed:
              (data.components_completed as number) ??
              prev.components_completed,
            components_failed:
              (data.components_failed as number) ?? prev.components_failed,
            error: (data.error as string) || undefined,
          };
        });
        pushEvent("job_done", data);
        es.close();
        setSseConnected(false);
        setCurrentNode(null);
      });

      es.onerror = () => {
        setSseConnected(false);
        es.close();
        // Exponential backoff retry
        const delay = Math.min(
          SSE_INITIAL_RETRY_MS * Math.pow(2, retryCountRef.current),
          SSE_MAX_RETRY_MS
        );
        retryCountRef.current++;
        setTimeout(() => {
          setCurrentJob((prev) => {
            if (
              prev &&
              !["completed", "failed", "cancelled"].includes(prev.job_status)
            ) {
              connectSSE(jobId);
            }
            return prev;
          });
        }, delay);
      };
    },
    [pushEvent]
  );

  // --- Fallback Polling ---
  const startPolling = useCallback((jobId: string) => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      try {
        const status = await getDesignJobStatus(jobId);
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            job_status: status.status,
            components_total: status.components_total,
            components_completed: status.components_completed,
            components_failed: status.components_failed,
            error: status.error || prev.error,
          };
        });
        if (["completed", "failed", "cancelled"].includes(status.status)) {
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
        }
      } catch {
        // Ignore polling errors
      }
    }, POLL_INTERVAL_MS);
  }, []);

  // --- Submit ---
  const submit = useCallback(
    async (
      request: DesignRunRequest | FigmaRunRequest
    ): Promise<DesignRunResponse | null> => {
      setSubmitting(true);
      setSubmitError(null);
      try {
        const isFigma = "figma_url" in request;
        const response = isFigma
          ? await submitFigmaRun(request as FigmaRunRequest)
          : await submitDesignRun(request as DesignRunRequest);
        const job: DesignJob = {
          job_id: response.job_id,
          job_status: response.status,
          design_file: response.design_file || "",
          output_dir: response.output_dir,
          created_at: response.created_at,
          components_total: 0,
          components_completed: 0,
          components_failed: 0,
        };
        setCurrentJob(job);
        setEvents([]);
        setCurrentNode(null);
        connectSSE(response.job_id);
        startPolling(response.job_id);
        return response;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "提交失败";
        setSubmitError(msg);
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [connectSSE, startPolling]
  );

  // --- Cancel ---
  const cancel = useCallback(async () => {
    if (!currentJob) return;
    setCurrentJob((prev) =>
      prev ? { ...prev, job_status: "cancelled" } : prev
    );
    eventSourceRef.current?.close();
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  }, [currentJob]);

  // --- Cleanup ---
  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  return {
    currentJob,
    submitting,
    submitError,
    stats,
    events,
    sseConnected,
    currentNode,
    submit,
    cancel,
  };
}
