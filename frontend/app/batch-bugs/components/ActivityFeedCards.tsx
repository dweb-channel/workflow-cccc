"use client";

import { useState } from "react";
import type {
  AIThinkingEvent,
  AIThinkingReadEvent,
  AIThinkingEditEvent,
  AIThinkingBashEvent,
} from "../types";
import {
  type ExploreGroup,
  EVENT_CONFIG,
  NODE_RESULT_CONFIG,
  formatRelativeTime,
  formatTime,
  getMiniContent,
} from "./ActivityFeedUtils";

// ================================================================
// AIAvatar — shared by EventCard and ExploreGroupCard
// ================================================================

export function AIAvatar() {
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
      <span className="text-[10px] font-bold text-primary">AI</span>
    </div>
  );
}

// ================================================================
// EventCard — single event with AI avatar + relative time
// ================================================================

export function EventCard({ event }: { event: AIThinkingEvent }) {
  const nodeId = event.node_id;
  const cfg = event.type === "result" && nodeId && NODE_RESULT_CONFIG[nodeId]
    ? NODE_RESULT_CONFIG[nodeId]
    : EVENT_CONFIG[event.type] ?? EVENT_CONFIG.text;

  const isError = event.type === "result" && "content" in event && (event as { content: string }).content.startsWith("\u6267\u884C\u51FA\u9519");
  const borderColor = isError ? "#ef4444" : cfg.borderColor;

  return (
    <div
      className={`border-b border-border px-4 py-3 ${borderColor ? "border-l-[3px]" : ""}`}
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
              {isError ? "\u274C \u6267\u884C\u51FA\u9519" : cfg.label}
            </span>
            <span className="shrink-0 text-[11px] text-muted-foreground">
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

// ================================================================
// EventContent — renders different event type payloads
// ================================================================

function EventContent({ event }: { event: AIThinkingEvent }) {
  switch (event.type) {
    case "thinking":
    case "text":
      return (
        <p className="text-xs leading-relaxed text-card-foreground">
          {"content" in event ? event.content : ""}
        </p>
      );

    case "read": {
      const e = event as AIThinkingReadEvent;
      return (
        <span className="font-mono text-xs text-foreground">
          {e.file}
          {e.lines && <span className="text-muted-foreground">  {e.lines}</span>}
        </span>
      );
    }

    case "edit": {
      const e = event as AIThinkingEditEvent;
      return (
        <div className="space-y-1.5">
          {e.description && (
            <p className="text-xs text-muted-foreground">{e.description}</p>
          )}
          <p className="font-mono text-xs font-medium text-foreground">{e.file}</p>
          {e.diff && (
            <div className="rounded-md bg-background px-2.5 py-2">
              <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed">
                {e.diff.split("\n").map((line, i) => (
                  <span key={`diff-${i}`} className={line.startsWith("+") ? "text-green-400" : line.startsWith("-") ? "text-red-400" : "text-muted-foreground"}>
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
            <p className="text-xs text-muted-foreground">{e.description}</p>
          )}
          <div className="rounded-md bg-background px-2.5 py-2 space-y-1">
            <p className="font-mono text-[11px] font-medium text-green-400">
              $ {e.command}
            </p>
            {e.output && (
              <pre className="whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-muted-foreground">
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
      const bdrColor = isVerify ? "rgba(34,197,94,0.3)" : isFix ? "rgba(6,182,212,0.3)" : "rgba(51,65,85,0.5)";
      const bgColor = isVerify ? "rgba(34,197,94,0.08)" : isFix ? "rgba(6,182,212,0.08)" : "rgba(30,41,59,0.5)";
      return (
        <div className="rounded-md border px-3 py-2" style={{ borderColor: bdrColor, backgroundColor: bgColor }}>
          <pre className="whitespace-pre-wrap text-xs leading-relaxed text-card-foreground">
            {event.content}
          </pre>
        </div>
      );
    }

    default:
      return (
        <p className="text-xs text-muted-foreground">
          {"content" in event ? (event as { content: string }).content : JSON.stringify(event)}
        </p>
      );
  }
}

// ================================================================
// ExploreGroupCard — merged explore events (thinking/read/text)
// ================================================================

export function ExploreGroupCard({ group }: { group: ExploreGroup }) {
  const [expanded, setExpanded] = useState(false);
  const count = group.events.length;

  const summaryParts: string[] = [];
  if (group.readCount > 0) summaryParts.push(`\u5DF2\u63A2\u7D22 ${group.readCount} \u4E2A\u6587\u4EF6`);
  if (group.thinkingCount > 0) summaryParts.push(`\u5206\u6790 ${group.thinkingCount} \u6B21`);
  const summaryStats = summaryParts.join(", ");

  const lastThinking = [...group.events].reverse().find((e) => e.type === "thinking" && "content" in e);
  const mainText = lastThinking && "content" in lastThinking
    ? (lastThinking as { content: string }).content.slice(0, 80)
    : "\u5206\u6790\u4EE3\u7801\u5E93\u4E2D...";

  return (
    <div className="border-b border-border px-4 py-3" data-testid="event-group" data-count={count}>
      <div className="flex gap-2.5">
        <AIAvatar />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <span
                className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
                style={{ backgroundColor: "rgba(139,92,246,0.15)", color: "#a78bfa" }}
              >
                {"\uD83D\uDCAD"} \u5206\u6790\u63A2\u7D22
              </span>
              <p className="mt-1 text-xs leading-relaxed text-card-foreground">
                {mainText}{mainText.length >= 80 ? "..." : ""}
              </p>
              {group.lastFile && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  \u6700\u8FD1: <span className="font-mono text-foreground">{group.lastFile}</span>
                </p>
              )}
              <p className="mt-0.5 text-[11px] text-muted-foreground">{summaryStats}</p>
            </div>
            <span className="shrink-0 text-[11px] text-muted-foreground">
              {formatRelativeTime(group.timestamp)}
            </span>
          </div>
          {count > 1 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1.5 text-[11px] font-medium text-primary hover:text-primary"
              data-testid="event-group-expand"
            >
              {expanded ? `\u6536\u8D77 ${count} \u6761\u8BE6\u60C5 \u25B4` : `\u5C55\u5F00 ${count} \u6761\u8BE6\u60C5 \u25BE`}
            </button>
          )}
          {expanded && (
            <div className="mt-2 space-y-1 border-l-2 border-border pl-3">
              {group.events.map((evt, i) => (
                <MiniEventRow key={evt.timestamp || `evt-${i}`} event={evt} />
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
      <span className="shrink-0 font-mono text-muted-foreground w-[48px]">{formatTime(event.timestamp)}</span>
      <span className="shrink-0 rounded px-1 py-0.5" style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}>
        {cfg.label}
      </span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {getMiniContent(event)}
      </span>
    </div>
  );
}
