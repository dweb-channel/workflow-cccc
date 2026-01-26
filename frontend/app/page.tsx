"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
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
import { AgentNode, type AgentNodeData, type AgentNodeStatus } from "@/components/agent-node";
import { NodeDetailPanel } from "@/components/node-detail-panel";
import { connectSSE, type SSEEvent } from "@/lib/sse";

const nodeTypes = { agentNode: AgentNode };

type FlowNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: AgentNodeData;
};

type FlowEdge = {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
  style?: Record<string, unknown>;
};

interface GraphData {
  nodes: Array<{
    id: string;
    type: string;
    data: { label: string; status: AgentNodeStatus };
    position: { x: number; y: number };
  }>;
  edges: Array<{ id: string; source: string; target: string }>;
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-slate-500" },
  running: { label: "运行中", color: "bg-emerald-500" },
  success: { label: "成功", color: "bg-green-500" },
  failed: { label: "失败", color: "bg-red-500" },
  paused: { label: "已暂停", color: "bg-amber-500" },
};

// Node ID to Chinese label mapping
const NODE_LABELS: Record<string, string> = {
  parse_requirements: "需求解析",
  peer1_plan: "Peer1 规划",
  peer2_review: "Peer2 审核",
  foreman_summary: "Foreman 汇总",
  dispatch_tasks: "任务分发",
  final_output: "最终输出",
};

