"use client";

import { useMemo } from "react";
import { useSSEStream, type UseSSEStreamReturn } from "./useSSEStream";
import { TERMINAL_STATUSES } from "./constants";

/**
 * Thin wrapper around useSSEStream that gates connection on job lifecycle.
 * Computes SSE URL only when job is active (non-terminal), passes through
 * to useSSEStream for the actual EventSource management.
 */
export interface UsePipelineConnectionOptions {
  jobId: string | undefined;
  jobStatus: string | undefined;
  getStreamUrl: (jobId: string) => string;
  handlers: Record<string, (data: Record<string, unknown>) => void>;
  terminalEvents?: string[];
  pollFn?: () => Promise<void>;
  onError?: () => void;
  onReconnect?: () => void;
}

export function usePipelineConnection(
  options: UsePipelineConnectionOptions
): UseSSEStreamReturn {
  const {
    jobId,
    jobStatus,
    getStreamUrl,
    handlers,
    terminalEvents,
    pollFn,
    onError,
    onReconnect,
  } = options;

  const sseUrl = useMemo(() => {
    if (!jobId || !jobStatus || TERMINAL_STATUSES.includes(jobStatus)) {
      return null;
    }
    return getStreamUrl(jobId);
  }, [jobId, jobStatus, getStreamUrl]);

  return useSSEStream({
    url: sseUrl,
    handlers,
    terminalEvents,
    pollFn,
    onError,
    onReconnect,
  });
}
