"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { getDesignJobFiles, getDesignJobPreviewUrl, type DesignGeneratedFile } from "@/lib/api";
import { FileCode, Copy, Check, Eye, Code, Smartphone, Tablet, Monitor } from "lucide-react";

/* ================================================================
   CodePreview — Full-width code + live preview panel.
   Shown after pipeline completion. Uses iframe srcdoc for rendering.
   ================================================================ */

type Viewport = "mobile" | "tablet" | "desktop";
const VIEWPORTS: { key: Viewport; label: string; width: number | null; icon: typeof Smartphone }[] = [
  { key: "mobile", label: "Mobile", width: 375, icon: Smartphone },
  { key: "tablet", label: "Tablet", width: 768, icon: Tablet },
  { key: "desktop", label: "Desktop", width: null, icon: Monitor },
];

interface CodePreviewProps {
  jobId: string;
  jobStatus: string;
}

export function CodePreview({ jobId, jobStatus }: CodePreviewProps) {
  const [files, setFiles] = useState<DesignGeneratedFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"preview" | "code">("preview");
  const [viewport, setViewport] = useState<Viewport>("mobile");

  const isFinished = ["completed", "failed", "cancelled"].includes(jobStatus);

  const fetchFiles = useCallback(async () => {
    if (!jobId || !isFinished) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getDesignJobFiles(jobId);
      setFiles(data.files || []);
      const pageFile = data.files?.find((f) => f.path === "Page.tsx");
      setActiveFile(pageFile?.path || data.files?.[0]?.path || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setLoading(false);
    }
  }, [jobId, isFinished]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  // Backend preview URL (primary) + srcdoc fallback
  const previewUrl = jobId ? getDesignJobPreviewUrl(jobId) : null;
  const fallbackHtml = useMemo(() => {
    if (files.length === 0) return "";
    return buildPreviewHtml(files);
  }, [files]);

  if (!isFinished) return null;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-slate-400">
        <span className="h-2 w-2 rounded-full bg-violet-500 animate-pulse" />
        <span className="text-sm">Loading generated files...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-4 py-3">
          <p className="text-sm text-amber-400">{error}</p>
        </div>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500 text-sm">
        No generated files found.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Top bar: file tabs + view mode toggle */}
      <div className="flex items-center gap-2 border-b border-slate-700 bg-slate-900 px-3 py-2 shrink-0">
        {/* File tabs */}
        <div className="flex items-center gap-1 flex-1 overflow-x-auto">
          {files.map((f) => (
            <button
              key={f.path}
              onClick={() => setActiveFile(f.path)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-mono whitespace-nowrap transition-colors ${
                activeFile === f.path
                  ? "bg-violet-500/20 text-violet-300"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
              }`}
            >
              <FileCode className="h-3 w-3 shrink-0" />
              {f.path.split("/").pop()}
            </button>
          ))}
        </div>

        {/* Viewport toggle (only in preview mode) */}
        {viewMode === "preview" && (
          <div className="flex items-center rounded-md border border-slate-700 shrink-0">
            {VIEWPORTS.map((vp, i) => {
              const Icon = vp.icon;
              return (
                <button
                  key={vp.key}
                  onClick={() => setViewport(vp.key)}
                  title={vp.label}
                  className={`flex items-center gap-1 px-2 py-1 text-[11px] transition-colors ${
                    i === 0 ? "rounded-l-md" : ""
                  } ${i === VIEWPORTS.length - 1 ? "rounded-r-md" : ""} ${
                    viewport === vp.key
                      ? "bg-violet-500/20 text-violet-300"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                </button>
              );
            })}
          </div>
        )}

        {/* View mode toggle */}
        <div className="flex items-center rounded-md border border-slate-700 shrink-0">
          <button
            onClick={() => setViewMode("preview")}
            className={`flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-l-md transition-colors ${
              viewMode === "preview"
                ? "bg-violet-500/20 text-violet-300"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Eye className="h-3 w-3" /> Preview
          </button>
          <button
            onClick={() => setViewMode("code")}
            className={`flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-r-md transition-colors ${
              viewMode === "code"
                ? "bg-violet-500/20 text-violet-300"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Code className="h-3 w-3" /> Code
          </button>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-hidden">
        {viewMode === "preview" ? (
          <IframePreview url={previewUrl} fallbackHtml={fallbackHtml} viewport={viewport} />
        ) : (
          <CodePanel
            file={files.find((f) => f.path === activeFile) || files[0]}
          />
        )}
      </div>
    </div>
  );
}

/* ================================================================
   buildPreviewHtml — Assemble a self-contained HTML document from
   the generated TSX files. Uses React CDN + Babel standalone for
   in-browser JSX compilation. Lightweight alternative to Sandpack.
   ================================================================ */

