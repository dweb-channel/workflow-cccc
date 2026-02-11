import { useMemo } from "react";
import type { AIThinkingEvent, AIThinkingStats } from "../types";

interface UseAIThinkingOptions {
  allEvents: AIThinkingEvent[];
  stats: AIThinkingStats;
  /** Only show events for this bug index (null = show all) */
  activeBugIndex: number | null;
}

/**
 * Filters AI thinking events by active bug index.
 * Does NOT open its own SSE — events come from useBatchJob.
 */
export function useAIThinking({ allEvents, stats, activeBugIndex }: UseAIThinkingOptions) {
  const events = useMemo(
    () =>
      activeBugIndex !== null
        ? allEvents.filter((e) => e.bug_index === activeBugIndex)
        : allEvents,
    [allEvents, activeBugIndex]
  );

  return { events, stats };
}
