"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { DesignJob, DesignJobStats, PipelineEvent } from "../types";
import type { ComponentSpec } from "@/lib/types/design-spec";

/* ================================================================
   DesignOverview — Right panel showing job status + stats +
   per-component progress dashboard (during pipeline run).
   ================================================================ */

interface ComponentTokenUsage {
  component_id: string;
  component_name: string;
  input_tokens: number;
  output_tokens: number;
}

interface DesignOverviewProps {
  currentJob: DesignJob | null;
  stats: DesignJobStats;
  /** Live components from designSpec (progressive SSE rendering) */
  components?: ComponentSpec[];
  /** Pipeline events for deriving per-component status & tokens */
  events?: PipelineEvent[];
  /** Aggregate token usage */
  tokenUsage?: { input_tokens: number; output_tokens: number } | null;
}

/** Derive per-component analysis status from SSE events */
function deriveComponentStatuses(
  components: ComponentSpec[],
  events: PipelineEvent[]
): Map<string, "pending" | "analyzing" | "complete" | "error"> {
  const statuses = new Map<string, "pending" | "analyzing" | "complete" | "error">();

  // Initialize all components as pending
  for (const comp of components) {
    statuses.set(comp.id, "pending");
  }

  // Walk events to update statuses
  for (const evt of events) {
    const compId = (evt.data?.component_id as string) || "";
    if (!compId) continue;

    if (evt.event_type === "spec_analyzed") {
      statuses.set(compId, "complete");
    }
  }

  // Check for components currently being analyzed (have description but no spec_analyzed event)
  for (const comp of components) {
    if (statuses.get(comp.id) === "pending" && comp.design_analysis) {
      statuses.set(comp.id, "complete");
    }
    if (statuses.get(comp.id) === "pending" && comp.description) {
      statuses.set(comp.id, "analyzing");
    }
  }

  return statuses;
}

/** Extract per-component token usage from spec_analyzed events */
function extractComponentTokens(events: PipelineEvent[]): ComponentTokenUsage[] {
  const tokens: ComponentTokenUsage[] = [];
  for (const evt of events) {
    if (evt.event_type !== "spec_analyzed") continue;
    const data = evt.data;
    if (!data) continue;
    const tokensUsed = data.tokens_used as { input_tokens?: number; output_tokens?: number } | undefined;
    if (!tokensUsed) continue;
    tokens.push({
      component_id: (data.component_id as string) || "",
      component_name: (data.suggested_name as string) || (data.component_name as string) || "?",
      input_tokens: tokensUsed.input_tokens ?? 0,
      output_tokens: tokensUsed.output_tokens ?? 0,
    });
  }
  return tokens;
}

