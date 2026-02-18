import type {
  BugStatus,
  AIThinkingEvent,
  AIThinkingReadEvent,
  AIThinkingEditEvent,
} from "../types";

// ---- Node label mapping ----
export const NODE_LABELS: Record<string, { icon: string; label: string }> = {
  fix_bug_peer:    { icon: "\u{1F527}", label: "\u4FEE\u590D\u8282\u70B9" },
  verify_fix:      { icon: "\u{1F50D}", label: "\u9A8C\u8BC1\u8282\u70B9" },
  update_status:   { icon: "\u{1F4DD}", label: "\u72B6\u6001\u66F4\u65B0" },
  should_continue: { icon: "\u{1F504}", label: "\u7EE7\u7EED\u5224\u65AD" },
  should_retry:    { icon: "\u{1F501}", label: "\u91CD\u8BD5\u5224\u65AD" },
};

export function getNodeLabel(nodeId: string) {
  return NODE_LABELS[nodeId] ?? { icon: "\u2699\uFE0F", label: nodeId };
}

// ---- Three-tier event classification ----
export type EventTier = "critical" | "action" | "explore";

export function getEventTier(event: AIThinkingEvent): EventTier {
  switch (event.type) {
    case "edit":
    case "result":
      return "critical";
    case "bash":
      return "action";
    default:
      return "explore";
  }
}

// ---- Feed item types ----
export type NodeSeparator = { _kind: "separator"; node_id: string; timestamp: string };
export type ExploreGroup = {
  _kind: "group";
  events: AIThinkingEvent[];
  readCount: number;
  thinkingCount: number;
  lastFile: string | null;
  timestamp: string;
};
export type SingleEvent = AIThinkingEvent & { _kind?: undefined };
export type FeedItem = SingleEvent | NodeSeparator | ExploreGroup;

export function isSeparator(item: FeedItem): item is NodeSeparator {
  return "_kind" in item && item._kind === "separator";
}
export function isGroup(item: FeedItem): item is ExploreGroup {
  return "_kind" in item && item._kind === "group";
}

/** Build feed items with node separators and explore-event grouping */
export function buildFeedItems(events: AIThinkingEvent[]): FeedItem[] {
  const items: FeedItem[] = [];
  let lastNodeId: string | undefined;
  let pendingExplore: AIThinkingEvent[] = [];

  function flushExplore() {
    if (pendingExplore.length === 0) return;
    if (pendingExplore.length === 1) {
      items.push(pendingExplore[0]);
    } else {
      const readEvents = pendingExplore.filter((e) => e.type === "read") as AIThinkingReadEvent[];
      const thinkingEvents = pendingExplore.filter((e) => e.type === "thinking" || e.type === "text");
      const lastRead = readEvents[readEvents.length - 1];
      items.push({
        _kind: "group",
        events: [...pendingExplore],
        readCount: readEvents.length,
        thinkingCount: thinkingEvents.length,
        lastFile: lastRead?.file ?? null,
        timestamp: pendingExplore[pendingExplore.length - 1].timestamp,
      });
    }
    pendingExplore = [];
  }

  for (const event of events) {
    if (event.node_id && event.node_id !== lastNodeId) {
      flushExplore();
      items.push({ _kind: "separator", node_id: event.node_id, timestamp: event.timestamp });
      lastNodeId = event.node_id;
    }
    const tier = getEventTier(event);
    if (tier === "explore") {
      pendingExplore.push(event);
    } else {
      flushExplore();
      items.push(event);
    }
  }
  flushExplore();
  return items;
}

// ---- Event style config ----
export const EVENT_CONFIG: Record<string, { tagBg: string; tagColor: string; label: string; borderColor?: string }> = {
  thinking: { tagBg: "rgba(139,92,246,0.15)", tagColor: "#a78bfa", label: "\u5206\u6790" },
  text:     { tagBg: "rgba(100,116,139,0.2)", tagColor: "#94a3b8", label: "\u8F93\u51FA" },
  read:     { tagBg: "rgba(16,185,129,0.12)", tagColor: "#34d399", label: "\u8BFB\u53D6" },
  edit:     { tagBg: "rgba(249,115,22,0.12)", tagColor: "#fb923c", label: "\u4FEE\u6539\u4EE3\u7801", borderColor: "#f59e0b" },
  bash:     { tagBg: "#0F172A", tagColor: "#4ade80", label: "\u6267\u884C\u547D\u4EE4" },
  result:   { tagBg: "rgba(6,182,212,0.12)", tagColor: "#22d3ee", label: "\u5B8C\u6210", borderColor: "#06b6d4" },
};

