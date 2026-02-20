"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import type {
  BatchJob,
  AIThinkingEvent,
  AIThinkingStats,
  DbSyncWarning,
} from "../types";
import { getStreamingLabel } from "./ActivityFeedUtils";
import { CollapsedBugRow, ExpandedBugSection } from "./ActivityFeedBugSection";

/* ================================================================
   ActivityFeed — Conversation-style execution view.
   Three-tier event classification:
     critical (edit, result) — independent prominent cards
     action (bash)           — independent collapsible cards
     explore (thinking, read, text) — merged into summary groups
   ================================================================ */

interface ActivityFeedProps {
  currentJob: BatchJob | null;
  allAiEvents: AIThinkingEvent[];
  aiStats: AIThinkingStats;
  activeBugIndex: number | null;
  onBugSelect: (index: number | null) => void;
  onRetryBug?: (bugIndex: number) => void;
  sseConnected?: boolean;
  dbSyncWarnings?: DbSyncWarning[];
}

export function ActivityFeed({
  currentJob,
  allAiEvents,
  aiStats,
  activeBugIndex,
  onBugSelect,
  onRetryBug,
  sseConnected = true,
  dbSyncWarnings = [],
}: ActivityFeedProps) {
  const [expandedBugs, setExpandedBugs] = useState<Set<number>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  const bugStatusKey = useMemo(
    () => currentJob?.bugs.map((b) => `${b.bug_id}:${b.status}`).join(",") ?? "",
    [currentJob?.bugs]
  );

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
  }, [bugStatusKey]);

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
      if (e.bug_index == null) continue;
      const list = map.get(e.bug_index) ?? [];
      list.push(e);
      map.set(e.bug_index, list);
    }
    return map;
  }, [allAiEvents]);

  if (!currentJob) {
    return (
      <div className="flex h-full items-center justify-center rounded-xl border border-border bg-card text-sm text-muted-foreground">
        提交任务后，执行日志将在此显示
      </div>
    );
  }

  const total = currentJob.bugs.length;
  const inProgressIdx = currentJob.bugs.findIndex((b) => b.status === "in_progress");
  const currentBugLabel = inProgressIdx >= 0 ? currentJob.bugs[inProgressIdx].bug_id : undefined;
  const isStreaming = aiStats.streaming;

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-card overflow-hidden">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between border-b border-border bg-background px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">执行日志</span>
          {isStreaming && (
            <span className="flex items-center gap-1 rounded-full bg-red-500/10 px-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
              <span className="text-[10px] font-semibold text-red-500">LIVE</span>
            </span>
          )}
        </div>
        {currentBugLabel && (
          <span className="text-xs text-muted-foreground">
            当前: {currentBugLabel} (Bug {inProgressIdx + 1}/{total})
          </span>
        )}
      </div>

      {/* ---- SSE Disconnect Banner ---- */}
      {!sseConnected && (
        <div className="flex items-center gap-2 bg-red-500/10 border-b border-red-500/20 px-4 py-2">
          <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
          <span className="text-xs font-medium text-red-500">
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
              key={bug.bug_id}
              bug={bug}
              bugIndex={idx}
              events={bugEvents}
              onCollapse={() => toggleBug(idx)}
              onRetry={onRetryBug ? () => onRetryBug(idx) : undefined}
              dbSyncWarnings={dbSyncWarnings.filter((w) => w.bug_index === idx)}
            />
          ) : (
            <CollapsedBugRow
              key={bug.bug_id}
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
      <div className="flex items-center gap-2 border-t border-border bg-background px-4 py-2.5">
        {isStreaming ? (
          <>
            <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-xs text-muted-foreground">
              {getStreamingLabel(allAiEvents)}
            </span>
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-muted-foreground/50" />
            <span className="text-xs text-muted-foreground">空闲</span>
          </>
        )}
        <div className="flex-1" />
        <span className="font-mono text-[11px] text-foreground">
          {aiStats.tokens_in.toLocaleString()} / {aiStats.tokens_out.toLocaleString()} tokens
        </span>
        <span className="font-mono text-[11px] font-medium text-muted-foreground">
          ${aiStats.cost.toFixed(2)}
        </span>
      </div>
    </div>
  );
}
