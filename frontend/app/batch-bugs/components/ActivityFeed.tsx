"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type {
  BatchJob,
  BugStatus,
  AIThinkingEvent,
  AIThinkingStats,
  AIThinkingReadEvent,
  AIThinkingEditEvent,
  AIThinkingBashEvent,
} from "../types";

/* ================================================================
   ActivityFeed — Conversation-style execution view.
   Three-tier event classification:
     🔴 Critical (edit, result) — independent prominent cards
     🟡 Action (bash)           — independent collapsible cards
     🟢 Explore (thinking, read, text) — merged into summary groups
   ================================================================ */

interface ActivityFeedProps {
  currentJob: BatchJob | null;
  allAiEvents: AIThinkingEvent[];
  aiStats: AIThinkingStats;
  activeBugIndex: number | null;
  onBugSelect: (index: number | null) => void;
  onRetryBug?: (bugIndex: number) => void;
  sseConnected?: boolean;
}

// ---- Node label mapping ----
const NODE_LABELS: Record<string, { icon: string; label: string }> = {
  fix_bug_peer:    { icon: "\u{1F527}", label: "\u4FEE\u590D\u8282\u70B9" },
  verify_fix:      { icon: "\u{1F50D}", label: "\u9A8C\u8BC1\u8282\u70B9" },
  update_status:   { icon: "\u{1F4DD}", label: "\u72B6\u6001\u66F4\u65B0" },
  should_continue: { icon: "\u{1F504}", label: "\u7EE7\u7EED\u5224\u65AD" },
  should_retry:    { icon: "\u{1F501}", label: "\u91CD\u8BD5\u5224\u65AD" },
};

function getNodeLabel(nodeId: string) {
  return NODE_LABELS[nodeId] ?? { icon: "\u2699\uFE0F", label: nodeId };
}

// ---- Three-tier event classification ----
type EventTier = "critical" | "action" | "explore";