// Execution status for progress display
interface ExecutionStatus {
  isRunning: boolean;
  currentNode: string | null;
  completedNodes: string[];
  error: string | null;
  sseEvents: Array<{ time: string; type: string; message: string }>;
}

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

  // Execution status for progress display
  const [executionStatus, setExecutionStatus] = useState<ExecutionStatus>({
    isRunning: false,
    currentNode: null,
    completedNodes: [],
    error: null,
    sseEvents: [],
  });

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  // Selected node for detail panel
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);

  // SSE connection cleanup
  const sseCleanupRef = useRef<(() => void) | null>(null);

  // Handle SSE events to update node status
  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      const timestamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });

      if (event.type === "node_update") {
        const { node, status } = event.data;
        const nodeLabel = NODE_LABELS[node] || node;

        // Update node visual state
        setNodes((nds) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, status } } : n
          )
        );

        // Animate edge when node starts running
        if (status === "running") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: true } : e
            )
          );
          // Update execution status
          setExecutionStatus((prev) => ({
            ...prev,
            currentNode: node,
            sseEvents: [
              { time: timestamp, type: "running", message: `${nodeLabel} 开始执行...` },
              ...prev.sseEvents.slice(0, 49), // Keep last 50 events
            ],
          }));
        } else if (status === "completed") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: false } : e
            )
          );
          // Update execution status
          setExecutionStatus((prev) => ({
            ...prev,
            currentNode: null,
            completedNodes: [...prev.completedNodes, node],
            sseEvents: [
              { time: timestamp, type: "completed", message: `${nodeLabel} 执行完成` },
              ...prev.sseEvents.slice(0, 49),
            ],
          }));
        } else if (status === "failed") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: false } : e
            )
          );
          // Update execution status with error
          setExecutionStatus((prev) => ({
            ...prev,
            currentNode: null,
            error: `${nodeLabel} 执行失败`,
            isRunning: false,
            sseEvents: [
              { time: timestamp, type: "error", message: `${nodeLabel} 执行失败` },
              ...prev.sseEvents.slice(0, 49),
            ],
          }));
        }
      } else if (event.type === "node_output") {
        const { node, output } = event.data;
        const nodeLabel = NODE_LABELS[node] || node;

        setNodes((nds) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, output } } : n
          )
        );

        // Log output event
        setExecutionStatus((prev) => ({
          ...prev,
          sseEvents: [
            { time: timestamp, type: "output", message: `${nodeLabel} 输出: ${typeof output === 'string' ? output.slice(0, 100) : '...'}`},
            ...prev.sseEvents.slice(0, 49),
          ],
        }));
      }
    },
    [setNodes, setEdges]
  );

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
      }
    };
  }, []);

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
  const [requestText, setRequestText] = useState("");  // Feature description input

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

  const loadGraph = useCallback(async (workflowId: string) => {
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(`${baseUrl}/api/workflows/${workflowId}/graph`);
      const data: GraphData = await res.json();

      // Use API data directly - backend returns React Flow compatible format
      const flowNodes: FlowNode[] = data.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      }));

      const flowEdges: FlowEdge[] = data.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        style: { stroke: "#94a3b8", strokeWidth: 2 },
      }));

      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (err) {
      console.error("加载流程图失败:", err);
      // Fallback mock data for development
      setNodes([
        {
          id: "parse_requirements",
          type: "agentNode",
          position: { x: 100, y: 100 },
          data: { label: "需求解析", status: "pending" },
        },
        {
          id: "peer1_plan",
          type: "agentNode",
          position: { x: 350, y: 50 },
          data: { label: "Peer1 规划", status: "pending" },
        },
        {
          id: "peer2_review",
          type: "agentNode",
          position: { x: 600, y: 100 },
          data: { label: "Peer2 审核", status: "pending" },
        },
        {
          id: "final_output",
          type: "agentNode",
          position: { x: 850, y: 100 },
          data: { label: "最终输出", status: "pending" },
        },
      ]);
      setEdges([
        { id: "e1", source: "parse_requirements", target: "peer1_plan", style: { stroke: "#94a3b8", strokeWidth: 2 } },
        { id: "e2", source: "peer1_plan", target: "peer2_review", style: { stroke: "#94a3b8", strokeWidth: 2 } },
        { id: "e3", source: "peer2_review", target: "final_output", style: { stroke: "#94a3b8", strokeWidth: 2 } },
      ]);
    }
  }, [setNodes, setEdges]);

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
            loadGraph(workflowId),
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
  }, [loadWorkflow, loadLogs, loadRuns, loadGraph]);

  const handleRun = async () => {
    if (!workflow) return;
    setRunning(true);

    // Reset execution status
    setExecutionStatus({
      isRunning: true,
      currentNode: null,
      completedNodes: [],
      error: null,
      sseEvents: [{ time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), type: "info", message: "工作流启动中..." }],
    });

    try {
      // Cleanup previous SSE connection
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
        sseCleanupRef.current = null;
      }

      // Reset node states to pending
      setNodes((nds) =>
        nds.map((n) => ({ ...n, data: { ...n.data, status: "pending" as AgentNodeStatus, output: undefined } }))
      );

      const result = await runWorkflow(workflow.id, {
        request: requestText || undefined,
        parameters: { trigger, priority, schedule, notifyBot },
      });

      // Update status after successful start
      setExecutionStatus((prev) => ({
        ...prev,
        sseEvents: [
          { time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), type: "info", message: `工作流已启动 (runId: ${result.runId.slice(0, 8)}...)` },
          ...prev.sseEvents.slice(0, 49),
        ],
      }));

      // Connect SSE to receive real-time updates
      const cleanup = connectSSE(workflow.id, result.runId, handleSSEEvent);
      sseCleanupRef.current = cleanup;

      // Reload workflow and logs
      await Promise.all([
        loadWorkflow(workflow.id),
        loadLogs(workflow.id, 1),
        loadRuns(workflow.id, 1),
      ]);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : "运行失败";
      setExecutionStatus((prev) => ({
        ...prev,
        isRunning: false,
        error: errorMsg,
        sseEvents: [
          { time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), type: "error", message: errorMsg },
          ...prev.sseEvents.slice(0, 49),
        ],
      }));
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

      {/* Execution Status Banner */}
      {(executionStatus.isRunning || executionStatus.currentNode || executionStatus.error || executionStatus.sseEvents.length > 0) && (
        <Card className={`border-l-4 ${executionStatus.error ? 'border-l-red-500 bg-red-50' : executionStatus.isRunning ? 'border-l-emerald-500 bg-emerald-50' : 'border-l-slate-300 bg-slate-50'}`}>
          <CardContent className="py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {executionStatus.isRunning && !executionStatus.error && (
                  <div className="h-3 w-3 animate-pulse rounded-full bg-emerald-500" />
                )}
                {executionStatus.error && (
                  <div className="h-3 w-3 rounded-full bg-red-500" />
                )}
                <div>
                  <p className={`text-sm font-medium ${executionStatus.error ? 'text-red-700' : 'text-slate-700'}`}>
                    {executionStatus.error
                      ? `执行失败: ${executionStatus.error}`
                      : executionStatus.currentNode
                        ? `正在执行: ${NODE_LABELS[executionStatus.currentNode] || executionStatus.currentNode}`
                        : executionStatus.isRunning
                          ? "工作流运行中..."
                          : executionStatus.completedNodes.length > 0
                            ? `已完成 ${executionStatus.completedNodes.length} 个节点`
                            : "就绪"
                    }
                  </p>
                  {executionStatus.completedNodes.length > 0 && !executionStatus.error && (
                    <p className="text-xs text-slate-500">
                      已完成: {executionStatus.completedNodes.map(n => NODE_LABELS[n] || n).join(" → ")}
                    </p>
                  )}
                </div>
              </div>
              {executionStatus.sseEvents.length > 0 && (
                <Badge variant="outline" className="text-xs">
                  {executionStatus.sseEvents.length} 条事件
                </Badge>
              )}
            </div>
            {/* Recent SSE Events */}
            {executionStatus.sseEvents.length > 0 && (
              <div className="mt-2 max-h-24 overflow-y-auto rounded bg-white/50 p-2 text-xs font-mono">
                {executionStatus.sseEvents.slice(0, 5).map((event, idx) => (
                  <div key={idx} className={`${event.type === 'error' ? 'text-red-600' : event.type === 'completed' ? 'text-emerald-600' : 'text-slate-600'}`}>
                    <span className="text-slate-400">[{event.time}]</span> {event.message}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
        <Card className="flex h-[520px] flex-col">
          <CardHeader className="flex flex-row items-center justify-between py-3">
            <CardTitle>流程画布</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-0">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={(_, node) => setSelectedNode(node as FlowNode)}
              onPaneClick={() => setSelectedNode(null)}
              nodeTypes={nodeTypes}
              fitView
              className="bg-slate-50"
            >
              <Controls />
              <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
            </ReactFlow>
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader>
            <CardTitle>运行参数</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="space-y-2">
              <Label className="text-base font-medium">功能描述</Label>
              <Textarea
                placeholder="请输入你想实现的功能，例如：实现一个用户登录功能，支持邮箱和手机号登录"
                value={requestText}
                onChange={(e) => setRequestText(e.target.value)}
                className="min-h-[80px] border-emerald-200 focus:border-emerald-500"
              />
              <p className="text-xs text-slate-500">这是工作流的第一步输入，将被解析并分发给各个 Agent 处理</p>
            </div>
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
                                variant="secondary"
                                onClick={() => handleOpenConfirmDialog(run.id, "initial")}
                                className="text-emerald-600 border border-emerald-200 hover:bg-emerald-50"
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

      {/* Node Detail Panel */}
      <NodeDetailPanel
        node={selectedNode}
        onClose={() => setSelectedNode(null)}
      />
    </main>
  );
}
