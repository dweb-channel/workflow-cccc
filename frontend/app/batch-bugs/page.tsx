"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
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
import { FileEdit, Play, BarChart3, Eye, X } from "lucide-react";

import type { DryRunResponse } from "@/lib/api";
import { submitDryRun } from "@/lib/api";
import type { ValidationLevel, FailurePolicy } from "./types";
import { useBatchJob } from "./hooks/useBatchJob";
import { useJobHistory } from "./hooks/useJobHistory";
import { BugInput } from "./components/BugInput";
import { ConfigOptions } from "./components/ConfigOptions";
import { DirectoryPicker } from "./components/DirectoryPicker";
import { OverviewTab } from "./components/OverviewTab";
import { HistoryCard } from "./components/HistoryCard";
import { ActivityFeed } from "./components/ActivityFeed";
import { PipelineBar } from "./components/PipelineBar";
import { MetricsTab } from "./components/MetricsTab";

/* ================================================================
   BatchBugsPage — Two-tab layout:
   Tab 1 (配置):  Left=Input form, Right=History
   Tab 2 (执行):  Pipeline + ActivityFeed(main) + Right panel
   Both tabs stay mounted (forceMount) to preserve SSE + scroll.
   ================================================================ */

const LS_KEY_CWD = "batch-bugs-target-cwd";

