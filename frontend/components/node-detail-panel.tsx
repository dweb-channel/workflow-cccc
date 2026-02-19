"use client";

import { X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { type AgentNodeData, type AgentNodeStatus } from "./agent-node";

interface NodeDetailPanelProps {
  node: {
    id: string;
    data: AgentNodeData;
  } | null;
  onClose: () => void;
}

const STATUS_INFO: Record<AgentNodeStatus, { label: string; color: string }> = {
  pending: { label: "等待中", color: "bg-muted-foreground" },
  running: { label: "执行中", color: "bg-blue-500" },
  completed: { label: "已完成", color: "bg-emerald-500" },
  failed: { label: "失败", color: "bg-red-500" },
  waiting_peer: { label: "等待 Peer 响应", color: "bg-purple-500" },
};

const NODE_LABELS: Record<string, string> = {
  parse_requirements: "需求解析",
  peer1_plan: "Peer1 规划",
  peer2_review: "Peer2 审核",
  foreman_summary: "Foreman 汇总",
  dispatch_tasks: "任务分发",
  final_output: "最终输出",
};

export function NodeDetailPanel({ node, onClose }: NodeDetailPanelProps) {
  if (!node) return null;

  const status = node.data.status || "pending";
  const statusInfo = STATUS_INFO[status];
  const nodeLabel = NODE_LABELS[node.id] || node.data.label || node.id;

  // Decode output - handle JSON-encoded strings and escape sequences
  const decodeOutput = (output: string): string => {
    let result = output;
    // Try to parse as JSON string (handles double-encoding)
    for (let i = 0; i < 3; i++) {
      try {
        const parsed = JSON.parse(result);
        if (typeof parsed === 'string') {
          result = parsed;
        } else {
          // If it's an object, stringify it nicely for Markdown code block display
          return '```json\n' + JSON.stringify(parsed, null, 2) + '\n```';
        }
      } catch {
        break;
      }
    }
    // Replace literal \n with actual newlines
    return result.replace(/\\n/g, '\n').replace(/\\"/g, '"');
  };

  const decodedOutput = node.data.output ? decodeOutput(node.data.output) : undefined;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-[400px] flex-col border-l border-border bg-card shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span className={`h-3 w-3 rounded-full ${statusInfo.color}`} />
          <h2 className="text-lg font-semibold text-card-foreground">{nodeLabel}</h2>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Status */}
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">状态</h3>
          <Badge className="text-sm border-border bg-muted text-foreground">
            <span className={`mr-2 h-2 w-2 rounded-full ${statusInfo.color}`} />
            {statusInfo.label}
          </Badge>
        </div>

        {/* Node ID */}
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">节点 ID</h3>
          <code className="rounded bg-muted px-2 py-1 text-xs text-primary">{node.id}</code>
        </div>

        {/* Input */}
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">📥 输入</h3>
          <div className="rounded-lg bg-background p-3">
            {node.data.input ? (
              <div className="text-sm text-foreground prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>
                  {typeof node.data.input === 'string'
                    ? node.data.input
                    : '```json\n' + JSON.stringify(node.data.input, null, 2) + '\n```'}
                </ReactMarkdown>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">等待执行...</p>
            )}
          </div>
        </div>

        {/* Output */}
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-medium text-muted-foreground">📤 输出</h3>
          <div className="rounded-lg bg-background p-3">
            {decodedOutput ? (
              <div className="max-h-[400px] overflow-auto text-sm text-foreground prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{decodedOutput}</ReactMarkdown>
              </div>
            ) : status === "running" ? (
              <div className="flex items-center gap-2 text-xs text-blue-500">
                <span className="h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                正在思考...
              </div>
            ) : status === "waiting_peer" ? (
              <div className="flex items-center gap-2 text-xs text-purple-500">
                <span className="h-2 w-2 animate-pulse rounded-full bg-purple-500" />
                等待 Agent 响应...
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">等待执行...</p>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="border-t border-border px-4 py-3">
        <p className="text-xs text-muted-foreground">
          点击画布其他区域或按 ESC 关闭面板
        </p>
      </div>
    </div>
  );
}
