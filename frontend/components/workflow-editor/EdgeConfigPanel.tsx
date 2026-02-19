"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface FlowEdge {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
  style?: Record<string, unknown>;
  label?: string;
  data?: { condition?: string; branches?: Record<string, string>; isLoop?: boolean };
}

interface EdgeConfigPanelProps {
  edge: FlowEdge | null;
  onClose: () => void;
  onUpdate: (edgeId: string, data: Partial<FlowEdge>) => void;
  onDelete: (edgeId: string) => void;
}

export function EdgeConfigPanel({ edge, onClose, onUpdate, onDelete }: EdgeConfigPanelProps) {
  const [condition, setCondition] = useState("");
  const [edgeLabel, setEdgeLabel] = useState("");

  useEffect(() => {
    if (edge) {
      setCondition(edge.data?.condition || "");
      setEdgeLabel((edge.label as string) || "");
    }
  }, [edge]);

  if (!edge) return null;

  const isConditional = condition.trim().length > 0;
  const isLoop = edge.data?.isLoop === true;

  const handleSave = () => {
    const style = isLoop
      ? { stroke: "#f97316", strokeWidth: 2, strokeDasharray: "5 4" }
      : isConditional
        ? { stroke: "#9333ea", strokeWidth: 2, strokeDasharray: "6 3" }
        : { stroke: "#94a3b8", strokeWidth: 2 };

    onUpdate(edge.id, {
      label: edgeLabel || undefined,
      data: {
        ...(edge.data || {}),
        condition: condition.trim() || undefined,
      },
      style,
    });
  };

  const handleDelete = () => {
    onDelete(edge.id);
    onClose();
  };

  const handleClearCondition = () => {
    setCondition("");
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="font-semibold text-card-foreground">连接配置</h3>
        <button
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-4">
          {/* Edge ID */}
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">连接 ID</Label>
            <Input value={edge.id} disabled className="bg-muted font-mono text-xs" />
          </div>

          {/* Source → Target */}
          <div className="flex gap-2">
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">来源节点</Label>
              <Input value={edge.source} disabled className="bg-muted font-mono text-xs" />
            </div>
            <div className="flex items-end pb-0.5 text-muted-foreground">→</div>
            <div className="flex-1 space-y-1">
              <Label className="text-xs text-muted-foreground">目标节点</Label>
              <Input value={edge.target} disabled className="bg-muted font-mono text-xs" />
            </div>
          </div>

          {/* Edge Label */}
          <div className="space-y-1">
            <Label>显示标签</Label>
            <Input
              value={edgeLabel}
              onChange={(e) => setEdgeLabel(e.target.value)}
              placeholder="可选，如：成功、失败"
            />
          </div>

          {/* Condition Expression */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <Label>条件表达式</Label>
              {isConditional && (
                <button
                  onClick={handleClearCondition}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  清除条件
                </button>
              )}
            </div>
            <Textarea
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              placeholder="留空为普通连接，填写后变为条件边&#10;例: result.score > 80"
              className="min-h-[80px] font-mono text-xs"
            />
            <p className="text-[10px] text-muted-foreground">
              {isConditional ? "条件边 - 紫色虚线显示" : "普通连接 - 灰色实线显示"}
            </p>
            {/* Syntax guide */}
            <div className="mt-1 rounded border border-border bg-muted/50 p-2 text-[10px] text-muted-foreground">
              <p className="font-medium text-foreground">表达式语法</p>
              <ul className="mt-1 space-y-0.5">
                <li>比较: <code className="text-primary">result.score &gt; 80</code></li>
                <li>相等: <code className="text-primary">status == &quot;success&quot;</code></li>
                <li>布尔: <code className="text-primary">count &gt; 0 and is_valid</code></li>
                <li>字段: <code className="text-primary">data.output.approved</code></li>
              </ul>
              <p className="mt-1 text-muted-foreground">禁止: 函数调用、lambda、import</p>
            </div>
          </div>

          {/* Loop indicator */}
          {isLoop && (
            <div className="rounded-md border border-orange-500/30 bg-orange-500/10 p-3">
              <div className="flex items-center gap-2">
                <span className="text-sm">🔄</span>
                <span className="text-xs font-medium text-orange-600 dark:text-orange-400">循环回路边</span>
              </div>
              <p className="mt-1 text-[10px] text-orange-500 dark:text-orange-400">
                此连接形成循环。需要循环路径中有 condition 节点控制退出。
              </p>
            </div>
          )}

          {/* Preview */}
          <div className="rounded-md border border-border bg-muted/50 p-3">
            <p className="text-xs font-medium text-muted-foreground">预览样式</p>
            <div className="mt-2 flex items-center gap-2">
              <svg width="80" height="20">
                {isLoop ? (
                  <line
                    x1="0" y1="10" x2="80" y2="10"
                    stroke="#f97316"
                    strokeWidth="2"
                    strokeDasharray="5 4"
                  />
                ) : isConditional ? (
                  <line
                    x1="0" y1="10" x2="80" y2="10"
                    stroke="#9333ea"
                    strokeWidth="2"
                    strokeDasharray="6 3"
                  />
                ) : (
                  <line
                    x1="0" y1="10" x2="80" y2="10"
                    stroke="#94a3b8"
                    strokeWidth="2"
                  />
                )}
              </svg>
              <span className="text-xs text-muted-foreground">
                {isLoop ? "循环回路边" : isConditional ? "条件边" : "普通连接"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-border px-4 py-3">
        <Button variant="destructive" size="sm" onClick={handleDelete}>
          删除连接
        </Button>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button size="sm" onClick={handleSave}>
            保存
          </Button>
        </div>
      </div>
    </div>
  );
}
