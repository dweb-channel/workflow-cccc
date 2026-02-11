"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AgentNodeData } from "@/components/agent-node";

interface FlowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: AgentNodeData;
}

interface NodeConfigPanelProps {
  node: FlowNode | null;
  onClose: () => void;
  onUpdate: (nodeId: string, data: Partial<AgentNodeData>) => void;
  onDelete: (nodeId: string) => void;
}

export function NodeConfigPanel({ node, onClose, onUpdate, onDelete }: NodeConfigPanelProps) {
  const [label, setLabel] = useState("");
  const [nodeType, setNodeType] = useState("");
  const [configJson, setConfigJson] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);

  // Only re-initialize when a different node is selected (by id), not on every data change
  const nodeId = node?.id;
  useEffect(() => {
    if (node) {
      setLabel(node.data.label || "");
      setNodeType(node.data.nodeType || "");
      setConfigJson(JSON.stringify(node.data.config || {}, null, 2));
      setErrors({});
      setInitialized(false);
      requestAnimationFrame(() => setInitialized(true));
    }
  }, [nodeId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-save to node data whenever label, nodeType, or configJson changes
  useEffect(() => {
    if (!node || !initialized) return;
    let config: Record<string, unknown> = {};
    try {
      config = JSON.parse(configJson);
    } catch {
      config = (node.data.config as Record<string, unknown>) || {};
    }
    onUpdate(node.id, { label, nodeType, config });
  }, [label, nodeType, configJson]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!node) return null;

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!label.trim()) errs.label = "显示名称不能为空";
    if (!nodeType) errs.nodeType = "请选择节点类型";

    // Type-specific required field validation
    let config: Record<string, unknown> = {};
    try { config = JSON.parse(configJson); } catch { config = (node.data.config as Record<string, unknown>) || {}; }

    if (nodeType === "llm_agent" && !((config.prompt as string) || "").trim()) {
      errs.prompt = "LLM Agent 的 Prompt 不能为空";
    }
    if (nodeType === "http_request" && !((config.url as string) || "").trim()) {
      errs.url = "URL 不能为空";
    }
    if (nodeType === "condition" && !((config.condition as string) || "").trim()) {
      errs.condition = "条件表达式不能为空";
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSave = () => {
    if (!validate()) return;
    onClose();
  };

  const handleDelete = () => {
    onDelete(node.id);
    onClose();
  };

  return (
    <div className="flex h-full flex-col rounded-xl border border-slate-200 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-800">节点配置</h3>
        <button
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          ✕
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex flex-col gap-4">
          {/* Node ID (read-only) */}
          <div className="space-y-1">
            <Label className="text-xs text-slate-500">节点 ID</Label>
            <Input value={node.id} disabled className="bg-slate-50 font-mono text-xs" />
          </div>

          {/* Label */}
          <div className="space-y-1">
            <RequiredLabel>显示名称</RequiredLabel>
            <Input
              value={label}
              onChange={(e) => { setLabel(e.target.value); setErrors((prev) => { const { label: _, ...rest } = prev; return rest; }); }}
              placeholder="节点名称"
              className={errors.label ? "border-red-300 focus-visible:ring-red-400" : ""}
            />
            <FieldError message={errors.label} />
          </div>

          {/* Node Type */}
          <div className="space-y-1">
            <RequiredLabel>节点类型</RequiredLabel>
            <Select value={nodeType} onValueChange={(v) => { setNodeType(v); setErrors((prev) => { const { nodeType: _, ...rest } = prev; return rest; }); }}>
              <SelectTrigger className={errors.nodeType ? "border-red-300 focus-visible:ring-red-400" : ""}>
                <SelectValue placeholder="选择类型" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="llm_agent">🤖 LLM Agent</SelectItem>
                <SelectItem value="data_source">💾 数据源</SelectItem>
                <SelectItem value="data_processor">⚙️ 数据处理</SelectItem>
                <SelectItem value="http_request">🌐 HTTP 请求</SelectItem>
                <SelectItem value="condition">🔀 条件分支</SelectItem>
                <SelectItem value="output">📤 输出</SelectItem>
              </SelectContent>
            </Select>
            <FieldError message={errors.nodeType} />
          </div>

          {/* Validation summary for type-specific fields */}
          {(errors.prompt || errors.url || errors.condition) && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2">
              <p className="text-xs font-medium text-red-600">请补充必填字段：</p>
              {Object.entries(errors).filter(([k]) => !["label", "nodeType"].includes(k)).map(([key, msg]) => (
                <p key={key} className="text-[11px] text-red-500">- {msg}</p>
              ))}
            </div>
          )}

          {/* Type-specific config fields */}
          {nodeType === "llm_agent" && (
            <LLMAgentConfig
              config={(node.data.config as Record<string, unknown>) || {}}
              onChange={(cfg) => setConfigJson(JSON.stringify(cfg, null, 2))}
            />
          )}

          {nodeType === "http_request" && (
            <HttpRequestConfig
              config={(node.data.config as Record<string, unknown>) || {}}
              onChange={(cfg) => setConfigJson(JSON.stringify(cfg, null, 2))}
            />
          )}

          {nodeType === "condition" && (
            <ConditionConfig
              config={(node.data.config as Record<string, unknown>) || {}}
              onChange={(cfg) => setConfigJson(JSON.stringify(cfg, null, 2))}
            />
          )}

          {/* Raw config JSON */}
          <div className="space-y-1">
            <Label className="text-xs text-slate-500">高级配置 (JSON)</Label>
            <Textarea
              value={configJson}
              onChange={(e) => setConfigJson(e.target.value)}
              className="min-h-[120px] font-mono text-xs"
              placeholder="{}"
            />
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
        <Button variant="destructive" size="sm" onClick={handleDelete}>
          删除节点
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

// ============ Type-specific config forms ============

function RequiredLabel({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <Label className={className}>
      {children}
      <span className="ml-0.5 text-red-500">*</span>
    </Label>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-[11px] text-red-500">{message}</p>;
}

function LLMAgentConfig({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (cfg: Record<string, unknown>) => void;
}) {
  const [prompt, setPrompt] = useState(
    (config.prompt as string) || ""
  );
  const [systemPrompt, setSystemPrompt] = useState(
    (config.system_prompt as string) || ""
  );
  const [cwd, setCwd] = useState(
    (config.cwd as string) || "."
  );
  const [timeout, setTimeout_] = useState(
    (config.timeout as number) || 300
  );
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    onChange({
      ...config,
      prompt,
      system_prompt: systemPrompt,
      cwd,
      timeout,
    });
  }, [prompt, systemPrompt, cwd, timeout]); // eslint-disable-line react-hooks/exhaustive-deps

  const promptError = touched && !prompt.trim() ? "Prompt 不能为空" : undefined;

  return (
    <div className="space-y-4 rounded-md border border-indigo-200 bg-indigo-50/50 p-3">
      <p className="text-xs font-medium text-indigo-600">LLM Agent 配置</p>

      {/* Prompt */}
      <div className="space-y-1">
        <RequiredLabel className="text-xs">Prompt 模板</RequiredLabel>
        <Textarea
          value={prompt}
          onChange={(e) => { setPrompt(e.target.value); setTouched(true); }}
          onBlur={() => setTouched(true)}
          placeholder="请分析以下需求：&#10;&#10;{request}&#10;&#10;输出格式：JSON"
          className={`min-h-[100px] font-mono text-xs ${promptError ? "border-red-300 focus-visible:ring-red-400" : ""}`}
        />
        <FieldError message={promptError} />
        <p className="text-[10px] text-slate-400">
          使用 {"{字段名}"} 引用上游节点输出
        </p>
      </div>

      {/* Advanced Settings */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="flex w-full items-center justify-between text-xs text-slate-500 hover:text-slate-700"
      >
        <span>高级设置</span>
        <span>{showAdvanced ? "▼" : "▶"}</span>
      </button>
      {showAdvanced && (
        <div className="space-y-3 border-t border-indigo-100 pt-3">
          <div className="space-y-1">
            <Label className="text-xs">System Prompt</Label>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="可选，系统提示词"
              className="min-h-[60px] text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">工作目录 (cwd)</Label>
            <Input
              value={cwd}
              onChange={(e) => setCwd(e.target.value)}
              placeholder="."
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">超时 (秒)</Label>
            <Input
              type="number"
              value={timeout}
              onChange={(e) => setTimeout_(Number(e.target.value))}
              className="text-xs"
            />
          </div>
        </div>
      )}
    </div>
  );
}

function HttpRequestConfig({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (cfg: Record<string, unknown>) => void;
}) {
  const [url, setUrl] = useState((config.url as string) || "");
  const [method, setMethod] = useState((config.method as string) || "GET");

  useEffect(() => {
    onChange({ ...config, url, method });
  }, [url, method]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-medium text-slate-500">HTTP 请求配置</p>
      <div className="space-y-1">
        <RequiredLabel className="text-xs">URL</RequiredLabel>
        <Input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://api.example.com/..."
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">方法</Label>
        <Select value={method} onValueChange={setMethod}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["GET", "POST", "PUT", "DELETE", "PATCH"].map((m) => (
              <SelectItem key={m} value={m}>{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

function ConditionConfig({
  config,
  onChange,
}: {
  config: Record<string, unknown>;
  onChange: (cfg: Record<string, unknown>) => void;
}) {
  const [condition, setCondition] = useState((config.condition as string) || "");
  const [trueBranch, setTrueBranch] = useState((config.true_branch as string) || "");
  const [falseBranch, setFalseBranch] = useState((config.false_branch as string) || "");

  useEffect(() => {
    onChange({ ...config, condition, true_branch: trueBranch, false_branch: falseBranch });
  }, [condition, trueBranch, falseBranch]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-medium text-slate-500">条件分支配置</p>
      <div className="space-y-1">
        <RequiredLabel className="text-xs">条件表达式</RequiredLabel>
        <Input
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          placeholder="e.g. result.score > 80"
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">True 分支 (节点ID)</Label>
        <Input
          value={trueBranch}
          onChange={(e) => setTrueBranch(e.target.value)}
          placeholder="目标节点 ID"
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">False 分支 (节点ID)</Label>
        <Input
          value={falseBranch}
          onChange={(e) => setFalseBranch(e.target.value)}
          placeholder="目标节点 ID"
        />
      </div>
    </div>
  );
}
