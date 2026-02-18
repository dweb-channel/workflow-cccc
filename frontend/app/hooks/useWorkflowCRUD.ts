"use client";

import { useCallback, useEffect, useState } from "react";
import {
  listWorkflows,
  getWorkflow,
  createWorkflow,
  deleteWorkflow,
  updateWorkflow,
  type V2WorkflowResponse,
} from "@/lib/api";
import { fromWorkflowDefinition } from "@/lib/workflow-converter";
import type { EditorMode } from "@/components/workflow-editor/EditorToolbar";
import type { FlowNode, FlowEdge } from "./useWorkflowEditor";

interface UseWorkflowCRUDOptions {
  setNodes: (updater: FlowNode[] | ((nds: FlowNode[]) => FlowNode[])) => void;
  setEdges: (updater: FlowEdge[] | ((eds: FlowEdge[]) => FlowEdge[])) => void;
  editorMode: EditorMode;
  setGraphChanged: (changed: boolean) => void;
  toast: (opts: { title: string; description?: string; variant?: "destructive" | "default" }) => void;
}

export function useWorkflowCRUD({
  setNodes,
  setEdges,
  editorMode,
  setGraphChanged,
  toast,
}: UseWorkflowCRUDOptions) {
  const [workflow, setWorkflow] = useState<V2WorkflowResponse | null>(null);
  const [workflowList, setWorkflowList] = useState<V2WorkflowResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const loadWorkflow = useCallback(async (workflowId: string) => {
    try {
      const data = await getWorkflow(workflowId);
      setWorkflow(data);

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
  }, [setNodes, setEdges, editorMode, setGraphChanged]);

  const refreshWorkflowList = useCallback(async () => {
    const result = await listWorkflows();
    setWorkflowList(result.items);
    return result.items;
  }, []);

  // Init: load workflow list and first workflow
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

  const handleDeleteWorkflow = useCallback((id: string) => {
    setPendingDeleteId(id);
    setDeleteDialogOpen(true);
  }, []);

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

  const handleSave = useCallback(async () => {
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
  }, [workflow, toast]);

  return {
    workflow,
    workflowList,
    loading,
    error,
    saving,
    creating,
    renamingId,
    renameValue,
    setRenameValue,
    setRenamingId,
    deleteDialogOpen,
    setDeleteDialogOpen,
    pendingDeleteId,
    setPendingDeleteId,
    loadWorkflow,
    handleCreateWorkflow,
    handleDeleteWorkflow,
    handleConfirmDelete,
    handleSwitchWorkflow,
    handleStartRename,
    handleConfirmRename,
    handleSave,
  };
}
