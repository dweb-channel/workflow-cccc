"use client";

import type { DesignJob, DesignJobStats } from "../types";

/* ================================================================
   DesignOverview — Right panel showing job status + stats.
   ================================================================ */

interface DesignOverviewProps {
  currentJob: DesignJob | null;
  stats: DesignJobStats;
}

export function DesignOverview({ currentJob, stats }: DesignOverviewProps) {
  if (!currentJob) {
    return (
      <div className="flex h-[300px] items-center justify-center text-slate-400">
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
        <p className="mt-1 text-xs text-slate-400">
          {stats.completed}/{stats.total} 组件完成 · {progressPct}%
        </p>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-slate-700 overflow-hidden">
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
        <div className="rounded-lg bg-slate-700/50 p-2">
          <p className="text-xl font-bold text-slate-300">{stats.pending}</p>
          <p className="text-[10px] text-slate-400">等待</p>
        </div>
        <div className="rounded-lg bg-red-500/10 p-2">
          <p className="text-xl font-bold text-red-400">{stats.failed}</p>
          <p className="text-[10px] text-red-500">失败</p>
        </div>
      </div>

      {/* Job details */}
      <div className="space-y-2 text-xs">
        <div className="flex items-center gap-2">
          <span className="text-slate-500">任务 ID:</span>
          <code className="bg-slate-700 px-1.5 py-0.5 rounded text-[11px] text-violet-300">
            {currentJob.job_id}
          </code>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 text-slate-500">设计文件:</span>
          <code className="bg-slate-700 px-1.5 py-0.5 rounded text-[11px] text-slate-300 break-all">
            {currentJob.design_file}
          </code>
        </div>
        <div className="flex items-start gap-2">
          <span className="shrink-0 text-slate-500">输出目录:</span>
          <code className="bg-slate-700 px-1.5 py-0.5 rounded text-[11px] text-slate-300 break-all">
            {currentJob.output_dir}
          </code>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-500">创建时间:</span>
          <span className="text-slate-300">
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
