"use client";

import { useState, useMemo, useCallback } from "react";
import type { DesignSpec, ComponentSpec } from "@/lib/types/design-spec";
import { SpecTree } from "./SpecTree";
import { SpecCard } from "./SpecCard";
import { SpecPreview } from "./SpecPreview";
import { Copy, Check, Download, FileText } from "lucide-react";

// ================================================================
// SpecBrowser — Three-panel spec document viewer
//
// Left:   SpecTree (240px) — component hierarchy navigation
// Center: SpecCard (flex-1) — selected component detail
// Right:  SpecPreview (280px) — screenshot / CSS preview
// ================================================================

interface SpecBrowserProps {
  spec: DesignSpec;
  jobId?: string;
}

export function SpecBrowser({ spec, jobId }: SpecBrowserProps) {
  const [selectedId, setSelectedId] = useState<string | null>(
    spec.components[0]?.id ?? null
  );
  const [copiedMode, setCopiedMode] = useState<"llm" | "json" | null>(null);

  // Build flat lookup map for O(1) component finding
  const componentMap = useMemo(() => {
    const map = new Map<string, ComponentSpec>();
    function walk(comps: ComponentSpec[]) {
      for (const c of comps) {
        map.set(c.id, c);
        if (c.children) walk(c.children);
      }
    }
    walk(spec.components);
    return map;
  }, [spec.components]);

  const selectedComponent = selectedId ? componentMap.get(selectedId) : null;

  const handleNavigate = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  // ---- Export: Copy as LLM prompt ----
  const handleCopyForLLM = useCallback(async () => {
    const text = selectedComponent
      ? formatComponentForLLM(selectedComponent)
      : formatFullSpecForLLM(spec);
    await copyToClipboard(text);
    setCopiedMode("llm");
    setTimeout(() => setCopiedMode(null), 2000);
  }, [selectedComponent, spec]);

  // ---- Export: Copy JSON ----
  const handleCopyJSON = useCallback(async () => {
    const data = selectedComponent
      ? JSON.stringify(selectedComponent, null, 2)
      : JSON.stringify(spec, null, 2);
    await copyToClipboard(data);
    setCopiedMode("json");
    setTimeout(() => setCopiedMode(null), 2000);
  }, [selectedComponent, spec]);

  // ---- Export: Download full spec ----
  const handleDownload = useCallback(() => {
    const json = JSON.stringify(spec, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `design_spec_${spec.page?.name || "unnamed"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [spec]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-800">
      {/* ---- Toolbar ---- */}
      <div className="flex items-center gap-2 border-b border-slate-700 bg-slate-900 px-4 py-2.5 shrink-0">
        <span className="text-sm font-semibold text-white">
          Spec Browser
        </span>
        {spec.page?.name && (
          <span className="text-xs text-slate-400">
            &mdash; {spec.page.name}
          </span>
        )}
        {spec.page?.device?.type && (
          <span className="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400">
            {spec.page.device.type}
            {spec.page.device.width && spec.page.device.height
              ? ` ${spec.page.device.width}x${spec.page.device.height}`
              : ""}
          </span>
        )}

        <div className="flex-1" />

        {/* Copy for LLM */}
        <button
          onClick={handleCopyForLLM}
          className="flex items-center gap-1 rounded-md border border-violet-500/40 bg-violet-500/10 px-2.5 py-1 text-[11px] text-violet-300 hover:bg-violet-500/20 transition-colors"
          title={selectedComponent ? "复制该组件的可读描述（适合粘贴给 LLM）" : "复制全部组件的可读描述"}
        >
          {copiedMode === "llm" ? (
            <Check className="h-3 w-3 text-green-400" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copiedMode === "llm" ? "已复制" : "复制为提示词"}
        </button>

        {/* Copy JSON */}
        <button
          onClick={handleCopyJSON}
          className="flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-700 transition-colors"
          title={selectedComponent ? "Copy selected component JSON" : "Copy full spec JSON"}
        >
          {copiedMode === "json" ? (
            <Check className="h-3 w-3 text-green-400" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copiedMode === "json" ? "已复制" : "JSON"}
        </button>

        {/* Download */}
        <button
          onClick={handleDownload}
          className="flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-700 transition-colors"
          title="Download full design_spec.json"
        >
          <Download className="h-3 w-3" />
          Download
        </button>
      </div>

      {/* ---- Three-panel layout ---- */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Tree */}
        <div className="w-[240px] shrink-0 border-r border-slate-700 overflow-hidden">
          <SpecTree
            components={spec.components}
            selectedId={selectedId}
            onSelect={handleNavigate}
          />
        </div>

        {/* Center: Spec Card */}
        <div className="flex flex-1 flex-col overflow-hidden border-r border-slate-700">
          <div className="flex-1 overflow-hidden">
            {selectedComponent ? (
              <SpecCard
                component={selectedComponent}
                onNavigate={handleNavigate}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-slate-500 text-xs">
                Select a component from the tree
              </div>
            )}
          </div>
        </div>

        {/* Right: Preview */}
        <div className="w-[280px] shrink-0 overflow-hidden">
          {selectedComponent ? (
            <SpecPreview component={selectedComponent} jobId={jobId} />
          ) : (
            <div className="flex h-full items-center justify-center text-slate-500 text-xs">
              No component selected
            </div>
          )}
        </div>
      </div>

      {/* ---- Bottom status bar ---- */}
      <div className="flex items-center gap-3 border-t border-slate-700 bg-slate-900 px-4 py-2 shrink-0">
        <span className="text-[11px] text-slate-500">
          {componentMap.size} components
        </span>
        {spec.design_tokens?.colors && (
          <span className="text-[11px] text-slate-500">
            {Object.keys(spec.design_tokens.colors).length} color tokens
          </span>
        )}
        {spec.source && (
          <span className="text-[11px] text-slate-500">
            Source: {spec.source.tool}
            {spec.source.file_name ? ` / ${spec.source.file_name}` : ""}
          </span>
        )}
        <div className="flex-1" />
        <span className="text-[10px] text-slate-600">
          v{spec.version}
        </span>
      </div>
    </div>
  );
}

// ================================================================
// Clipboard helper
// ================================================================

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
}

// ================================================================
// LLM-friendly format helpers
// ================================================================

function resolveColorStr(c: unknown): string {
  if (typeof c === "string") return c;
  if (c && typeof c === "object" && "value" in c) return String((c as { value: string }).value);
  return "";
}

function formatComponentForLLM(comp: ComponentSpec): string {
  const lines: string[] = [];

  // Header
  lines.push(`## ${comp.name}（${comp.role}）`);
  if (comp.description) {
    lines.push(comp.description);
  }
  lines.push("");

  // Position & Size
  lines.push(`尺寸: ${Math.round(comp.bounds.width)} × ${Math.round(comp.bounds.height)}`);
  lines.push(`位置: x=${Math.round(comp.bounds.x)}, y=${Math.round(comp.bounds.y)}`);
  if (comp.z_index != null) lines.push(`层级: z-index ${comp.z_index}`);
  lines.push("");

  // Layout
  const layout = comp.layout;
  if (layout.type) {
    const parts: string[] = [`布局: ${layout.type}`];
    if (layout.direction) parts.push(layout.direction);
    lines.push(parts.join(" "));
    if (layout.justify) lines.push(`  对齐: justify=${layout.justify}`);
    if (layout.align) lines.push(`  对齐: align=${layout.align}`);
    if (layout.gap != null) {
      const g = typeof layout.gap === "object" ? layout.gap.value : layout.gap;
      lines.push(`  间距: gap=${g}px`);
    }
    if (layout.padding) {
      const p = layout.padding.map((v) => typeof v === "object" ? v.value : v);
      if (p.some((v) => v !== 0)) {
        lines.push(`  内边距: padding=[${p.join(", ")}]`);
      }
    }
    lines.push("");
  }

  // Sizing
  if (comp.sizing) {
    if (comp.sizing.width) lines.push(`宽度: ${comp.sizing.width}`);
    if (comp.sizing.height) lines.push(`高度: ${comp.sizing.height}`);
    lines.push("");
  }

  // Style
  const style = comp.style;
  const styleLines: string[] = [];
  if (style.background) {
    if (style.background.type === "solid" && style.background.color) {
      styleLines.push(`背景: ${resolveColorStr(style.background.color)}`);
    } else if (style.background.type === "none") {
      styleLines.push("背景: 透明");
    } else if (style.background.type?.startsWith("gradient")) {
      styleLines.push(`背景: ${style.background.type}`);
    }
  }
  if (style.corner_radius != null) {
    const cr = style.corner_radius;
    styleLines.push(`圆角: ${typeof cr === "number" ? `${cr}px` : `[${cr.join(", ")}]px`}`);
  }
  if (style.shadow && style.shadow.length > 0) {
    for (const s of style.shadow) {
      styleLines.push(`阴影: ${s.type || "drop"} x=${s.x ?? 0} y=${s.y ?? 0} blur=${s.blur ?? 0} spread=${s.spread ?? 0}${s.color ? ` color=${resolveColorStr(s.color)}` : ""}`);
    }
  }
  if (style.opacity != null && style.opacity !== 1) {
    styleLines.push(`透明度: ${style.opacity}`);
  }
  if (style.blur) {
    styleLines.push(`模糊: ${style.blur.type || "layer"} ${style.blur.radius || 0}px`);
  }
  if (styleLines.length > 0) {
    lines.push("样式:");
    for (const sl of styleLines) lines.push(`  ${sl}`);
    lines.push("");
  }

  // Typography
  if (comp.typography) {
    const t = comp.typography;
    lines.push("文字:");
    if (t.content) lines.push(`  内容: "${t.content}"`);
    if (t.font_family) lines.push(`  字体: ${t.font_family}`);
    if (t.font_size) lines.push(`  字号: ${t.font_size}px`);
    if (t.font_weight) lines.push(`  字重: ${t.font_weight}`);
    if (t.line_height) lines.push(`  行高: ${t.line_height}px`);
    if (t.color) lines.push(`  颜色: ${resolveColorStr(t.color)}`);
    if (t.align) lines.push(`  对齐: ${t.align}`);
    lines.push("");
  }

  // Interaction
  if (comp.interaction?.behaviors && comp.interaction.behaviors.length > 0) {
    lines.push("交互:");
    for (const b of comp.interaction.behaviors) {
      lines.push(`  - ${b.trigger || "click"} → ${b.action || "未知"}${b.target ? ` (${b.target})` : ""}`);
    }
    lines.push("");
  }

  // Children count
  if (comp.children_collapsed != null && comp.children_collapsed > 0) {
    lines.push(`子节点: ${comp.children_collapsed} 个`);
  }
  if (comp.children && comp.children.length > 0) {
    lines.push(`子组件: ${comp.children.length} 个`);
    for (const child of comp.children) {
      lines.push(`  - ${child.name}（${child.role}）${Math.round(child.bounds.width)}×${Math.round(child.bounds.height)}`);
    }
  }

  return lines.join("\n").trim();
}

function formatFullSpecForLLM(spec: DesignSpec): string {
  const lines: string[] = [];

  // Page info
  lines.push(`# ${spec.page?.name || "未命名页面"}`);
  if (spec.page?.device) {
    const d = spec.page.device;
    lines.push(`设备: ${d.type || "unknown"} ${d.width || "?"}×${d.height || "?"}`);
  }
  lines.push(`组件数量: ${spec.components.length}`);
  lines.push("");
  lines.push("---");
  lines.push("");

  // Each component
  for (const comp of spec.components) {
    lines.push(formatComponentForLLM(comp));
    lines.push("");
    lines.push("---");
    lines.push("");
  }

  return lines.join("\n").trim();
}
