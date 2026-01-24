"use client";

import { useEffect, useState, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  WorkflowDetail,
  WorkflowLog,
  RunRecord,
  listWorkflows,
  getWorkflow,
  getWorkflowLogs,
  getWorkflowRuns,
  runWorkflow,
  saveWorkflow,
} from "@/lib/api";
import { WorkflowConfirmDialog } from "@/components/workflow-confirm-dialog";

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-slate-500" },
  running: { label: "运行中", color: "bg-emerald-500" },
  success: { label: "成功", color: "bg-green-500" },
  failed: { label: "失败", color: "bg-red-500" },
  paused: { label: "已暂停", color: "bg-amber-500" },
};

const PRIORITY_OPTIONS = [
  { value: "low", label: "低" },
  { value: "normal", label: "普通" },
  { value: "high", label: "高" },
];

const TRIGGER_OPTIONS = [
  { value: "zhangsan", label: "张三" },
  { value: "lisi", label: "李四" },
  { value: "wangwu", label: "王五" },
];

function formatTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString("zh-CN", { hour12: false });
  } catch {
    return isoString;
  }
}

function formatRelativeTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "刚刚";
    if (diffMins < 60) return `${diffMins} 分钟前`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} 小时前`;
    return date.toLocaleDateString("zh-CN");
  } catch {
    return isoString;
  }
}

export default function Page() {
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);

  // Confirm dialog state
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false);
  const [confirmRunId, setConfirmRunId] = useState<string | null>(null);
  const [confirmStage, setConfirmStage] = useState<"initial" | "final">("initial");

  // Form state
  const [trigger, setTrigger] = useState("zhangsan");
  const [priority, setPriority] = useState<"low" | "normal" | "high">("normal");
  const [schedule, setSchedule] = useState("");
  const [notifyBot, setNotifyBot] = useState(true);
  const [nodeConfig, setNodeConfig] = useState("");

  // Pagination state
  const [logsPage, setLogsPage] = useState(1);
  const [logsTotal, setLogsTotal] = useState(0);
  const [runsPage, setRunsPage] = useState(1);
  const [runsTotal, setRunsTotal] = useState(0);
  const pageSize = 10;

  const loadWorkflow = useCallback(async (workflowId: string) => {
    try {
      const data = await getWorkflow(workflowId);
      setWorkflow(data);
      // Initialize form with workflow data
      setTrigger(data.parameters.trigger);
      setPriority(data.parameters.priority);
      setSchedule(data.parameters.schedule);
      setNotifyBot(data.parameters.notifyBot);
      setNodeConfig(data.nodeConfig);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载工作流失败");
    }
  }, []);

  const loadLogs = useCallback(async (workflowId: string, page: number) => {
    try {
      const data = await getWorkflowLogs(workflowId, page, pageSize);
      setLogs(data.items);
      setLogsTotal(data.total);
    } catch (err) {
      console.error("加载日志失败:", err);
    }
  }, []);

  const loadRuns = useCallback(async (workflowId: string, page: number) => {
    try {
      const data = await getWorkflowRuns(workflowId, page, pageSize);
      setRuns(data.items);
      setRunsTotal(data.total);
    } catch (err) {
      console.error("加载运行记录失败:", err);
    }
  }, []);

  useEffect(() => {
    async function init() {
      setLoading(true);
      try {
        // Get first workflow from list
        const workflows = await listWorkflows();
        if (workflows.length > 0) {
          const workflowId = workflows[0].id;
          await Promise.all([
            loadWorkflow(workflowId),
            loadLogs(workflowId, 1),
            loadRuns(workflowId, 1),
          ]);
        } else {
          setError("未找到工作流");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "初始化失败");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [loadWorkflow, loadLogs, loadRuns]);

  const handleRun = async () => {
    if (!workflow) return;
    setRunning(true);
    try {
      await runWorkflow(workflow.id, {
        parameters: { trigger, priority, schedule, notifyBot },
      });
      // Reload workflow and logs
      await Promise.all([
        loadWorkflow(workflow.id),
        loadLogs(workflow.id, 1),
        loadRuns(workflow.id, 1),
      ]);
    } catch (err) {
      alert(err instanceof Error ? err.message : "运行失败");
    } finally {
      setRunning(false);
    }
  };

  const handleSave = async () => {
    if (!workflow) return;
    setSaving(true);
    try {
      const result = await saveWorkflow(workflow.id, {
        parameters: { trigger, priority, schedule, notifyBot },
        nodeConfig,
      });
      setWorkflow(result.workflow);
      alert("保存成功");
    } catch (err) {
      alert(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleLogsPageChange = async (newPage: number) => {
    if (!workflow) return;
    setLogsPage(newPage);
    await loadLogs(workflow.id, newPage);
  };

  const handleRunsPageChange = async (newPage: number) => {
    if (!workflow) return;
    setRunsPage(newPage);
    await loadRuns(workflow.id, newPage);
  };

  const handleOpenConfirmDialog = (runId: string, stage: "initial" | "final") => {
    setConfirmRunId(runId);
    setConfirmStage(stage);
    setConfirmDialogOpen(true);
  };

  const handleConfirmed = async () => {
    if (!workflow) return;
    await Promise.all([
      loadWorkflow(workflow.id),
      loadRuns(workflow.id, runsPage),
      loadLogs(workflow.id, logsPage),
    ]);
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-slate-500">加载中...</p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-red-500">{error}</p>
      </main>
    );
  }

  if (!workflow) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-slate-500">未找到工作流</p>
      </main>
    );
  }

  const statusInfo = STATUS_MAP[workflow.status] || {
    label: workflow.status,
    color: "bg-slate-500",
  };
  const logsMaxPage = Math.ceil(logsTotal / pageSize);
  const runsMaxPage = Math.ceil(runsTotal / pageSize);

  return (
    <main className="mx-auto flex min-h-screen max-w-[1400px] flex-col gap-4 px-6 py-6">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{workflow.name}</CardTitle>
            <p className="text-xs text-slate-500">
              版本 {workflow.version} · 最近更新{" "}
              {formatRelativeTime(workflow.updated_at)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge>
              <span className={`h-2 w-2 rounded-full ${statusInfo.color}`} />
              {statusInfo.label}
            </Badge>
            <div className="flex items-center gap-2">
              <Button onClick={handleRun} disabled={running}>
                {running ? "运行中..." : "运行"}
              </Button>
              <Button variant="secondary" onClick={handleSave} disabled={saving}>
                {saving ? "保存中..." : "保存草稿"}
              </Button>
              <Button variant="ghost" disabled>
                发布
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="flex h-[520px] flex-col">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>流程画布</CardTitle>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm">
                放大
              </Button>
              <Button variant="secondary" size="sm">
                缩小
              </Button>
              <Button variant="secondary" size="sm">
                自动布局
              </Button>
            </div>
          </CardHeader>
          <CardContent className="flex-1">
            <div className="flex h-full flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-400">
              拖拽节点到画布以构建流程
            </div>
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle>运行参数</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="space-y-2">
              <Label>触发人</Label>
              <Select value={trigger} onValueChange={setTrigger}>
                <SelectTrigger>
                  <SelectValue placeholder="请选择触发人" />
                </SelectTrigger>
                <SelectContent>
                  {TRIGGER_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>执行优先级</Label>
              <Select
                value={priority}
                onValueChange={(v) => setPriority(v as "low" | "normal" | "high")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>计划时间</Label>
              <Input
                placeholder="2026-01-24 10:00"
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
              />
            </div>
            <div className="flex items-center justify-between rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
              <span className="text-xs text-slate-600">通知机器人</span>
              <Switch checked={notifyBot} onCheckedChange={setNotifyBot} />
            </div>

            <div className="space-y-2 pt-2">
              <Label>节点配置</Label>
              <Textarea
                placeholder="描述该节点的输入、输出与重试策略"
                value={nodeConfig}
                onChange={(e) => setNodeConfig(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <Tabs defaultValue="logs">
            <TabsList>
              <TabsTrigger value="logs">运行日志</TabsTrigger>
              <TabsTrigger value="history">历史记录</TabsTrigger>
              <TabsTrigger value="alerts">告警</TabsTrigger>
            </TabsList>

            <TabsContent value="logs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>时间</TableHead>
                    <TableHead>级别</TableHead>
                    <TableHead>消息</TableHead>
                    <TableHead>来源</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-center text-slate-400">
                        暂无日志
                      </TableCell>
                    </TableRow>
                  ) : (
                    logs.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell>{formatTime(log.time)}</TableCell>
                        <TableCell>
                          <span
                            className={
                              log.level === "error"
                                ? "text-red-600"
                                : log.level === "warn"
                                  ? "text-amber-600"
                                  : "text-slate-600"
                            }
                          >
                            {log.level}
                          </span>
                        </TableCell>
                        <TableCell>{log.message}</TableCell>
                        <TableCell className="text-slate-500">{log.source}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              {logsMaxPage > 1 && (
                <div className="mt-4 flex items-center justify-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={logsPage <= 1}
                    onClick={() => handleLogsPageChange(logsPage - 1)}
                  >
                    上一页
                  </Button>
                  <span className="text-sm text-slate-500">
                    {logsPage} / {logsMaxPage}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={logsPage >= logsMaxPage}
                    onClick={() => handleLogsPageChange(logsPage + 1)}
                  >
                    下一页
                  </Button>
                </div>
              )}
            </TabsContent>

            <TabsContent value="history">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>运行 ID</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>开始时间</TableHead>
                    <TableHead>结束时间</TableHead>
                    <TableHead>触发人</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} className="text-center text-slate-400">
                        暂无运行记录
                      </TableCell>
                    </TableRow>
                  ) : (
                    runs.map((run) => {
                      const runStatus = STATUS_MAP[run.status] || {
                        label: run.status,
                        color: "bg-slate-500",
                      };
                      return (
                        <TableRow key={run.id}>
                          <TableCell className="font-mono text-xs">
                            {run.id.slice(0, 8)}...
                          </TableCell>
                          <TableCell>
                            <Badge className="border-slate-200 bg-slate-50 text-slate-700">
                              <span
                                className={`mr-1 h-2 w-2 rounded-full ${runStatus.color}`}
                              />
                              {runStatus.label}
                            </Badge>
                          </TableCell>
                          <TableCell>{formatTime(run.started_at)}</TableCell>
                          <TableCell>
                            {run.ended_at ? formatTime(run.ended_at) : "-"}
                          </TableCell>
                          <TableCell>{run.triggered_by}</TableCell>
                          <TableCell>
                            {run.status === "running" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleOpenConfirmDialog(run.id, "initial")}
                                className="text-emerald-600 border-emerald-200 hover:bg-emerald-50"
                              >
                                确认
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
              {runsMaxPage > 1 && (
                <div className="mt-4 flex items-center justify-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={runsPage <= 1}
                    onClick={() => handleRunsPageChange(runsPage - 1)}
                  >
                    上一页
                  </Button>
                  <span className="text-sm text-slate-500">
                    {runsPage} / {runsMaxPage}
                  </span>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={runsPage >= runsMaxPage}
                    onClick={() => handleRunsPageChange(runsPage + 1)}
                  >
                    下一页
                  </Button>
                </div>
              )}
            </TabsContent>

            <TabsContent value="alerts">
              <div className="flex h-32 items-center justify-center text-slate-400">
                告警功能暂未实现
              </div>
            </TabsContent>
          </Tabs>
        </CardHeader>
      </Card>

      <WorkflowConfirmDialog
        open={confirmDialogOpen}
        onOpenChange={setConfirmDialogOpen}
        workflowId={workflow.id}
        runId={confirmRunId || ""}
        stage={confirmStage}
        onConfirmed={handleConfirmed}
      />
    </main>
  );
}
