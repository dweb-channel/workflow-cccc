"use client";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { BatchJob, BatchJobStats } from "../types";

interface OverviewTabProps {
  currentJob: BatchJob | null;
  stats: BatchJobStats;
  onCancel: () => void;
}

export function OverviewTab({ currentJob, stats, onCancel }: OverviewTabProps) {
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

  const dotColor =
    currentJob.job_status === "completed"
      ? "bg-green-500"
      : currentJob.job_status === "failed" || currentJob.job_status === "cancelled"
        ? "bg-red-500"
        : "bg-blue-500 animate-pulse";

  return (
    <div className="space-y-4" data-testid="tab-overview">
      {/* Current task status */}
      <div className="rounded-lg bg-green-50 p-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotColor}`} />
          <span className="text-sm font-medium text-green-800">
            {statusLabel}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">
          {stats.completed}/{total} 完成
        </p>
      </div>

      {/* Header with progress */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge className="border-slate-200 bg-slate-50 text-slate-700">
            {stats.completed}/{total} 完成
          </Badge>
          <span className="text-xs text-slate-400">{progressPct}%</span>
        </div>
        {currentJob.job_status !== "completed" &&
          currentJob.job_status !== "failed" &&
          currentJob.job_status !== "cancelled" && (
            <Button
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs text-red-600 hover:bg-red-50 hover:text-red-700"
              onClick={onCancel}
            >
              取消
            </Button>
          )}
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full rounded-full bg-green-500 transition-all duration-500"
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