function getEventTier(event: AIThinkingEvent): EventTier {
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
type NodeSeparator = { _kind: "separator"; node_id: string; timestamp: string };
type ExploreGroup = {
  _kind: "group";
  events: AIThinkingEvent[];
  readCount: number;
  thinkingCount: number;
  lastFile: string | null;
  timestamp: string;
};
type SingleEvent = AIThinkingEvent & { _kind?: undefined };
type FeedItem = SingleEvent | NodeSeparator | ExploreGroup;

function isSeparator(item: FeedItem): item is NodeSeparator {
  return "_kind" in item && item._kind === "separator";
}
function isGroup(item: FeedItem): item is ExploreGroup {
  return "_kind" in item && item._kind === "group";
}

/** Build feed items with node separators and explore-event grouping */
function buildFeedItems(events: AIThinkingEvent[]): FeedItem[] {
  const items: FeedItem[] = [];
  let lastNodeId: string | undefined;
  let pendingExplore: AIThinkingEvent[] = [];

  function flushExplore() {
    if (pendingExplore.length === 0) return;
    if (pendingExplore.length === 1) {
      // Single explore event — don't group, show as individual card
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
    // Insert node separator on node_id change
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
const EVENT_CONFIG: Record<string, { tagBg: string; tagColor: string; label: string; borderColor?: string }> = {
  thinking: { tagBg: "#f3e8ff", tagColor: "#7c3aed", label: "\u5206\u6790" },
  text:     { tagBg: "#f1f5f9", tagColor: "#475569", label: "\u8F93\u51FA" },
  read:     { tagBg: "#ecfdf5", tagColor: "#059669", label: "\u8BFB\u53D6" },
  edit:     { tagBg: "#fff7ed", tagColor: "#ea580c", label: "\u4FEE\u6539\u4EE3\u7801", borderColor: "#f59e0b" },
  bash:     { tagBg: "#1e293b", tagColor: "#4ade80", label: "\u6267\u884C\u547D\u4EE4" },
  result:   { tagBg: "#dbeafe", tagColor: "#3b82f6", label: "\u5B8C\u6210", borderColor: "#3b82f6" },
};

const NODE_RESULT_CONFIG: Record<string, { tagBg: string; tagColor: string; label: string; borderColor: string }> = {
  fix_bug_peer: { tagBg: "#dbeafe", tagColor: "#2563eb", label: "\u4FEE\u590D\u7ED3\u679C", borderColor: "#3b82f6" },
  verify_fix:   { tagBg: "#dcfce7", tagColor: "#16a34a", label: "\u9A8C\u8BC1\u7ED3\u679C", borderColor: "#22c55e" },
};

/* ================================================================
   Main Component
   ================================================================ */

export function ActivityFeed({
  currentJob,
  allAiEvents,
  aiStats,
  activeBugIndex,
  onBugSelect,
  onRetryBug,
  sseConnected = true,
}: ActivityFeedProps) {
  const [expandedBugs, setExpandedBugs] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!currentJob) return;
    const inProgressIndices = currentJob.bugs
      .map((b, i) => (b.status === "in_progress" ? i : -1))
      .filter((i) => i >= 0);

    if (inProgressIndices.length > 0) {
      setExpandedBugs((prev) => {
        const next = new Set(prev);
        inProgressIndices.forEach((i) => next.add(i));
        return next;
      });
    }
  }, [currentJob?.bugs.map((b) => `${b.bug_id}:${b.status}`).join(",")]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [allAiEvents.length]);

  const toggleBug = (idx: number) => {
    setExpandedBugs((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
    onBugSelect(idx);
  };

  const eventsByBug = useMemo(() => {
    const map = new Map<number, AIThinkingEvent[]>();
    for (const e of allAiEvents) {
      const list = map.get(e.bug_index) ?? [];
      list.push(e);
      map.set(e.bug_index, list);
    }
    return map;
  }, [allAiEvents]);

  if (!currentJob) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-[#e2e8f0] bg-white text-sm text-slate-400">
        提交任务后，执行日志将在此显示
      </div>
    );
  }

  const total = currentJob.bugs.length;
  const inProgressIdx = currentJob.bugs.findIndex((b) => b.status === "in_progress");
  const currentBugLabel = inProgressIdx >= 0 ? currentJob.bugs[inProgressIdx].bug_id : undefined;
  const isStreaming = aiStats.streaming;

  return (
    <div className="flex h-full flex-col rounded-xl border border-[#e2e8f0] bg-white overflow-hidden">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between border-b border-[#e2e8f0] bg-[#f8fafc] px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-[#0f172a]">执行日志</span>
          {isStreaming && (
            <span className="flex items-center gap-1 rounded-full bg-[#fef2f2] px-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#ef4444] animate-pulse" />
              <span className="text-[10px] font-semibold text-[#dc2626]">LIVE</span>
            </span>
          )}
        </div>
        {currentBugLabel && (
          <span className="text-xs text-[#64748b]">
            当前: {currentBugLabel} (Bug {inProgressIdx + 1}/{total})
          </span>
        )}
      </div>

      {/* ---- SSE Disconnect Banner ---- */}
      {!sseConnected && (
        <div className="flex items-center gap-2 bg-[#fef2f2] border-b border-[#fecaca] px-4 py-2">
          <span className="h-2 w-2 rounded-full bg-[#ef4444] animate-pulse" />
          <span className="text-xs font-medium text-[#dc2626]">
            连接已断开，正在重连... 数据可能不是最新的
          </span>
        </div>
      )}

      {/* ---- Feed Body ---- */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {currentJob.bugs.map((bug, idx) => {
          const isExpanded = expandedBugs.has(idx) || bug.status === "in_progress";
          const bugEvents = eventsByBug.get(idx) ?? [];

          return isExpanded ? (
            <ExpandedBugSection
              key={idx}
              bug={bug}
              bugIndex={idx}
              events={bugEvents}
              onCollapse={() => toggleBug(idx)}
              onRetry={onRetryBug ? () => onRetryBug(idx) : undefined}
            />
          ) : (
            <CollapsedBugRow
              key={idx}
              bug={bug}
              bugIndex={idx}
              events={bugEvents}
              onExpand={() => toggleBug(idx)}
              onRetry={onRetryBug ? () => onRetryBug(idx) : undefined}
            />
          );
        })}
      </div>

      {/* ---- Bottom Bar ---- */}
      <div className="flex items-center gap-2 border-t border-[#e2e8f0] bg-[#f8fafc] px-4 py-2.5">
        {isStreaming ? (
          <>
            <span className="h-2 w-2 rounded-full bg-[#3b82f6] animate-pulse" />
            <span className="text-xs text-[#64748b]">
              {getStreamingLabel(allAiEvents)}
            </span>
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-slate-300" />
            <span className="text-xs text-slate-400">空闲</span>
          </>
        )}
        <div className="flex-1" />
        <span className="font-mono text-[11px] text-[#cbd5e1]">
          {aiStats.tokens_in.toLocaleString()} / {aiStats.tokens_out.toLocaleString()} tokens
        </span>
        <span className="font-mono text-[11px] font-medium text-[#64748b]">
          ${aiStats.cost.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

/* ================================================================
   Collapsed Bug Row
   ================================================================ */

function CollapsedBugRow({
  bug,
  bugIndex,
  events,
  onExpand,
  onRetry,
}: {
  bug: BugStatus;
  bugIndex: number;
  events: AIThinkingEvent[];
  onExpand: () => void;
  onRetry?: () => void;
}) {
  const bgColor = bug.status === "completed" ? "#f0fdf4"
    : bug.status === "failed" || bug.status === "skipped" ? "#fef2f2"
    : "#f8fafc";

  const iconColor = bug.status === "completed" ? "#16a34a"
    : bug.status === "failed" ? "#dc2626"
    : "#64748b";

  const statusIcon = bug.status === "completed" ? "\u2705"
    : bug.status === "failed" ? "\u274C"
    : bug.status === "skipped" ? "\u23ED\uFE0F"
    : bug.status === "in_progress" ? "\u{1F504}"
    : "\u23F3";

  return (
    <div
      className="flex w-full items-center gap-2.5 border-b border-[#e2e8f0] px-4 py-3 text-left transition-colors hover:bg-[#f8fafc] cursor-pointer"
      style={{ backgroundColor: bgColor }}
      onClick={onExpand}
    >
      <span className="text-sm">{statusIcon}</span>
      <span className="font-mono text-[13px] font-semibold" style={{ color: iconColor }}>
        {bug.bug_id}
      </span>
      <span className="flex-1 truncate text-xs" style={{ color: iconColor }}>
        {getBugSummaryText(bug, events)}
      </span>
      {bug.status === "failed" && onRetry && (
        <button
          onClick={(e) => { e.stopPropagation(); onRetry(); }}
          className="shrink-0 rounded px-2 py-1 text-[11px] font-medium text-[#2563eb] bg-[#dbeafe] hover:bg-[#bfdbfe] transition-colors"
        >
          重试
        </button>
      )}
      <span className="text-[11px] text-[#94a3b8]">展开 ▾</span>
    </div>
  );
}

/* ================================================================
   Expanded Bug Section — node separators + grouped event stream
   ================================================================ */

function ExpandedBugSection({
  bug,
  bugIndex,
  events,
  onCollapse,
  onRetry,
}: {
  bug: BugStatus;
  bugIndex: number;
  events: AIThinkingEvent[];
  onCollapse: () => void;
  onRetry?: () => void;
}) {
  const feedItems = useMemo(() => buildFeedItems(events), [events]);

  return (
    <div className="border-b border-[#e2e8f0]">
      {bug.status !== "in_progress" && (
        <div
          onClick={onCollapse}
          className="flex w-full items-center gap-2.5 bg-[#f8fafc] px-4 py-2 text-left border-b border-[#f1f5f9] hover:bg-[#f1f5f9] transition-colors cursor-pointer"
        >
          <span className="text-sm">
            {bug.status === "completed" ? "\u2705" : bug.status === "failed" ? "\u274C" : "\u23F3"}
          </span>
          <span className="font-mono text-[13px] font-semibold text-[#0f172a]">{bug.bug_id}</span>
          <div className="flex-1" />
          {bug.status === "failed" && onRetry && (
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(); }}
              className="shrink-0 rounded px-2 py-1 text-[11px] font-medium text-[#2563eb] bg-[#dbeafe] hover:bg-[#bfdbfe] transition-colors"
            >
              重试
            </button>
          )}
          <span className="text-[11px] text-[#94a3b8]">收起 ▴</span>
        </div>
      )}

      <div className="space-y-0">
        {feedItems.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-3">
            <span className="h-2 w-2 rounded-full bg-[#3b82f6] animate-pulse" />
            <span className="text-xs text-[#64748b]">等待 AI 开始分析...</span>
          </div>
        ) : (
          feedItems.map((item, i) => {
            if (isSeparator(item)) {
              return <NodeSeparatorLine key={`sep-${i}`} nodeId={item.node_id} timestamp={item.timestamp} bugId={bug.bug_id} />;
            }
            if (isGroup(item)) {
              return <ExploreGroupCard key={`grp-${i}`} group={item} />;
            }
            return <EventCard key={`evt-${i}`} event={item} />;
          })
        )}
      </div>
    </div>
  );
}

/* ================================================================
   Node Separator Line
   ================================================================ */

function NodeSeparatorLine({ nodeId, timestamp, bugId }: { nodeId: string; timestamp: string; bugId: string }) {
  const { icon, label } = getNodeLabel(nodeId);

  return (
    <div className="flex items-center gap-2 bg-[#eff6ff] px-4 py-2.5 border-b border-[#e2e8f0]">
      <div className="h-px w-5 bg-[#93c5fd]" />
      <span className="text-xs font-semibold text-[#2563eb]">
        {icon} {label} — {bugId}
      </span>
      <span className="font-mono text-[11px] text-[#93c5fd]">{formatTime(timestamp)}</span>
      <div className="h-px flex-1 bg-[#93c5fd]" />
    </div>
  );
}

/* ================================================================
   AI Avatar — shared by EventCard and ExploreGroupCard
   ================================================================ */

function AIAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#eff6ff]">
      <span className="text-[10px] font-bold text-[#3b82f6]">AI</span>
    </div>
  );
}

/* ================================================================
   ExploreGroupCard — merged explore events (thinking/read/text)
   ================================================================ */

function ExploreGroupCard({ group }: { group: ExploreGroup }) {
  const [expanded, setExpanded] = useState(false);
  const count = group.events.length;

  // Build summary text with last file name
  const summaryParts: string[] = [];
  if (group.readCount > 0) {
    summaryParts.push(`已探索 ${group.readCount} 个文件`);
  }
  if (group.thinkingCount > 0) {
    summaryParts.push(`分析 ${group.thinkingCount} 次`);
  }
  const summaryStats = summaryParts.join(", ");

  // Get the main description from the last thinking event
  const lastThinking = [...group.events].reverse().find((e) => e.type === "thinking" && "content" in e);
  const mainText = lastThinking && "content" in lastThinking
    ? (lastThinking as { content: string }).content.slice(0, 80)
    : "分析代码库中...";

  return (
    <div
      className="border-b border-[#f1f5f9] px-4 py-3"
      data-testid="event-group"
      data-count={count}
    >
      <div className="flex gap-2.5">
        <AIAvatar />
        <div className="min-w-0 flex-1">
          {/* Summary line */}
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <span
                className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
                style={{ backgroundColor: "#f3e8ff", color: "#7c3aed" }}
              >
                💭 分析探索
              </span>
              <p className="mt-1 text-xs leading-relaxed text-[#334155]">
                {mainText}{mainText.length >= 80 ? "..." : ""}
              </p>
              {group.lastFile && (
                <p className="mt-0.5 text-[11px] text-[#64748b]">
                  最近: <span className="font-mono text-[#0f172a]">{group.lastFile}</span>
                </p>
              )}
              <p className="mt-0.5 text-[11px] text-[#94a3b8]">
                {summaryStats}
              </p>
            </div>
            <span className="shrink-0 text-[11px] text-[#94a3b8]">
              {formatRelativeTime(group.timestamp)}
            </span>
          </div>

          {/* Expand toggle */}
          {count > 1 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1.5 text-[11px] font-medium text-[#3b82f6] hover:text-[#2563eb]"
              data-testid="event-group-expand"
            >
              {expanded ? `收起 ${count} 条详情 ▴` : `展开 ${count} 条详情 ▾`}
            </button>
          )}

          {/* Expanded detail list */}
          {expanded && (
            <div className="mt-2 space-y-1 border-l-2 border-[#e2e8f0] pl-3">
              {group.events.map((evt, i) => (
                <MiniEventRow key={i} event={evt} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Compact event row inside an expanded group */
function MiniEventRow({ event }: { event: AIThinkingEvent }) {
  const cfg = EVENT_CONFIG[event.type] ?? EVENT_CONFIG.text;

  return (
    <div className="flex items-start gap-1.5 text-[11px]">
      <span className="shrink-0 font-mono text-[#94a3b8] w-[48px]">{formatTime(event.timestamp)}</span>
      <span className="shrink-0 rounded px-1 py-0.5" style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}>
        {cfg.label}
      </span>
      <span className="min-w-0 flex-1 truncate text-[#475569]">
        {getMiniContent(event)}
      </span>
    </div>
  );
}

function getMiniContent(event: AIThinkingEvent): string {
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

/* ================================================================
   EventCard — single event with AI avatar + relative time.
   Critical events (edit/result) get a colored left border.
   ================================================================ */

function EventCard({ event }: { event: AIThinkingEvent }) {
  const nodeId = event.node_id;
  const cfg = event.type === "result" && nodeId && NODE_RESULT_CONFIG[nodeId]
    ? NODE_RESULT_CONFIG[nodeId]
    : EVENT_CONFIG[event.type] ?? EVENT_CONFIG.text;

  const isError = event.type === "result" && "content" in event && (event as { content: string }).content.startsWith("执行出错");
  const borderColor = isError ? "#ef4444" : cfg.borderColor;
  const tier = getEventTier(event);

  return (
    <div
      className={`border-b border-[#f1f5f9] px-4 py-3 ${borderColor ? "border-l-[3px]" : ""}`}
      style={borderColor ? { borderLeftColor: borderColor } : undefined}
      data-testid="event-card"
    >
      <div className="flex gap-2.5">
        <AIAvatar />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <span
              className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
              style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
            >
              {isError ? "❌ 执行出错" : cfg.label}
            </span>
            <span className="shrink-0 text-[11px] text-[#94a3b8]">
              {formatRelativeTime(event.timestamp)}
            </span>
          </div>
          <div className="mt-1.5">
            <EventContent event={event} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Event Content Renderers
   ================================================================ */

function EventContent({ event }: { event: AIThinkingEvent }) {
  switch (event.type) {
    case "thinking":
    case "text":
      return (
        <p className="text-xs leading-relaxed text-[#334155]">
          {"content" in event ? event.content : ""}
        </p>
      );

    case "read": {
      const e = event as AIThinkingReadEvent;
      return (
        <span className="font-mono text-xs text-[#0f172a]">
          {e.file}
          {e.lines && <span className="text-[#94a3b8]">  {e.lines}</span>}
        </span>
      );
    }

    case "edit": {
      const e = event as AIThinkingEditEvent;
      return (
        <div className="space-y-1.5">
          {e.description && (
            <p className="text-xs text-[#475569]">{e.description}</p>
          )}
          <p className="font-mono text-xs font-medium text-[#0f172a]">{e.file}</p>
          {e.diff && (
            <div className="rounded-md bg-[#fefce8] px-2.5 py-2">
              <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed">
                {e.diff.split("\n").map((line, i) => (
                  <span key={i} className={line.startsWith("+") ? "text-[#16a34a]" : line.startsWith("-") ? "text-[#dc2626]" : "text-[#78350f]"}>
                    {line}{"\n"}
                  </span>
                ))}
              </pre>
            </div>
          )}
        </div>
      );
    }

    case "bash": {
      const e = event as AIThinkingBashEvent;
      return (
        <div className="space-y-1">
          {e.description && (
            <p className="text-xs text-[#475569]">{e.description}</p>
          )}
          <div className="rounded-md bg-[#1e293b] px-2.5 py-2 space-y-1">
            <p className="font-mono text-[11px] font-medium text-[#4ade80]">
              $ {e.command}
            </p>
            {e.output && (
              <pre className="whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-[#94a3b8]">
                {e.output}
              </pre>
            )}
          </div>
        </div>
      );
    }

    case "result": {
      const isVerify = event.node_id === "verify_fix";
      const isFix = event.node_id === "fix_bug_peer";
      const borderColor = isVerify ? "#bbf7d0" : isFix ? "#bfdbfe" : "#e2e8f0";
      const bgColor = isVerify ? "#f0fdf4" : isFix ? "#eff6ff" : "#f8fafc";
      return (
        <div className="rounded-md border px-3 py-2" style={{ borderColor, backgroundColor: bgColor }}>
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-[#334155]">
            {event.content}
          </pre>
        </div>
      );
    }

    default:
      return (
        <p className="text-xs text-[#94a3b8]">
          {"content" in event ? (event as { content: string }).content : JSON.stringify(event)}
        </p>
      );
  }
}

/* ================================================================
   Helpers
   ================================================================ */

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return ts;
  }
}

function formatRelativeTime(ts: string): string {
  try {
    const diffMs = Date.now() - new Date(ts).getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 5) return "刚刚";
    if (diffSec < 60) return `${diffSec}秒前`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}分钟前`;
    return `${Math.floor(diffSec / 3600)}小时前`;
  } catch {
    return ts;
  }
}

function getBugSummaryText(bug: BugStatus, events: AIThinkingEvent[]): string {
  const parts: string[] = [];

  if (bug.status === "completed") parts.push("修复完成");
  else if (bug.status === "failed") parts.push("修复失败");
  else if (bug.status === "skipped") parts.push("已跳过");

  const totalMs = (bug.steps ?? []).reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  if (totalMs > 0) {
    const sec = Math.round(totalMs / 1000);
    const min = Math.floor(sec / 60);
    const rem = sec % 60;
    parts.push(min > 0 ? `${min}m ${rem}s` : `${rem}s`);
  }

  if (bug.retry_count && bug.retry_count > 0) {
    parts.push(`${bug.retry_count}次重试`);
  }

  const editFiles = new Set(
    events.filter((e): e is AIThinkingEditEvent => e.type === "edit").map((e) => e.file)
  );
  if (editFiles.size > 0) {
    parts.push(`修改 ${editFiles.size} 个文件`);
  }

  if (bug.status === "failed" && bug.error) {
    parts.push(bug.error);
  }

  return parts.join(" \u00B7 ");
}

function getStreamingLabel(events: AIThinkingEvent[]): string {
  if (events.length === 0) return "等待开始...";
  const readCount = events.filter((e) => e.type === "read").length;
  const lastRead = [...events].reverse().find((e) => e.type === "read") as AIThinkingReadEvent | undefined;
  const fileSuffix = lastRead ? ` 最近: ${lastRead.file}` : "";
  const countSuffix = readCount > 0 ? ` (已探索 ${readCount} 个文件)` : "";
  const last = events[events.length - 1];
  switch (last.type) {
    case "thinking": return `正在分析代码...${countSuffix}${fileSuffix}`;
    case "read":     return `正在读取文件...${countSuffix}${fileSuffix}`;
    case "edit":     return `正在修改代码...${countSuffix}`;
    case "bash":     return `正在执行命令...${countSuffix}`;
    default:         return `处理中...${countSuffix}`;
  }
}
