"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Sidebar } from "@/components/sidebar/Sidebar";

import type { ValidationLevel, FailurePolicy, CCCCGroup } from "./types";
import { useBatchJob } from "./hooks/useBatchJob";
import { useJobHistory } from "./hooks/useJobHistory";
import { GroupSelector } from "./components/GroupSelector";
import { BugInput } from "./components/BugInput";
import { ConfigOptions } from "./components/ConfigOptions";
import { OverviewTab } from "./components/OverviewTab";
import { BugDetailTab } from "./components/BugDetailTab";
import { HistoryCard } from "./components/HistoryCard";
import { WorkflowTab } from "./components/WorkflowTab";

export default function BatchBugsPage() {
  // Group & peer selection
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [fixerPeerId, setFixerPeerId] = useState<string | null>(null);
  const [verifierPeerId, setVerifierPeerId] = useState<string | null>(null);

  // Form inputs
  const [jiraUrls, setJiraUrls] = useState("");
  const [validationLevel, setValidationLevel] =
    useState<ValidationLevel>("standard");
  const [failurePolicy, setFailurePolicy] =
    useState<FailurePolicy>("skip");

  // Hooks
  const { currentJob, submitting, stats, submit, cancel } = useBatchJob();
  const history = useJobHistory();

  const handleGroupChange = useCallback(
    (groupId: string, _group: CCCCGroup | undefined) => {
      setSelectedGroupId(groupId);
      setFixerPeerId(null);
      setVerifierPeerId(null);
    },
    []
  );

  const parseJiraUrls = useCallback(() => {
    return jiraUrls
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  }, [jiraUrls]);

  const handleSubmit = useCallback(async () => {
    const urls = parseJiraUrls();
    if (!selectedGroupId || urls.length === 0) return;

    const result = await submit({
      target_group_id: selectedGroupId,
      jira_urls: urls,
      config: {
        validation_level: validationLevel,
        failure_policy: failurePolicy,
      },
      ...(fixerPeerId && { fixer_peer_id: fixerPeerId }),
      ...(verifierPeerId && { verifier_peer_id: verifierPeerId }),
    });

    if (result) {
      history.loadHistory();
    }
  }, [
    selectedGroupId,
    parseJiraUrls,
    validationLevel,
    failurePolicy,
    fixerPeerId,
    verifierPeerId,
    submit,
    history,
  ]);

  return (
    <main className="flex h-screen overflow-hidden">
      <Sidebar>
        <div className="space-y-3">
          <h2 className="text-xs font-medium text-slate-500">当前任务</h2>
          {currentJob ? (
            <div className="rounded-lg bg-green-50 p-3">
              <div className="flex items-center gap-2">
                <span
                  className={`h-2 w-2 rounded-full ${
                    currentJob.job_status === "completed"
                      ? "bg-green-500"
                      : currentJob.job_status === "failed" ||
                          currentJob.job_status === "cancelled"
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

      <div className="flex flex-1 flex-col overflow-y-auto p-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-slate-900">批量 Bug 修复</h1>
          <p className="text-sm text-slate-500">
            粘贴 Jira Bug 链接，一键启动自动修复流程
          </p>
        </div>

        <div className="flex flex-1 gap-6">
          {/* Left Column - Input */}
          <div className="flex w-1/2 flex-col gap-4">
            <GroupSelector
              selectedGroupId={selectedGroupId}
              fixerPeerId={fixerPeerId}
              verifierPeerId={verifierPeerId}
              onGroupChange={handleGroupChange}
              onFixerChange={setFixerPeerId}
              onVerifierChange={setVerifierPeerId}
            />

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
                onClick={handleSubmit}
                disabled={
                  submitting ||
                  !selectedGroupId ||
                  parseJiraUrls().length === 0
                }
              >
                {submitting ? "提交中..." : "开始修复"}
              </Button>
            </div>
          </div>

          {/* Right Column - 4 Tab Layout */}
          <div className="flex w-1/2 flex-col">
            <Card className="flex-1">
              <CardContent className="p-0">
                <Tabs defaultValue="overview" className="h-full">
                  <TabsList className="w-full justify-start rounded-none border-b bg-transparent px-4 pt-2">
                    <TabsTrigger
                      value="workflow"
                      data-testid="tab-workflow"
                      className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none"
                    >
                      工作流程
                    </TabsTrigger>
                    <TabsTrigger
                      value="overview"
                      data-testid="tab-overview"
                      className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none"
                    >
                      总览
                    </TabsTrigger>
                    <TabsTrigger
                      value="detail"
                      data-testid="tab-detail"
                      className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none"
                    >
                      Bug 详情
                    </TabsTrigger>
                    <TabsTrigger
                      value="history"
                      data-testid="tab-history"
                      className="data-[state=active]:border-b-2 data-[state=active]:border-blue-500 rounded-none"
                    >
                      历史记录
                    </TabsTrigger>
                  </TabsList>

                  <div className="overflow-y-auto p-4" style={{ maxHeight: "calc(100vh - 220px)" }}>
                    <TabsContent value="workflow" className="mt-0">
                      <WorkflowTab />
                    </TabsContent>

                    <TabsContent value="overview" className="mt-0">
                      <OverviewTab
                        currentJob={currentJob}
                        stats={stats}
                        onCancel={cancel}
                      />
                    </TabsContent>

                    <TabsContent value="detail" className="mt-0">
                      <BugDetailTab currentJob={currentJob} />
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
                      />
                    </TabsContent>
                  </div>
                </Tabs>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </main>
  );
}
