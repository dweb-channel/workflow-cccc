"use client";

import { useState, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/hooks/use-toast";
import {
  getCCCCGroups,
  submitBatchBugFix,
  getBatchJobStreamUrl,
  getBatchJobHistory,
  getBatchJobStatus,
  cancelBatchJob,
  type CCCCGroup,
  type CCCCPeer,
  type BatchJobHistoryItem,
} from "@/lib/api";
import { Sidebar } from "@/components/sidebar/Sidebar";

// ============ Types ============

interface BugStatus {
  bug_id: string;
  url: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped";
  error?: string;
}

interface BatchJob {
  job_id: string;
  bugs: BugStatus[];
  started_at: string;
  job_status: string;
}

type VerificationLevel = "quick" | "standard" | "full";
type FailureStrategy = "continue" | "stop";

// ============ Component ============

export default function BatchBugsPage() {
  const { toast } = useToast();

  // Group selection
  const [groups, setGroups] = useState<CCCCGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [loadingGroups, setLoadingGroups] = useState(false);

  // Peer selection
  const [fixerPeerId, setFixerPeerId] = useState<string | null>(null);
  const [verifierPeerId, setVerifierPeerId] = useState<string | null>(null);

  // Form inputs
  const [jiraUrls, setJiraUrls] = useState("");
  const [verificationLevel, setVerificationLevel] = useState<VerificationLevel>("standard");
  const [failureStrategy, setFailureStrategy] = useState<FailureStrategy>("continue");

  // Job status
  const [currentJob, setCurrentJob] = useState<BatchJob | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // History
  const [historyJobs, setHistoryJobs] = useState<BatchJobHistoryItem[]>([]);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [expandedJobDetails, setExpandedJobDetails] = useState<BatchJob | null>(null);

  // Load groups and history on mount
  useEffect(() => {
    loadGroups();
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load history when page changes
  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [historyPage]);

  // SSE stream for real-time job status updates
  useEffect(() => {
    if (!currentJob || currentJob.job_status === "completed" || currentJob.job_status === "failed") {
      return;
    }

    const streamUrl = getBatchJobStreamUrl(currentJob.job_id);
    const eventSource = new EventSource(streamUrl);

    // Handle initial job state
    eventSource.addEventListener("job_state", (e) => {
      const data = JSON.parse(e.data);
      setCurrentJob((prev) => prev ? {
        ...prev,
        job_status: data.status,
        bugs: prev.bugs.map((bug, idx) => ({
          ...bug,
          status: data.bugs?.[idx]?.status ?? bug.status,
          error: data.bugs?.[idx]?.error,
        })),
      } : prev);
    });

    // Handle bug started
    eventSource.addEventListener("bug_started", (e) => {
      const data = JSON.parse(e.data);
      setCurrentJob((prev) => prev ? {
        ...prev,
        bugs: prev.bugs.map((bug, idx) =>
          idx === data.bug_index ? { ...bug, status: "in_progress" as const } : bug
        ),
      } : prev);
    });

    // Handle bug completed
    eventSource.addEventListener("bug_completed", (e) => {
      const data = JSON.parse(e.data);
      setCurrentJob((prev) => prev ? {
        ...prev,
        bugs: prev.bugs.map((bug, idx) =>
          idx === data.bug_index ? { ...bug, status: "completed" as const } : bug
        ),
      } : prev);
    });

    // Handle bug failed
    eventSource.addEventListener("bug_failed", (e) => {
      const data = JSON.parse(e.data);
      setCurrentJob((prev) => prev ? {
        ...prev,
        bugs: prev.bugs.map((bug, idx) =>
          idx === data.bug_index ? { ...bug, status: "failed" as const, error: data.error } : bug
        ),
      } : prev);
    });

    // Handle job done
    eventSource.addEventListener("job_done", (e) => {
      const data = JSON.parse(e.data);
      setCurrentJob((prev) => prev ? {
        ...prev,
        job_status: data.status,
      } : prev);
      eventSource.close();
      // Refresh history after job completes
      loadHistory();
    });

    // Handle connection errors
    eventSource.onerror = () => {
      console.error("SSE connection error, will retry...");
    };

    return () => {
      eventSource.close();
    };
  }, [currentJob?.job_id, currentJob?.job_status]);

  // Load groups from API
  const loadGroups = useCallback(async () => {
    setLoadingGroups(true);
    try {
      const data = await getCCCCGroups("running");
      setGroups(data.groups);
      if (data.groups.length === 0) {
        toast({
          title: "没有可用的 Group",
          description: "请先启动一个 CCCC Group",
          variant: "default",
        });
      }
    } catch (err) {
      toast({
        title: "加载 Groups 失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setLoadingGroups(false);
    }
  }, [toast]);

  // Load job history
  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = await getBatchJobHistory(historyPage, 10);
      setHistoryJobs(data.jobs);
      setHistoryTotal(data.total);
    } catch (err) {
      console.error("Failed to load history:", err);
    } finally {
      setLoadingHistory(false);
    }
  }, [historyPage]);

  // Expand job to see details
  const toggleJobDetails = useCallback(async (jobId: string) => {
    if (expandedJobId === jobId) {
      setExpandedJobId(null);
      setExpandedJobDetails(null);
      return;
    }

    setExpandedJobId(jobId);
    try {
      const status = await getBatchJobStatus(jobId);
      setExpandedJobDetails({
        job_id: status.job_id,
        bugs: status.bugs.map((b, idx) => ({
          bug_id: `BUG-${idx + 1}`,
          url: b.url,
          status: b.status,
          error: b.error,
        })),
        started_at: status.created_at,
        job_status: status.status,
      });
    } catch (err) {
      console.error("Failed to load job details:", err);
      setExpandedJobId(null);
    }
  }, [expandedJobId]);

  // Parse Jira URLs from input
  const parseJiraUrls = useCallback(() => {
    return jiraUrls
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }, [jiraUrls]);

  // Submit batch job
  const handleSubmit = useCallback(async () => {
    const urls = parseJiraUrls();

    if (!selectedGroupId) {
      toast({
        title: "请选择目标 Group",
        variant: "destructive",
      });
      return;
    }

    if (urls.length === 0) {
      toast({
        title: "请输入 Jira Bug 链接",
        variant: "destructive",
      });
      return;
    }

    setSubmitting(true);
    try {
      const data = await submitBatchBugFix({
        target_group_id: selectedGroupId,
        jira_urls: urls,
        verification_level: verificationLevel,
        on_failure: failureStrategy,
        ...(fixerPeerId && { fixer_peer_id: fixerPeerId }),
        ...(verifierPeerId && { verifier_peer_id: verifierPeerId }),
      });

      // Initialize job with pending bugs
      const bugs: BugStatus[] = urls.map((url, index) => ({
        bug_id: `BUG-${index + 1}`,
        url: url,
        status: "pending",
      }));

      setCurrentJob({
        job_id: data.job_id,
        bugs,
        started_at: data.created_at,
        job_status: data.status,
      });

      toast({
        title: "任务已提交",
        description: `开始修复 ${data.total_bugs} 个 Bug (Job: ${data.job_id})`,
      });
    } catch (err) {
      toast({
        title: "提交失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }, [selectedGroupId, parseJiraUrls, verificationLevel, failureStrategy, fixerPeerId, verifierPeerId, toast]);

  // Calculate stats
  const stats = currentJob
    ? {
        completed: currentJob.bugs.filter((b) => b.status === "completed").length,
        in_progress: currentJob.bugs.filter((b) => b.status === "in_progress").length,
        pending: currentJob.bugs.filter((b) => b.status === "pending").length,
        failed: currentJob.bugs.filter((b) => b.status === "failed").length,
        skipped: currentJob.bugs.filter((b) => b.status === "skipped").length,
      }
    : { completed: 0, in_progress: 0, pending: 0, failed: 0, skipped: 0 };

  const selectedGroup = groups.find((g) => g.group_id === selectedGroupId);
  const availablePeers: CCCCPeer[] = selectedGroup?.peers ?? [];

  // Handle group selection change
  const handleGroupChange = useCallback((groupId: string) => {
    setSelectedGroupId(groupId);
    // Reset peer selections when group changes
    setFixerPeerId(null);
    setVerifierPeerId(null);
  }, []);

  return (
    <main className="flex h-screen overflow-hidden">
      {/* Sidebar with Navigation */}
      <Sidebar>
        {/* Current Task Status */}
        <div className="space-y-3">
          <h2 className="text-xs font-medium text-slate-500">当前任务</h2>
          {currentJob ? (
            <div className="rounded-lg bg-green-50 p-3">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    currentJob.job_status === "completed"
                      ? "bg-green-500"
                      : currentJob.job_status === "failed" || currentJob.job_status === "cancelled"
                        ? "bg-red-500"
                        : "bg-blue-500 animate-pulse"
                  }`}
                />
                <span className="text-sm font-medium text-green-800">
                  {currentJob.job_status === "completed"
                    ? "已完成"
                    : currentJob.job_status === "failed"
                      ? "失败"
                      : currentJob.job_status === "cancelled"
                        ? "已取消"
                        : "修复中"}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {stats.completed}/{currentJob.bugs.length} 完成
              </p>
            </div>
          ) : (
            <p className="text-xs text-slate-400">尚未启动任务</p>
          )}
        </div>
      </Sidebar>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">批量 Bug 修复</h1>
          <p className="text-sm text-slate-500">
            粘贴 Jira Bug 链接，一键启动自动修复流程
          </p>
        </div>

        {/* Main Content - Two Column Layout */}
        <div className="flex flex-1 gap-6">
        {/* Left Column - Input */}
        <div className="flex w-1/2 flex-col gap-4">
          {/* Group Selector */}
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm">目标 Group</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select
                value={selectedGroupId || ""}
                onValueChange={handleGroupChange}
                disabled={loadingGroups}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择目标 Group" />
                </SelectTrigger>
                <SelectContent>
                  {groups.length === 0 ? (
                    <SelectItem value="__empty" disabled>
                      暂无可用 Group
                    </SelectItem>
                  ) : (
                    groups
                      .filter((g) => g.running && g.state === "active")
                      .map((g) => (
                        <SelectItem
                          key={g.group_id}
                          value={g.group_id}
                          disabled={!g.ready}
                        >
                          {g.title} · {g.enabled_peers} peers
                          {!g.ready && " (不可用)"}
                        </SelectItem>
                      ))
                  )}
                </SelectContent>
              </Select>

              {selectedGroup && (
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={`h-2 w-2 rounded-full ${
                      selectedGroup.ready ? "bg-green-500" : "bg-slate-400"
                    }`}
                  />
                  <span className="text-slate-600">
                    {selectedGroup.ready ? "运行中" : "不可用"} ·{" "}
                    {selectedGroup.enabled_peers} 个 peer 可用
                  </span>
                </div>
              )}

              {/* Peer Selectors */}
              {selectedGroup && availablePeers.length > 0 && (
                <div className="grid grid-cols-2 gap-3 pt-2 border-t">
                  <div className="space-y-1">
                    <Label className="text-xs">修复执行者</Label>
                    <Select
                      value={fixerPeerId || ""}
                      onValueChange={setFixerPeerId}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择 Peer (可选)" />
                      </SelectTrigger>
                      <SelectContent>
                        {availablePeers.map((peer) => (
                          <SelectItem key={peer.id} value={peer.id}>
                            <span className="flex items-center gap-2">
                              <span>{peer.running ? "🟢" : "🔴"}</span>
                              <span>{peer.title} ({peer.id})</span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">验证执行者</Label>
                    <Select
                      value={verifierPeerId || ""}
                      onValueChange={setVerifierPeerId}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择 Peer (可选)" />
                      </SelectTrigger>
                      <SelectContent>
                        {availablePeers.map((peer) => (
                          <SelectItem key={peer.id} value={peer.id}>
                            <span className="flex items-center gap-2">
                              <span>{peer.running ? "🟢" : "🔴"}</span>
                              <span>{peer.title} ({peer.id})</span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              )}

              <Button
                variant="outline"
                size="sm"
                onClick={loadGroups}
                disabled={loadingGroups}
              >
                {loadingGroups ? "加载中..." : "刷新 Groups"}
              </Button>
            </CardContent>
          </Card>

          {/* Jira URLs Input */}
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm">Jira Bug 链接</CardTitle>
            </CardHeader>
            <CardContent>
              <Textarea
                placeholder={`每行一个 Jira Bug 链接，例如：
https://jira.example.com/browse/BUG-1234
https://jira.example.com/browse/BUG-1235
https://jira.example.com/browse/BUG-1236`}
                value={jiraUrls}
                onChange={(e) => setJiraUrls(e.target.value)}
                className="min-h-[160px] font-mono text-sm"
              />
              <p className="mt-2 text-xs text-slate-500">
                已输入 {parseJiraUrls().length} 个链接
              </p>
            </CardContent>
          </Card>

          {/* Configuration Options */}
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm">配置选项</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-xs">验证级别</Label>
                <Select
                  value={verificationLevel}
                  onValueChange={(v) => setVerificationLevel(v as VerificationLevel)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="quick">快速验证 (lint only)</SelectItem>
                    <SelectItem value="standard">标准验证 (lint + 单元测试)</SelectItem>
                    <SelectItem value="full">完整验证 (lint + 单元 + E2E)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-xs">失败策略</Label>
                <Select
                  value={failureStrategy}
                  onValueChange={(v) => setFailureStrategy(v as FailureStrategy)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="continue">跳过继续 (推荐)</SelectItem>
                    <SelectItem value="stop">停止等待</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          {/* Actions */}
          <div className="flex gap-3">
            <Button variant="outline" disabled={parseJiraUrls().length === 0}>
              预览 Bug 列表
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={submitting || !selectedGroupId || parseJiraUrls().length === 0}
            >
              {submitting ? "提交中..." : "开始修复"}
            </Button>
          </div>
        </div>

        {/* Right Column - Progress */}
        <div className="flex w-1/2 flex-col gap-4">
          {/* Progress Header */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-3">
              <CardTitle className="text-sm">修复进度</CardTitle>
              {currentJob && (
                <div className="flex items-center gap-2">
                  <Badge className="border-slate-200 bg-slate-50 text-slate-700">
                    {stats.completed}/{currentJob.bugs.length} 完成
                  </Badge>
                  {currentJob.job_status !== "completed" && currentJob.job_status !== "failed" && currentJob.job_status !== "cancelled" && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 px-2 text-xs text-red-600 hover:bg-red-50 hover:text-red-700"
                      onClick={async () => {
                        try {
                          await cancelBatchJob(currentJob.job_id);
                          setCurrentJob((prev) => prev ? { ...prev, job_status: "cancelled" } : prev);
                          toast({
                            title: "任务已取消",
                            description: `Job ${currentJob.job_id} 已取消`,
                          });
                          loadHistory();
                        } catch (err) {
                          toast({
                            title: "取消失败",
                            description: err instanceof Error ? err.message : "未知错误",
                            variant: "destructive",
                          });
                        }
                      }}
                    >
                      取消
                    </Button>
                  )}
                </div>
              )}
            </CardHeader>
            <CardContent>
              {currentJob ? (
                <div className="space-y-2">
                  {currentJob.bugs.map((bug) => (
                    <div
                      key={bug.bug_id}
                      className="flex items-center gap-3 rounded-lg border border-slate-200 p-3"
                    >
                      <span className="text-lg">
                        {bug.status === "completed" && "✅"}
                        {bug.status === "in_progress" && "🔄"}
                        {bug.status === "pending" && "⏳"}
                        {bug.status === "failed" && "❌"}
                        {bug.status === "skipped" && "⏭️"}
                      </span>
                      <div className="flex-1">
                        <p className="font-mono text-sm font-medium">{bug.bug_id}</p>
                        <p className="truncate text-xs text-slate-500">{bug.url}</p>
                      </div>
                      {bug.status === "in_progress" && (
                        <span className="text-xs text-blue-500">修复中...</span>
                      )}
                      {bug.status === "failed" && (
                        <span className="text-xs text-red-500">{bug.error || "失败"}</span>
                      )}
                      {bug.status === "skipped" && (
                        <span className="text-xs text-orange-500">已跳过</span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex h-[200px] items-center justify-center text-slate-400">
                  <p>尚未开始任务</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Stats */}
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-sm">统计信息</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-5 gap-3 text-center">
                <div className="rounded-lg bg-green-50 p-3">
                  <p className="text-2xl font-bold text-green-600">{stats.completed}</p>
                  <p className="text-xs text-green-700">完成</p>
                </div>
                <div className="rounded-lg bg-blue-50 p-3">
                  <p className="text-2xl font-bold text-blue-600">{stats.in_progress}</p>
                  <p className="text-xs text-blue-700">进行</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-2xl font-bold text-slate-600">{stats.pending}</p>
                  <p className="text-xs text-slate-700">等待</p>
                </div>
                <div className="rounded-lg bg-orange-50 p-3">
                  <p className="text-2xl font-bold text-orange-600">{stats.skipped}</p>
                  <p className="text-xs text-orange-700">跳过</p>
                </div>
                <div className="rounded-lg bg-red-50 p-3">
                  <p className="text-2xl font-bold text-red-600">{stats.failed}</p>
                  <p className="text-xs text-red-700">失败</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* History */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-3">
              <CardTitle className="text-sm">历史任务</CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => loadHistory()}
                disabled={loadingHistory}
              >
                {loadingHistory ? "加载中..." : "刷新"}
              </Button>
            </CardHeader>
            <CardContent>
              {historyJobs.length > 0 ? (
                <div className="space-y-2">
                  {historyJobs.map((job) => (
                    <div key={job.job_id}>
                      <div
                        className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-200 p-3 hover:bg-slate-50"
                        onClick={() => toggleJobDetails(job.job_id)}
                      >
                        <span className="text-lg">
                          {job.status === "completed" && "✅"}
                          {job.status === "running" && "🔄"}
                          {job.status === "failed" && "❌"}
                          {job.status === "pending" && "⏳"}
                        </span>
                        <div className="flex-1">
                          <p className="font-mono text-xs text-slate-600">{job.job_id}</p>
                          <p className="text-xs text-slate-400">
                            {new Date(job.created_at).toLocaleString()} · {job.total_bugs} bugs
                          </p>
                        </div>
                        <div className="text-right text-xs">
                          <span className="text-green-600">{job.completed} ✓</span>
                          {job.failed > 0 && (
                            <span className="ml-2 text-red-600">{job.failed} ✗</span>
                          )}
                        </div>
                        <span className="text-slate-400">
                          {expandedJobId === job.job_id ? "▼" : "▶"}
                        </span>
                      </div>
                      {expandedJobId === job.job_id && expandedJobDetails && (
                        <div className="ml-4 mt-2 space-y-1 border-l-2 border-slate-200 pl-4">
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
                              <span className="truncate text-slate-600">{bug.url}</span>
                              {bug.error && (
                                <span className="text-red-500">({bug.error})</span>
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
                        onClick={() => setHistoryPage((p) => p - 1)}
                      >
                        上一页
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setHistoryPage((p) => p + 1)}
                      >
                        下一页
                      </Button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex h-[100px] items-center justify-center text-slate-400">
                  <p>{loadingHistory ? "加载中..." : "暂无历史任务"}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
        </div>
      </div>
    </main>
  );
}
