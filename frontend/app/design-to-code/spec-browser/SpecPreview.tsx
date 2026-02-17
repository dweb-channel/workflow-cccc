"use client";

import type { ComponentSpec, StyleSpec, BackgroundSpec } from "@/lib/types/design-spec";
import { resolveColor } from "@/lib/types/design-spec";

// ================================================================
// SpecPreview — Right panel showing component screenshot or CSS preview
// ================================================================

interface SpecPreviewProps {
  component: ComponentSpec;
  jobId?: string;
}

export function SpecPreview({ component, jobId }: SpecPreviewProps) {
  const hasScreenshot = !!component.screenshot_path;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-700 px-3 py-2.5">
        <span className="text-xs font-semibold text-slate-300">Preview</span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {/* Screenshot */}
        {hasScreenshot ? (
          <div className="space-y-2">
            <span className="text-[10px] text-slate-500">Screenshot</span>
            <div className="relative rounded-lg border border-slate-700 bg-slate-900 overflow-hidden">
              <img
                src={getScreenshotUrl(component.screenshot_path!, jobId)}
                alt={component.name}
                className="w-full h-auto object-contain"
                onError={(e) => {
                  // Hide broken image
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
              {/* Bounds overlay */}
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent px-2 py-1.5">
                <span className="font-mono text-[9px] text-white/70">
                  {component.bounds.width} x {component.bounds.height}
                </span>
              </div>
            </div>
          </div>
        ) : (
          /* CSS-based preview when no screenshot */
          <div className="space-y-2">
            <span className="text-[10px] text-slate-500">CSS Preview</span>
            <CSSPreview component={component} />
          </div>
        )}

        {/* Meta info */}
        <div className="space-y-1.5 border-t border-slate-700/50 pt-3">
          <MetaRow label="Node ID" value={component.id} mono />
          <MetaRow
            label="Size"
            value={`${component.bounds.width} x ${component.bounds.height}`}
            mono
          />
          <MetaRow
            label="Position"
            value={`(${component.bounds.x}, ${component.bounds.y})`}
            mono
          />
          {component.z_index != null && (
            <MetaRow label="Z-Index" value={String(component.z_index)} mono />
          )}
          {component.render_hint && component.render_hint !== "full" && (
            <MetaRow label="Render Hint" value={component.render_hint} />
          )}
          {component.sizing?.aspect_ratio && (
            <MetaRow label="Aspect Ratio" value={component.sizing.aspect_ratio} />
          )}
        </div>
      </div>
    </div>
  );
}

// ================================================================
// CSS-based preview (fallback when no screenshot)
// ================================================================

function CSSPreview({ component }: { component: ComponentSpec }) {
  const style = buildPreviewStyle(component);

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900 p-4 flex items-center justify-center min-h-[120px]">
      <div style={style} className="transition-all">
        {component.typography?.content && (
          <span className="block truncate">{component.typography.content}</span>
        )}
        {!component.typography?.content && component.content?.icon?.name && (
          <span className="text-xs text-slate-400">{component.content.icon.name}</span>
        )}
      </div>
    </div>
  );
}

function buildPreviewStyle(component: ComponentSpec): React.CSSProperties {
  const s = component.style;
  const css: React.CSSProperties = {};

  // Constrain preview to fit the panel
  const maxWidth = 220;
  const scale = Math.min(1, maxWidth / component.bounds.width);
  css.width = component.bounds.width * scale;
  css.height = component.bounds.height * scale;
  css.maxWidth = maxWidth;
  css.overflow = "hidden";

  // Background
  if (s.background) {
    if (s.background.type === "solid" && s.background.color) {
      css.backgroundColor = resolveColor(s.background.color);
    } else if (
      s.background.type === "gradient-linear" &&
      s.background.gradient?.stops
    ) {
      const stops = s.background.gradient.stops
        .map((st) => `${resolveColor(st.color)} ${(st.position * 100).toFixed(0)}%`)
        .join(", ");
      const angle = s.background.gradient.angle ?? 180;
      css.background = `linear-gradient(${angle}deg, ${stops})`;
    }
  }

  // Corner radius
  if (s.corner_radius != null) {
    if (typeof s.corner_radius === "number") {
      css.borderRadius = s.corner_radius * scale;
    } else {
      css.borderRadius = s.corner_radius.map((r) => `${r * scale}px`).join(" ");
    }
  }

  // Border
  if (s.border && s.border.width && s.border.width > 0) {
    css.borderWidth = s.border.width;
    css.borderStyle = s.border.style || "solid";
    if (s.border.color) css.borderColor = resolveColor(s.border.color);
  }

  // Opacity
  if (s.opacity != null) css.opacity = s.opacity;

  // Typography
  if (component.typography) {
    const t = component.typography;
    if (t.font_size) css.fontSize = t.font_size * scale;
    if (t.font_weight) css.fontWeight = t.font_weight;
    if (t.color) css.color = resolveColor(t.color);
    if (t.align) css.textAlign = t.align;
    if (t.line_height) css.lineHeight = `${t.line_height * scale}px`;
  }

  // Layout
  if (component.layout.type === "flex") {
    css.display = "flex";
    css.flexDirection = component.layout.direction || "column";
    if (component.layout.justify) {
      const justifyMap: Record<string, string> = {
        start: "flex-start",
        center: "center",
        end: "flex-end",
        "space-between": "space-between",
        "space-around": "space-around",
      };
      css.justifyContent = justifyMap[component.layout.justify] || component.layout.justify;
    }
    if (component.layout.align) {
      const alignMap: Record<string, string> = {
        start: "flex-start",
        center: "center",
        end: "flex-end",
        stretch: "stretch",
        baseline: "baseline",
      };
      css.alignItems = alignMap[component.layout.align] || component.layout.align;
    }
  }

  return css;
}

// ================================================================
// Helpers
// ================================================================

function getScreenshotUrl(path: string, jobId?: string): string {
  // Extract bare filename from screenshot_path (e.g. "screenshots/16650_539.png" → "16650_539.png")
  const filename = path.split("/").pop() || path;
  if (jobId) {
    return `/api/v2/design/${jobId}/screenshots/${encodeURIComponent(filename)}`;
  }
  return path;
}

function MetaRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[10px] text-slate-500">{label}</span>
      <span
        className={`text-[11px] text-slate-400 ${mono ? "font-mono" : ""}`}
      >
        {value}
      </span>
    </div>
  );
}
