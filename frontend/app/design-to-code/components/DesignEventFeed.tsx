"use client";

import { useRef, useEffect, useState, useMemo } from "react";
import type { PipelineEvent } from "../types";

/* ================================================================
   DesignEventFeed — Real-time pipeline event stream display.
   Shows node transitions, component loop iterations, and results.
   Features: event type filtering, compact summary mode, noise reduction.
   ================================================================ */

interface DesignEventFeedProps {
  events: PipelineEvent[];
  currentNode: string | null;
  sseConnected: boolean;
  jobStatus?: string;
}

// Pipeline node labels
const NODE_LABELS: Record<string, { icon: string; label: string }> = {
  design_analyzer: { icon: "\uD83D\uDD0D", label: "设计分析" },
  skeleton_generator: { icon: "\uD83C\uDFD7\uFE0F", label: "骨架生成" },
  component_generator: { icon: "\u2699\uFE0F", label: "组件生成" },
  visual_diff: { icon: "\uD83D\uDCF7", label: "视觉验证" },
  assembler: { icon: "\uD83D\uDCE6", label: "页面组装" },
  should_continue_components: { icon: "\uD83D\uDD04", label: "循环判断" },
  should_retry_component: { icon: "\uD83D\uDD01", label: "重试判断" },
};

// Event type display config
const EVENT_CONFIG: Record<string, { tagBg: string; tagColor: string; label: string }> = {
  workflow_start: { tagBg: "rgba(6,182,212,0.12)", tagColor: "#22d3ee", label: "Pipeline 启动" },
  node_started: { tagBg: "rgba(139,92,246,0.15)", tagColor: "#a78bfa", label: "节点开始" },
  node_completed: { tagBg: "rgba(34,197,94,0.12)", tagColor: "#4ade80", label: "节点完成" },
  node_output: { tagBg: "rgba(34,197,94,0.08)", tagColor: "#86efac", label: "节点输出" },
  loop_iteration: { tagBg: "rgba(249,115,22,0.12)", tagColor: "#fb923c", label: "组件迭代" },
  loop_terminated: { tagBg: "rgba(239,68,68,0.12)", tagColor: "#f87171", label: "循环终止" },
  job_status: { tagBg: "rgba(59,130,246,0.12)", tagColor: "#60a5fa", label: "状态更新" },
  workflow_complete: { tagBg: "rgba(34,197,94,0.15)", tagColor: "#4ade80", label: "Pipeline 完成" },
  workflow_error: { tagBg: "rgba(239,68,68,0.12)", tagColor: "#f87171", label: "Pipeline 错误" },
  ai_thinking: { tagBg: "rgba(139,92,246,0.15)", tagColor: "#a78bfa", label: "AI 分析" },
  job_done: { tagBg: "rgba(6,182,212,0.15)", tagColor: "#22d3ee", label: "任务结束" },
  figma_fetch_start: { tagBg: "rgba(139,92,246,0.12)", tagColor: "#a78bfa", label: "Figma 获取" },
  figma_fetch_complete: { tagBg: "rgba(34,197,94,0.12)", tagColor: "#4ade80", label: "Figma 完成" },
  frame_decomposed: { tagBg: "rgba(6,182,212,0.15)", tagColor: "#22d3ee", label: "结构分解" },
  spec_analyzed: { tagBg: "rgba(139,92,246,0.15)", tagColor: "#a78bfa", label: "语义分析" },
  spec_complete: { tagBg: "rgba(34,197,94,0.15)", tagColor: "#4ade80", label: "规格完成" },
};

// Filter categories mapping event types to filter groups
type FilterCategory = "all" | "node" | "spec" | "loop" | "error";

const FILTER_BUTTONS: { key: FilterCategory; label: string; icon: string }[] = [
  { key: "all", label: "全部", icon: "" },
  { key: "node", label: "节点", icon: "\u2699\uFE0F" },
  { key: "spec", label: "分析", icon: "\uD83D\uDD0D" },
  { key: "loop", label: "循环", icon: "\uD83D\uDD04" },
  { key: "error", label: "错误", icon: "\u26A0\uFE0F" },
];