export function DesignOverview({
  currentJob,
  stats,
  components,
  events,
  tokenUsage,
}: DesignOverviewProps) {
  const [showTokenDetail, setShowTokenDetail] = useState(false);

  const componentStatuses = useMemo(
    () => deriveComponentStatuses(components ?? [], events ?? []),
    [components, events]
  );

  const componentTokens = useMemo(
    () => extractComponentTokens(events ?? []),
    [events]
  );

  if (!currentJob) {
    return (
      <div className="flex h-[300px] items-center justify-center text-muted-foreground">
        <p>尚未开始任务</p>
      </div>
    );
  }

  const progressPct =
    stats.total > 0
      ? Math.round(((stats.completed + stats.failed) / stats.total) * 100)
      : 0;

  const statusLabel =
    currentJob.job_status === "completed"
      ? "已完成"
      : currentJob.job_status === "failed"
        ? "失败"
        : currentJob.job_status === "cancelled"
          ? "已取消"
          : "生成中";

  const statusStyle: Record<
    string,
    { bg: string; text: string; dot: string }
  > = {
    started: {
      bg: "bg-blue-500/10",
      text: "text-blue-400",
      dot: "bg-blue-500 animate-pulse",
    },
    running: {
      bg: "bg-violet-500/10",
      text: "text-violet-400",
      dot: "bg-violet-500 animate-pulse",
    },
    completed: {
      bg: "bg-green-500/10",
      text: "text-green-400",
      dot: "bg-green-500",
    },
    failed: {
      bg: "bg-red-500/10",
      text: "text-red-400",
      dot: "bg-red-500",
    },
    cancelled: {
      bg: "bg-amber-500/10",
      text: "text-amber-400",
      dot: "bg-amber-500",
    },
  };
  const style = statusStyle[currentJob.job_status] ?? statusStyle.running;

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className={`rounded-lg p-3 ${style.bg}`}>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${style.dot}`} />
          <span className={`text-sm font-medium ${style.text}`}>
            {statusLabel}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {stats.completed}/{stats.total} 组件完成 · {progressPct}%
        </p>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            currentJob.job_status === "failed"
              ? "bg-red-500"
              : currentJob.job_status === "cancelled"
                ? "bg-amber-500"
                : currentJob.job_status === "completed"
                  ? "bg-green-500"
                  : "bg-violet-500"
          }`}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-green-500/10 p-2">
          <p className="text-xl font-bold text-green-400">{stats.completed}</p>
          <p className="text-[10px] text-green-500">完成</p>
        </div>
        <div className="rounded-lg bg-muted/50 p-2">
          <p className="text-xl font-bold text-foreground">{stats.pending}</p>
          <p className="text-[10px] text-muted-foreground">等待</p>
        </div>
        <div className="rounded-lg bg-red-500/10 p-2">
          <p className="text-xl font-bold text-red-400">{stats.failed}</p>
          <p className="text-[10px] text-red-500">失败</p>
        </div>
      </div>

      {/* Component progress list */}
      {components && components.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            组件进度
          </p>
          <div className="space-y-1 max-h-[200px] overflow-y-auto">
            {components.map((comp) => {
              const status = componentStatuses.get(comp.id) ?? "pending";
              return (
                <ComponentProgressRow
                  key={comp.id}
                  name={comp.name}
                  role={comp.role}
                  status={status}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Token usage summary + per-component detail */}
      {tokenUsage && (tokenUsage.input_tokens > 0 || tokenUsage.output_tokens > 0) && (
        <div className="space-y-1.5">
          <button
            onClick={() => setShowTokenDetail((v) => !v)}
            className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground uppercase tracking-wider hover:text-foreground transition-colors"
          >
            {showTokenDetail ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Token 用量
          </button>
          <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
            <span>输入 <span className="text-foreground font-mono">{tokenUsage.input_tokens.toLocaleString()}</span></span>
            <span>输出 <span className="text-foreground font-mono">{tokenUsage.output_tokens.toLocaleString()}</span></span>
            <span>合计 <span className="text-foreground font-mono">{(tokenUsage.input_tokens + tokenUsage.output_tokens).toLocaleString()}</span></span>
          </div>
          {showTokenDetail && componentTokens.length > 0 && (
            <div className="space-y-0.5 mt-1">
              {componentTokens.map((ct) => (
                <div key={ct.component_id} className="flex items-center justify-between text-[10px] text-muted-foreground px-1 py-0.5 rounded hover:bg-muted/30">
                  <span className="text-muted-foreground truncate max-w-[140px]">{ct.component_name}</span>
                  <span className="font-mono text-muted-foreground shrink-0">
                    {ct.input_tokens > 0 && <span className="mr-2">in:{ct.input_tokens.toLocaleString()}</span>}
                    out:{ct.output_tokens.toLocaleString()}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Job details */}
      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">任务 ID:</span>
          <code className="bg-muted px-1.5 py-0.5 rounded text-[11px] text-violet-300">
            {currentJob.job_id}
          </code>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 text-muted-foreground">设计文件:</span>
          <code className="bg-muted px-1.5 py-0.5 rounded text-[11px] text-foreground break-all">
            {currentJob.design_file}
          </code>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 text-muted-foreground">输出目录:</span>
          <code className="bg-muted px-1.5 py-0.5 rounded text-[11px] text-foreground break-all">
            {currentJob.output_dir}
          </code>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">创建时间:</span>
          <span className="text-foreground">
            {formatDateTime(currentJob.created_at)}
          </span>
        </div>
        {currentJob.error && (
          <div className="mt-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2">
            <p className="text-xs text-red-400">{currentJob.error}</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================
   ComponentProgressRow — Single component status in the dashboard
   ================================================================ */

const STATUS_CONFIG = {
  pending: { dot: "bg-muted-foreground", label: "等待", text: "text-muted-foreground" },
  analyzing: { dot: "bg-violet-500 animate-pulse", label: "分析中", text: "text-violet-400" },
  complete: { dot: "bg-green-500", label: "完成", text: "text-green-400" },
  error: { dot: "bg-red-500", label: "失败", text: "text-red-400" },
} as const;

const ROLE_COLORS: Record<string, string> = {
  header: "text-blue-400",
  nav: "text-cyan-400",
  section: "text-violet-400",
  button: "text-amber-400",
  card: "text-emerald-400",
  list: "text-teal-400",
  image: "text-pink-400",
  text: "text-muted-foreground",
  container: "text-muted-foreground",
  footer: "text-indigo-400",
};

function ComponentProgressRow({
  name,
  role,
  status,
}: {
  name: string;
  role: string;
  status: "pending" | "analyzing" | "complete" | "error";
}) {
  const cfg = STATUS_CONFIG[status];
  const roleColor = ROLE_COLORS[role] ?? "text-muted-foreground";

  return (
    <div className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-muted/30 transition-colors">
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${cfg.dot}`} />
      <span className="text-[11px] text-foreground truncate flex-1">{name}</span>
      <span className={`text-[10px] ${roleColor} shrink-0`}>{role}</span>
      <span className={`text-[10px] ${cfg.text} shrink-0 w-8 text-right`}>{cfg.label}</span>
    </div>
  );
}

function formatDateTime(ts: string): string {
  try {
    return new Date(ts).toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}
