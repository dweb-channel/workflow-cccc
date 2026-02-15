"use client";

import { useRef, useEffect, useState } from "react";
import type { PipelineEvent } from "../types";

/* ================================================================
   DesignEventFeed — Real-time pipeline event stream display.
   Shows node transitions, component loop iterations, and results.
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

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  const isRunning =
    jobStatus === "running" || jobStatus === "started";

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

      {/* ---- SSE Disconnect Banner ---- */}
      {!sseConnected && isRunning && (
        <div className="flex items-center gap-2 bg-[#fef2f2] border-b border-[#fecaca] px-4 py-2">
          <span className="h-2 w-2 rounded-full bg-[#ef4444] animate-pulse" />
          <span className="text-xs font-medium text-[#dc2626]">
            连接已断开，正在重连...
          </span>
        </div>
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
        ) : (
          events.map((evt, i) => (
            <EventRow key={i} event={evt} />
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
          {events.length} 条事件
        </span>
      </div>
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

  const isNodeEvent =
    event.event_type === "node_started" ||
    event.event_type === "node_completed";

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

  // node_output — show compact summary, expandable for raw data
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
   NodeOutputRow — Compact node output with expandable raw data
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
      // Handle both backend field formats: iteration/max_iterations (current) and current_index/total (future)
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
    case "ai_thinking":
      return (event.data?.content as string)?.slice(0, 80) || "AI 正在分析...";
    default:
      return JSON.stringify(event.data || {}).slice(0, 80);
  }
}
