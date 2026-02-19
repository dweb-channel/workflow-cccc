"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { BatchJob, BatchJobHistoryItem } from "../types";

interface HistoryCardProps {
  historyJobs: BatchJobHistoryItem[];
  historyTotal: number;
  historyPage: number;
  loadingHistory: boolean;
  expandedJobId: string | null;
  expandedJobDetails: BatchJob | null;
  onRefresh: () => void;
  onPageChange: (page: number) => void;
  onToggleDetails: (jobId: string) => void;
  onDelete?: (jobId: string) => void;
}

export function HistoryCard({
  historyJobs,
  historyTotal,
  historyPage,
  loadingHistory,
  expandedJobId,
  expandedJobDetails,
  onRefresh,
  onPageChange,
  onToggleDetails,
  onDelete,
}: HistoryCardProps) {
  const [deleteJobId, setDeleteJobId] = useState<string | null>(null);

  return (
    <div>
      <div className="flex items-center justify-between pb-3">
        <h3 className="text-sm font-semibold text-foreground">历史任务</h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRefresh}
          disabled={loadingHistory}
        >
          {loadingHistory ? "加载中..." : "刷新"}
        </Button>
      </div>
      <div>
        {historyJobs.length > 0 ? (
          <div className="space-y-2">
            {historyJobs.map((job) => (
              <div key={job.job_id}>
                <div
                  className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3 hover:bg-muted"
                  onClick={() => onToggleDetails(job.job_id)}
                >
                  <span className="text-lg">
                    {job.status === "completed" && "✅"}
                    {job.status === "running" && "🔄"}
                    {job.status === "failed" && "❌"}
                    {job.status === "cancelled" && "⛔"}
                    {job.status === "pending" && "⏳"}
                  </span>
                  <div className="flex-1">
                    <p className="font-mono text-xs text-muted-foreground">
                      {job.job_id}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString()} ·{" "}
                      {job.total_bugs} bugs
                      {job.status === "cancelled" && " · 已取消"}
                    </p>
                  </div>
                  <div className="text-right text-xs">
                    <span className="text-green-400">{job.completed} ✓</span>
                    {job.failed > 0 && (
                      <span className="ml-2 text-red-400">
                        {job.failed} ✗
                      </span>
                    )}
                  </div>
                  {onDelete && (
                    <button
                      className="rounded p-1 text-muted-foreground hover:bg-red-500/20 hover:text-red-400"
                      title="删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteJobId(job.job_id);
                      }}
                    >
                      ✕
                    </button>
                  )}
                  <span className="text-muted-foreground">
                    {expandedJobId === job.job_id ? "▼" : "▶"}
                  </span>
                </div>
                {expandedJobId === job.job_id && expandedJobDetails && (
                  <div className="ml-4 mt-2 space-y-1 border-l-2 border-border pl-4">
                    {expandedJobDetails.bugs.map((bug) => (
                      <div
                        key={bug.bug_id}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span>
                          {bug.status === "completed" && "✅"}
                          {bug.status === "in_progress" && "🔄"}
                          {bug.status === "pending" && "⏳"}
                          {bug.status === "failed" && "❌"}
                          {bug.status === "skipped" && "⏭️"}
                        </span>
                        <span className="truncate text-muted-foreground">
                          {bug.url}
                        </span>
                        {bug.error && (
                          <span className="text-red-400">({bug.error})</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {historyTotal > historyJobs.length && (
              <div className="flex justify-center gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={historyPage === 1}
                  onClick={() => onPageChange(historyPage - 1)}
                >
                  上一页
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onPageChange(historyPage + 1)}
                >
                  下一页
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-[100px] items-center justify-center text-muted-foreground">
            <p>{loadingHistory ? "加载中..." : "暂无历史任务"}</p>
          </div>
        )}
      </div>

      {/* Delete confirmation dialog */}
      <AlertDialog open={!!deleteJobId} onOpenChange={(open) => !open && setDeleteJobId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认删除？</AlertDialogTitle>
            <AlertDialogDescription>
              确定要删除任务 <span className="font-mono">{deleteJobId}</span> 吗？此操作无法撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90 text-destructive-foreground"
              onClick={() => {
                if (deleteJobId && onDelete) {
                  onDelete(deleteJobId);
                }
                setDeleteJobId(null);
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