const EVENT_CATEGORY_MAP: Record<string, FilterCategory> = {
  node_started: "node",
  node_completed: "node",
  node_output: "node",
  workflow_start: "node",
  workflow_complete: "node",
  job_status: "node",
  job_done: "node",
  figma_fetch_start: "spec",
  figma_fetch_complete: "spec",
  frame_decomposed: "spec",
  spec_analyzed: "spec",
  spec_complete: "spec",
  ai_thinking: "spec",
  loop_iteration: "loop",
  loop_terminated: "loop",
  workflow_error: "error",
};

function getEventCategory(eventType: string): FilterCategory {
  return EVENT_CATEGORY_MAP[eventType] ?? "node";
}

function getNodeLabel(nodeId: string) {
  return NODE_LABELS[nodeId] ?? { icon: "\u2699\uFE0F", label: nodeId };
}

export function DesignEventFeed({
  events,
  currentNode,
  sseConnected,
  jobStatus,
}: DesignEventFeedProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [activeFilter, setActiveFilter] = useState<FilterCategory>("all");

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  const isRunning =
    jobStatus === "running" || jobStatus === "started";
  const isCompleted =
    jobStatus === "completed" || jobStatus === "failed";

  // Compute filter counts
  const filterCounts = useMemo(() => {
    const counts: Record<FilterCategory, number> = {
      all: events.length,
      node: 0,
      spec: 0,
      loop: 0,
      error: 0,
    };
    for (const evt of events) {
      const cat = getEventCategory(evt.event_type);
      counts[cat]++;
    }
    return counts;
  }, [events]);

  // Filter events
  const filteredEvents = useMemo(() => {
    if (activeFilter === "all") return events;
    return events.filter(
      (evt) => getEventCategory(evt.event_type) === activeFilter
    );
  }, [events, activeFilter]);

  // Compact summary for completed pipelines
  const completionSummary = useMemo(() => {
    if (!isCompleted) return null;
    const specEvents = events.filter(
      (e) => e.event_type === "spec_analyzed"
    );
    const errors = events.filter(
      (e) =>
        e.event_type === "workflow_error" ||
        (e.event_type === "workflow_complete" &&
          e.data?.status === "failed")
    );
    const startEvt = events.find(
      (e) => e.event_type === "workflow_start"
    );
    const endEvt = events.findLast(
      (e) =>
        e.event_type === "workflow_complete" ||
        e.event_type === "job_done"
    );
    let durationStr = "";
    if (startEvt && endEvt) {
      const ms =
        new Date(endEvt.timestamp).getTime() -
        new Date(startEvt.timestamp).getTime();
      durationStr =
        ms >= 60000
          ? `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
          : `${Math.round(ms / 1000)}s`;
    }
    return {
      componentsAnalyzed: specEvents.length,
      errorCount: errors.length,
      totalEvents: events.length,
      duration: durationStr,
      status: jobStatus,
    };
  }, [events, isCompleted, jobStatus]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-700 bg-slate-800 overflow-hidden">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">Pipeline 日志</span>
          {isRunning && (
            <span className="flex items-center gap-1 rounded-full bg-[#fef2f2] px-2 py-0.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#ef4444] animate-pulse" />
              <span className="text-[10px] font-semibold text-[#dc2626]">
                LIVE
              </span>
            </span>
          )}
        </div>
        {currentNode && (
          <span className="text-xs text-slate-400">
            当前: {getNodeLabel(currentNode).icon}{" "}
            {getNodeLabel(currentNode).label}
          </span>
        )}
      </div>

      {/* ---- Filter Bar ---- */}
      {events.length > 0 && (
        <div className="flex items-center gap-1 border-b border-slate-700 bg-slate-900/50 px-3 py-1.5">
          {FILTER_BUTTONS.map((btn) => {
            const count = filterCounts[btn.key];
            const isActive = activeFilter === btn.key;
            return (
              <button
                key={btn.key}
                onClick={() => setActiveFilter(btn.key)}
                className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors ${
                  isActive
                    ? "bg-slate-600 text-white"
                    : "text-slate-400 hover:bg-slate-700/50 hover:text-slate-300"
                }`}
              >
                {btn.icon && <span className="text-[10px]">{btn.icon}</span>}
                {btn.label}
                {count > 0 && (
                  <span
                    className={`ml-0.5 rounded-full px-1.5 text-[10px] ${
                      isActive
                        ? "bg-slate-500 text-white"
                        : "bg-slate-700 text-slate-500"
                    }`}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* ---- SSE Disconnect Banner ---- */}
      {!sseConnected && isRunning && (
        <div className="flex items-center gap-2 bg-[#fef2f2] border-b border-[#fecaca] px-4 py-2">
          <span className="h-2 w-2 rounded-full bg-[#ef4444] animate-pulse" />
          <span className="text-xs font-medium text-[#dc2626]">
            连接已断开，正在重连...
          </span>
        </div>
      )}

      {/* ---- Completion Summary Banner ---- */}
      {completionSummary && (
        <CompletionSummary summary={completionSummary} />
      )}

      {/* ---- Feed Body ---- */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {events.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-8 justify-center">
            {isRunning ? (
              <>
                <span className="h-2 w-2 rounded-full bg-[#3b82f6] animate-pulse" />
                <span className="text-xs text-slate-400">
                  等待 Pipeline 启动...
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-500">
                提交任务后，Pipeline 事件将在此显示
              </span>
            )}
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="flex items-center justify-center px-4 py-8">
            <span className="text-xs text-slate-500">
              没有匹配「{FILTER_BUTTONS.find((b) => b.key === activeFilter)?.label}」的事件
            </span>
          </div>
        ) : (
          filteredEvents.map((evt, i) => (
            <EventRow key={`${evt.event_type}-${evt.timestamp}-${i}`} event={evt} />
          ))
        )}
      </div>

      {/* ---- Bottom Bar ---- */}
      <div className="flex items-center gap-2 border-t border-slate-700 bg-slate-900 px-4 py-2.5">
        {isRunning ? (
          <>
            <span className="h-2 w-2 rounded-full bg-[#3b82f6] animate-pulse" />
            <span className="text-xs text-slate-400">
              {currentNode
                ? `正在执行: ${getNodeLabel(currentNode).label}`
                : "处理中..."}
            </span>
          </>
        ) : (
          <>
            <span className="h-2 w-2 rounded-full bg-slate-300" />
            <span className="text-xs text-slate-400">
              {jobStatus === "completed"
                ? "Pipeline 已完成"
                : jobStatus === "failed"
                  ? "Pipeline 失败"
                  : "空闲"}
            </span>
          </>
        )}
        <div className="flex-1" />
        <span className="font-mono text-[11px] text-slate-500">
          {activeFilter !== "all"
            ? `${filteredEvents.length}/${events.length} 条事件`
            : `${events.length} 条事件`}
        </span>
      </div>
    </div>
  );
}

/* ================================================================
   CompletionSummary — Compact summary shown after pipeline completes
   ================================================================ */

function CompletionSummary({
  summary,
}: {
  summary: {
    componentsAnalyzed: number;
    errorCount: number;
    totalEvents: number;
    duration: string;
    status?: string;
  };
}) {
  const isFailed = summary.status === "failed";
  return (
    <div
      className={`flex items-center gap-3 border-b px-4 py-2.5 ${
        isFailed
          ? "border-red-500/30 bg-red-500/5"
          : "border-green-500/30 bg-green-500/5"
      }`}
    >
      <span
        className={`text-xs font-semibold ${
          isFailed ? "text-red-400" : "text-green-400"
        }`}
      >
        {isFailed ? "Pipeline 失败" : "Pipeline 完成"}
      </span>
      <span className="text-[11px] text-slate-400">
        {summary.componentsAnalyzed} 组件分析
      </span>
      {summary.errorCount > 0 && (
        <span className="text-[11px] text-red-400">
          {summary.errorCount} 错误
        </span>
      )}
      {summary.duration && (
        <span className="text-[11px] text-slate-500">
          耗时 {summary.duration}
        </span>
      )}
      <span className="ml-auto text-[11px] text-slate-600">
        {summary.totalEvents} 条事件
      </span>
    </div>
  );
}

/* ================================================================
   EventRow — Single pipeline event display
   ================================================================ */

function EventRow({ event }: { event: PipelineEvent }) {
  const cfg = EVENT_CONFIG[event.event_type] ?? {
    tagBg: "rgba(100,116,139,0.2)",
    tagColor: "#94a3b8",
    label: event.event_type,
  };

  // ai_thinking — collapsed by default, minimal noise
  if (event.event_type === "ai_thinking") {
    return <AiThinkingRow event={event} cfg={cfg} />;
  }

  // Node separator style for node transitions
  if (event.event_type === "node_started" && event.node_id) {
    const { icon, label } = getNodeLabel(event.node_id);
    return (
      <div className="flex items-center gap-2 bg-violet-500/10 px-4 py-2.5 border-b border-slate-700">
        <div className="h-px w-5 bg-violet-500/40" />
        <span className="text-xs font-semibold text-violet-400">
          {icon} {label}
        </span>
        <span className="font-mono text-[11px] text-violet-500/50">
          {formatTime(event.timestamp)}
        </span>
        <div className="h-px flex-1 bg-violet-500/40" />
      </div>
    );
  }

  // Node completed
  if (event.event_type === "node_completed" && event.node_id) {
    const { icon, label } = getNodeLabel(event.node_id);
    return (
      <div className="flex items-center gap-2 border-b border-slate-700 px-4 py-2">
        <span
          className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
          style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
        >
          {cfg.label}
        </span>
        <span className="text-xs text-slate-300">
          {icon} {label}
        </span>
        <span className="ml-auto font-mono text-[11px] text-slate-500">
          {formatTime(event.timestamp)}
        </span>
      </div>
    );
  }

  // Job done / workflow complete — highlighted
  if (
    event.event_type === "workflow_complete" ||
    event.event_type === "job_done"
  ) {
    const borderColor =
      event.data?.status === "failed" ? "#ef4444" : "#22c55e";
    return (
      <div
        className="border-b border-slate-700 border-l-[3px] px-4 py-3"
        style={{ borderLeftColor: borderColor }}
      >
        <div className="flex items-center gap-2">
          <span
            className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
          >
            {cfg.label}
          </span>
          <span className="text-xs text-slate-300">
            {event.data?.status === "failed"
              ? `Pipeline 失败: ${event.data?.error || "未知错误"}`
              : `Pipeline 完成 — ${event.data?.components_completed || 0}/${event.data?.components_total || 0} 组件`}
          </span>
          <span className="ml-auto font-mono text-[11px] text-slate-500">
            {formatTime(event.timestamp)}
          </span>
        </div>
      </div>
    );
  }

  // Workflow error
  if (event.event_type === "workflow_error") {
    return (
      <div
        className="border-b border-slate-700 border-l-[3px] px-4 py-3"
        style={{ borderLeftColor: "#ef4444" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
          >
            {cfg.label}
          </span>
          <span className="text-xs text-red-400">
            {event.message ||
              (event.data?.error as string) ||
              "Pipeline 执行出错"}
          </span>
          <span className="ml-auto font-mono text-[11px] text-slate-500">
            {formatTime(event.timestamp)}
          </span>
        </div>
      </div>
    );
  }

  // spec_complete — show validation result
  if (event.event_type === "spec_complete") {
    const validation = event.data?.validation as Record<string, unknown> | undefined;
    const compliant = validation?.auto_layout_compliant === true;
    const inferredNodes = (validation?.inferred_nodes ?? []) as Array<{ name: string; path: string; children_count: number }>;
    const borderColor = compliant ? "#22c55e" : "#f59e0b";
    return (
      <div
        className="border-b border-slate-700 border-l-[3px] px-4 py-3"
        style={{ borderLeftColor: borderColor }}
      >
        <div className="flex items-center gap-2">
          <span
            className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
            style={{ backgroundColor: compliant ? "rgba(34,197,94,0.15)" : "rgba(245,158,11,0.15)", color: compliant ? "#4ade80" : "#fbbf24" }}
          >
            {compliant ? "规格完成" : "规格警告"}
          </span>
          <span className="text-xs text-slate-300">
            {event.data?.components_succeeded as number ?? 0}/{event.data?.components_count as number ?? 0} 组件
            {!compliant && ` — ${inferredNodes.length} 个节点缺少 auto-layout`}
          </span>
          <span className="ml-auto font-mono text-[11px] text-slate-500">
            {formatTime(event.timestamp)}
          </span>
        </div>
        {!compliant && inferredNodes.length > 0 && (
          <ValidationWarning nodes={inferredNodes} />
        )}
      </div>
    );
  }

  // node_output — show compact summary with key fields only
  if (event.event_type === "node_output") {
    return <NodeOutputRow event={event} cfg={cfg} />;
  }

  // Default event row
  return (
    <div className="flex items-center gap-2 border-b border-slate-700 px-4 py-2">
      <span
        className="inline-block rounded px-1.5 py-0.5 text-[11px] font-medium"
        style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
      >
        {cfg.label}
      </span>
      <span className="text-xs text-slate-300 truncate flex-1">
        {event.message || describeEvent(event)}
      </span>
      <span className="shrink-0 font-mono text-[11px] text-slate-500">
        {formatTime(event.timestamp)}
      </span>
    </div>
  );
}

/* ================================================================
   AiThinkingRow — Collapsed by default to reduce noise
   ================================================================ */

function AiThinkingRow({
  event,
  cfg,
}: {
  event: PipelineEvent;
  cfg: { tagBg: string; tagColor: string; label: string };
}) {
  const [expanded, setExpanded] = useState(false);
  const content = (event.data?.content as string) || "AI 正在分析...";
  const preview = content.slice(0, 60) + (content.length > 60 ? "..." : "");

  return (
    <div className="border-b border-slate-700">
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center gap-2 px-4 py-1 text-left hover:bg-slate-700/30 transition-colors"
      >
        <span
          className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium shrink-0 opacity-60"
          style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
        >
          {cfg.label}
        </span>
        <span className="text-[10px] text-slate-500 truncate flex-1">
          {preview}
        </span>
        <span className="text-[10px] text-slate-600 shrink-0">
          {expanded ? "▼" : "▶"}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-600">
          {formatTime(event.timestamp)}
        </span>
      </button>
      {expanded && (
        <div className="bg-slate-900/60 px-4 py-2 text-[11px] text-slate-400 whitespace-pre-wrap max-h-[150px] overflow-y-auto">
          {content}
        </div>
      )}
    </div>
  );
}

/* ================================================================
   NodeOutputRow — Compact node output with key fields only
   ================================================================ */

function NodeOutputRow({
  event,
  cfg,
}: {
  event: PipelineEvent;
  cfg: { tagBg: string; tagColor: string; label: string };
}) {
  const [expanded, setExpanded] = useState(false);
  const summary = summarizeNodeOutput(event);
  const keyFields = extractKeyFields(event);

  return (
    <div className="border-b border-slate-700">
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center gap-2 px-4 py-1.5 text-left hover:bg-slate-700/30 transition-colors"
      >
        <span
          className="inline-block rounded px-1.5 py-0.5 text-[10px] font-medium shrink-0"
          style={{ backgroundColor: cfg.tagBg, color: cfg.tagColor }}
        >
          {cfg.label}
        </span>
        <span className="text-[11px] text-slate-400 truncate flex-1">
          {summary}
        </span>
        {keyFields.length > 0 && (
          <span className="hidden sm:flex items-center gap-1 shrink-0">
            {keyFields.map((kf, i) => (
              <span
                key={`${kf}-${i}`}
                className="rounded bg-slate-700/50 px-1.5 py-0.5 text-[10px] text-slate-500"
              >
                {kf}
              </span>
            ))}
          </span>
        )}
        <span className="text-[10px] text-slate-600 shrink-0">
          {expanded ? "▼" : "▶"}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-slate-600">
          {formatTime(event.timestamp)}
        </span>
      </button>
      {expanded && (
        <pre className="bg-slate-900 px-4 py-2 text-[11px] text-slate-500 overflow-x-auto max-h-[200px] overflow-y-auto font-mono">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

/* ================================================================
   ValidationWarning — Expandable auto-layout compliance warning
   ================================================================ */

function ValidationWarning({
  nodes,
}: {
  nodes: Array<{ name: string; path: string; children_count: number }>;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center gap-2 text-left"
      >
        <span className="text-xs text-amber-400">
          ⚠ {nodes.length} 个节点缺少 auto-layout，需要在 Figma 中补充
        </span>
        <span className="ml-auto text-[10px] text-amber-500/60">
          {expanded ? "收起" : "展开"}
        </span>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1 max-h-40 overflow-y-auto">
          {nodes.map((n, i) => (
            <div key={`${n.name}-${i}`} className="flex items-center gap-2 text-[11px]">
              <span className="text-amber-400/80">•</span>
              <span className="text-amber-300 font-medium">{n.name}</span>
              <span className="text-amber-500/60 truncate">{n.path}</span>
              <span className="ml-auto text-amber-500/50 shrink-0">
                {n.children_count} children
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Helpers
   ================================================================ */

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function extractKeyFields(event: PipelineEvent): string[] {
  const fields: string[] = [];
  const data = event.data;
  if (!data) return fields;

  if (typeof data.components_count === "number") {
    fields.push(`${data.components_count} 组件`);
  }
  if (typeof data.succeeded === "number" && typeof data.total === "number") {
    fields.push(`${data.succeeded}/${data.total}`);
  }
  if (data.design_file) {
    fields.push(String(data.design_file).split("/").pop() || "");
  }
  return fields.slice(0, 3);
}

function summarizeNodeOutput(event: PipelineEvent): string {
  const nodeId = event.node_id || (event.data?.node as string) || "";
  const { label } = getNodeLabel(nodeId);
  const output = event.data?.output;

  // Try to detect code output (has lines)
  if (typeof output === "string" && output.includes("\n")) {
    const lines = output.split("\n").length;
    return `${label} — ${lines} lines output`;
  }

  // Try to describe known output shapes
  if (event.data?.design_file) {
    return `${label} — processing ${String(event.data.design_file).split("/").pop()}`;
  }

  return `${label} — output received`;
}

function describeEvent(event: PipelineEvent): string {
  switch (event.event_type) {
    case "loop_iteration": {
      const idx = event.data?.iteration ?? event.data?.current_index;
      const total = event.data?.max_iterations ?? event.data?.total;
      return idx != null && total != null
        ? `组件 ${Number(idx)}/${total}`
        : "组件循环迭代";
    }
    case "loop_terminated": {
      const nodeId = event.data?.node_id as string;
      const reason = event.data?.reason as string;
      return `${nodeId || "节点"} 循环终止 — ${reason || "超过最大迭代次数"}`;
    }
    case "job_status":
      return `状态: ${event.data?.status || "unknown"}`;
    case "workflow_start":
      return "Pipeline 开始执行";
    case "figma_fetch_start":
      return "正在从 Figma 获取设计数据...";
    case "figma_fetch_complete":
      return "Figma 设计数据获取完成";
    case "frame_decomposed": {
      const count = event.data?.components_count as number;
      const pageName = (event.data?.page as Record<string, unknown>)?.name as string;
      return pageName
        ? `页面「${pageName}」已拆解为 ${count ?? "?"} 个组件`
        : `结构拆解完成，共 ${count ?? "?"} 个组件`;
    }
    case "spec_analyzed": {
      const compName = event.data?.component_name as string;
      const role = event.data?.role as string;
      const idx = event.data?.index as number;
      const total = event.data?.total as number;
      const progress = idx != null && total ? `(${idx + 1}/${total}) ` : "";
      const roleBadge = role ? `[${role}] ` : "";
      return `${progress}${roleBadge}${compName || "组件"} 语义分析完成`;
    }
    case "ai_thinking":
      return (event.data?.content as string)?.slice(0, 80) || "AI 正在分析...";
    default:
      return JSON.stringify(event.data || {}).slice(0, 80);
  }
}
