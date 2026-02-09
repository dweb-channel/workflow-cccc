"use client";

import { useEffect, useState, useCallback, useRef, type DragEvent } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  addEdge,
  useReactFlow,
  ReactFlowProvider,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/hooks/use-toast";
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
import {
  type V2WorkflowResponse,
  listWorkflows,
  getWorkflow,
  runWorkflow,
  updateWorkflow,
  saveWorkflowGraph,
  createWorkflow,
  deleteWorkflow,
} from "@/lib/api";
import { AgentNode, type AgentNodeData, type AgentNodeStatus } from "@/components/agent-node";
import { NodeDetailPanel } from "@/components/node-detail-panel";
import { connectSSE, type SSEEvent } from "@/lib/sse";
import { EditorToolbar, type EditorMode } from "@/components/workflow-editor/EditorToolbar";
import { NodePalette } from "@/components/workflow-editor/NodePalette";
import { NodeConfigPanel } from "@/components/workflow-editor/NodeConfigPanel";
import { TemplateSelector, type TemplateDetail } from "@/components/workflow-editor/TemplateSelector";
import { EdgeConfigPanel } from "@/components/workflow-editor/EdgeConfigPanel";
import { toWorkflowDefinition, fromWorkflowDefinition, applyLoopStyles } from "@/lib/workflow-converter";
import { Sidebar } from "@/components/sidebar/Sidebar";

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
  data?: { condition?: string; isLoop?: boolean };
};

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-slate-500" },
  published: { label: "已发布", color: "bg-blue-500" },
  archived: { label: "已归档", color: "bg-gray-500" },
  running: { label: "运行中", color: "bg-emerald-500" },
  success: { label: "成功", color: "bg-green-500" },
  failed: { label: "失败", color: "bg-red-500" },
};

