"use client";

import { Button } from "@/components/ui/button";
import { RefreshCw, ChevronDown, ChevronRight, CheckCircle2, Loader2, XCircle, Ban, Clock, FileText, FolderOutput } from "lucide-react";
import type { DesignJob } from "../types";
import type { DesignJobHistoryItem } from "../hooks/useDesignJobHistory";

interface DesignHistoryCardProps {
  historyJobs: DesignJobHistoryItem[];
  loadingHistory: boolean;
  expandedJobId: string | null;
  expandedJobDetails: DesignJob | null;
  onRefresh: () => void;
  onToggleDetails: (jobId: string) => void;
}

/** Format a relative time string in Chinese */
function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  if (diffMs < 0) return formatDateTime(dateStr);

  const minutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(diffMs / 3600000);
  const days = Math.floor(diffMs / 86400000);

  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  if (hours < 24) return `${hours} 小时前`;
  if (days < 7) return `${days} 天前`;
  return formatDateTime(dateStr);
}

/** Format as readable date-time */
function formatDateTime(dateStr: string): string {
  const date = new Date(dateStr);
  const m = date.getMonth() + 1;
  const d = date.getDate();
  const h = date.getHours().toString().padStart(2, "0");
  const min = date.getMinutes().toString().padStart(2, "0");
  return `${m}月${d}日 ${h}:${min}`;
}

/** Truncate job ID for display */
function shortJobId(jobId: string): string {
  // spec_13eb6f76c482 → 13eb6f76
  const parts = jobId.replace(/^spec_/, "");
  return parts.slice(0, 8);
}

/** Status config for icons and colors */
function getStatusConfig(status: string) {
  switch (status) {
    case "completed":
      return {
        icon: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
        label: "已完成",
        badgeBg: "bg-emerald-500/10",
        badgeText: "text-emerald-600 dark:text-emerald-400",
      };
    case "running":
    case "started":
      return {
        icon: <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />,
        label: "运行中",
        badgeBg: "bg-blue-500/10",
        badgeText: "text-blue-600 dark:text-blue-400",
      };
    case "failed":
      return {
        icon: <XCircle className="h-4 w-4 text-red-500" />,
        label: "失败",
        badgeBg: "bg-red-500/10",
        badgeText: "text-red-600 dark:text-red-400",
      };
    case "cancelled":
      return {
        icon: <Ban className="h-4 w-4 text-amber-500" />,
        label: "已取消",
        badgeBg: "bg-amber-500/10",
        badgeText: "text-amber-600 dark:text-amber-400",
      };
    default:
      return {
        icon: <Clock className="h-4 w-4 text-muted-foreground" />,
        label: status,
        badgeBg: "bg-muted",
        badgeText: "text-muted-foreground",
      };
  }
}

export function DesignHistoryCard({
  historyJobs,
  loadingHistory,
  expandedJobId,
  expandedJobDetails,
  onRefresh,
  onToggleDetails,
}: DesignHistoryCardProps) {
  return (
    <div>
      <div className="flex items-center justify-between pb-3">
        <h3 className="text-sm font-semibold text-foreground">历史任务</h3>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={onRefresh}
          disabled={loadingHistory}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loadingHistory ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {historyJobs.length > 0 ? (
        <div className="space-y-2">
          {historyJobs.map((job) => {
            const sc = getStatusConfig(job.status);
            const isExpanded = expandedJobId === job.job_id;

            return (
              <div key={job.job_id} className="rounded-lg border border-border overflow-hidden">
                {/* Job row */}
                <div
                  className="flex cursor-pointer items-center gap-2.5 px-3 py-2.5 hover:bg-muted/50 transition-colors"
                  onClick={() => onToggleDetails(job.job_id)}
                >
                  {sc.icon}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ${sc.badgeBg} ${sc.badgeText}`}>
                        {sc.label}
                      </span>
                      <span className="text-xs text-muted-foreground truncate">
                        #{shortJobId(job.job_id)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[11px] text-muted-foreground">
                        {formatRelativeTime(job.created_at)}
                      </span>
                      <span className="text-[11px] text-muted-foreground">·</span>
                      <span className="text-[11px] text-muted-foreground">
                        {job.components_total} 个组件
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {job.components_completed > 0 && (
                      <span className="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                        {job.components_completed}✓
                      </span>
                    )}
                    {job.components_failed > 0 && (
                      <span className="text-[11px] text-red-500 font-medium">
                        {job.components_failed}✗
                      </span>
                    )}
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                  </div>
                </div>

                {/* Expanded details */}
                {isExpanded && expandedJobDetails && (
                  <div className="border-t border-border bg-muted/30 px-3 py-2.5 space-y-2">
                    <div className="flex items-start gap-2 text-[11px]">
                      <FolderOutput className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <span className="text-muted-foreground">输出目录</span>
                        <p className="font-mono text-foreground truncate">
                          {expandedJobDetails.output_dir}
                        </p>
                      </div>
                    </div>
                    {expandedJobDetails.design_file && (
                      <div className="flex items-start gap-2 text-[11px]">
                        <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <span className="text-muted-foreground">设计文件</span>
                          <p className="font-mono text-foreground truncate">
                            {expandedJobDetails.design_file.split("/").pop()}
                          </p>
                        </div>
                      </div>
                    )}
                    {expandedJobDetails.error && (
                      <div className="rounded-md bg-red-500/10 px-2.5 py-1.5 text-[11px] text-red-600 dark:text-red-400">
                        {expandedJobDetails.error}
                      </div>
                    )}
                    {expandedJobDetails.completed_at && (
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground pt-1 border-t border-border">
                        <Clock className="h-3 w-3" />
                        <span>完成于 {formatDateTime(expandedJobDetails.completed_at)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex h-[80px] items-center justify-center text-sm text-muted-foreground">
          {loadingHistory ? (
            <span className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中...
            </span>
          ) : (
            "暂无历史任务"
          )}
        </div>
      )}
    </div>
  );
}
