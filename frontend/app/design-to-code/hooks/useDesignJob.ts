"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import {
  submitSpecRun,
  getDesignJobStatus,
  getDesignJobStreamUrl,
  getActiveDesignJob,
  type SpecRunRequest,
  type DesignRunResponse,
} from "@/lib/api";
import { usePipelineConnection } from "@/lib/usePipelineConnection";
import { TERMINAL_STATUSES } from "@/lib/constants";
import type { DesignJob, PipelineEvent } from "../types";
import type { DesignSpec, ComponentSpec, ComponentUpdate, SemanticRole } from "@/lib/types/design-spec";
import { applyComponentUpdates } from "@/lib/types/design-spec";
const MAX_EVENTS = 500;
const TRIM_TO = 300;

export function useDesignJob() {
  const [currentJob, setCurrentJob] = useState<DesignJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [currentNode, setCurrentNode] = useState<string | null>(null);
  const [designSpec, setDesignSpec] = useState<DesignSpec | null>(null);
  const [specComplete, setSpecComplete] = useState(false);
  const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const [tokenUsage, setTokenUsage] = useState<{ input_tokens: number; output_tokens: number } | null>(null);

  // Recovery: on mount, check for active (non-terminal) job in DB
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const activeJob = await getActiveDesignJob();
        if (controller.signal.aborted || !activeJob) return;
        setCurrentJob({
          job_id: activeJob.job_id,
          job_status: activeJob.status,
          design_file: activeJob.design_file || "",
          output_dir: activeJob.output_dir,
          created_at: activeJob.created_at,
          completed_at: activeJob.completed_at,
          error: activeJob.error,
          components_total: activeJob.components_total,
          components_completed: activeJob.components_completed,
          components_failed: activeJob.components_failed,
          result: activeJob.result,
        });
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        console.warn("Failed to recover active design job on mount");
      }
    })();
    return () => controller.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
        timestamp: (data.timestamp as string) || new Date().toISOString(),
        data,
        message: (data.message as string) || undefined,
      };
      setEvents((prev) => {
        const next = [...prev, evt];
        if (next.length > MAX_EVENTS) return next.slice(next.length - TRIM_TO);
        return next;
      });
    },
    []
  );

  // --- SSE URL gated by job lifecycle (via shared helper) ---

  // --- Node event dedup ---
  const seenNodeEventsRef = useRef(new Set<string>());
  // Reset dedup set when job changes
  useEffect(() => {
    seenNodeEventsRef.current = new Set();
  }, [currentJob?.job_id]);

  // --- Ref for jobId (used in pollFn) ---
  const jobIdRef = useRef(currentJob?.job_id);
  jobIdRef.current = currentJob?.job_id;

  // --- SSE event handlers ---
  const sseHandlers = useMemo<Record<string, (data: Record<string, unknown>) => void>>(() => {
    const handleNodeEvent = (
      eventType: "node_started" | "node_completed",
      data: Record<string, unknown>
    ) => {
      const nodeId = (data.node_id as string) || (data.node as string) || null;
      const key = `${eventType}:${nodeId}:${data.timestamp || ""}`;
      if (seenNodeEventsRef.current.has(key)) return;
      seenNodeEventsRef.current.add(key);
      if (eventType === "node_started") {
        setCurrentNode(nodeId);
      }
      pushEvent(eventType, { ...data, node_id: nodeId });
    };

    return {
      job_state: (data) => {
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            job_status: (data.status as string) || prev.job_status,
            components_total: (data.components_total as number) ?? prev.components_total,
            components_completed: (data.components_completed as number) ?? prev.components_completed,
            components_failed: (data.components_failed as number) ?? prev.components_failed,
          };
        });
      },

      job_status: (data) => {
        setCurrentJob((prev) =>
          prev
            ? { ...prev, job_status: (data.status as string) || prev.job_status }
            : prev
        );
        pushEvent("job_status", data);
      },

      node_update: (data) => {
        const status = data.status as string;
        if (status === "running") {
          handleNodeEvent("node_started", data);
        } else if (status === "completed") {
          handleNodeEvent("node_completed", data);
        }
      },

      node_output: (data) => {
        pushEvent("node_output", { ...data, node_id: (data.node_id as string) || (data.node as string) });
      },

      node_started: (data) => {
        handleNodeEvent("node_started", data);
      },

      node_completed: (data) => {
        handleNodeEvent("node_completed", data);
      },

      loop_iteration: (data) => {
        pushEvent("loop_iteration", data);
      },

      loop_terminated: (data) => {
        pushEvent("loop_terminated", data);
      },

      workflow_start: (data) => {
        pushEvent("workflow_start", data);
      },

      workflow_complete: (data) => {
        pushEvent("workflow_complete", data);
      },

      workflow_error: (data) => {
        pushEvent("workflow_error", data);
      },

      figma_fetch_start: (data) => {
        pushEvent("figma_fetch_start", data);
      },

      figma_fetch_complete: (data) => {
        pushEvent("figma_fetch_complete", data);
      },

      ai_thinking: (data) => {
        pushEvent("ai_thinking", data);
      },

      // ---- Design Spec progressive rendering ----

      frame_decomposed: (data) => {
        const components = data.components as ComponentSpec[] | undefined;
        const page = data.page as DesignSpec["page"] | undefined;
        if (components && components.length > 0) {
          setDesignSpec((prev) => {
            if (!prev) {
              return {
                version: "1.0",
                source: (data.source as DesignSpec["source"]) ?? { tool: "figma", file_key: "" },
                page: page ?? {},
                design_tokens: data.design_tokens as DesignSpec["design_tokens"] | undefined,
                components,
              };
            }
            const merged = [...prev.components];
            for (const comp of components) {
              const idx = merged.findIndex((c) => c.id === comp.id);
              if (idx >= 0) {
                merged[idx] = { ...merged[idx], ...comp };
              } else {
                merged.push(comp);
              }
            }
            return { ...prev, components: merged, page: page ?? prev.page };
          });
        }
        pushEvent("frame_decomposed", data);
      },

      spec_analyzed: (data) => {
        const componentId = data.component_id as string | undefined;
        if (componentId) {
          const update: ComponentUpdate = {
            id: componentId,
            name: (data.suggested_name as string | undefined) || undefined,
            role: data.role as SemanticRole | undefined,
            description: data.description as string | undefined,
            design_analysis: data.design_analysis as string | undefined,
          };
          setDesignSpec((prev) => {
            if (!prev) return prev;
            return {
              ...prev,
              components: applyComponentUpdates(prev.components, [update]),
            };
          });
        }
        const compTokens = data.tokens_used as { input_tokens?: number; output_tokens?: number } | undefined;
        if (compTokens) {
          setTokenUsage((prev) => ({
            input_tokens: (prev?.input_tokens ?? 0) + (compTokens.input_tokens ?? 0),
            output_tokens: (prev?.output_tokens ?? 0) + (compTokens.output_tokens ?? 0),
          }));
        }
        pushEvent("spec_analyzed", data);
      },

      spec_complete: (data) => {
        setSpecComplete(true);
        if (data.validation) {
          setValidation(data.validation as Record<string, unknown>);
        }
        const totalTokens = data.token_usage as { input_tokens?: number; output_tokens?: number } | undefined;
        if (totalTokens) {
          setTokenUsage({
            input_tokens: totalTokens.input_tokens ?? 0,
            output_tokens: totalTokens.output_tokens ?? 0,
          });
        }
        pushEvent("spec_complete", data);
      },

      job_done: (data) => {
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            job_status: (data.status as string) || "completed",
            components_total: (data.components_total as number) ?? prev.components_total,
            components_completed: (data.components_completed as number) ?? prev.components_completed,
            components_failed: (data.components_failed as number) ?? prev.components_failed,
            error: (data.error as string) || undefined,
          };
        });
        pushEvent("job_done", data);
        setCurrentNode(null);
      },
    };
  }, [pushEvent]);

  // --- Fallback poll function ---
  const pollFn = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId) return;
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
  }, []);

  // --- SSE connection via shared pipeline helper ---
  const { connected: sseConnected, stale: sseStale } = usePipelineConnection({
    jobId: currentJob?.job_id,
    jobStatus: currentJob?.job_status,
    getStreamUrl: getDesignJobStreamUrl,
    handlers: sseHandlers,
    terminalEvents: ["job_done"],
    pollFn,
  });

  // --- Submit ---
  const submit = useCallback(
    async (
      request: SpecRunRequest & Record<string, unknown>
    ): Promise<DesignRunResponse | null> => {
      setSubmitting(true);
      setSubmitError(null);
      try {
        const response = await submitSpecRun(request as SpecRunRequest);
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
        setDesignSpec(null);
        setSpecComplete(false);
        setTokenUsage(null);
        setValidation(null);
        return response;
      } catch (err) {
        const msg = err instanceof Error ? err.message : "提交失败";
        setSubmitError(msg);
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    []
  );

  // --- Cancel ---
  const cancel = useCallback(async () => {
    if (!currentJob) return;
    setCurrentJob((prev) =>
      prev ? { ...prev, job_status: "cancelled" } : prev
    );
  }, [currentJob]);

  return {
    currentJob,
    submitting,
    submitError,
    stats,
    events,
    sseConnected,
    sseStale,
    currentNode,
    designSpec,
    specComplete,
    validation,
    tokenUsage,
    submit,
    cancel,
  };
}
