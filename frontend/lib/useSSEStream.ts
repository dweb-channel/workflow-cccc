"use client";

import { useState, useEffect, useRef } from "react";

// ---------------------------------------------------------------------------
// Shared utilities
// ---------------------------------------------------------------------------

/** Safe JSON.parse — returns null on failure instead of throwing */
export function safeParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/** Exponential backoff: baseMs → baseMs*2 → baseMs*4 → … → maxMs cap */
function getBackoffMs(
  retryCount: number,
  baseMs: number,
  maxMs: number
): number {
  return Math.min(baseMs * Math.pow(2, retryCount), maxMs);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UseSSEStreamOptions {
  /**
   * URL to connect EventSource to.
   * `null` or `undefined` means "don't connect" — use this to control
   * lifecycle (e.g. set to null when job is terminal).
   */
  url: string | null | undefined;

  /**
   * Map of SSE event type → handler.
   * Each handler receives the parsed JSON payload of that event.
   * Handlers are stored by ref — updating them does NOT trigger reconnection.
   */
  handlers: Record<string, (data: Record<string, unknown>) => void>;

  /**
   * Event types that signal the stream is done (e.g. `["job_done"]`).
   * When received, EventSource is closed and no reconnection is attempted.
   */
  terminalEvents?: string[];

  /**
   * Optional fallback poll function, called every `pollIntervalMs`.
   * Errors thrown by this function are silently caught (polling is best-effort).
   */
  pollFn?: () => Promise<void>;

  /** Poll interval in ms (default 30 000) */
  pollIntervalMs?: number;

  /**
   * Heartbeat timeout in ms.
   * If no SSE event is received for this long, `stale` becomes `true`.
   * Set to 0 to disable. Default: 60 000.
   */
  heartbeatTimeoutMs?: number;

  /** Backoff base in ms (default 3 000) */
  backoffBaseMs?: number;

  /** Max backoff in ms (default 30 000) */
  backoffMaxMs?: number;

  /** Called once on first SSE error per connection cycle (useful for toast) */
  onError?: () => void;

  /** Called when connection restores after one or more errors (useful for toast) */
  onReconnect?: () => void;
}

export interface UseSSEStreamReturn {
  /** Whether EventSource is currently open */
  connected: boolean;

  /**
   * `true` when connected but no SSE event received for longer than
   * `heartbeatTimeoutMs`. Resets to `false` on next event or reconnect.
   */
  stale: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSSEStream(options: UseSSEStreamOptions): UseSSEStreamReturn {
  const {
    url,
    pollIntervalMs = 30_000,
    heartbeatTimeoutMs = 60_000,
    backoffBaseMs = 3_000,
    backoffMaxMs = 30_000,
  } = options;

  const [connected, setConnected] = useState(false);
  const [stale, setStale] = useState(false);

  // --- Mutable refs so EventSource listeners always read latest values ---
  const handlersRef = useRef(options.handlers);
  handlersRef.current = options.handlers;

  const pollFnRef = useRef(options.pollFn);
  pollFnRef.current = options.pollFn;

  const onErrorRef = useRef(options.onError);
  onErrorRef.current = options.onError;

  const onReconnectRef = useRef(options.onReconnect);
  onReconnectRef.current = options.onReconnect;

  const terminalEventsRef = useRef(options.terminalEvents ?? []);
  terminalEventsRef.current = options.terminalEvents ?? [];

  // --- Internal state refs ---
  const retryCountRef = useRef(0);
  const errorFiredRef = useRef(false);
  const closedIntentionallyRef = useRef(false);
  const heartbeatTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!url) {
      setConnected(false);
      setStale(false);
      return;
    }

    let eventSource: EventSource | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let destroyed = false;

    retryCountRef.current = 0;
    errorFiredRef.current = false;
    closedIntentionallyRef.current = false;

    // -- Heartbeat helpers --
    const clearHeartbeat = () => {
      if (heartbeatTimerRef.current) {
        clearTimeout(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
    };

    const resetHeartbeat = () => {
      if (heartbeatTimeoutMs <= 0) return;
      clearHeartbeat();
      setStale(false);
      heartbeatTimerRef.current = setTimeout(() => {
        setStale(true);
      }, heartbeatTimeoutMs);
    };

    // -- Connection --
    const connect = () => {
      if (destroyed) return;

      const es = new EventSource(url);
      eventSource = es;

      es.onopen = () => {
        setConnected(true);
        setStale(false);
        resetHeartbeat();
        // If we had errors before, this is a reconnect
        if (retryCountRef.current > 0) {
          retryCountRef.current = 0;
          errorFiredRef.current = false;
          onReconnectRef.current?.();
        }
      };

      // Collect unique event types to register (handlers + terminal)
      const handlerKeys = Object.keys(handlersRef.current);
      const terminalKeys = terminalEventsRef.current;
      const seen: Record<string, boolean> = {};
      const eventTypes: string[] = [];
      for (const k of handlerKeys) {
        if (!seen[k]) { seen[k] = true; eventTypes.push(k); }
      }
      for (const k of terminalKeys) {
        if (!seen[k]) { seen[k] = true; eventTypes.push(k); }
      }

      for (const eventType of eventTypes) {
        es.addEventListener(eventType, (e: MessageEvent) => {
          resetHeartbeat();
          const data = safeParse(e.data) as Record<string, unknown> | null;
          if (!data) return;

          // Dispatch to handler if one exists
          handlersRef.current[eventType]?.(data);

          // Auto-close on terminal events
          if (terminalEventsRef.current.includes(eventType)) {
            closedIntentionallyRef.current = true;
            es.close();
            setConnected(false);
            clearHeartbeat();
          }
        });
      }

      es.onerror = () => {
        setConnected(false);
        clearHeartbeat();
        es.close();

        if (closedIntentionallyRef.current || destroyed) return;

        // Fire onError callback once per connection cycle
        if (!errorFiredRef.current) {
          errorFiredRef.current = true;
          onErrorRef.current?.();
        }

        // Reconnect with exponential backoff
        const delay = getBackoffMs(
          retryCountRef.current,
          backoffBaseMs,
          backoffMaxMs
        );
        retryCountRef.current++;
        retryTimer = setTimeout(connect, delay);
      };
    };

    // Start connection
    connect();

    // Start fallback polling
    pollTimer = setInterval(() => {
      pollFnRef.current?.().catch(() => {
        // Polling failure is non-critical — SSE is the primary channel
      });
    }, pollIntervalMs);

    // Cleanup
    return () => {
      destroyed = true;
      closedIntentionallyRef.current = true;
      eventSource?.close();
      clearHeartbeat();
      if (pollTimer) clearInterval(pollTimer);
      if (retryTimer) clearTimeout(retryTimer);
      setConnected(false);
      setStale(false);
    };
  }, [url, heartbeatTimeoutMs, pollIntervalMs, backoffBaseMs, backoffMaxMs]);

  return { connected, stale };
}
