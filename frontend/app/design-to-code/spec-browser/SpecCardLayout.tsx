import type { LayoutSpec, SizingSpec } from "@/lib/types/design-spec";
import { resolveSpacing } from "@/lib/types/design-spec";

// ================================================================
// LayoutSection
// ================================================================

export function LayoutSection({ layout }: { layout: LayoutSpec }) {
  const DIRECTION_ZH: Record<string, string> = { row: "水平排列", column: "纵向排列" };
  const JUSTIFY_ZH: Record<string, string> = {
    start: "靠前", center: "居中", end: "靠后",
    "space-between": "两端对齐", "space-around": "均匀分布",
  };
  const ALIGN_ZH: Record<string, string> = {
    start: "顶部对齐", center: "居中对齐", end: "底部对齐",
    stretch: "拉伸", baseline: "基线对齐",
  };

  const lines: string[] = [];
  if (layout.type === "flex") {
    const dir = DIRECTION_ZH[layout.direction || "row"] || layout.direction || "水平排列";
    lines.push(dir);
    if (layout.gap != null) {
      lines[0] += `，间距 ${resolveSpacing(layout.gap)}px`;
    }
    if (layout.justify && layout.justify !== "start") {
      lines.push(`主轴: ${JUSTIFY_ZH[layout.justify] || layout.justify}`);
    }
    if (layout.align && layout.align !== "start") {
      lines.push(`交叉轴: ${ALIGN_ZH[layout.align] || layout.align}`);
    }
  } else if (layout.type === "absolute") {
    lines.push("绝对定位");
  } else if (layout.type === "grid") {
    lines.push("网格布局");
  } else if (layout.type === "stack") {
    lines.push("层叠布局");
  } else if (layout.type) {
    lines.push(layout.type);
  }

  if (layout.padding) {
    const p = layout.padding.map((v) => resolveSpacing(v));
    if (p.some((v) => v !== 0)) {
      const unique = [...new Set(p)];
      if (unique.length === 1) {
        lines.push(`内边距: ${unique[0]}px`);
      } else {
        lines.push(`内边距: 上${p[0]} 右${p[1]} 下${p[2]} 左${p[3]}px`);
      }
    }
  }
  if (layout.wrap) lines.push("允许换行");
  if (layout.overflow && layout.overflow !== "visible") lines.push(`溢出: ${layout.overflow === "hidden" ? "隐藏" : "滚动"}`);

  return (
    <div className="space-y-0.5">
      {lines.map((line, i) => (
        <div key={i} className="text-[11px] text-slate-300">{line}</div>
      ))}
    </div>
  );
}

// ================================================================
// SizingSection
// ================================================================

export function SizingSection({ sizing }: { sizing: SizingSpec }) {
  const SIZING_ZH: Record<string, string> = {
    fill: "撑满父容器",
    "fill_container": "撑满父容器",
    hug: "自适应内容",
    "hug_contents": "自适应内容",
  };

  function humanize(v: string | undefined): string {
    if (!v) return "";
    for (const [key, zh] of Object.entries(SIZING_ZH)) {
      if (v.toLowerCase().includes(key.toLowerCase())) return zh;
    }
    return v;
  }

  const lines: string[] = [];
  if (sizing.width) lines.push(`宽度: ${humanize(sizing.width)}`);
  if (sizing.height) lines.push(`高度: ${humanize(sizing.height)}`);
  if (sizing.min_width != null) lines.push(`最小宽度: ${sizing.min_width}px`);
  if (sizing.max_width != null) lines.push(`最大宽度: ${sizing.max_width}px`);
  if (sizing.min_height != null) lines.push(`最小高度: ${sizing.min_height}px`);
  if (sizing.max_height != null) lines.push(`最大高度: ${sizing.max_height}px`);
  if (sizing.aspect_ratio) lines.push(`宽高比: ${sizing.aspect_ratio}`);

  return (
    <div className="space-y-0.5">
      {lines.map((line, i) => (
        <div key={i} className="text-[11px] text-slate-300">{line}</div>
      ))}
    </div>
  );
}