interface ExecutionStatus {
  isRunning: boolean;
  currentNode: string | null;
  completedNodes: string[];
  error: string | null;
  sseEvents: Array<{ time: string; type: string; message: string }>;
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

// Counter for unique node IDs
let nodeIdCounter = 0;

function WorkflowPage() {
  const { toast } = useToast();
  const [workflow, setWorkflow] = useState<V2WorkflowResponse | null>(null);
  const [workflowList, setWorkflowList] = useState<V2WorkflowResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Delete confirmation dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  // Editor mode
  const [editorMode, setEditorMode] = useState<EditorMode>("view");
  const [graphChanged, setGraphChanged] = useState(false);
  const [savingGraph, setSavingGraph] = useState(false);
  const [maxIterations, setMaxIterations] = useState(10);

  // Execution status
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
  const reactFlowInstance = useReactFlow();

  // Selected node/edge for detail/config panel
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<FlowEdge | null>(null);

  // SSE connection cleanup
  const sseCleanupRef = useRef<(() => void) | null>(null);

  // Propagate editorMode to all nodes
  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, editorMode },
      }))
    );
  }, [editorMode, setNodes]);

  // Handle SSE events
  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      const timestamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });

      if (event.type === "node_update") {
        const { node, status } = event.data;
        const nodeLabel = node;

        setNodes((nds) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, status } } : n
          )
        );

        if (status === "running") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: true } : e
            )
          );
          setExecutionStatus((prev) => ({
            ...prev,
            currentNode: node,
            sseEvents: [
              { time: timestamp, type: "running", message: `${nodeLabel} 开始执行...` },
              ...prev.sseEvents.slice(0, 49),
            ],
          }));
        } else if (status === "completed") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: false } : e
            )
          );
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
        const nodeLabel = node;

        setNodes((nds) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, output } } : n
          )
        );

        setExecutionStatus((prev) => ({
          ...prev,
          sseEvents: [
            { time: timestamp, type: "output", message: `${nodeLabel} 输出: ${typeof output === 'string' ? output.slice(0, 100) : '...'}` },
            ...prev.sseEvents.slice(0, 49),
          ],
        }));
      } else if (event.type === "loop_iteration") {
        const { node, iteration, max_iterations } = event.data;
        const nodeLabel = node;

        setNodes((nds) =>
          nds.map((n) =>
            n.id === node
              ? { ...n, data: { ...n.data, iteration, maxIterations: max_iterations } }
              : n
          )
        );

        setExecutionStatus((prev) => ({
          ...prev,
          sseEvents: [
            { time: timestamp, type: "info", message: `🔄 ${nodeLabel} 循环迭代 ${iteration}/${max_iterations}` },
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

  // Form state for run input
  const [requestText, setRequestText] = useState("");

  const loadWorkflow = useCallback(async (workflowId: string) => {
    try {
      const data = await getWorkflow(workflowId);
      setWorkflow(data);

      // Load graph from embedded graph_definition
      if (data.graph_definition) {
        const { nodes: flowNodes, edges: flowEdges } = fromWorkflowDefinition(data.graph_definition);
        setNodes(flowNodes.map((n) => ({ ...n, data: { ...n.data, editorMode } })));
        setEdges(flowEdges);
      } else {
        setNodes([]);
        setEdges([]);
      }
      setGraphChanged(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载工作流失败");
    }
  }, [setNodes, setEdges, editorMode]);

  const refreshWorkflowList = useCallback(async () => {
    const result = await listWorkflows();
    setWorkflowList(result.items);
    return result.items;
  }, []);

  useEffect(() => {
    async function init() {
      setLoading(true);
      try {
        const items = await refreshWorkflowList();
        if (items.length > 0) {
          await loadWorkflow(items[0].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "初始化失败");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [loadWorkflow, refreshWorkflowList]);

  const handleCreateWorkflow = useCallback(async () => {
    const name = prompt("请输入工作流名称：", `工作流-${new Date().toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })}`);
    if (!name?.trim()) return;
    setCreating(true);
    try {
      const newWf = await createWorkflow({ name: name.trim() });
      await refreshWorkflowList();
      await loadWorkflow(newWf.id);
    } catch (err) {
      toast({
        title: "创建失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setCreating(false);
    }
  }, [refreshWorkflowList, loadWorkflow, toast]);

  // Open delete confirmation dialog
  const handleDeleteWorkflow = useCallback((id: string) => {
    setPendingDeleteId(id);
    setDeleteDialogOpen(true);
  }, []);

  // Execute delete after confirmation
  const handleConfirmDelete = useCallback(async () => {
    if (!pendingDeleteId) return;
    const id = pendingDeleteId;
    setDeleteDialogOpen(false);
    setPendingDeleteId(null);
    try {
      await deleteWorkflow(id);
      const items = await refreshWorkflowList();
      if (workflow?.id === id) {
        if (items.length > 0) {
          await loadWorkflow(items[0].id);
        } else {
          setWorkflow(null);
          setNodes([]);
          setEdges([]);
        }
      }
    } catch (err) {
      toast({
        title: "删除失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    }
  }, [pendingDeleteId, refreshWorkflowList, loadWorkflow, workflow, setNodes, setEdges, toast]);

  // Handle template selection - apply template to current canvas
  const handleApplyTemplate = useCallback((template: TemplateDetail) => {
    // Convert template nodes to FlowNode format
    // Templates use standard React Flow format: node.data.label, node.data.config
    const templateNodes = template.nodes.map((node) => ({
      id: node.id,
      type: "agentNode",
      position: node.position,
      data: {
        label: (node.data?.label as string) || node.id,
        icon: (node.data?.icon as string) || "🔷",
        status: "pending" as const,
        nodeType: node.type,
        config: (node.data?.config || {}) as Record<string, unknown>,
        editorMode,
      },
    }));

    // Convert template edges to FlowEdge format
    const templateEdges = template.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      style: { stroke: "#94a3b8", strokeWidth: 2 },
      data: edge.data,
    }));

    setNodes(templateNodes as FlowNode[]);
    setEdges(applyLoopStyles(templateNodes as FlowNode[], templateEdges as FlowEdge[]) as FlowEdge[]);
    setGraphChanged(true);
    setEditorMode("edit");
  }, [setNodes, setEdges, editorMode]);

  const handleSwitchWorkflow = useCallback(async (id: string) => {
    if (id === workflow?.id) return;
    await loadWorkflow(id);
  }, [workflow, loadWorkflow]);

  const handleStartRename = useCallback((wf: V2WorkflowResponse, e: React.MouseEvent) => {
    e.stopPropagation();
    setRenamingId(wf.id);
    setRenameValue(wf.name);
  }, []);

  const handleConfirmRename = useCallback(async (id: string) => {
    const trimmed = renameValue.trim();
    if (!trimmed) { setRenamingId(null); return; }
    try {
      const updated = await updateWorkflow(id, { name: trimmed });
      await refreshWorkflowList();
      if (workflow?.id === id) setWorkflow(updated);
    } catch (err) {
      toast({
        title: "重命名失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    }
    setRenamingId(null);
  }, [renameValue, refreshWorkflowList, workflow, toast]);

  // ============ Editor handlers ============

  const onConnect = useCallback(
    (params: Connection) => {
      if (editorMode !== "edit") return;
      setEdges((eds) => {
        const newEdges = addEdge(
          { ...params, style: { stroke: "#94a3b8", strokeWidth: 2 } },
          eds
        );
        // Re-detect loop edges and apply styling
        return applyLoopStyles(nodes as FlowNode[], newEdges as FlowEdge[]) as typeof newEdges;
      });
      setGraphChanged(true);
    },
    [editorMode, setEdges, nodes]
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      if (editorMode !== "edit") return;

      const raw = event.dataTransfer.getData("application/reactflow");
      if (!raw) return;

      const { type, label } = JSON.parse(raw);
      const position = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      nodeIdCounter += 1;
      const newNode: FlowNode = {
        id: `node-${Date.now()}-${nodeIdCounter}`,
        type: "agentNode",
        position,
        data: {
          label,
          status: "pending" as AgentNodeStatus,
          nodeType: type,
          config: {},
          editorMode,
        },
      };

      setNodes((nds) => [...nds, newNode]);
      setGraphChanged(true);
    },
    [editorMode, reactFlowInstance, setNodes]
  );

  const onNodesDelete = useCallback(
    (deleted: FlowNode[]) => {
      if (editorMode !== "edit") return;
      const ids = new Set(deleted.map((n) => n.id));
      setEdges((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
      setGraphChanged(true);
      if (selectedNode && ids.has(selectedNode.id)) {
        setSelectedNode(null);
      }
    },
    [editorMode, setEdges, selectedNode]
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: FlowNode) => {
      setSelectedNode(node);
      setSelectedEdge(null);
    },
    []
  );

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: FlowEdge) => {
      if (editorMode !== "edit") return;
      setSelectedEdge(edge);
      setSelectedNode(null);
    },
    [editorMode]
  );

  const handleEdgeUpdate = useCallback(
    (edgeId: string, data: Partial<FlowEdge>) => {
      setEdges((eds) => {
        const updated = eds.map((e) =>
          e.id === edgeId ? { ...e, ...data } : e
        );
        return applyLoopStyles(nodes as FlowNode[], updated as FlowEdge[]) as typeof updated;
      });
      setGraphChanged(true);
      setSelectedEdge(null);
    },
    [setEdges, nodes]
  );

  const handleEdgeDelete = useCallback(
    (edgeId: string) => {
      setEdges((eds) => {
        const filtered = eds.filter((e) => e.id !== edgeId);
        return applyLoopStyles(nodes as FlowNode[], filtered as FlowEdge[]) as typeof filtered;
      });
      setGraphChanged(true);
    },
    [setEdges, nodes]
  );

  const handleNodeUpdate = useCallback(
    (nodeId: string, data: Partial<AgentNodeData>) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n
        )
      );
      setGraphChanged(true);
    },
    [setNodes]
  );

  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setGraphChanged(true);
    },
    [setNodes, setEdges]
  );

  const handleSaveGraph = useCallback(async () => {
    if (!workflow) return;

    // Client-side validation: check required fields per node type
    const validationErrors: string[] = [];
    for (const node of nodes) {
      const data = node.data as AgentNodeData;
      const cfg = (data.config as Record<string, unknown>) || {};
      const nodeLabel = data.label || node.id;
      const nodeType = data.nodeType || "";

      if (nodeType === "llm_agent") {
        if (!((cfg.prompt as string) || "").trim()) {
          validationErrors.push(`「${nodeLabel}」: Prompt 不能为空`);
        }
      } else if (nodeType === "cccc_peer") {
        if (!((cfg.peer_id as string) || "").trim()) {
          validationErrors.push(`「${nodeLabel}」: Peer ID 不能为空`);
        }
        if (!((cfg.prompt as string) || "").trim()) {
          validationErrors.push(`「${nodeLabel}」: Prompt 不能为空`);
        }
        if (!((cfg.group_id as string) || "").trim()) {
          validationErrors.push(`「${nodeLabel}」: Group ID 不能为空`);
        }
      }
    }

    if (validationErrors.length > 0) {
      toast({
        title: "请补充必填字段",
        description: validationErrors.join("；"),
        variant: "destructive",
      });
      return;
    }

    setSavingGraph(true);
    try {
      const definition = toWorkflowDefinition(nodes, edges, workflow.name, maxIterations);
      await saveWorkflowGraph(workflow.id, {
        nodes: definition.nodes,
        edges: definition.edges,
        entry_point: definition.entry_point,
      });
      setGraphChanged(false);
    } catch (err) {
      toast({
        title: "保存图失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setSavingGraph(false);
    }
  }, [workflow, nodes, edges, maxIterations, toast]);

  // ============ Run/Save handlers ============

  const handleRun = async () => {
    if (!workflow) return;
    // Switch to view mode when running
    setEditorMode("view");
    setRunning(true);

    setExecutionStatus({
      isRunning: true,
      currentNode: null,
      completedNodes: [],
      error: null,
      sseEvents: [{ time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), type: "info", message: "工作流启动中..." }],
    });

    try {
      if (sseCleanupRef.current) {
        sseCleanupRef.current();
        sseCleanupRef.current = null;
      }

      setNodes((nds) =>
        nds.map((n) => ({ ...n, data: { ...n.data, status: "pending" as AgentNodeStatus, output: undefined } }))
      );

      const initialState: Record<string, unknown> = {};
      if (requestText) initialState.request = requestText;

      const result = await runWorkflow(workflow.id, initialState);

      setExecutionStatus((prev) => ({
        ...prev,
        sseEvents: [
          { time: new Date().toLocaleTimeString("zh-CN", { hour12: false }), type: "info", message: `工作流已启动 (runId: ${result.run_id.slice(0, 8)}...)` },
          ...prev.sseEvents.slice(0, 49),
        ],
      }));

      const cleanup = connectSSE(workflow.id, result.run_id, handleSSEEvent);
      sseCleanupRef.current = cleanup;

      await loadWorkflow(workflow.id);
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
      const result = await updateWorkflow(workflow.id, {
        name: workflow.name,
        description: workflow.description || undefined,
      });
      setWorkflow(result);
      toast({
        title: "保存成功",
        description: "工作流草稿已保存",
      });
    } catch (err) {
      toast({
        title: "保存失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
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

  const statusInfo = workflow
    ? STATUS_MAP[workflow.status] || { label: workflow.status, color: "bg-slate-500" }
    : null;

  return (
    <main className="flex h-screen overflow-hidden">
      {/* Sidebar with Navigation */}
      <Sidebar>
        {/* Workflow List */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-medium text-slate-500">工作流列表</h2>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-base"
              onClick={handleCreateWorkflow}
              disabled={creating}
            >
              {creating ? "…" : "+"}
            </Button>
          </div>
          <div className="space-y-1">
            {workflowList.length === 0 ? (
              <p className="py-4 text-center text-xs text-slate-400">暂无工作流，点击 + 创建</p>
            ) : (
              workflowList.map((wf) => {
                const active = wf.id === workflow?.id;
                const wfStatus = STATUS_MAP[wf.status] || { label: wf.status, color: "bg-slate-500" };
                return (
                  <div
                    key={wf.id}
                    className={`group cursor-pointer rounded-lg px-3 py-2 transition-colors ${
                      active ? "bg-slate-100 ring-1 ring-slate-200" : "hover:bg-slate-50"
                    }`}
                    onClick={() => handleSwitchWorkflow(wf.id)}
                    onDoubleClick={(e) => handleStartRename(wf, e)}
                  >
                    <div className="flex items-center justify-between">
                      {renamingId === wf.id ? (
                        <input
                          className="w-full rounded border border-blue-300 bg-white px-1 py-0.5 text-sm outline-none focus:ring-1 focus:ring-blue-400"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => handleConfirmRename(wf.id)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleConfirmRename(wf.id);
                            if (e.key === "Escape") setRenamingId(null);
                          }}
                          onClick={(e) => e.stopPropagation()}
                          autoFocus
                        />
                      ) : (
                        <span className={`truncate text-sm ${active ? "font-medium text-slate-900" : "text-slate-600"}`}>
                          {wf.name}
                        </span>
                      )}
                      {renamingId !== wf.id && (
                        <button
                          className="ml-1 hidden shrink-0 rounded p-0.5 text-slate-400 hover:bg-red-50 hover:text-red-500 group-hover:block"
                          onClick={(e) => { e.stopPropagation(); handleDeleteWorkflow(wf.id); }}
                          title="删除"
                        >
                          ✕
                        </button>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <span className={`inline-block h-1.5 w-1.5 rounded-full ${wfStatus.color}`} />
                      <span className="text-[10px] text-slate-400">{wfStatus.label}</span>
                      <span className="text-[10px] text-slate-300">·</span>
                      <span className="text-[10px] text-slate-400">{formatRelativeTime(wf.updated_at)}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
        {/* Template Selector */}
        <div className="mt-4 border-t border-slate-200 pt-4">
          <TemplateSelector
            onSelectTemplate={handleApplyTemplate}
            disabled={!workflow || running}
          />
        </div>
      </Sidebar>

      {/* Main Content */}
      <div className="flex flex-1 flex-col gap-4 overflow-hidden px-6 py-6">
      {workflow ? (
      <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{workflow.name}</CardTitle>
            <p className="text-xs text-slate-500">
              版本 {workflow.version} · 最近更新 {formatRelativeTime(workflow.updated_at)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge>
              <span className={`h-2 w-2 rounded-full ${statusInfo!.color}`} />
              {statusInfo!.label}
            </Badge>
            <div className="flex items-center gap-2">
              <Button onClick={handleRun} disabled={running || editorMode === "edit"}>
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

      <section className="flex min-h-0 flex-1 gap-4">
        {/* Node Palette - visible in edit mode */}
        {editorMode === "edit" && (
          <div className="w-[200px] shrink-0">
            <NodePalette />
          </div>
        )}

        {/* Canvas */}
        <Card className="flex min-h-0 flex-1 flex-col">
          <CardHeader className="flex flex-row items-center justify-between py-3">
            <CardTitle>流程画布</CardTitle>
            <EditorToolbar
              mode={editorMode}
              onModeChange={setEditorMode}
              onSaveGraph={handleSaveGraph}
              saving={savingGraph}
              hasChanges={graphChanged}
            />
          </CardHeader>
          <CardContent className="flex-1 p-0">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={(changes) => {
                onEdgesChange(changes);
                if (editorMode === "edit") setGraphChanged(true);
              }}
              onConnect={onConnect}
              onNodeClick={(e, node) => handleNodeClick(e, node as FlowNode)}
              onEdgeClick={(e, edge) => handleEdgeClick(e, edge as FlowEdge)}
              onPaneClick={() => { setSelectedNode(null); setSelectedEdge(null); }}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onNodesDelete={(deleted) => onNodesDelete(deleted as FlowNode[])}
              nodeTypes={nodeTypes}
              nodesDraggable={editorMode === "edit"}
              nodesConnectable={editorMode === "edit"}
              deleteKeyCode={editorMode === "edit" ? "Backspace" : null}
              fitView
              fitViewOptions={{ maxZoom: 1 }}
              className={editorMode === "edit" ? "bg-blue-50/30" : "bg-slate-50"}
            >
              <Controls />
              <Background
                variant={BackgroundVariant.Dots}
                gap={16}
                size={1}
                color={editorMode === "edit" ? "#93c5fd" : undefined}
              />
            </ReactFlow>
          </CardContent>
        </Card>

        {/* Right Panel - context-aware */}
        {editorMode === "edit" ? (
          /* Edit mode: inline config panel */
          <div className="w-[360px] shrink-0">
            {selectedNode ? (
              <NodeConfigPanel
                node={selectedNode}
                onClose={() => setSelectedNode(null)}
                onUpdate={handleNodeUpdate}
                onDelete={handleNodeDelete}
              />
            ) : selectedEdge ? (
              <EdgeConfigPanel
                edge={selectedEdge}
                onClose={() => setSelectedEdge(null)}
                onUpdate={handleEdgeUpdate}
                onDelete={handleEdgeDelete}
              />
            ) : (
              <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
                <div className="border-b border-slate-200 px-4 py-3">
                  <h3 className="font-semibold text-slate-800">工作流设置</h3>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="space-y-4">
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-slate-600">最大循环迭代次数</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={maxIterations}
                        onChange={(e) => {
                          setMaxIterations(Math.max(1, Math.min(100, Number(e.target.value) || 10)));
                          setGraphChanged(true);
                        }}
                        className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
                      />
                      <p className="text-[10px] text-slate-400">
                        循环路径中节点的最大重复执行次数（防止无限循环），默认 10
                      </p>
                    </div>
                    <hr className="border-slate-100" />
                    <p className="text-xs text-slate-400">点击节点或连接进行配置</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* View mode: run input */
          <Card className="flex w-[360px] shrink-0 flex-col">
            <CardHeader>
              <CardTitle>运行输入</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="space-y-2">
                <Label className="text-base font-medium">初始输入</Label>
                <Textarea
                  placeholder="请输入工作流的初始输入，例如：实现一个用户登录功能，支持邮箱和手机号登录"
                  value={requestText}
                  onChange={(e) => setRequestText(e.target.value)}
                  className="min-h-[120px] border-emerald-200 focus:border-emerald-500"
                />
                <p className="text-xs text-slate-500">
                  作为 initial_state.request 传递给工作流入口节点
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </section>

      {/* SSE Events Log (view mode only) */}
      {editorMode === "view" && executionStatus.sseEvents.length > 0 && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm">执行日志</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-48 overflow-y-auto rounded bg-slate-50 p-3 text-xs font-mono">
              {executionStatus.sseEvents.map((event, idx) => (
                <div key={idx} className={`${event.type === 'error' ? 'text-red-600' : event.type === 'completed' ? 'text-emerald-600' : 'text-slate-600'}`}>
                  <span className="text-slate-400">[{event.time}]</span> {event.message}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Node Detail Panel (view mode only) */}
      {editorMode === "view" && (
        <NodeDetailPanel
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
        />
      )}
      </>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center">
            <p className="text-slate-400">请从左侧选择工作流，或点击 + 创建新工作流</p>
          </div>
        </div>
      )}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确定删除此工作流？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作不可撤销，删除后工作流将永久丢失。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => setPendingDeleteId(null)}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmDelete}>确认删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}

// Wrap with ReactFlowProvider for useReactFlow hook
export default function Page() {
  return (
    <ReactFlowProvider>
      <WorkflowPage />
    </ReactFlowProvider>
  );
}
