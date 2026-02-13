"use client";

import type { BatchJob, BatchJobStats } from "../types";

interface OverviewTabProps {
  currentJob: BatchJob | null;
  stats: BatchJobStats;
}

export function OverviewTab({ currentJob, stats }: OverviewTabProps) {
  if (!currentJob) {
    return (
      <div
        className="flex h-[300px] items-center justify-center text-slate-400"
        data-testid="tab-overview"
      >
        <p>尚未开始任务</p>
      </div>
    );
  }

  const total = currentJob.bugs.length;
  const progressPct =
    total > 0
      ? Math.round(
          ((stats.completed + stats.failed + stats.skipped) / total) * 100
        )
      : 0;

  const statusLabel =
    currentJob.job_status === "completed"
      ? "已完成"
      : currentJob.job_status === "failed"
        ? "失败"
        : currentJob.job_status === "cancelled"
          ? "已取消"
          : "修复中";

  const statusStyle: Record<string, { bg: string; text: string; dot: string }> = {
    running:   { bg: "bg-blue-50",   text: "text-blue-800",  dot: "bg-blue-500 animate-pulse" },
    completed: { bg: "bg-green-50",  text: "text-green-800", dot: "bg-green-500" },
    failed:    { bg: "bg-red-50",    text: "text-red-800",   dot: "bg-red-500" },
    cancelled: { bg: "bg-amber-50",  text: "text-amber-800", dot: "bg-amber-500" },
  };
  const style = statusStyle[currentJob.job_status] ?? statusStyle.running;

  return (
    <div className="space-y-4" data-testid="tab-overview">
      {/* Current task status */}
      <div className={`rounded-lg p-3 ${style.bg}`}>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${style.dot}`} />
          <span className={`text-sm font-medium ${style.text}`}>
            {statusLabel}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {stats.completed}/{total} 完成 · {progressPct}%
        </p>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            currentJob.job_status === "failed" ? "bg-red-500"
            : currentJob.job_status === "cancelled" ? "bg-amber-500"
            : currentJob.job_status === "completed" ? "bg-green-500"
            : "bg-blue-500"
          }`}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-5 gap-2 text-center">
        <div className="rounded-lg bg-green-50 p-2">
          <p className="text-xl font-bold text-green-600">{stats.completed}</p>
          <p className="text-[10px] text-green-700">完成</p>
        </div>
        <div className="rounded-lg bg-blue-50 p-2">
          <p className="text-xl font-bold text-blue-600">
            {stats.in_progress}
          </p>
          <p className="text-[10px] text-blue-700">进行</p>
        </div>
        <div className="rounded-lg bg-slate-50 p-2">
          <p className="text-xl font-bold text-slate-600">{stats.pending}</p>
          <p className="text-[10px] text-slate-700">等待</p>
        </div>
        <div className="rounded-lg bg-orange-50 p-2">
          <p className="text-xl font-bold text-orange-600">{stats.skipped}</p>
          <p className="text-[10px] text-orange-700">跳过</p>
        </div>
        <div className="rounded-lg bg-red-50 p-2">
          <p className="text-xl font-bold text-red-600">{stats.failed}</p>
          <p className="text-[10px] text-red-700">失败</p>
        </div>
      </div>

      {/* Compact bug list */}
      <div className="space-y-1">
        {currentJob.bugs.map((bug) => (
          <div
            key={bug.bug_id}
            data-testid={`bug-row-${bug.bug_id}`}
            className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50"
          >
            <span className="text-base">
              {bug.status === "completed" && "✅"}
              {bug.status === "in_progress" && "🔄"}
              {bug.status === "pending" && "⏳"}
              {bug.status === "failed" && "❌"}
              {bug.status === "skipped" && "⏭️"}
            </span>
            <span className="font-mono text-xs font-medium text-slate-700">
              {bug.bug_id}
            </span>
            <span className="flex-1 truncate text-xs text-slate-400">
              {bug.url}
            </span>
            {bug.status === "in_progress" && (
              <span className="text-[10px] text-blue-500">修复中...</span>
            )}
            {bug.status === "failed" && (
              <span className="truncate text-[10px] text-red-500 max-w-[120px]">
                {bug.error || "失败"}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
