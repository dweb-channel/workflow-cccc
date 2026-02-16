"use client";

import { useEffect, useState, CSSProperties } from "react";

/* ================================================================
   Design Spec Preview — Renders design_spec.json as React + inline styles.
   No Tailwind. Images use placeholder boxes.
   Purpose: validate whether the spec structure produces reasonable layout.
   ================================================================ */

// ---------- Types matching design_spec.json ----------

interface SpecBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface SpecSizing {
  width: string;
  height: string;
  aspect_ratio?: string;
}

interface SpecLayout {
  type: "stack" | "flex" | "absolute";
  direction?: "row" | "column";
  gap?: number;
  padding?: number[]; // [top, right, bottom, left]
  justify?: string;   // "start" | "center" | "end" | "space-between"
  align?: string;     // "start" | "center" | "end" | "stretch"
  overflow?: string;
}

interface SpecTypography {
  content: string;
  font_family: string;
  font_size: number;
  font_weight: number;
  line_height: number;
  align: string;
  color: string;
  letter_spacing?: number;
}

interface SpecBackground {
  type: "solid" | "image" | "none" | "gradient";
  color?: string;
  image?: { url: string; fit: string };
}

interface SpecStyle {
  background: SpecBackground;
  opacity?: number;
  border_radius?: number | string;
  corner_radius?: number | string;
  border?: { width: number; color: string; style: string };
  overflow?: string;
}

interface SpecInteraction {
  behaviors: Array<{
    trigger: string;
    action: string;
    target?: string;
  }>;
}

interface SpecNode {
  id: string;
  name: string;
  role: string;
  description: string;
  bounds: SpecBounds;
  layout: SpecLayout;
  sizing: SpecSizing;
  style: SpecStyle;
  z_index: number;
  typography?: SpecTypography;
  content?: {
    image?: { src: string; alt: string; fit: string; aspect_ratio?: string };
  };
  children?: SpecNode[];
  render_hint?: string;
  interaction?: SpecInteraction;
  screenshot_path?: string;
}

interface DesignSpec {
  version: string;
  source: { tool: string; file_key: string; file_name: string };
  page: {
    name: string;
    node_id: string;
    device: { type: string; width: number; height: number };
    layout: { type: string };
  };
  design_tokens: Record<string, unknown>;
  components: SpecNode[];
}

// ---------- Page origin (for coordinate normalization) ----------

function getPageOrigin(spec: DesignSpec): { x: number; y: number } {
  // Use the first full-width component as origin reference
  const firstFullWidth = spec.components.find(
    (c) => Math.abs(c.bounds.width - spec.page.device.width) < 1
  );
  if (firstFullWidth) {
    return { x: firstFullWidth.bounds.x, y: firstFullWidth.bounds.y };
  }
  // Fallback: min x/y
  return {
    x: Math.min(...spec.components.map((c) => c.bounds.x)),
    y: Math.min(...spec.components.map((c) => c.bounds.y)),
  };
}

// ---------- Style mapping ----------

function parseSizing(value: string): string | number {
  if (value === "fill") return "100%";
  if (value === "hug") return "auto";
  // "393px" → "393px"
  if (value.endsWith("px")) return value;
  return value;
}

function mapJustify(val: string | undefined): CSSProperties["justifyContent"] {
  if (!val) return undefined;
  const map: Record<string, string> = {
    start: "flex-start", center: "center", end: "flex-end",
    "space-between": "space-between", "space-around": "space-around",
  };
  return map[val] || val;
}

function mapAlign(val: string | undefined): CSSProperties["alignItems"] {
  if (!val) return undefined;
  const map: Record<string, string> = {
    start: "flex-start", center: "center", end: "flex-end", stretch: "stretch",
  };
  return map[val] || val;
}

