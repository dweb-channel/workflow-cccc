"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export type AgentNodeStatus = "pending" | "running" | "completed" | "failed" | "waiting_peer";

export interface AgentNodeData {
  label: string;
  status: AgentNodeStatus;
  output?: string;
  [key: string]: unknown;
}

const STATUS_STYLES: Record<AgentNodeStatus, { bg: string; border: string; dot: string }> = {
  pending: { bg: "bg-slate-50", border: "border-slate-200", dot: "bg-slate-400" },
  running: { bg: "bg-blue-50", border: "border-blue-300", dot: "bg-blue-500 animate-pulse" },
  completed: { bg: "bg-emerald-50", border: "border-emerald-300", dot: "bg-emerald-500" },
  failed: { bg: "bg-red-50", border: "border-red-300", dot: "bg-red-500" },
  waiting_peer: { bg: "bg-purple-50", border: "border-purple-300", dot: "bg-purple-500 animate-pulse" },
};

function AgentNodeComponent({ data }: NodeProps) {
  const nodeData = data as AgentNodeData;
  const status = nodeData.status || "pending";
  const styles = STATUS_STYLES[status];

  return (
    <div
      className={`min-w-[180px] rounded-xl border-2 px-4 py-3 shadow-sm ${styles.bg} ${styles.border}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-400" />

      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${styles.dot}`} />
        <span className="font-medium text-slate-800">{nodeData.label}</span>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-slate-400" />
    </div>
  );
}

export const AgentNode = memo(AgentNodeComponent);
