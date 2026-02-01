"use client";

import { type DragEvent } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface NodeTypeInfo {
  type: string;
  label: string;
  icon: string;
  color: string;
  category: string;
}

/**
 * Hardcoded node types matching backend registry.
 * Will be replaced by GET /api/node-types when T020 is done.
 */
export const NODE_TYPE_PALETTE: NodeTypeInfo[] = [
  { type: "llm_agent", label: "LLM Agent", icon: "🤖", color: "#6366F1", category: "agent" },
  { type: "cccc_peer", label: "CCCC Peer", icon: "👥", color: "#F59E0B", category: "agent" },
  { type: "data_source", label: "数据源", icon: "💾", color: "#4CAF50", category: "data" },
  { type: "data_processor", label: "数据处理", icon: "⚙️", color: "#2196F3", category: "processing" },
  { type: "http_request", label: "HTTP 请求", icon: "🌐", color: "#FF9800", category: "integration" },
  { type: "condition", label: "条件分支", icon: "🔀", color: "#9C27B0", category: "control" },
  { type: "output", label: "输出", icon: "📤", color: "#607D8B", category: "output" },
];

const CATEGORY_LABELS: Record<string, string> = {
  agent: "执行器",
  data: "数据",
  processing: "处理",
  integration: "集成",
  control: "控制",
  output: "输出",
};

function onDragStart(event: DragEvent, nodeInfo: NodeTypeInfo) {
  event.dataTransfer.setData(
    "application/reactflow",
    JSON.stringify({ type: nodeInfo.type, label: nodeInfo.label, icon: nodeInfo.icon, color: nodeInfo.color })
  );
  event.dataTransfer.effectAllowed = "move";
}

export function NodePalette() {
  // Group by category
  const grouped = NODE_TYPE_PALETTE.reduce<Record<string, NodeTypeInfo[]>>((acc, item) => {
    const cat = item.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});

  return (
    <Card className="h-full overflow-y-auto">
      <CardHeader className="py-3">
        <CardTitle className="text-sm">节点工具箱</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 px-3 pb-3">
        {Object.entries(grouped).map(([category, items]) => (
          <div key={category}>
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-slate-400">
              {CATEGORY_LABELS[category] || category}
            </p>
            <div className="flex flex-col gap-1">
              {items.map((info) => (
                <div
                  key={info.type}
                  draggable
                  onDragStart={(e) => onDragStart(e, info)}
                  className="flex cursor-grab items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50 active:cursor-grabbing"
                >
                  <span>{info.icon}</span>
                  <span className="text-slate-700">{info.label}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
