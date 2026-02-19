"use client";

import { useMemo } from "react";
import type { BatchJob, BugStatus } from "../types";

/* ================================================================
   PipelineBar — Horizontal progress bar with clickable bug badges.
   Shows completion status at a glance and allows navigating to
   specific bugs in the ActivityFeed.
   ================================================================ */

interface PipelineBarProps {
  currentJob: BatchJob | null;
  activeBugIndex: number | null;
  onBugSelect: (index: number) => void;
}

export function PipelineBar({ currentJob, activeBugIndex, onBugSelect }: PipelineBarProps) {
  if (!currentJob) return null;

  const bugs = currentJob.bugs;
  const completed = bugs.filter((b) => b.status === "completed").length;
  const failed = bugs.filter((b) => b.status === "failed" || b.status === "skipped").length;
  const total = bugs.length;

  const isFinished = ["completed", "failed", "cancelled"].includes(currentJob.job_status);

  return (
    <div className="rounded-xl border border-border bg-card px-5 py-3.5">
      {/* Header row */}
      <div className="flex items-center justify-between mb-2.5">
        <span className="text-[13px] font-semibold text-card-foreground">执行进度</span>
        <span className="text-xs text-muted-foreground">
          {isFinished ? (
            <>
              {completed}/{total} 完成
              {failed > 0 && <> · {failed} 失败</>}
            </>
          ) : (
            <>{completed}/{total} 完成</>
          )}
        </span>
      </div>

      {/* Badge row */}
      <div className="flex items-center gap-2 overflow-x-auto pb-0.5">
        {bugs.map((bug, idx) => (
          <BugBadgeGroup key={bug.bug_id} bug={bug} index={idx} isLast={idx === total - 1} isActive={activeBugIndex === idx} onSelect={() => onBugSelect(idx)} />
        ))}
      </div>
    </div>
  );
}

/* ---- Badge + Arrow group ---- */

function BugBadgeGroup({
  bug,
  index,
  isLast,
  isActive,
  onSelect,
}: {
  bug: BugStatus;
  index: number;
  isLast: boolean;
  isActive: boolean;
  onSelect: () => void;
}) {
  return (
    <>
      <BugBadge bug={bug} isActive={isActive} onSelect={onSelect} />
      {!isLast && <span className="shrink-0 text-muted-foreground">&rarr;</span>}
    </>
  );
}

/* ---- Individual Badge ---- */

const BADGE_CONFIG: Record<string, {
  bg: string;
  border: string;
  borderWidth: number;
  icon: string;
  idColor: string;
  subColor: string;
}> = {
  completed: {
    bg: "rgba(34,197,94,0.1)",
    border: "rgba(34,197,94,0.3)",
    borderWidth: 1,
    icon: "\u2705",
    idColor: "#4ade80",
    subColor: "#22c55e",
  },
  in_progress: {
    bg: "rgba(6,182,212,0.1)",
    border: "#06b6d4",
    borderWidth: 2,
    icon: "\u{1F527}",
    idColor: "#22d3ee",
    subColor: "#06b6d4",
  },
  pending: {
    bg: "rgba(51,65,85,0.5)",
    border: "rgba(71,85,105,0.5)",
    borderWidth: 1,
    icon: "\u23F3",
    idColor: "#94a3b8",
    subColor: "#64748b",
  },
  failed: {
    bg: "rgba(239,68,68,0.1)",
    border: "rgba(239,68,68,0.3)",
    borderWidth: 1,
    icon: "\u274C",
    idColor: "#f87171",
    subColor: "#ef4444",
  },
  skipped: {
    bg: "rgba(239,68,68,0.1)",
    border: "rgba(239,68,68,0.3)",
    borderWidth: 1,
    icon: "\u23ED\uFE0F",
    idColor: "#f87171",
    subColor: "#ef4444",
  },
};

function BugBadge({
  bug,
  isActive,
  onSelect,
}: {
  bug: BugStatus;
  isActive: boolean;
  onSelect: () => void;
}) {
  const cfg = BADGE_CONFIG[bug.status] ?? BADGE_CONFIG.pending;
  const subText = useBugSubText(bug);

  return (
    <button
      onClick={onSelect}
      className={`flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-2 transition-shadow ${
        isActive ? "ring-2 ring-ring ring-offset-1 ring-offset-card" : ""
      }`}
      style={{
        backgroundColor: cfg.bg,
        border: `${cfg.borderWidth}px solid ${cfg.border}`,
      }}
    >
      <span className="text-sm">{cfg.icon}</span>
      <div className="flex flex-col items-start gap-0.5">
        <span
          className="font-mono text-xs font-semibold leading-none"
          style={{ color: cfg.idColor }}
        >
          {bug.bug_id}
        </span>
        <span
          className="text-[10px] leading-none"
          style={{ color: cfg.subColor }}
        >
          {subText}
        </span>
      </div>
    </button>
  );
}

/* ---- Helpers ---- */

function useBugSubText(bug: BugStatus): string {
  return useMemo(() => {
    const parts: string[] = [];

    if (bug.status === "in_progress") {
      parts.push("修复中");
      // Elapsed from steps
      const elapsed = getElapsedFromSteps(bug);
      if (elapsed) parts.push(elapsed);
    } else if (bug.status === "completed") {
      const duration = getTotalDuration(bug);
      if (duration) parts.push(duration);
      if (bug.retry_count && bug.retry_count > 0) {
        parts.push(`${bug.retry_count}次重试`);
      }
    } else if (bug.status === "failed") {
      parts.push("失败");
      if (bug.retry_count && bug.retry_count > 0) {
        parts.push(`${bug.retry_count}次重试后跳过`);
      }
    } else if (bug.status === "skipped") {
      parts.push("已跳过");
    } else {
      parts.push("等待中");
    }

    return parts.join(" \u00B7 ");
  }, [bug.status, bug.retry_count, bug.steps]);
}

function getTotalDuration(bug: BugStatus): string | null {
  const totalMs = (bug.steps ?? []).reduce((sum, s) => sum + (s.duration_ms ?? 0), 0);
  if (totalMs <= 0) return null;
  return formatDuration(totalMs);
}

function getElapsedFromSteps(bug: BugStatus): string | null {
  const steps = bug.steps ?? [];
  // Find the earliest started_at
  const started = steps
    .map((s) => s.started_at)
    .filter(Boolean)
    .sort()[0];
  if (!started) return null;

  const elapsed = Date.now() - new Date(started).getTime();
  if (elapsed <= 0) return null;
  return formatDuration(elapsed);
}

function formatDuration(ms: number): string {
  const sec = Math.round(ms / 1000);
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return min > 0 ? `${min}m ${String(rem).padStart(2, "0")}s` : `${rem}s`;
}
