"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { AgentNode, type AgentNodeData, type AgentNodeStatus } from "@/components/agent-node";
import { connectSSE, type SSEEvent } from "@/lib/sse";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const nodeTypes = { agent: AgentNode };

interface GraphData {
  nodes: Array<{ id: string; label: string; position?: { x: number; y: number } }>;
  edges: Array<{ id: string; source: string; target: string }>;
}

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

export default function CanvasPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);

  // Load graph topology
  useEffect(() => {
    async function loadGraph() {
      try {
        const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const res = await fetch(`${baseUrl}/api/workflows/wf-001/graph`);
        const data: GraphData = await res.json();

        // Convert to React Flow format
        const flowNodes = data.nodes.map((n, i) => ({
          id: n.id,
          type: "agent",
          position: n.position || { x: 100 + i * 250, y: 100 + (i % 2) * 80 },
          data: { label: n.label, status: "pending" as AgentNodeStatus },
        }));

        const flowEdges = data.edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          animated: false,
          style: { stroke: "#94a3b8", strokeWidth: 2 },
        }));

        setNodes(flowNodes);
        setEdges(flowEdges);
      } catch (err) {
        console.error("Failed to load graph:", err);
        // Use mock data for development
        setNodes([
          {
            id: "parse_requirements",
            type: "agent",
            position: { x: 100, y: 100 },
            data: { label: "需求解析", status: "pending" },
          },
          {
            id: "peer1_plan",
            type: "agent",
            position: { x: 350, y: 50 },
            data: { label: "Peer1 规划", status: "pending" },
          },
          {
            id: "peer2_review",
            type: "agent",
            position: { x: 600, y: 100 },
            data: { label: "Peer2 审核", status: "pending" },
          },
          {
            id: "final_output",
            type: "agent",
            position: { x: 850, y: 100 },
            data: { label: "最终输出", status: "pending" },
          },
        ]);
        setEdges([
          { id: "e1", source: "parse_requirements", target: "peer1_plan" },
          { id: "e2", source: "peer1_plan", target: "peer2_review" },
          { id: "e3", source: "peer2_review", target: "final_output" },
        ]);
      }
    }
    loadGraph();
  }, [setNodes, setEdges]);

  // Handle SSE events
  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      if (event.type === "node_update") {
        const { node, status } = event.data;
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
        } else if (status === "completed" || status === "failed") {
          setEdges((eds) =>
            eds.map((e) =>
              e.target === node ? { ...e, animated: false } : e
            )
          );
        }
        setLogs((prev) => [...prev, `[${status.toUpperCase()}] ${node}`]);
      } else if (event.type === "node_output") {
        const { node, output } = event.data;
        setNodes((nds) =>
          nds.map((n) =>
            n.id === node ? { ...n, data: { ...n.data, output } } : n
          )
        );
        setLogs((prev) => [...prev, `[OUTPUT] ${node}: ${output}`]);
      }
    },
    [setNodes, setEdges]
  );

  // Connect to SSE stream
  const handleConnect = useCallback(() => {
    if (isConnected) return;

    const cleanup = connectSSE("wf-001", "test-run", handleSSEEvent);
    setIsConnected(true);
    setLogs((prev) => [...prev, "[CONNECTED] SSE stream connected"]);

    // Cleanup on unmount handled by effect
    return cleanup;
  }, [isConnected, handleSSEEvent]);

  return (
    <div className="flex h-screen flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b bg-white px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">Agent 编排画布</h1>
          <p className="text-sm text-slate-500">可视化 Agent 执行流程</p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`flex items-center gap-2 text-sm ${isConnected ? "text-emerald-600" : "text-slate-400"}`}
          >
            <span
              className={`h-2 w-2 rounded-full ${isConnected ? "bg-emerald-500" : "bg-slate-300"}`}
            />
            {isConnected ? "已连接" : "未连接"}
          </span>
          <Button onClick={handleConnect} disabled={isConnected}>
            {isConnected ? "已连接 SSE" : "连接 Demo 流"}
          </Button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1">
        {/* Canvas */}
        <div className="flex-1">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView
            className="bg-slate-50"
          >
            <Controls />
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
          </ReactFlow>
        </div>

        {/* Log panel */}
        <Card className="w-[360px] rounded-none border-l border-t-0">
          <CardHeader className="py-3">
            <CardTitle className="text-sm">实时日志</CardTitle>
          </CardHeader>
          <CardContent className="h-[calc(100vh-180px)] overflow-auto p-3">
            {logs.length === 0 ? (
              <p className="text-sm text-slate-400">点击"连接 Demo 流"开始</p>
            ) : (
              <div className="space-y-1 font-mono text-xs">
                {logs.map((log, i) => (
                  <div
                    key={`log-${i}`}
                    className={`rounded px-2 py-1 ${
                      log.includes("[RUNNING]")
                        ? "bg-blue-50 text-blue-700"
                        : log.includes("[COMPLETED]")
                          ? "bg-emerald-50 text-emerald-700"
                          : log.includes("[FAILED]")
                            ? "bg-red-50 text-red-700"
                            : log.includes("[OUTPUT]")
                              ? "bg-amber-50 text-amber-700"
                              : "bg-slate-50 text-slate-600"
                    }`}
                  >
                    {log}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
