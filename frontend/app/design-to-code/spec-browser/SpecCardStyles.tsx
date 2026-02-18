import type { StyleSpec, ColorValue } from "@/lib/types/design-spec";
import { isTokenColor, resolveColor } from "@/lib/types/design-spec";

// ================================================================
// ColorDisplay — shared inline color swatch + hex + optional token
// ================================================================

export function ColorDisplay({ value }: { value: ColorValue }) {
  const hex = resolveColor(value);
  const token = isTokenColor(value) ? value.token : undefined;

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block h-3 w-3 shrink-0 rounded border border-slate-600"
        style={{ backgroundColor: hex }}
      />
      <span>{hex}</span>
      {token && (
        <span className="rounded bg-violet-500/15 px-1 py-0.5 text-[9px] text-violet-400">
          {token}
        </span>
      )}
    </span>
  );
}

// ================================================================
// StyleSection
// ================================================================

export function StyleSection({ style }: { style: StyleSpec }) {
  const BORDER_STYLE_ZH: Record<string, string> = {
    solid: "实线", dashed: "虚线", dotted: "点线", none: "无",
  };
  const BORDER_SIDES_ZH: Record<string, string> = {
    all: "四边", top: "上", bottom: "下", left: "左", right: "右",
    "top-bottom": "上下", "left-right": "左右",
  };

  const lines: Array<{ text: string; color?: string }> = [];

  // Background
  if (style.background) {
    const bg = style.background;
    if (bg.type === "none") {
      lines.push({ text: "背景: 透明" });
    } else if (bg.type === "solid" && bg.color) {
      const hex = resolveColor(bg.color);
      lines.push({ text: `背景: ${hex}`, color: hex });
    } else if (bg.type === "gradient-linear" && bg.gradient) {
      const stops = bg.gradient.stops?.map((s) => resolveColor(s.color)).join(" → ") || "";
      lines.push({ text: `背景: 线性渐变 ${bg.gradient.angle ?? 0}° ${stops}` });
    } else if (bg.type === "gradient-radial" && bg.gradient) {
      const stops = bg.gradient.stops?.map((s) => resolveColor(s.color)).join(" → ") || "";
      lines.push({ text: `背景: 径向渐变 ${stops}` });
    } else if (bg.type === "image") {
      const fit = bg.image?.fit ? ` (${bg.image.fit})` : "";
      lines.push({ text: `背景: 图片${fit}` });
    }
  }

  // Border
  if (style.border && style.border.width != null && style.border.width > 0) {
    const b = style.border;
    const parts: string[] = [`${b.width}px`];
    if (b.style) parts.push(BORDER_STYLE_ZH[b.style] || b.style);
    if (b.color) parts.push(resolveColor(b.color));
    if (b.sides && b.sides !== "all") parts.push(BORDER_SIDES_ZH[b.sides] || b.sides);
    const hex = b.color ? resolveColor(b.color) : undefined;
    lines.push({ text: `边框: ${parts.join(" ")}`, color: hex });
  }

  // Corner radius
  if (style.corner_radius != null) {
    const cr = style.corner_radius;
    if (typeof cr === "number") {
      if (cr > 0) lines.push({ text: `圆角: ${cr}px` });
    } else {
      const unique = [...new Set(cr)];
      if (unique.length === 1 && unique[0] > 0) {
        lines.push({ text: `圆角: ${unique[0]}px` });
      } else if (cr.some((v) => v > 0)) {
        lines.push({ text: `圆角: 左上${cr[0]} 右上${cr[1]} 右下${cr[2]} 左下${cr[3]}px` });
      }
    }
  }

  // Shadow
  if (style.shadow && style.shadow.length > 0) {
    for (const s of style.shadow) {
      const type = s.type === "inner" ? "内阴影" : "阴影";
      const parts = [`x=${s.x ?? 0}`, `y=${s.y ?? 0}`, `模糊=${s.blur ?? 0}`];
      if (s.spread) parts.push(`扩展=${s.spread}`);
      const hex = s.color ? resolveColor(s.color) : undefined;
      if (hex) parts.push(hex);
      lines.push({ text: `${type}: ${parts.join(" ")}`, color: hex });
    }
  }

  // Opacity
  if (style.opacity != null && style.opacity !== 1) {
    lines.push({ text: `透明度: ${Math.round(style.opacity * 100)}%` });
  }

  // Blur
  if (style.blur) {
    const type = style.blur.type === "background" ? "背景模糊" : "模糊";
    lines.push({ text: `${type}: ${style.blur.radius || 0}px` });
  }

  return (
    <div className="space-y-0.5">
      {lines.map((line, i) => (
        <div key={`style-${i}`} className="flex items-center gap-1.5 text-[11px] text-slate-300">
          {line.color && (
            <span
              className="inline-block h-3 w-3 shrink-0 rounded border border-slate-600"
              style={{ backgroundColor: line.color }}
            />
          )}
          <span>{line.text}</span>
        </div>
      ))}
      {lines.length === 0 && (
        <div className="text-[11px] text-slate-500">无样式</div>
      )}
    </div>
  );
}
