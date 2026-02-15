"use client";

import { useState, useMemo, useCallback } from "react";
import type { DesignSpec, ComponentSpec } from "@/lib/types/design-spec";
import { SpecTree } from "./SpecTree";
import { SpecCard } from "./SpecCard";
import { SpecPreview } from "./SpecPreview";
import { Copy, Check, Download } from "lucide-react";

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
  const [copied, setCopied] = useState(false);

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

  // ---- Export: Copy JSON ----
  const handleCopyJSON = useCallback(async () => {
    const data = selectedComponent
      ? JSON.stringify(selectedComponent, null, 2)
      : JSON.stringify(spec, null, 2);
    try {
      await navigator.clipboard.writeText(data);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS
      const textarea = document.createElement("textarea");
      textarea.value = data;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
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

        {/* Copy JSON */}
        <button
          onClick={handleCopyJSON}
          className="flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2.5 py-1 text-[11px] text-slate-300 hover:bg-slate-700 transition-colors"
          title={selectedComponent ? "Copy selected component JSON" : "Copy full spec JSON"}
        >
          {copied ? (
            <Check className="h-3 w-3 text-green-400" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? "Copied" : selectedComponent ? "Copy Component" : "Copy All"}
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

        {/* Center: Card */}
        <div className="flex-1 overflow-hidden border-r border-slate-700">
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
