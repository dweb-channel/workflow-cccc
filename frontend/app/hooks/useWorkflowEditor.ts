"use client";

import { useCallback, useEffect, useState, type DragEvent } from "react";
import {
  addEdge,
  type Connection,
  type ReactFlowInstance,
} from "@xyflow/react";
import type { AgentNodeData, AgentNodeStatus } from "@/components/agent-node";
import type { TemplateDetail } from "@/components/workflow-editor/TemplateSelector";
import type { EditorMode } from "@/components/workflow-editor/EditorToolbar";
import { toWorkflowDefinition, applyLoopStyles } from "@/lib/workflow-converter";
import { saveWorkflowGraph, type V2WorkflowResponse } from "@/lib/api";

// Shared types for workflow graph
export type FlowNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: AgentNodeData;
};

export type FlowEdge = {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
  style?: Record<string, unknown>;
  data?: { condition?: string; isLoop?: boolean };
};

let nodeIdCounter = 0;

interface UseWorkflowEditorOptions {
  nodes: FlowNode[];
  setNodes: (updater: FlowNode[] | ((nds: FlowNode[]) => FlowNode[])) => void;
  edges: FlowEdge[];
  setEdges: (updater: FlowEdge[] | ((eds: FlowEdge[]) => FlowEdge[])) => void;
  reactFlowInstance: ReactFlowInstance;
  workflow: V2WorkflowResponse | null;
  editorMode: EditorMode;
  setEditorMode: (mode: EditorMode) => void;
  graphChanged: boolean;
  setGraphChanged: (changed: boolean) => void;
  toast: (opts: { title: string; description?: string; variant?: "destructive" | "default" }) => void;
}

export function useWorkflowEditor({
  nodes,
  setNodes,
  edges,
  setEdges,
  reactFlowInstance,
  workflow,
  editorMode,
  setEditorMode,
  graphChanged,
  setGraphChanged,
  toast,
}: UseWorkflowEditorOptions) {
  const [savingGraph, setSavingGraph] = useState(false);
  const [maxIterations, setMaxIterations] = useState(10);
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<FlowEdge | null>(null);

  // Propagate editorMode to all nodes
  useEffect(() => {
    setNodes((nds: FlowNode[]) =>
      nds.map((n) => ({
        ...n,
        data: { ...n.data, editorMode },
      }))
    );
  }, [editorMode, setNodes]);

  const onConnect = useCallback(
    (params: Connection) => {
      if (editorMode !== "edit") return;
      setEdges((eds: FlowEdge[]) => {
        const newEdges = addEdge(
          { ...params, style: { stroke: "#94a3b8", strokeWidth: 2 } },
          eds
        );
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

      setNodes((nds: FlowNode[]) => [...nds, newNode]);
      setGraphChanged(true);
    },
    [editorMode, reactFlowInstance, setNodes]
  );

  const onNodesDelete = useCallback(
    (deleted: FlowNode[]) => {
      if (editorMode !== "edit") return;
      const ids = new Set(deleted.map((n) => n.id));
      setEdges((eds: FlowEdge[]) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
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
      setEdges((eds: FlowEdge[]) => {
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
      setEdges((eds: FlowEdge[]) => {
        const filtered = eds.filter((e) => e.id !== edgeId);
        return applyLoopStyles(nodes as FlowNode[], filtered as FlowEdge[]) as typeof filtered;
      });
      setGraphChanged(true);
    },
    [setEdges, nodes]
  );

  const handleNodeUpdate = useCallback(
    (nodeId: string, data: Partial<AgentNodeData>) => {
      setNodes((nds: FlowNode[]) =>
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
      setNodes((nds: FlowNode[]) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds: FlowEdge[]) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setGraphChanged(true);
    },
    [setNodes, setEdges]
  );

  const handleSaveGraph = useCallback(async () => {
    if (!workflow) return;

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

  const handleApplyTemplate = useCallback((template: TemplateDetail) => {
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
  }, [setNodes, setEdges, editorMode, setEditorMode]);

  return {
    graphChanged,
    setGraphChanged,
    savingGraph,
    maxIterations,
    setMaxIterations,
    selectedNode,
    setSelectedNode,
    selectedEdge,
    setSelectedEdge,
    onConnect,
    onDragOver,
    onDrop,
    onNodesDelete,
    handleNodeClick,
    handleEdgeClick,
    handleEdgeUpdate,
    handleEdgeDelete,
    handleNodeUpdate,
    handleNodeDelete,
    handleSaveGraph,
    handleApplyTemplate,
  };
}
