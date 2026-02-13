"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, TrendingUp, Clock, CheckCircle, Bug, BarChart3 } from "lucide-react";
import { getGlobalMetrics } from "@/lib/api";
import type { GlobalMetrics, StepMetrics, JobMetricsSummary } from "../types";

/* ================================================================
   MetricsTab — Global metrics dashboard for batch bug fix jobs
   Shows: summary cards, step performance table, recent jobs list
   ================================================================ */

export function MetricsTab() {
  const [metrics, setMetrics] = useState<GlobalMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadMetrics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getGlobalMetrics();
      setMetrics(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load metrics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  if (loading && !metrics) {
    return (
      <div className="flex h-[400px] items-center justify-center text-slate-400" data-testid="metrics-loading">
        <div className="text-center">
          <RefreshCw className="mx-auto h-6 w-6 animate-spin text-slate-300" />
          <p className="mt-2 text-sm">加载度量数据...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-[400px] items-center justify-center" data-testid="metrics-error">
        <div className="text-center">
          <p className="text-sm text-red-500">{error}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={loadMetrics}>
            重试
          </Button>
        </div>
      </div>
    );
  }

  if (!metrics) return null;

  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto pr-2" data-testid="metrics-tab">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <h2 className="text-lg font-semibold text-slate-800">修复效果度量</h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={loadMetrics}
          disabled={loading}
          className="text-slate-500 hover:text-slate-700"
        >
          <RefreshCw className={`h-4 w-4 mr-1.5 ${loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4 shrink-0">
        <SummaryCard
          icon={<BarChart3 className="h-4 w-4 text-blue-500" />}
          label="总任务数"
          value={metrics.total_jobs}
          bg="bg-blue-50"
        />
        <SummaryCard
          icon={<Bug className="h-4 w-4 text-purple-500" />}
          label="总 Bug 数"
          value={metrics.total_bugs}
          bg="bg-purple-50"
        />
        <SummaryCard
          icon={<CheckCircle className="h-4 w-4 text-green-500" />}
          label="整体成功率"
          value={`${metrics.overall_success_rate.toFixed(1)}%`}
          bg="bg-green-50"
        />
        <SummaryCard
          icon={<Clock className="h-4 w-4 text-amber-500" />}
          label="平均耗时/Bug"
          value={formatDuration(metrics.avg_bug_duration_ms)}
          bg="bg-amber-50"
        />
      </div>

      {/* Step Performance Table */}
      {metrics.step_metrics.length > 0 && (
        <Card className="shrink-0">
          <CardContent className="p-4">
            <h3 className="mb-3 text-sm font-medium text-slate-700 flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4 text-slate-400" />
              步骤性能
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="step-metrics-table">
                <thead>
                  <tr className="border-b text-left text-xs text-slate-500">
                    <th className="pb-2 font-medium">步骤</th>
                    <th className="pb-2 font-medium text-right">平均耗时</th>
                    <th className="pb-2 font-medium text-right">成功率</th>
                    <th className="pb-2 font-medium text-right">执行次数</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.step_metrics.map((step) => (
                    <StepRow key={step.step_name} step={step} />
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Jobs */}
      {metrics.recent_jobs.length > 0 && (
        <Card className="shrink-0">
          <CardContent className="p-4">
            <h3 className="mb-3 text-sm font-medium text-slate-700">
              最近任务
            </h3>
            <div className="space-y-2" data-testid="recent-jobs-list">
              {metrics.recent_jobs.map((job) => (
                <RecentJobRow key={job.job_id} job={job} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {metrics.total_jobs === 0 && (
        <div className="flex flex-1 items-center justify-center text-slate-400">
          <div className="text-center">
            <BarChart3 className="mx-auto h-10 w-10 text-slate-200" />
            <p className="mt-2 text-sm">暂无度量数据</p>
            <p className="mt-1 text-xs">完成第一个修复任务后，这里会显示统计信息</p>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---- Sub-components ---- */

function SummaryCard({
  icon,
  label,
  value,
  bg,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  bg: string;
}) {
  return (
    <Card data-testid="metrics-summary-card">
      <CardContent className={`p-4 ${bg} rounded-lg`}>
        <div className="flex items-center gap-2 mb-1">
          {icon}
          <span className="text-xs text-slate-500">{label}</span>
        </div>
        <p className="text-2xl font-bold text-slate-800">{value}</p>
      </CardContent>
    </Card>
  );
}

function StepRow({ step }: { step: StepMetrics }) {
  const successPct = step.success_rate.toFixed(0);
  const barColor =
    step.success_rate >= 0.8 ? "bg-green-500" :
    step.success_rate >= 0.5 ? "bg-amber-500" : "bg-red-500";

  return (
    <tr className="border-b last:border-0">
      <td className="py-2">
        <span className="text-slate-700">{step.label}</span>
      </td>
      <td className="py-2 text-right text-slate-600">
        {formatDuration(step.avg_duration_ms)}
      </td>
      <td className="py-2 text-right">
        <div className="inline-flex items-center gap-2">
          <div className="h-1.5 w-16 rounded-full bg-slate-100 overflow-hidden">
            <div
              className={`h-full rounded-full ${barColor}`}
              style={{ width: `${successPct}%` }}
            />
          </div>
          <span className="text-xs text-slate-600 w-10 text-right">{successPct}%</span>
        </div>
      </td>
      <td className="py-2 text-right text-slate-500">{step.total_executions}</td>
    </tr>
  );
}

function RecentJobRow({ job }: { job: JobMetricsSummary }) {
  const statusConfig: Record<string, { color: string; label: string }> = {
    completed: { color: "text-green-600", label: "完成" },
    failed: { color: "text-red-600", label: "失败" },
    cancelled: { color: "text-amber-600", label: "取消" },
    running: { color: "text-blue-600", label: "运行中" },
  };
  const sc = statusConfig[job.status] ?? { color: "text-slate-600", label: job.status };
  const successPct = job.success_rate.toFixed(0);

  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-slate-50 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-500 truncate">{job.job_id.slice(0, 12)}</span>
          <span className={`text-xs font-medium ${sc.color}`}>{sc.label}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-3 text-[11px] text-slate-400">
          <span>{job.completed}/{job.total_bugs} bugs</span>
          <span>成功率 {successPct}%</span>
          <span>{formatDuration(job.total_duration_ms)}</span>
        </div>
      </div>
      <span className="text-[11px] text-slate-400 shrink-0">
        {formatRelativeTime(job.created_at)}
      </span>
    </div>
  );
}

/* ---- Helpers ---- */

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const mins = Math.floor(ms / 60000);
  const secs = Math.round((ms % 60000) / 1000);
  return `${mins}m ${secs}s`;
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins}分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}小时前`;
  const days = Math.floor(hours / 24);
  return `${days}天前`;
}
