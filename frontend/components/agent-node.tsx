"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export type AgentNodeStatus = "pending" | "running" | "completed" | "failed" | "waiting_peer";

export interface AgentNodeData {
  label: string;
  status: AgentNodeStatus;
  output?: string;
  nodeType?: string;
  config?: Record<string, unknown>;
  editorMode?: "view" | "edit";
  iteration?: number;
  maxIterations?: number;
  [key: string]: unknown;
}

const STATUS_STYLES: Record<AgentNodeStatus, { bg: string; border: string; dot: string }> = {
  pending: { bg: "bg-card", border: "border-border", dot: "bg-muted-foreground" },
  running: { bg: "bg-cyan-50 dark:bg-cyan-900/30", border: "border-cyan-500", dot: "bg-cyan-500 dark:bg-cyan-400 animate-pulse" },
  completed: { bg: "bg-emerald-50 dark:bg-emerald-900/30", border: "border-emerald-500", dot: "bg-emerald-500 dark:bg-emerald-400" },
  failed: { bg: "bg-red-50 dark:bg-red-900/30", border: "border-red-500", dot: "bg-red-500 dark:bg-red-400" },
  waiting_peer: { bg: "bg-purple-50 dark:bg-purple-900/30", border: "border-purple-500", dot: "bg-purple-500 dark:bg-purple-400 animate-pulse" },
};

const NODE_TYPE_ICONS: Record<string, string> = {
  llm_agent: "🤖",
  peer1_plan: "📋",
  peer2_review: "🔍",
  foreman_summary: "📊",
  dispatch_tasks: "🚀",
  data_source: "💾",
  data_processor: "⚙️",
  http_request: "🌐",
  condition: "🔀",
  output: "📤",
};

function AgentNodeComponent({ data }: NodeProps) {
  const nodeData = data as AgentNodeData;
  const status = nodeData.status || "pending";
  const styles = STATUS_STYLES[status];
  const isEdit = nodeData.editorMode === "edit";
  const icon = NODE_TYPE_ICONS[nodeData.nodeType || ""] || "🔷";

  return (
    <div
      className={`min-w-[140px] max-w-[200px] rounded-lg border-2 px-3 py-2 shadow-sm ${styles.bg} ${styles.border} ${
        isEdit ? "ring-1 ring-primary/30" : ""
      }`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className={isEdit ? "!h-2.5 !w-2.5 !bg-primary !border-2 !border-card" : "!bg-muted-foreground"}
      />

      <div className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${styles.dot}`} />
        {isEdit && <span className="text-xs">{icon}</span>}
        <span className="text-sm font-medium text-foreground">{nodeData.label}</span>
        {nodeData.iteration != null && nodeData.iteration > 0 && (
          <span className="ml-auto rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-400">
            {nodeData.iteration}/{nodeData.maxIterations || "?"}
          </span>
        )}
      </div>

      {isEdit && nodeData.nodeType && (
        <p className="mt-0.5 text-[10px] text-muted-foreground">{nodeData.nodeType}</p>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className={isEdit ? "!h-2.5 !w-2.5 !bg-primary !border-2 !border-card" : "!bg-muted-foreground"}
      />
    </div>
  );
}

export const AgentNode = memo(AgentNodeComponent);
