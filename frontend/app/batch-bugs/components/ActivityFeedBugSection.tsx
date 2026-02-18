"use client";

import { useState, useMemo } from "react";
import type { BugStatus, BugStep, AIThinkingEvent, DbSyncWarning } from "../types";
import {
  buildFeedItems,
  isSeparator,
  isGroup,
  getNodeLabel,
  getBugSummaryText,
  formatTime,
  STEP_ICONS,
} from "./ActivityFeedUtils";
import { EventCard, ExploreGroupCard } from "./ActivityFeedCards";

// ================================================================
// CollapsedBugRow
// ================================================================

export function CollapsedBugRow({
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
  const bgColor = bug.status === "completed" ? "rgba(34,197,94,0.08)"
    : bug.status === "failed" || bug.status === "skipped" ? "rgba(239,68,68,0.08)"
    : "rgba(30,41,59,0.5)";

  const iconColor = bug.status === "completed" ? "#4ade80"
    : bug.status === "failed" ? "#f87171"
    : "#94a3b8";

  const statusIcon = bug.status === "completed" ? "\u2705"
    : bug.status === "failed" ? "\u274C"
    : bug.status === "skipped" ? "\u23ED\uFE0F"
    : bug.status === "in_progress" ? "\u{1F504}"
    : "\u23F3";

  return (
    <div
      className="flex w-full items-center gap-2.5 border-b border-slate-700 px-4 py-3 text-left transition-colors hover:bg-slate-700/50 cursor-pointer"
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
          className="shrink-0 rounded px-2 py-1 text-[11px] font-medium text-cyan-400 bg-cyan-500/10 hover:bg-cyan-500/20 transition-colors"
        >
          \u91CD\u8BD5
        </button>
      )}
      <span className="text-[11px] text-slate-500">\u5C55\u5F00 \u25BE</span>
    </div>
  );
}

// ================================================================
// ExpandedBugSection — node separators + grouped event stream
// ================================================================

export function ExpandedBugSection({
  bug,
  bugIndex,
  events,
  onCollapse,
  onRetry,
  dbSyncWarnings = [],
}: {
  bug: BugStatus;
  bugIndex: number;
  events: AIThinkingEvent[];
  onCollapse: () => void;
  onRetry?: () => void;
  dbSyncWarnings?: DbSyncWarning[];
}) {
  const feedItems = useMemo(() => buildFeedItems(events), [events]);
  const completedSteps = useMemo(
    () => (bug.steps ?? []).filter((s) => s.status === "completed" && s.output_preview),
    [bug.steps],
  );

  return (
    <div className="border-b border-slate-700">
      {bug.status !== "in_progress" && (
        <div
          onClick={onCollapse}
          className="flex w-full items-center gap-2.5 bg-slate-900 px-4 py-2 text-left border-b border-slate-700 hover:bg-slate-700/50 transition-colors cursor-pointer"
        >
          <span className="text-sm">
            {bug.status === "completed" ? "\u2705" : bug.status === "failed" ? "\u274C" : "\u23F3"}
          </span>
          <span className="font-mono text-[13px] font-semibold text-white">{bug.bug_id}</span>
          <div className="flex-1" />
          {bug.status === "failed" && onRetry && (
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(); }}
              className="shrink-0 rounded px-2 py-1 text-[11px] font-medium text-cyan-400 bg-cyan-500/10 hover:bg-cyan-500/20 transition-colors"
            >
              \u91CD\u8BD5
            </button>
          )}
          <span className="text-[11px] text-slate-500">\u6536\u8D77 \u25B4</span>
        </div>
      )}

      {/* DB sync warnings */}
      {dbSyncWarnings.map((w, i) => (
        <div key={`dbw-${i}`} className="flex items-center gap-2 bg-amber-500/10 border-b border-amber-500/30 px-4 py-2">
          <span className="text-xs">{"\u26A0\uFE0F"}</span>
          <span className="text-xs font-medium text-amber-400">{w.message}</span>
          <span className="ml-auto text-[10px] text-amber-500">{formatTime(w.timestamp)}</span>
        </div>
      ))}

      {/* Step summary strip */}
      {completedSteps.length > 0 && (
        <div className="border-b border-slate-700 bg-slate-900/50 px-4 py-2.5 space-y-1.5">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">\u6B65\u9AA4\u6458\u8981</span>
          {completedSteps.map((step, i) => (
            <StepOutputRow key={`step-${i}`} step={step} />
          ))}
        </div>
      )}

      <div className="space-y-0">
        {feedItems.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-3">
            <span className="h-2 w-2 rounded-full bg-[#3b82f6] animate-pulse" />
            <span className="text-xs text-slate-400">\u7B49\u5F85 AI \u5F00\u59CB\u5206\u6790...</span>
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

// ================================================================
// NodeSeparatorLine
// ================================================================

function NodeSeparatorLine({ nodeId, timestamp, bugId }: { nodeId: string; timestamp: string; bugId: string }) {
  const { icon, label } = getNodeLabel(nodeId);
  return (
    <div className="flex items-center gap-2 bg-cyan-500/10 px-4 py-2.5 border-b border-slate-700">
      <div className="h-px w-5 bg-cyan-500/40" />
      <span className="text-xs font-semibold text-cyan-400">
        {icon} {label} — {bugId}
      </span>
      <span className="font-mono text-[11px] text-cyan-500/50">{formatTime(timestamp)}</span>
      <div className="h-px flex-1 bg-cyan-500/40" />
    </div>
  );
}

// ================================================================
// StepOutputRow — pipeline step with expandable output_preview
// ================================================================

function StepOutputRow({ step }: { step: BugStep }) {
  const [expanded, setExpanded] = useState(false);
  const preview = step.output_preview ?? "";
  const isLong = preview.length > 80;
  const icon = STEP_ICONS[step.step] ?? "\u2705";

  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="shrink-0 mt-0.5">{icon}</span>
      <span className="shrink-0 font-medium text-slate-300">{step.label}</span>
      <div className="min-w-0 flex-1">
        <span className={`text-slate-400 ${!expanded && isLong ? "line-clamp-1" : ""}`}>
          <OutputPreviewText text={expanded ? preview : (isLong ? preview.slice(0, 80) + "..." : preview)} />
        </span>
        {isLong && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="ml-1 text-[11px] font-medium text-cyan-400 hover:text-cyan-300"
          >
            {expanded ? "\u6536\u8D77" : "\u5C55\u5F00"}
          </button>
        )}
      </div>
      {step.duration_ms != null && step.duration_ms > 0 && (
        <span className="shrink-0 font-mono text-[10px] text-slate-500">
          {Math.round(step.duration_ms / 1000)}s
        </span>
      )}
    </div>
  );
}

/** Renders text with auto-linked URLs */
function OutputPreviewText({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s,)]+)/g);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, i) =>
        /^https?:\/\//.test(part) ? (
          <a
            key={i}
            href={part}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 underline hover:text-cyan-300"
            onClick={(e) => e.stopPropagation()}
          >
            {part}
          </a>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}