function buildPreviewHtml(files: DesignGeneratedFile[]): string {
  const variablesCss = files.find((f) => f.path === "variables.css");
  const pageFile = files.find((f) => f.path === "Page.tsx");
  const componentFiles = files.filter(
    (f) => f.path.endsWith(".tsx") && f.path !== "Page.tsx"
  );

  // Strip TypeScript type annotations for browser compatibility
  // (Babel standalone with React preset handles JSX but not full TS)
  const stripTypes = (code: string): string => {
    return code
      // Remove import type statements
      .replace(/^import\s+type\s+.*$/gm, "")
      // Remove type-only imports from mixed imports
      .replace(/,\s*type\s+\w+/g, "")
      // Remove interface declarations
      .replace(/^(export\s+)?interface\s+\w+\s*\{[^}]*\}/gm, "")
      // Remove type declarations
      .replace(/^(export\s+)?type\s+\w+\s*=\s*\{[^}]*\}/gm, "")
      // Remove type annotations from function params: (x: Type) → (x)
      .replace(/:\s*(?:React\.(?:FC|ReactNode|CSSProperties)|string|number|boolean|any|void|undefined|null)(?:\[\])?/g, "")
      // Remove generic type params: <Props> → empty
      .replace(/<(?:React\.(?:FC|ReactNode)|Props|[A-Z]\w*Props)>/g, "")
      // Remove `as const` / `as Type`
      .replace(/\s+as\s+(?:const|string|number|any|\w+)/g, "")
      // Remove React.FC type annotation
      .replace(/:\s*React\.FC(?:<\w+>)?/g, "");
  };

  // Build component scripts — each wrapped in its own scope
  const componentScripts = componentFiles
    .map((f) => {
      const name = f.path.replace(/\.tsx?$/, "").split("/").pop();
      const cleaned = stripTypes(f.content)
        // Remove import/export statements (we'll expose as globals)
        .replace(/^import\s+.*$/gm, "")
        .replace(/^export\s+default\s+/gm, "")
        .replace(/^export\s+/gm, "");
      return `
        const ${name} = (() => {
          ${cleaned}
          return typeof ${name} !== 'undefined' ? ${name} : () => React.createElement('div', null, '${name}');
        })();
      `;
    })
    .join("\n");

  // Build Page script
  let pageScript = "";
  if (pageFile) {
    const cleaned = stripTypes(pageFile.content)
      .replace(/^import\s+.*$/gm, "")
      .replace(/^export\s+default\s+/gm, "")
      .replace(/^export\s+/gm, "");
    pageScript = `
      const Page = (() => {
        ${cleaned}
        return typeof Page !== 'undefined' ? Page : () => React.createElement('div', null, 'Page');
      })();
    `;
  }

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <script src="https://cdn.tailwindcss.com"><\/script>
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"><\/script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"><\/script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"><\/script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: -apple-system, PingFang SC, sans-serif; }
    ${variablesCss?.content || ""}
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel" data-presets="react">
    ${componentScripts}
    ${pageScript}
    const root = ReactDOM.createRoot(document.getElementById('root'));
    root.render(React.createElement(Page || (() => React.createElement('div', null, 'No Page component')), null));
  <\/script>
</body>
</html>`;
}

/* ================================================================
   IframePreview — Renders preview HTML in a sandboxed iframe
   ================================================================ */

function IframePreview({
  url,
  fallbackHtml,
  viewport,
}: {
  url: string | null;
  fallbackHtml: string;
  viewport: Viewport;
}) {
  const [useFallback, setUseFallback] = useState(false);
  const vpConfig = VIEWPORTS.find((v) => v.key === viewport);
  const vpWidth = vpConfig?.width ?? null;

  const hasContent = url || fallbackHtml;
  if (!hasContent) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500 text-sm">
        No files to preview.
      </div>
    );
  }

  // Use backend URL if available and not failed; otherwise srcdoc fallback
  const useUrl = url && !useFallback;

  return (
    <div className="h-full flex justify-center bg-slate-950 overflow-hidden">
      <div
        className="h-full transition-all duration-300"
        style={{ width: vpWidth ? `${vpWidth}px` : "100%", maxWidth: "100%" }}
      >
        {useUrl ? (
          <iframe
            src={url}
            className="h-full w-full border-0 bg-white"
            title="Preview"
            onError={() => setUseFallback(true)}
          />
        ) : (
          <iframe
            srcDoc={fallbackHtml}
            className="h-full w-full border-0 bg-white"
            sandbox="allow-scripts"
            title="Preview"
          />
        )}
      </div>
    </div>
  );
}

/* ================================================================
   CodePanel — Syntax-highlighted code view with copy
   ================================================================ */

function CodePanel({ file }: { file: DesignGeneratedFile }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(file.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard not available
    }
  };

  const lineCount = file.content.split("\n").length;
  const sizeLabel =
    file.size >= 1024
      ? `${(file.size / 1024).toFixed(1)} KB`
      : `${file.size} B`;

  return (
    <div className="relative h-full flex flex-col">
      {/* File info bar */}
      <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-700 shrink-0">
        <span className="text-xs font-mono text-slate-300">{file.path}</span>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-slate-500">
            {lineCount} lines · {sizeLabel}
          </span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 rounded-md border border-slate-600 bg-slate-800 px-2 py-1 text-[10px] text-slate-400 hover:text-white hover:border-slate-500 transition-colors"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3" /> Copied
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" /> Copy
              </>
            )}
          </button>
        </div>
      </div>
      {/* Code */}
      <pre className="flex-1 overflow-auto bg-[#0d1117] p-4 text-[13px] leading-[1.6]">
        <code className="text-slate-300 font-mono whitespace-pre">
          {file.content}
        </code>
      </pre>
    </div>
  );
}
