"use client";

import { Button } from "@/components/ui/button";
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
                    {job.status === "completed" && "\u2705"}
                    {(job.status === "running" || job.status === "started") && "\uD83D\uDD04"}
                    {job.status === "failed" && "\u274C"}
                    {job.status === "cancelled" && "\u26D4"}
                  </span>
                  <div className="flex-1">
                    <p className="font-mono text-xs text-muted-foreground">
                      {job.job_id}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString()} &middot;{" "}
                      {job.components_total} components
                      {job.status === "cancelled" && " \u00B7 \u5DF2\u53D6\u6D88"}
                    </p>
                  </div>
                  <div className="text-right text-xs">
                    <span className="text-green-400">{job.components_completed} \u2713</span>
                    {job.components_failed > 0 && (
                      <span className="ml-2 text-red-400">
                        {job.components_failed} \u2717
                      </span>
                    )}
                  </div>
                  <span className="text-muted-foreground">
                    {expandedJobId === job.job_id ? "\u25BC" : "\u25B6"}
                  </span>
                </div>
                {expandedJobId === job.job_id && expandedJobDetails && (
                  <div className="ml-4 mt-2 space-y-1 border-l-2 border-border pl-4">
                    <div className="text-xs text-muted-foreground">
                      <span className="font-medium text-foreground">Output:</span>{" "}
                      <span className="font-mono">{expandedJobDetails.output_dir}</span>
                    </div>
                    {expandedJobDetails.design_file && (
                      <div className="text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">Design file:</span>{" "}
                        <span className="font-mono">
                          {expandedJobDetails.design_file.split("/").pop()}
                        </span>
                      </div>
                    )}
                    {expandedJobDetails.error && (
                      <div className="text-xs text-red-400">
                        Error: {expandedJobDetails.error}
                      </div>
                    )}
                    {expandedJobDetails.completed_at && (
                      <div className="text-xs text-muted-foreground">
                        Completed: {new Date(expandedJobDetails.completed_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex h-[100px] items-center justify-center text-muted-foreground">
            <p>{loadingHistory ? "加载中..." : "暂无历史任务"}</p>
          </div>
        )}
      </div>
    </div>
  );
}