export const NODE_RESULT_CONFIG: Record<string, { tagBg: string; tagColor: string; label: string; borderColor: string }> = {
  fix_bug_peer: { tagBg: "rgba(6,182,212,0.12)", tagColor: "#22d3ee", label: "\u4FEE\u590D\u7ED3\u679C", borderColor: "#06b6d4" },
  verify_fix:   { tagBg: "rgba(34,197,94,0.12)", tagColor: "#4ade80", label: "\u9A8C\u8BC1\u7ED3\u679C", borderColor: "#22c55e" },
};

export const STEP_ICONS: Record<string, string> = {
  code_summary: "\u{1F4CA}",
  git_commit: "\u{1F4E6}",
  git_revert: "\u{1F504}",
};

// ---- Formatting helpers ----

export function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

export function formatRelativeTime(ts: string): string {
  try {
    const diffMs = Date.now() - new Date(ts).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 5) return "\u521A\u521A";
    if (diffSec < 60) return `${diffSec}\u79D2\u524D`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}\u5206\u949F\u524D`;
    return `${Math.floor(diffSec / 3600)}\u5C0F\u65F6\u524D`;
  } catch {
    return ts;
  }
}

export function getBugSummaryText(bug: BugStatus, events: AIThinkingEvent[]): string {
  const parts: string[] = [];

  if (bug.status === "completed") parts.push("\u4FEE\u590D\u5B8C\u6210");
  else if (bug.status === "failed") parts.push("\u4FEE\u590D\u5931\u8D25");
  else if (bug.status === "skipped") parts.push("\u5DF2\u8DF3\u8FC7");

  const totalMs = (bug.steps ?? []).reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  if (totalMs > 0) {
    const sec = Math.round(totalMs / 1000);
    const min = Math.floor(sec / 60);
    const rem = sec % 60;
    parts.push(min > 0 ? `${min}m ${rem}s` : `${rem}s`);
  }

  if (bug.retry_count && bug.retry_count > 0) {
    parts.push(`${bug.retry_count}\u6B21\u91CD\u8BD5`);
  }

  const editFiles = new Set(
    events.filter((e): e is AIThinkingEditEvent => e.type === "edit").map((e) => e.file)
  );
  if (editFiles.size > 0) {
    parts.push(`\u4FEE\u6539 ${editFiles.size} \u4E2A\u6587\u4EF6`);
  }

  if (bug.status === "failed" && bug.error) {
    parts.push(bug.error);
  }

  return parts.join(" \u00B7 ");
}

export function getStreamingLabel(events: AIThinkingEvent[]): string {
  if (events.length === 0) return "\u7B49\u5F85\u5F00\u59CB...";
  const readCount = events.filter((e) => e.type === "read").length;
  const lastRead = [...events].reverse().find((e) => e.type === "read") as AIThinkingReadEvent | undefined;
  const fileSuffix = lastRead ? ` \u6700\u8FD1: ${lastRead.file}` : "";
  const countSuffix = readCount > 0 ? ` (\u5DF2\u63A2\u7D22 ${readCount} \u4E2A\u6587\u4EF6)` : "";
  const last = events[events.length - 1];
  switch (last.type) {
    case "thinking": return `\u6B63\u5728\u5206\u6790\u4EE3\u7801...${countSuffix}${fileSuffix}`;
    case "read":     return `\u6B63\u5728\u8BFB\u53D6\u6587\u4EF6...${countSuffix}${fileSuffix}`;
    case "edit":     return `\u6B63\u5728\u4FEE\u6539\u4EE3\u7801...${countSuffix}`;
    case "bash":     return `\u6B63\u5728\u6267\u884C\u547D\u4EE4...${countSuffix}`;
    default:         return `\u5904\u7406\u4E2D...${countSuffix}`;
  }
}

export function getMiniContent(event: AIThinkingEvent): string {
  switch (event.type) {
    case "thinking":
    case "text":
      return "content" in event ? (event as { content: string }).content.slice(0, 60) : "";
    case "read":
      return (event as AIThinkingReadEvent).file;
    default:
      return "content" in event ? (event as { content: string }).content.slice(0, 60) : "";
  }
}
