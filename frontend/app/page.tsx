"use client";

import { useState } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
  useReactFlow,
  ReactFlowProvider,
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
import { AgentNode } from "@/components/agent-node";
import { NodeDetailPanel } from "@/components/node-detail-panel";
import { EditorToolbar, type EditorMode } from "@/components/workflow-editor/EditorToolbar";
import { NodePalette } from "@/components/workflow-editor/NodePalette";
import { NodeConfigPanel } from "@/components/workflow-editor/NodeConfigPanel";
import { EdgeConfigPanel } from "@/components/workflow-editor/EdgeConfigPanel";
import { useWorkflowEditor, type FlowNode, type FlowEdge } from "./hooks/useWorkflowEditor";
import { useWorkflowExecution } from "./hooks/useWorkflowExecution";
import { useWorkflowCRUD } from "./hooks/useWorkflowCRUD";
import { WorkflowSidebar } from "./components/WorkflowSidebar";
import { ExecutionLog } from "./components/ExecutionLog";

const nodeTypes = { agentNode: AgentNode };

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-muted-foreground" },
  published: { label: "已发布", color: "bg-blue-500" },
  archived: { label: "已归档", color: "bg-muted-foreground" },
  running: { label: "运行中", color: "bg-emerald-500" },
  success: { label: "成功", color: "bg-green-500" },
  failed: { label: "失败", color: "bg-red-500" },
};

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