function buildNodeStyle(
  node: SpecNode,
  parentOrigin: { x: number; y: number },
  parentLayoutType: "absolute" | "flex" | "stack" | "page-root",
): CSSProperties {
  const style: CSSProperties = {};

  // Sizing
  const w = parseSizing(node.sizing.width);
  const h = parseSizing(node.sizing.height);
  if (w !== "auto") style.width = w;
  if (h !== "auto") style.height = h;

  // Position: determined by PARENT's layout type, not this node's
  if (parentLayoutType === "absolute" || parentLayoutType === "page-root") {
    style.position = "absolute";
    style.left = node.bounds.x - parentOrigin.x;
    style.top = node.bounds.y - parentOrigin.y;
  }
  // In flex/stack parent: node flows normally (no absolute positioning)

  // Z-index
  if (node.z_index !== undefined) {
    style.zIndex = node.z_index;
  }

  // This node's layout describes how IT lays out its children
  if (node.layout.type === "flex") {
    style.display = "flex";
    style.flexDirection = node.layout.direction || "column";
    if (node.layout.gap) style.gap = node.layout.gap;
    style.justifyContent = mapJustify(node.layout.justify);
    style.alignItems = mapAlign(node.layout.align);
  } else if (node.layout.type === "stack") {
    style.display = "flex";
    style.flexDirection = "column";
    if (node.layout.gap) style.gap = node.layout.gap;
  } else if (node.layout.type === "absolute") {
    // Container for absolutely positioned children
    style.position = style.position || "relative";
  }

  // Background
  const bg = node.style.background;
  if (bg.type === "solid" && bg.color) {
    style.backgroundColor = bg.color;
  } else if (bg.type === "image") {
    style.backgroundColor = "#d1d5db";
  }

  // Opacity
  if (node.style.opacity !== undefined) {
    style.opacity = node.style.opacity;
  }

  // Border radius (spec may use corner_radius or border_radius)
  const br = node.style.corner_radius ?? node.style.border_radius;
  if (br) {
    style.borderRadius = br as number;
  }

  // Border
  if (node.style.border) {
    style.border = `${node.style.border.width}px ${node.style.border.style || "solid"} ${node.style.border.color}`;
  }

  // Overflow (from style or layout)
  const overflow = node.style.overflow || node.layout.overflow;
  if (overflow && overflow !== "visible") {
    style.overflow = overflow as CSSProperties["overflow"];
  }

  // Padding: array [top, right, bottom, left]
  if (node.layout.padding) {
    const p = node.layout.padding;
    if (Array.isArray(p)) {
      if (p[0]) style.paddingTop = p[0];
      if (p[1]) style.paddingRight = p[1];
      if (p[2]) style.paddingBottom = p[2];
      if (p[3]) style.paddingLeft = p[3];
    }
  }

  // Flex sizing hints
  if (node.sizing.width === "fill") {
    style.flex = 1;
    style.width = undefined;
  }

  return style;
}

function buildTypographyStyle(typo: SpecTypography): CSSProperties {
  return {
    fontFamily: typo.font_family || "inherit",
    fontSize: typo.font_size,
    fontWeight: typo.font_weight,
    lineHeight: `${typo.line_height}px`,
    textAlign: typo.align as CSSProperties["textAlign"],
    color: typo.color,
    letterSpacing: typo.letter_spacing,
    margin: 0,
  };
}

// ---------- Recursive renderer ----------

