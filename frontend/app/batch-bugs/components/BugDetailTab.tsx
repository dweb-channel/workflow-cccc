"use client";

import { useState, useEffect } from "react";
import type { BatchJob } from "../types";
import { BugStepper } from "./BugStepper";

interface BugDetailTabProps {
  currentJob: BatchJob | null;
}

export function BugDetailTab({ currentJob }: BugDetailTabProps) {
  const [expandedBugs, setExpandedBugs] = useState<Set<string>>(new Set());

  // Auto-expand in_progress bugs
  useEffect(() => {
    if (!currentJob) return;
    const inProgressIds = currentJob.bugs
      .filter((b) => b.status === "in_progress")
      .map((b) => b.bug_id);

    if (inProgressIds.length > 0) {
      setExpandedBugs((prev) => {
        const next = new Set(prev);
        inProgressIds.forEach((id) => next.add(id));
        return next;
      });
    }
  }, [currentJob?.bugs.map((b) => `${b.bug_id}:${b.status}`).join(",")]);

  const toggleBug = (bugId: string) => {
    setExpandedBugs((prev) => {
      const next = new Set(prev);
      if (next.has(bugId)) {
        next.delete(bugId);
      } else {
        next.add(bugId);
      }
      return next;
    });
  };

  if (!currentJob) {
    return (
      <div className="flex h-[300px] items-center justify-center text-slate-400">
        <p>尚未开始任务</p>
      </div>
    );
  }

  return (
    <div className="space-y-2" data-testid="tab-detail">
      {currentJob.bugs.map((bug, idx) => {
        const isExpanded = expandedBugs.has(bug.bug_id);
        return (
          <div
            key={bug.bug_id}
            data-testid={`bug-detail-${idx}`}
            className="rounded-lg border border-slate-200 overflow-hidden"
          >
            {/* Accordion header */}
            <button
              onClick={() => toggleBug(bug.bug_id)}
              className="flex w-full items-center gap-3 p-3 text-left hover:bg-slate-50 transition-colors"
            >
              <span className="text-lg">
                {bug.status === "completed" && "✅"}
                {bug.status === "in_progress" && "🔄"}
                {bug.status === "pending" && "⏳"}
                {bug.status === "failed" && "❌"}
                {bug.status === "skipped" && "⏭️"}
              </span>
              <div className="flex-1 min-w-0">
                <p className="font-mono text-sm font-medium">{bug.bug_id}</p>
                <p className="truncate text-xs text-slate-500">{bug.url}</p>
              </div>
              <div className="flex items-center gap-2">
                {bug.status === "in_progress" && (
                  <span className="text-xs text-blue-500">修复中...</span>
                )}
                {bug.status === "failed" && (
                  <span className="text-xs text-red-500">
                    {bug.error || "失败"}
                  </span>
                )}
                {bug.status === "skipped" && (
                  <span className="text-xs text-orange-500">已跳过</span>
                )}
                {bug.retry_count !== undefined && bug.retry_count > 0 && (
                  <span className="rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-600">
                    重试 {bug.retry_count}
                  </span>
                )}
                <span className="text-slate-400 text-sm">
                  {isExpanded ? "▼" : "▶"}
                </span>
              </div>
            </button>

            {/* Accordion content */}
            {isExpanded && (
              <div className="border-t border-slate-100 bg-slate-50/50 px-4 py-3">
                <BugStepper
                  steps={bug.steps}
                  bugStatus={bug.status}
                  retryCount={bug.retry_count}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