function WorkflowPage() {
  const { toast } = useToast();

  // Editor mode — shared across hooks
  const [editorMode, setEditorMode] = useState<EditorMode>("view");
  // Lifted graph-changed state — shared between editor and CRUD hooks
  const [graphChanged, setGraphChanged] = useState(false);

  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const reactFlowInstance = useReactFlow();

  // --- CRUD hook ---
  const crud = useWorkflowCRUD({
    setNodes, setEdges,
    editorMode,
    setGraphChanged,
    toast,
  });

  // --- Editor hook ---
  const editor = useWorkflowEditor({
    nodes, setNodes, edges, setEdges,
    reactFlowInstance,
    workflow: crud.workflow,
    editorMode, setEditorMode,
    graphChanged, setGraphChanged,
    toast,
  });

  // --- Execution hook ---
  const execution = useWorkflowExecution({
    workflow: crud.workflow,
    setNodes, setEdges,
    loadWorkflow: crud.loadWorkflow,
    setEditorMode,
  });

  // --- Loading / Error states ---
  if (crud.loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">加载中...</p>
      </main>
    );
  }

  if (crud.error) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-red-500">{crud.error}</p>
      </main>
    );
  }

  const { workflow } = crud;
  const statusInfo = workflow
    ? STATUS_MAP[workflow.status] || { label: workflow.status, color: "bg-muted-foreground" }
    : null;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Workflow List Sidebar */}
      <WorkflowSidebar
        workflowList={crud.workflowList}
        currentWorkflowId={workflow?.id}
        creating={crud.creating}
        running={execution.running}
        workflow={workflow}
        renamingId={crud.renamingId}
        renameValue={crud.renameValue}
        setRenameValue={crud.setRenameValue}
        setRenamingId={crud.setRenamingId}
        onCreateWorkflow={crud.handleCreateWorkflow}
        onSwitchWorkflow={crud.handleSwitchWorkflow}
        onStartRename={crud.handleStartRename}
        onConfirmRename={crud.handleConfirmRename}
        onDeleteWorkflow={crud.handleDeleteWorkflow}
        onApplyTemplate={editor.handleApplyTemplate}
      />

      {/* Main Content */}
      <div className="flex flex-1 flex-col gap-4 overflow-hidden px-6 py-6">
      {workflow ? (
      <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <div>
            <CardTitle>{workflow.name}</CardTitle>
            <p className="text-xs text-muted-foreground">
              版本 {workflow.version} · 最近更新 {formatRelativeTime(workflow.updated_at)}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge>
              <span className={`h-2 w-2 rounded-full ${statusInfo!.color}`} />
              {statusInfo!.label}
            </Badge>
            <div className="flex items-center gap-2">
              <Button onClick={execution.handleRun} disabled={execution.running || editorMode === "edit"}>
                {execution.running ? "运行中..." : "运行"}
              </Button>
              <Button variant="secondary" onClick={crud.handleSave} disabled={crud.saving}>
                {crud.saving ? "保存中..." : "保存草稿"}
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
              onSaveGraph={editor.handleSaveGraph}
              saving={editor.savingGraph}
              hasChanges={editor.graphChanged}
            />
          </CardHeader>
          <CardContent className="flex-1 p-0">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={(changes) => {
                onEdgesChange(changes);
                if (editorMode === "edit") editor.setGraphChanged(true);
              }}
              onConnect={editor.onConnect}
              onNodeClick={(e, node) => editor.handleNodeClick(e, node as FlowNode)}
              onEdgeClick={(e, edge) => editor.handleEdgeClick(e, edge as FlowEdge)}
              onPaneClick={() => { editor.setSelectedNode(null); editor.setSelectedEdge(null); }}
              onDrop={editor.onDrop}
              onDragOver={editor.onDragOver}
              onNodesDelete={(deleted) => editor.onNodesDelete(deleted as FlowNode[])}
              nodeTypes={nodeTypes}
              nodesDraggable={editorMode === "edit"}
              nodesConnectable={editorMode === "edit"}
              deleteKeyCode={editorMode === "edit" ? "Backspace" : null}
              fitView
              fitViewOptions={{ maxZoom: 1 }}
              className={editorMode === "edit" ? "bg-background/50" : "bg-background"}
            >
              <Controls />
              <Background
                variant={BackgroundVariant.Dots}
                gap={16}
                size={1}
                color={editorMode === "edit" ? "#22D3EE33" : "#334155"}
              />
            </ReactFlow>
          </CardContent>
        </Card>

        {/* Right Panel - context-aware */}
        {editorMode === "edit" ? (
          <div className="w-[360px] shrink-0">
            {editor.selectedNode ? (
              <NodeConfigPanel
                node={editor.selectedNode}
                onClose={() => editor.setSelectedNode(null)}
                onUpdate={editor.handleNodeUpdate}
                onDelete={editor.handleNodeDelete}
              />
            ) : editor.selectedEdge ? (
              <EdgeConfigPanel
                edge={editor.selectedEdge}
                onClose={() => editor.setSelectedEdge(null)}
                onUpdate={editor.handleEdgeUpdate}
                onDelete={editor.handleEdgeDelete}
              />
            ) : (
              <div className="flex h-full flex-col rounded-xl border border-border bg-card shadow-sm">
                <div className="border-b border-border px-4 py-3">
                  <h3 className="font-semibold text-card-foreground">工作流设置</h3>
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  <div className="space-y-4">
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-muted-foreground">最大循环迭代次数</label>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={editor.maxIterations}
                        onChange={(e) => {
                          editor.setMaxIterations(Math.max(1, Math.min(100, Number(e.target.value) || 10)));
                          editor.setGraphChanged(true);
                        }}
                        className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-1 focus:ring-ring"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        循环路径中节点的最大重复执行次数（防止无限循环），默认 10
                      </p>
                    </div>
                    <hr className="border-border" />
                    <p className="text-xs text-muted-foreground">点击节点或连接进行配置</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <Card className="flex w-[360px] shrink-0 flex-col">
            <CardHeader>
              <CardTitle>运行输入</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="space-y-2">
                <Label className="text-base font-medium">初始输入</Label>
                <Textarea
                  placeholder="请输入工作流的初始输入，例如：实现一个用户登录功能，支持邮箱和手机号登录"
                  value={execution.requestText}
                  onChange={(e) => execution.setRequestText(e.target.value)}
                  className="min-h-[120px] border-input focus:border-primary"
                />
                <p className="text-xs text-muted-foreground">
                  作为 initial_state.request 传递给工作流入口节点
                </p>
              </div>
            </CardContent>
          </Card>
        )}
      </section>

      {/* SSE Events Log (view mode only) */}
      {editorMode === "view" && (
        <ExecutionLog events={execution.executionStatus.sseEvents} />
      )}

      {/* Node Detail Panel (view mode only) */}
      {editorMode === "view" && (
        <NodeDetailPanel
          node={editor.selectedNode}
          onClose={() => editor.setSelectedNode(null)}
        />
      )}
      </>
      ) : (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center">
            <p className="text-muted-foreground">请从左侧选择工作流，或点击 + 创建新工作流</p>
          </div>
        </div>
      )}
      </div>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={crud.deleteDialogOpen} onOpenChange={crud.setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确定删除此工作流？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作不可撤销，删除后工作流将永久丢失。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => crud.setPendingDeleteId(null)}>取消</AlertDialogCancel>
            <AlertDialogAction onClick={crud.handleConfirmDelete}>确认删除</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
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
