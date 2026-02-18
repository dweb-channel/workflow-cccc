"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { runWorkflow, type V2WorkflowResponse } from "@/lib/api";
import { connectSSE, type SSEEvent } from "@/lib/sse";
import type { AgentNodeStatus } from "@/components/agent-node";
import type { FlowNode, FlowEdge } from "./useWorkflowEditor";

export interface ExecutionStatus {
  isRunning: boolean;
  currentNode: string | null;
  completedNodes: string[];
  error: string | null;
  sseEvents: Array<{ time: string; type: string; message: string }>;
}

interface UseWorkflowExecutionOptions {
  workflow: V2WorkflowResponse | null;
  setNodes: (updater: FlowNode[] | ((nds: FlowNode[]) => FlowNode[])) => void;
  setEdges: (updater: FlowEdge[] | ((eds: FlowEdge[]) => FlowEdge[])) => void;
  loadWorkflow: (id: string) => Promise<void>;
  setEditorMode: (mode: "view" | "edit") => void;
}

export function useWorkflowExecution({
  workflow,
  setNodes,
  setEdges,
  loadWorkflow,
  setEditorMode,
}: UseWorkflowExecutionOptions) {
  const [executionStatus, setExecutionStatus] = useState<ExecutionStatus>({
    isRunning: false,
    currentNode: null,
    completedNodes: [],
    error: null,
    sseEvents: [],
  });
  const [running, setRunning] = useState(false);
  const [requestText, setRequestText] = useState("");

  const sseCleanupRef = useRef<(() => void) | null>(null);

  // Handle SSE events
  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      const timestamp = new Date().toLocaleTimeString("zh-CN", { hour12: false });

      if (event.type === "node_update") {
        const { node, status } = event.data;
        const nodeLabel = node;

        setNodes((nds: FlowNode[]) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, status } } : n
          )
        );

        if (status === "running") {
          setEdges((eds: FlowEdge[]) =>
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
          setEdges((eds: FlowEdge[]) =>
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
          setEdges((eds: FlowEdge[]) =>
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

        setNodes((nds: FlowNode[]) =>
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

        setNodes((nds: FlowNode[]) =>
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

  const handleRun = useCallback(async () => {
    if (!workflow) return;
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

      setNodes((nds: FlowNode[]) =>
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
  }, [workflow, requestText, setNodes, handleSSEEvent, loadWorkflow, setEditorMode]);

  return {
    executionStatus,
    running,
    requestText,
    setRequestText,
    handleRun,
  };
}