function SpecNodeRenderer({
  node,
  parentOrigin,
  parentLayoutType = "page-root",
  depth = 0,
}: {
  node: SpecNode;
  parentOrigin: { x: number; y: number };
  parentLayoutType?: "absolute" | "flex" | "stack" | "page-root";
  depth?: number;
}) {
  // Spacer: render as empty fixed-height div, skip children
  if (node.render_hint === "spacer") {
    const isAbsPos = parentLayoutType === "absolute" || parentLayoutType === "page-root";
    return (
      <div
        data-spec-id={node.id}
        data-spec-role="spacer"
        style={{
          width: parseSizing(node.sizing.width),
          height: parseSizing(node.sizing.height),
          position: isAbsPos ? "absolute" : undefined,
          left: isAbsPos ? node.bounds.x - parentOrigin.x : undefined,
          top: isAbsPos ? node.bounds.y - parentOrigin.y : undefined,
          zIndex: node.z_index,
        }}
      />
    );
  }

  const nodeStyle = buildNodeStyle(node, parentOrigin, parentLayoutType);

  // This node's layout.type determines how children are positioned
  const childLayoutType = node.layout.type;

  // Image role: render placeholder
  if (
    node.role === "image" ||
    node.style.background.type === "image"
  ) {
    const alt =
      node.content?.image?.alt || node.description?.slice(0, 40) || node.name;
    return (
      <div
        data-spec-id={node.id}
        data-spec-role={node.role}
        data-spec-name={node.name}
        style={{
          ...nodeStyle,
          backgroundColor: "#e5e7eb",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        <span
          style={{
            fontSize: 10,
            color: "#9ca3af",
            textAlign: "center",
            padding: 4,
            wordBreak: "break-all",
          }}
        >
          {alt}
        </span>
        {node.children?.map((child) => (
          <SpecNodeRenderer
            key={child.id}
            node={child}
            parentOrigin={node.bounds}
            parentLayoutType={childLayoutType}
            depth={depth + 1}
          />
        ))}
      </div>
    );
  }

  // Text role with typography
  if (node.typography) {
    const typoStyle = buildTypographyStyle(node.typography);
    return (
      <div
        data-spec-id={node.id}
        data-spec-role={node.role}
        data-spec-name={node.name}
        style={{ ...nodeStyle, ...typoStyle }}
      >
        {node.typography.content}
      </div>
    );
  }

  // Decorative: render as colored box
  if (node.role === "decorative") {
    return (
      <div
        data-spec-id={node.id}
        data-spec-role="decorative"
        data-spec-name={node.name}
        style={nodeStyle}
      />
    );
  }

  // Container/section/header/nav/list/button/icon/other: render with children
  return (
    <div
      data-spec-id={node.id}
      data-spec-role={node.role}
      data-spec-name={node.name}
      style={nodeStyle}
    >
      {node.children?.map((child) => (
        <SpecNodeRenderer
          key={child.id}
          node={child}
          parentOrigin={node.bounds}
          parentLayoutType={childLayoutType}
          depth={depth + 1}
        />
      ))}
    </div>
  );
}

// ---------- Main Preview Page ----------

export default function DesignPreviewPage() {
  const [spec, setSpec] = useState<DesignSpec | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showOutlines, setShowOutlines] = useState(false);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  useEffect(() => {
    fetch("/spec-data/design_spec.json")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => setSpec(data))
      .catch((err) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div style={{ padding: 40, fontFamily: "system-ui", color: "#ef4444" }}>
        Failed to load spec: {error}
      </div>
    );
  }

  if (!spec) {
    return (
      <div style={{ padding: 40, fontFamily: "system-ui", color: "#6b7280" }}>
        Loading design spec...
      </div>
    );
  }

  const pageOrigin = getPageOrigin(spec);
  const { width: pageWidth, height: pageHeight } = spec.page.device;

  // Calculate actual content height (max bottom edge of all components)
  const contentHeight = Math.max(
    pageHeight,
    ...spec.components.map(
      (c) => c.bounds.y - pageOrigin.y + c.bounds.height
    )
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: "#1e1e1e",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "32px 16px",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      {/* Controls */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 24,
          color: "#9ca3af",
          fontSize: 13,
        }}
      >
        <span style={{ color: "#e5e7eb", fontWeight: 600, fontSize: 15 }}>
          Spec Preview: {spec.page.name}
        </span>
        <span>
          {pageWidth}x{pageHeight} ({spec.page.device.type})
        </span>
        <span>{spec.components.length} components</span>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={showOutlines}
            onChange={(e) => setShowOutlines(e.target.checked)}
          />
          Show outlines
        </label>
      </div>

      {/* Phone frame */}
      <div
        style={{
          width: pageWidth,
          height: contentHeight,
          position: "relative",
          backgroundColor: "#ffffff",
          overflow: "hidden",
          borderRadius: 20,
          boxShadow: "0 25px 50px rgba(0,0,0,0.5)",
        }}
        onMouseOver={(e) => {
          const target = (e.target as HTMLElement).closest("[data-spec-id]");
          if (target) setHoveredNode(target.getAttribute("data-spec-id"));
        }}
        onMouseOut={() => setHoveredNode(null)}
      >
        {/* Outline overlay styles */}
        {showOutlines && (
          <style>{`
            [data-spec-role] {
              outline: 1px dashed rgba(99, 102, 241, 0.4);
            }
            [data-spec-role="header"] { outline-color: rgba(34, 197, 94, 0.6); }
            [data-spec-role="section"] { outline-color: rgba(59, 130, 246, 0.6); }
            [data-spec-role="nav"] { outline-color: rgba(249, 115, 22, 0.6); }
            [data-spec-role="button"] { outline-color: rgba(236, 72, 153, 0.6); }
            [data-spec-role="text"] { outline-color: rgba(139, 92, 246, 0.5); }
            [data-spec-role="image"] { outline-color: rgba(6, 182, 212, 0.5); }
            [data-spec-role="list"] { outline-color: rgba(234, 179, 8, 0.6); }
            [data-spec-role="list-item"] { outline-color: rgba(234, 179, 8, 0.4); }
            [data-spec-role="icon"] { outline-color: rgba(168, 85, 247, 0.5); }
          `}</style>
        )}

        {/* Render all top-level components (page is absolute layout) */}
        {spec.components.map((node) => (
          <SpecNodeRenderer
            key={node.id}
            node={node}
            parentOrigin={pageOrigin}
            parentLayoutType="page-root"
          />
        ))}
      </div>

      {/* Hover info tooltip */}
      {hoveredNode && (
        <div
          style={{
            position: "fixed",
            bottom: 16,
            left: "50%",
            transform: "translateX(-50%)",
            backgroundColor: "rgba(0,0,0,0.85)",
            color: "#e5e7eb",
            padding: "8px 16px",
            borderRadius: 8,
            fontSize: 12,
            fontFamily: "monospace",
            zIndex: 9999,
            maxWidth: 500,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {(() => {
            const node = findNodeById(spec.components, hoveredNode);
            if (!node) return hoveredNode;
            return `[${node.role}] ${node.name} — ${node.sizing.width}x${node.sizing.height} — ${node.description?.slice(0, 60) || ""}`;
          })()}
        </div>
      )}

      {/* Legend */}
      {showOutlines && (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            marginTop: 20,
            fontSize: 11,
            color: "#9ca3af",
          }}
        >
          {[
            { role: "header", color: "rgba(34, 197, 94, 0.8)" },
            { role: "section", color: "rgba(59, 130, 246, 0.8)" },
            { role: "nav", color: "rgba(249, 115, 22, 0.8)" },
            { role: "button", color: "rgba(236, 72, 153, 0.8)" },
            { role: "text", color: "rgba(139, 92, 246, 0.7)" },
            { role: "image", color: "rgba(6, 182, 212, 0.7)" },
            { role: "list", color: "rgba(234, 179, 8, 0.8)" },
            { role: "icon", color: "rgba(168, 85, 247, 0.7)" },
          ].map((item) => (
            <span key={item.role} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  border: `2px dashed ${item.color}`,
                  display: "inline-block",
                }}
              />
              {item.role}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Utility: find node by ID in tree ----------

function findNodeById(nodes: SpecNode[], id: string): SpecNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    if (node.children) {
      const found = findNodeById(node.children, id);
      if (found) return found;
    }
  }
  return null;
}
