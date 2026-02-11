"use client";

import { useEffect, useRef } from "react";
import type {
  AIThinkingEvent,
  AIThinkingStats,
  AIThinkingReadEvent,
  AIThinkingEditEvent,
  AIThinkingBashEvent,
} from "../types";

interface AIThinkingPanelProps {
  events: AIThinkingEvent[];
  stats: AIThinkingStats;
  bugLabel?: string;
}

export function AIThinkingPanel({ events, stats, bugLabel }: AIThinkingPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-[#e2e8f0] bg-white overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-[#f1f5f9] px-4 py-3.5">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#eff6ff]">
          <span className="text-[10px] font-bold text-[#3b82f6]">AI</span>
        </div>
        <span className="text-[15px] font-semibold text-[#1e293b]">AI 思考过程</span>
        <div className="flex-1" />
        {bugLabel && (
          <span className="text-xs font-medium text-[#64748b]">{bugLabel}</span>
        )}
      </div>

      {/* Stream area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-3"
      >
        {events.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            等待 AI 开始分析...
          </div>
        ) : (
          events.map((event, idx) => (
            <div key={idx}>
              {idx > 0 && <div className="mb-3 h-px bg-[#f1f5f9]" />}
              <EventRow event={event} />
            </div>
          ))
        )}
      </div>

      {/* Bottom bar */}
      <div className="flex items-center gap-2 border-t border-[#e2e8f0] bg-[#f8fafc] px-4 py-2.5">
        {stats.streaming ? (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-[#22c55e] animate-pulse" />
            <span className="text-[11px] font-medium text-[#16a34a]">Streaming</span>
          </>
        ) : (
          <>
            <span className="h-1.5 w-1.5 rounded-full bg-slate-300" />
            <span className="text-[11px] font-medium text-slate-400">Idle</span>
          </>
        )}
        <div className="flex-1" />
        <span className="text-[11px] text-[#94a3b8]">
          Token: {stats.tokens_in.toLocaleString()} in / {stats.tokens_out.toLocaleString()} out
        </span>
        <span className="text-[11px] font-medium text-[#64748b]">
          ${stats.cost.toFixed(3)}
        </span>
      </div>
    </div>
  );
}

/* ---- Event Renderers ---- */

const EVENT_CONFIG = {
  thinking: { icon: "\u{1F4AD}", bg: "#faf5ff", tagColor: "#7c3aed", label: "Thinking" },
  read:     { icon: "\u{1F4D6}", bg: "#f0fdf4", tagColor: "#16a34a", label: "Read" },
  edit:     { icon: "\u270F\uFE0F", bg: "#fffbeb", tagColor: "#d97706", label: "Edit" },
  bash:     { icon: ">_",         bg: "#1e293b", tagColor: "#1e293b", label: "Bash" },
  result:   { icon: "\u2705",     bg: "#eff6ff", tagColor: "#3b82f6", label: "Result" },
} as const;

function EventRow({ event }: { event: AIThinkingEvent }) {
  const cfg = EVENT_CONFIG[event.type];

  return (
    <div className="flex gap-2.5">
      {/* Icon */}
      <div
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
        style={{ backgroundColor: cfg.bg }}
      >
        {event.type === "bash" ? (
          <span className="text-[11px] font-bold text-[#22c55e]">{cfg.icon}</span>
        ) : (
          <span className="text-sm">{cfg.icon}</span>
        )}
      </div>

      {/* Body */}
      <div className="min-w-0 flex-1 space-y-1">
        {/* Label row */}
        <div className="flex items-center gap-1.5">
          <span
            className="text-[11px] font-semibold"
            style={{ color: cfg.tagColor }}
          >
            {cfg.label}
          </span>
          <span className="text-[10px] text-[#94a3b8]">
            {formatTimestamp(event.timestamp)}
          </span>
        </div>

        {/* Content */}
        <EventContent event={event} />
      </div>
    </div>
  );
}

function EventContent({ event }: { event: AIThinkingEvent }) {
  switch (event.type) {
    case "thinking":
      return (
        <p className="text-xs leading-relaxed text-[#475569]">{event.content}</p>
      );

    case "read":
      return <ReadBlock event={event} />;

    case "edit":
      return <EditBlock event={event} />;

    case "bash":
      return <BashBlock event={event} />;

    case "result":
      return (
        <p className="text-xs leading-relaxed text-[#475569]">{event.content}</p>
      );
  }
}

function ReadBlock({ event }: { event: AIThinkingReadEvent }) {
  return (
    <div className="rounded-md border border-[#e2e8f0] bg-[#f8fafc] px-2.5 py-2 space-y-0.5">
      <p className="font-mono text-[11px] font-medium text-[#1e293b]">{event.file}</p>
      {(event.lines || event.description) && (
        <p className="text-[10px] text-[#94a3b8]">
          {[event.lines, event.description].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>
  );
}

function EditBlock({ event }: { event: AIThinkingEditEvent }) {
  return (
    <div className="rounded-md border border-[#fde68a] bg-[#fffbeb] px-2.5 py-2 space-y-1">
      <p className="font-mono text-[11px] font-medium text-[#92400e]">{event.file}</p>
      {event.diff && (
        <pre className="whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[#78350f]">
          {event.diff}
        </pre>
      )}
    </div>
  );
}

function BashBlock({ event }: { event: AIThinkingBashEvent }) {
  return (
    <div className="rounded-md bg-[#1e293b] px-2.5 py-2 space-y-1">
      <p className="font-mono text-[11px] font-medium text-[#22c55e]">
        $ {event.command}
      </p>
      {event.output && (
        <pre className="whitespace-pre-wrap font-mono text-[10px] leading-relaxed text-[#94a3b8]">
          {event.output}
        </pre>
      )}
    </div>
  );
}

/* ---- Helpers ---- */

function formatTimestamp(ts: string): string {
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 5) return "just now";
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    return `${Math.floor(diffSec / 3600)}h ago`;
  } catch {
    return ts;
  }
}
