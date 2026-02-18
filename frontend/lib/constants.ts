/**
 * Job statuses that indicate the pipeline is no longer running.
 * Used by both batch-bugs and design-to-code hooks to gate SSE connections.
 */
export const TERMINAL_STATUSES: string[] = ["completed", "failed", "cancelled"];