export default function BatchBugsPage() {
  // Form inputs
  const [jiraUrls, setJiraUrls] = useState("");
  const [targetCwd, setTargetCwd] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(LS_KEY_CWD) ?? "";
    }
    return "";
  });
  const [validationLevel, setValidationLevel] =
    useState<ValidationLevel>("standard");
  const [failurePolicy, setFailurePolicy] =
    useState<FailurePolicy>("skip");

  const [activeBugIndex, setActiveBugIndex] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<string>("config");
  const [dryRunResult, setDryRunResult] = useState<DryRunResponse | null>(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);

  // Persist targetCwd to localStorage
  useEffect(() => {
    if (targetCwd) {
      localStorage.setItem(LS_KEY_CWD, targetCwd);
    } else {
      localStorage.removeItem(LS_KEY_CWD);
    }
  }, [targetCwd]);

  // Hooks
  const { currentJob, submitting, stats, submit, cancel, retryBug, sseConnected, aiThinkingEvents, aiThinkingStats, dbSyncWarnings } = useBatchJob();
  const history = useJobHistory();

  // Auto-switch to execution tab when job starts running
  const jobActive = currentJob && !["completed", "failed", "cancelled"].includes(currentJob.job_status);
  useEffect(() => {
    if (jobActive) setActiveTab("execution");
  }, [jobActive]);

  // Execution tab is disabled when there's no job at all
  const hasJob = !!currentJob;

  // Dynamic execution tab label with mini progress
  const executionTabSuffix = useMemo(() => {
    if (!currentJob) return "";
    const total = currentJob.bugs.length;
    const done = stats.completed;
    switch (currentJob.job_status) {
      case "running":   return ` (${done}/${total} 修复中...)`;
      case "completed": return ` (${done}/${total} ✅)`;
      case "failed":    return ` (${done}/${total} ❌)`;
      case "cancelled": return ` (${done}/${total} ⛔)`;
      default:          return ` (${done}/${total} 修复中...)`;
    }
  }, [currentJob?.job_status, currentJob?.bugs.length, stats.completed]);

  const parseJiraUrls = useCallback(() => {
    return jiraUrls
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }, [jiraUrls]);

  const handleSubmit = useCallback(async () => {
    const urls = parseJiraUrls();
    if (urls.length === 0) return;

    const result = await submit({
      jira_urls: urls,
      cwd: targetCwd.trim() || undefined,
      config: {
        validation_level: validationLevel,
        failure_policy: failurePolicy,
      },
    });

    if (result) {
      setActiveTab("execution");
      history.loadHistory();
    }
  }, [
    parseJiraUrls,
    targetCwd,
    validationLevel,
    failurePolicy,
    submit,
    history,
  ]);

  const handleNewJob = () => {
    setActiveTab("config");
    setActiveBugIndex(null);
    setDryRunResult(null);
  };

  const handleDryRun = useCallback(async () => {
    const urls = parseJiraUrls();
    if (urls.length === 0) return;
    setDryRunLoading(true);
    try {
      const result = await submitDryRun({
        jira_urls: urls,
        cwd: targetCwd.trim() || undefined,
        config: {
          validation_level: validationLevel,
          failure_policy: failurePolicy,
        },
      });
      setDryRunResult(result);
    } catch {
      setDryRunResult(null);
    } finally {
      setDryRunLoading(false);
    }
  }, [parseJiraUrls, targetCwd, validationLevel, failurePolicy]);

  const handleConfirmExecute = useCallback(async () => {
    setDryRunResult(null);
    await handleSubmit();
  }, [handleSubmit]);

  const isFinished = currentJob && ["completed", "failed", "cancelled"].includes(currentJob.job_status);

  return (
    <div className="flex h-full flex-col overflow-hidden p-6">
        {/* ---- Header ---- */}
        <div className="mb-4 shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold text-slate-900">批量 Bug 修复</h1>
            {currentJob && (
              <>
                <span className="rounded-full bg-[#dbeafe] px-2.5 py-0.5 font-mono text-xs text-[#2563eb]">
                  {currentJob.job_id}
                </span>
                <JobStatusBadge status={currentJob.job_status} />
              </>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-500">
            粘贴 Jira Bug 链接，一键启动自动修复流程
          </p>
        </div>

        {/* ---- Two Big Tabs ---- */}
        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex flex-1 flex-col overflow-hidden"
        >
          <TabsList className="mb-4 w-fit shrink-0 bg-slate-100 p-1 rounded-lg" data-testid="main-tabs">
            <TabsTrigger
              value="config"
              className="rounded-md px-4 py-2 text-sm font-medium data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
              data-testid="tab-config"
            >
              <span className="inline-flex items-center gap-1.5">
                <FileEdit className="h-3.5 w-3.5" /> 配置
              </span>
            </TabsTrigger>
            <TabsTrigger
              value="execution"
              disabled={!hasJob}
              className="rounded-md px-4 py-2 text-sm font-medium data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="tab-execution"
            >
              <span className="inline-flex items-center gap-1.5">
                <Play className="h-3.5 w-3.5" /> 执行{executionTabSuffix}
              </span>
            </TabsTrigger>
            <TabsTrigger
              value="metrics"
              className="rounded-md px-4 py-2 text-sm font-medium data-[state=active]:bg-white data-[state=active]:text-slate-900 data-[state=active]:shadow-sm"
              data-testid="tab-metrics"
            >
              <span className="inline-flex items-center gap-1.5">
                <BarChart3 className="h-3.5 w-3.5" /> 度量
              </span>
            </TabsTrigger>
          </TabsList>

          {/* Config Tab — always mounted */}
          <TabsContent
            value="config"
            forceMount
            className="flex-1 overflow-hidden data-[state=inactive]:hidden"
          >
            <div className="flex flex-1 h-full gap-6 overflow-hidden">
              {/* Left: Input form */}
              <div className="flex flex-1 flex-col gap-4 overflow-y-auto pr-2">
                <Card>
                  <CardContent className="pt-4 pb-3 space-y-2">
                    <Label className="text-xs">目标代码库路径</Label>
                    <DirectoryPicker
                      value={targetCwd}
                      onChange={setTargetCwd}
                    />
                    <p className="text-xs text-slate-400">
                      Claude CLI 的工作目录，指向需要修复的项目代码库
                    </p>
                  </CardContent>
                </Card>

                <BugInput
                  jiraUrls={jiraUrls}
                  onJiraUrlsChange={setJiraUrls}
                  parseJiraUrls={parseJiraUrls}
                />

                <ConfigOptions
                  validationLevel={validationLevel}
                  failurePolicy={failurePolicy}
                  onValidationLevelChange={setValidationLevel}
                  onFailurePolicyChange={setFailurePolicy}
                />

                <div className="flex gap-3">
                  <Button
                    variant="outline"
                    onClick={handleDryRun}
                    disabled={dryRunLoading || submitting || parseJiraUrls().length === 0}
                  >
                    <Eye className="mr-1.5 h-3.5 w-3.5" />
                    {dryRunLoading ? "预览中..." : "预览"}
                  </Button>
                  <Button
                    className="bg-blue-600 hover:bg-blue-700 text-white"
                    onClick={handleSubmit}
                    disabled={submitting || parseJiraUrls().length === 0}
                  >
                    <Play className="mr-1.5 h-3.5 w-3.5" />
                    {submitting ? "提交中..." : "开始修复"}
                  </Button>
                </div>

                {/* Dry-run preview panel */}
                {dryRunResult && (
                  <DryRunPreviewPanel
                    result={dryRunResult}
                    onConfirm={handleConfirmExecute}
                    onDismiss={() => setDryRunResult(null)}
                    submitting={submitting}
                  />
                )}
              </div>

              {/* Right: History */}
              <div className="w-[360px] shrink-0 overflow-y-auto">
                <Card>
                  <CardContent className="p-4">
                    <HistoryCard
                      historyJobs={history.historyJobs}
                      historyTotal={history.historyTotal}
                      historyPage={history.historyPage}
                      loadingHistory={history.loadingHistory}
                      expandedJobId={history.expandedJobId}
                      expandedJobDetails={history.expandedJobDetails}
                      onRefresh={history.loadHistory}
                      onPageChange={history.setHistoryPage}
                      onToggleDetails={history.toggleJobDetails}
                      onDelete={history.deleteJob}
                    />
                  </CardContent>
                </Card>
              </div>
            </div>
          </TabsContent>

          {/* Execution Tab — always mounted to preserve SSE + scroll */}
          <TabsContent
            value="execution"
            forceMount
            className="flex-1 overflow-hidden data-[state=inactive]:hidden"
          >
            <div className="flex flex-1 h-full flex-col overflow-hidden gap-4">
              <PipelineBar
                currentJob={currentJob}
                activeBugIndex={activeBugIndex}
                onBugSelect={setActiveBugIndex}
              />

              <div className="flex flex-1 gap-4 overflow-hidden">
                {/* Left: Activity Feed (main view) */}
                <div className="flex-1 overflow-hidden">
                  <ActivityFeed
                    currentJob={currentJob}
                    allAiEvents={aiThinkingEvents}
                    aiStats={aiThinkingStats}
                    activeBugIndex={activeBugIndex}
                    onBugSelect={setActiveBugIndex}
                    onRetryBug={retryBug}
                    sseConnected={sseConnected}
                    dbSyncWarnings={dbSyncWarnings}
                  />
                </div>

                {/* Right: Overview / History panel (320px) */}
                <div className="w-[360px] shrink-0 overflow-hidden">
                  <Card className="h-full flex flex-col">
                    <CardContent className="p-0 flex-1 flex flex-col overflow-hidden">
                      <Tabs defaultValue="overview" className="flex-1 flex flex-col overflow-hidden">
                        <TabsList className="w-full justify-start rounded-none border-b bg-transparent px-2 pt-1 shrink-0">
                          <TabsTrigger
                            value="overview"
                            className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none text-[13px]"
                          >
                            总览
                          </TabsTrigger>
                          <TabsTrigger
                            value="history"
                            className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none text-[13px]"
                          >
                            历史记录
                          </TabsTrigger>
                        </TabsList>

                        <div className="flex-1 overflow-y-auto p-4">
                          <TabsContent value="overview" className="mt-0">
                            <OverviewTab
                              currentJob={currentJob}
                              stats={stats}
                            />
                            {/* Action buttons */}
                            <div className="mt-4 flex gap-2">
                              {!isFinished && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="flex-1 text-red-600 border-red-200 hover:bg-red-50"
                                  onClick={() => setShowCancelConfirm(true)}
                                >
                                  取消任务
                                </Button>
                              )}
                              <Button
                                variant={isFinished ? "default" : "outline"}
                                size="sm"
                                className="flex-1"
                                onClick={handleNewJob}
                              >
                                新建任务
                              </Button>
                            </div>
                          </TabsContent>

                          <TabsContent value="history" className="mt-0">
                            <HistoryCard
                              historyJobs={history.historyJobs}
                              historyTotal={history.historyTotal}
                              historyPage={history.historyPage}
                              loadingHistory={history.loadingHistory}
                              expandedJobId={history.expandedJobId}
                              expandedJobDetails={history.expandedJobDetails}
                              onRefresh={history.loadHistory}
                              onPageChange={history.setHistoryPage}
                              onToggleDetails={history.toggleJobDetails}
                              onDelete={history.deleteJob}
                            />
                          </TabsContent>
                        </div>
                      </Tabs>
                    </CardContent>
                  </Card>
                </div>
              </div>
            </div>
          </TabsContent>

          {/* Metrics Tab — loaded on demand, no forceMount needed */}
          <TabsContent
            value="metrics"
            className="flex-1 overflow-hidden"
          >
            <MetricsTab />
          </TabsContent>
        </Tabs>

        {/* Cancel task confirmation dialog */}
        <AlertDialog open={showCancelConfirm} onOpenChange={setShowCancelConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认取消？</AlertDialogTitle>
              <AlertDialogDescription>
                当前任务进度 {stats.completed}/{currentJob?.bugs.length ?? 0} 完成。取消后正在执行的 Bug 修复将被中断，已完成的不受影响。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>继续执行</AlertDialogCancel>
              <AlertDialogAction
                className="bg-red-600 hover:bg-red-700 text-white"
                onClick={() => {
                  cancel();
                  setShowCancelConfirm(false);
                }}
              >
                确认取消
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
    </div>
  );
}

/* ================================================================
   Dry-Run Preview Panel
   ================================================================ */

function DryRunPreviewPanel({
  result,
  onConfirm,
  onDismiss,
  submitting,
}: {
  result: DryRunResponse;
  onConfirm: () => void;
  onDismiss: () => void;
  submitting: boolean;
}) {
  return (
    <Card className="border-blue-200 bg-blue-50/50">
      <CardContent className="pt-4 pb-3 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-blue-900">
            Dry Run 预览
          </h3>
          <button
            onClick={onDismiss}
            className="text-slate-400 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex gap-4 text-xs text-slate-600">
          <span>Bug 数量: <strong>{result.total_bugs}</strong></span>
          <span>工作目录: <code className="bg-white px-1.5 py-0.5 rounded text-[11px]">{result.cwd}</code></span>
          <span>验证级别: <strong>{result.config.validation_level}</strong></span>
          <span>失败策略: <strong>{result.config.failure_policy}</strong></span>
        </div>

        {/* Bug list */}
        <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
          {result.bugs.map((bug, i) => (
            <div
              key={i}
              className="flex items-center gap-2 rounded bg-white px-3 py-1.5 text-xs"
            >
              <span className="shrink-0 rounded-full bg-blue-100 px-1.5 py-0.5 font-mono text-[10px] text-blue-700">
                #{i + 1}
              </span>
              <span className="font-medium text-slate-800">{bug.jira_key}</span>
              <span className="truncate text-slate-400">{bug.url}</span>
            </div>
          ))}
        </div>

        {/* Expected steps */}
        <div className="text-xs text-slate-500">
          <span className="font-medium">每个 Bug 的执行步骤: </span>
          {result.expected_steps_per_bug.join(" → ")}
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          <Button
            size="sm"
            onClick={onConfirm}
            disabled={submitting}
          >
            {submitting ? "执行中..." : "确认执行"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onDismiss}
          >
            取消
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}


/* ================================================================
   Job Status Badge
   ================================================================ */

function JobStatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; dotColor: string; text: string; label: string }> = {
    running:   { bg: "#dcfce7", dotColor: "#22c55e", text: "#16a34a", label: "修复中" },
    completed: { bg: "#dcfce7", dotColor: "#22c55e", text: "#16a34a", label: "已完成" },
    failed:    { bg: "#fef2f2", dotColor: "#ef4444", text: "#dc2626", label: "失败" },
    cancelled: { bg: "#fef3c7", dotColor: "#f59e0b", text: "#d97706", label: "已取消" },
  };
  const c = config[status] ?? config.running;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5"
      style={{ backgroundColor: c.bg }}
    >
      <span
        className={`h-2 w-2 rounded-full ${status === "running" ? "animate-pulse" : ""}`}
        style={{ backgroundColor: c.dotColor }}
      />
      <span className="text-xs font-medium" style={{ color: c.text }}>
        {c.label}
      </span>
    </span>
  );
}
