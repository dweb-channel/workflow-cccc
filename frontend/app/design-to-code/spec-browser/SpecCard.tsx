"use client";

import { useState } from "react";
import type {
  ComponentSpec,
  ColorValue,
  LayoutSpec,
  SizingSpec,
  StyleSpec,
  TypographySpec,
  ContentSpec,
  InteractionSpec,
} from "@/lib/types/design-spec";
import { isTokenColor, resolveColor, resolveSpacing } from "@/lib/types/design-spec";
import { ChevronDown, ChevronRight, ArrowRight, Copy, Check } from "lucide-react";

// ================================================================
// SpecCard — Displays full ComponentSpec details in collapsible sections
// ================================================================

interface SpecCardProps {
  component: ComponentSpec;
  onNavigate?: (id: string) => void;
}

export function SpecCard({ component, onNavigate }: SpecCardProps) {
  const isSpacer = component.render_hint === "spacer";
  const isPlatform = component.render_hint === "platform";
  const [copied, setCopied] = useState(false);

  const handleCopySpec = async () => {
    const text = formatComponentSpec(component);
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
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      {/* Component header */}
      <div className="sticky top-0 z-10 border-b border-slate-700 bg-slate-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-white truncate">
            {component.name}
          </h2>
          <RoleBadge role={component.role} />
          {(isSpacer || isPlatform) && (
            <span className="rounded bg-slate-600 px-1.5 py-0.5 text-[10px] text-slate-300">
              {isSpacer ? "Spacer" : "Platform"}
            </span>
          )}
          {component.z_index != null && (
            <span className="rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-400">
              z-index: {component.z_index}
            </span>
          )}
          <div className="flex-1" />
          <button
            onClick={handleCopySpec}
            className="flex items-center gap-1 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[10px] text-violet-300 hover:bg-violet-500/20 transition-colors shrink-0"
            title="复制该组件 Spec（适合粘贴给 LLM）"
          >
            {copied ? (
              <><Check className="h-3 w-3 text-green-400" /> 已复制</>
            ) : (
              <><Copy className="h-3 w-3" /> 复制 Spec</>
            )}
          </button>
        </div>
        {component.description && (
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
            {component.description}
          </p>
        )}
        {/* Bounds */}
        <div className="mt-1.5 flex gap-3 text-[10px] text-slate-500 font-mono">
          <span>x:{Math.round(component.bounds.x)} y:{Math.round(component.bounds.y)}</span>
          <span>{Math.round(component.bounds.width)} x {Math.round(component.bounds.height)}</span>
          <span>id: {component.id}</span>
        </div>

        {/* Quality indicators */}
        <QualityIndicators component={component} />
      </div>

      {/* Sections */}
      <div className="flex-1 p-2 space-y-1">
        {component.design_analysis && (
          <Section title="设计解读" icon="analysis" defaultOpen>
            <DesignAnalysisSection text={component.design_analysis} />
          </Section>
        )}

        <Section title="布局" icon="layout" defaultOpen>
          <LayoutSection layout={component.layout} />
        </Section>

        {component.sizing && (
          <Section title="尺寸约束" icon="sizing" defaultOpen>
            <SizingSection sizing={component.sizing} />
          </Section>
        )}

        <Section title="样式" icon="style" defaultOpen>
          <StyleSection style={component.style} />
        </Section>

        {component.typography && !isSpacer && (
          <Section title="文字" icon="typography">
            <TypographySection typography={component.typography} />
          </Section>
        )}

        {component.content && !isSpacer && (
          <Section title="内容" icon="content">
            <ContentSection content={component.content} />
          </Section>
        )}

        {component.interaction && !isSpacer && (
          <Section title="交互" icon="interaction">
            <InteractionSection interaction={component.interaction} />
          </Section>
        )}

        {component.children && component.children.length > 0 && (
          <Section title={`子组件 (${component.children.length})`} icon="children">
            <ChildrenSection children={component.children} onNavigate={onNavigate} />
          </Section>
        )}

        {component.children_collapsed != null && component.children_collapsed > 0 && (
          <div className="rounded-lg border border-slate-700/50 bg-slate-800/50 px-3 py-2">
            <span className="text-[11px] text-slate-500">
              {component.children_collapsed} 个子节点已折叠（骨架层）
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ================================================================
// Quality Indicators — per-component header metrics
// ================================================================

function QualityIndicators({ component }: { component: ComponentSpec }) {
  // Count descendant description coverage
  let totalDesc = 0;
  let filledDesc = 0;
  function walkDesc(node: ComponentSpec) {
    if (node.children) {
      for (const child of node.children) {
        totalDesc++;
        if (child.description && child.description.trim()) filledDesc++;
        walkDesc(child);
      }
    }
  }
  walkDesc(component);

  const hasAnalysis = !!component.design_analysis;
  const hasInteraction = !!(component.interaction?.behaviors?.length || component.interaction?.states?.length);
  const coveragePercent = totalDesc > 0 ? Math.round((filledDesc / totalDesc) * 100) : null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {/* Design analysis indicator */}
      <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] ${
        hasAnalysis ? "bg-emerald-500/10 text-emerald-400" : "bg-slate-700/50 text-slate-500"
      }`}>
        {hasAnalysis ? "\u2713" : "\u2717"} 设计解读
      </span>

      {/* Interaction indicator */}
      {hasInteraction && (
        <span className="inline-flex items-center gap-1 rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] text-orange-400">
          \u2713 交互
        </span>
      )}

      {/* Children description coverage */}
      {coveragePercent !== null && (
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] ${
          coveragePercent >= 80
            ? "bg-emerald-500/10 text-emerald-400"
            : coveragePercent >= 50
              ? "bg-yellow-500/10 text-yellow-400"
              : "bg-red-500/10 text-red-400"
        }`}>
          <span className="font-mono">{filledDesc}/{totalDesc}</span> 子描述
          <span className="ml-0.5 inline-block h-1 w-8 rounded-full bg-slate-700 overflow-hidden">
            <span
              className={`block h-full rounded-full ${
                coveragePercent >= 80
                  ? "bg-emerald-500"
                  : coveragePercent >= 50
                    ? "bg-yellow-500"
                    : "bg-red-500"
              }`}
              style={{ width: `${coveragePercent}%` }}
            />
          </span>
        </span>
      )}

      {/* Role "other" warning */}
      {component.role === "other" && (
        <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-400">
          ⚠ role=other
        </span>
      )}
    </div>
  );
}

// ================================================================
// Collapsible Section
// ================================================================

const SECTION_ICONS: Record<string, string> = {
  analysis: "\uD83D\uDCA1",
  layout: "\uD83D\uDCD0",
  sizing: "\uD83D\uDCCF",
  style: "\uD83C\uDFA8",
  typography: "\uD83D\uDCDD",
  content: "\uD83D\uDDBC\uFE0F",
  interaction: "\uD83D\uDD04",
  children: "\uD83D\uDD17",
};

function Section({
  title,
  icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/50">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-700/30 transition-colors"
      >
        <span className="text-xs">{SECTION_ICONS[icon] || "\u2699\uFE0F"}</span>
        <span className="text-xs font-medium text-slate-200">{title}</span>
        <span className="ml-auto text-slate-500">
          {open ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      </button>
      {open && <div className="border-t border-slate-700/50 px-3 py-2">{children}</div>}
    </div>
  );
}

// ================================================================
// Section content renderers
// ================================================================

function LayoutSection({ layout }: { layout: LayoutSpec }) {
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

function SizingSection({ sizing }: { sizing: SizingSpec }) {
  const SIZING_ZH: Record<string, string> = {
    fill: "撑满父容器",
    "fill_container": "撑满父容器",
    hug: "自适应内容",
    "hug_contents": "自适应内容",
  };

  function humanize(v: string | undefined): string {
    if (!v) return "";
    // Check for known keywords
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

function StyleSection({ style }: { style: StyleSpec }) {
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
        <div key={i} className="flex items-center gap-1.5 text-[11px] text-slate-300">
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

function TypographySection({ typography }: { typography: TypographySpec }) {
  const WEIGHT_NAMES: Record<number, string> = {
    100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Regular",
    500: "Medium", 600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black",
  };
  const ALIGN_ZH: Record<string, string> = {
    left: "左对齐", center: "居中", right: "右对齐", justify: "两端对齐",
  };
  const DECORATION_ZH: Record<string, string> = {
    underline: "下划线", strikethrough: "删除线",
  };
  const TRANSFORM_ZH: Record<string, string> = {
    uppercase: "全大写", lowercase: "全小写", capitalize: "首字母大写",
  };
  const OVERFLOW_ZH: Record<string, string> = {
    ellipsis: "省略号截断", clip: "裁剪", visible: "可见",
  };

  // Build a compact one-line font summary: "PingFang SC Medium 14px/20px #333333"
  const fontParts: string[] = [];
  if (typography.font_family) fontParts.push(typography.font_family);
  if (typography.font_weight != null) fontParts.push(WEIGHT_NAMES[typography.font_weight] || String(typography.font_weight));
  if (typography.font_size != null) {
    let sizeStr = `${typography.font_size}px`;
    if (typography.line_height != null) sizeStr += `/${typography.line_height}px`;
    fontParts.push(sizeStr);
  }

  const details: string[] = [];
  if (typography.letter_spacing != null && typography.letter_spacing !== 0) {
    details.push(`字间距 ${typography.letter_spacing}px`);
  }
  if (typography.align) details.push(ALIGN_ZH[typography.align] || typography.align);
  if (typography.decoration && typography.decoration !== "none") {
    details.push(DECORATION_ZH[typography.decoration] || typography.decoration);
  }
  if (typography.transform && typography.transform !== "none") {
    details.push(TRANSFORM_ZH[typography.transform] || typography.transform);
  }
  if (typography.overflow) details.push(OVERFLOW_ZH[typography.overflow] || typography.overflow);
  if (typography.max_lines != null) details.push(`最多 ${typography.max_lines} 行`);

  return (
    <div className="space-y-1.5">
      {/* Text content preview */}
      {typography.content && (
        <div className="rounded bg-slate-900 px-2 py-1.5">
          <span className="text-[11px] text-slate-300">
            &ldquo;{typography.content}&rdquo;
          </span>
        </div>
      )}
      {/* Font summary line */}
      {fontParts.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-300">{fontParts.join(" ")}</span>
          {typography.color && <ColorDisplay value={typography.color} />}
        </div>
      )}
      {/* Additional details */}
      {details.length > 0 && (
        <div className="text-[11px] text-slate-400">{details.join("  |  ")}</div>
      )}
    </div>
  );
}

function ContentSection({ content }: { content: ContentSpec }) {
  const FIT_ZH: Record<string, string> = {
    cover: "裁剪填充", contain: "完整显示", fill: "拉伸填充", none: "原始尺寸",
  };
  const PLACEHOLDER_ZH: Record<string, string> = {
    blur: "模糊占位", color: "色块占位", skeleton: "骨架屏", none: "无占位",
  };

  return (
    <div className="space-y-2">
      {content.image && (
        <div className="space-y-1">
          <span className="text-[10px] font-medium text-slate-400">图片</span>
          {content.image.alt && (
            <div className="text-[11px] text-slate-300">描述: {content.image.alt}</div>
          )}
          {content.image.src && (
            <div className="text-[10px] text-slate-500 truncate">来源: {content.image.src}</div>
          )}
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-400">
            {content.image.fit && <span>{FIT_ZH[content.image.fit] || content.image.fit}</span>}
            {content.image.aspect_ratio && <span>比例 {content.image.aspect_ratio}</span>}
            {content.image.placeholder && (
              <span>{PLACEHOLDER_ZH[content.image.placeholder] || content.image.placeholder}</span>
            )}
          </div>
        </div>
      )}
      {content.icon && (
        <div className="space-y-1">
          <span className="text-[10px] font-medium text-slate-400">图标</span>
          <div className="flex items-center gap-2 text-[11px] text-slate-300">
            {content.icon.name && <span>{content.icon.name}</span>}
            {content.icon.size != null && <span>{content.icon.size}px</span>}
            {content.icon.color && <ColorDisplay value={content.icon.color} />}
          </div>
        </div>
      )}
    </div>
  );
}

function InteractionSection({ interaction }: { interaction: InteractionSpec }) {
  const TRIGGER_ZH: Record<string, string> = {
    click: "点击", hover: "悬停", focus: "聚焦",
    scroll: "滚动", load: "加载时", swipe: "滑动",
  };

  return (
    <div className="space-y-2">
      {interaction.behaviors && interaction.behaviors.length > 0 && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">行为</span>
          {interaction.behaviors.map((b, i) => (
            <div key={i} className="mt-1 rounded bg-slate-900 px-2 py-1.5 text-[11px]">
              <span className="text-orange-400">{TRIGGER_ZH[b.trigger || "click"] || b.trigger}</span>
              <span className="text-slate-500"> → </span>
              <span className="text-slate-300">{b.action}</span>
              {b.target && (
                <span className="ml-1 text-slate-500">({b.target})</span>
              )}
            </div>
          ))}
        </div>
      )}
      {interaction.states && interaction.states.length > 0 && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">状态变化</span>
          {interaction.states.map((s, i) => (
            <div key={i} className="mt-1 rounded bg-slate-900 px-2 py-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-violet-400">{s.name}</span>
                {s.description && (
                  <span className="text-[10px] text-slate-500">{s.description}</span>
                )}
              </div>
              {s.style_overrides && (
                <pre className="mt-1 text-[10px] text-slate-500 font-mono overflow-x-auto">
                  {JSON.stringify(s.style_overrides, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
      {interaction.transitions && interaction.transitions.length > 0 && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">过渡动画</span>
          {interaction.transitions.map((t, i) => (
            <div key={i} className="mt-1 text-[11px] text-slate-400">
              {t.property} {t.duration_ms}ms {t.easing || "ease"}
            </div>
          ))}
        </div>
      )}
      {interaction.raw_notes && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">备注</span>
          <p className="mt-1 text-[11px] text-slate-500 italic">{interaction.raw_notes}</p>
        </div>
      )}
    </div>
  );
}

function DesignAnalysisSection({ text }: { text: string }) {
  const lines = text.split("\n");

  return (
    <div className="space-y-1 text-[11px] leading-relaxed text-slate-300">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} className="h-1" />;

        // ## Header
        if (trimmed.startsWith("## ")) {
          return (
            <div key={i} className="font-semibold text-white text-[12px] mt-2 first:mt-0">
              {renderInline(trimmed.slice(3))}
            </div>
          );
        }
        // ### Sub-header
        if (trimmed.startsWith("### ")) {
          return (
            <div key={i} className="font-medium text-slate-200 text-[11px] mt-1.5">
              {renderInline(trimmed.slice(4))}
            </div>
          );
        }
        // - List item (unordered)
        if (trimmed.startsWith("- ")) {
          return (
            <div key={i} className="flex gap-1.5 pl-2">
              <span className="text-slate-500 shrink-0">•</span>
              <span>{renderInline(trimmed.slice(2))}</span>
            </div>
          );
        }
        // 1. Numbered list item
        const numberedMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
        if (numberedMatch) {
          return (
            <div key={i} className="flex gap-1.5 pl-2">
              <span className="text-slate-500 shrink-0 tabular-nums">{numberedMatch[1]}.</span>
              <span>{renderInline(numberedMatch[2])}</span>
            </div>
          );
        }
        // Regular line
        return <div key={i}>{renderInline(trimmed)}</div>;
      })}
    </div>
  );
}

/** Render inline formatting: **bold** and `code` */
function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  if (parts.length === 1) return text;
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="text-white font-medium">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={i} className="rounded bg-slate-700/80 px-1 py-0.5 text-[10px] font-mono text-emerald-400">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

function ChildrenSection({
  children,
  onNavigate,
}: {
  children: ComponentSpec[];
  onNavigate?: (id: string) => void;
}) {
  const ROLE_NAMES_ZH: Record<string, string> = {
    page: "页面", section: "区块", container: "容器", nav: "导航",
    header: "头部", footer: "底部", button: "按钮", input: "输入框",
    card: "卡片", list: "列表", "list-item": "列表项", image: "图片",
    icon: "图标", text: "文本", badge: "徽章", divider: "分割线",
    overlay: "遮罩", decorative: "装饰",
  };
  const genericNames = new Set(["Frame", "Rectangle", "Group", "Vector", "Ellipse", "Line", "Component"]);

  function getChildDisplayName(child: ComponentSpec): string {
    if (child.name && !genericNames.has(child.name)) return child.name;
    const roleZh = ROLE_NAMES_ZH[child.role] || child.role;
    return `${roleZh} ${Math.round(child.bounds.width)}×${Math.round(child.bounds.height)}`;
  }

  return (
    <div className="space-y-0.5">
      {children.map((child) => (
        <button
          key={child.id}
          onClick={() => onNavigate?.(child.id)}
          className="group flex w-full flex-col gap-0.5 rounded-md px-2 py-1.5 text-left hover:bg-violet-500/10 border border-transparent hover:border-violet-500/20 transition-colors"
        >
          <div className="flex items-center gap-1.5 w-full">
            <span className="text-[11px] text-slate-300 truncate flex-1 group-hover:text-white transition-colors">
              {getChildDisplayName(child)}
            </span>
            <RoleBadge role={child.role} small />
            <ArrowRight className="h-3 w-3 text-slate-600 group-hover:text-violet-400 transition-colors" />
          </div>
          {child.description && (
            <div className="text-[10px] text-slate-500 truncate leading-tight">
              {child.description.slice(0, 80)}{child.description.length > 80 ? "..." : ""}
            </div>
          )}
          <div className="flex items-center gap-2 text-[10px] font-mono text-slate-500">
            <span>{Math.round(child.bounds.width)} × {Math.round(child.bounds.height)}</span>
            {child.children && child.children.length > 0 && (
              <span className="text-slate-600">{child.children.length} 子组件</span>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}

// ================================================================
// Shared display components
// ================================================================

function ColorDisplay({ value }: { value: ColorValue }) {
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

function RoleBadge({ role, small }: { role: string; small?: boolean }) {
  const ROLE_COLORS: Record<string, { bg: string; text: string }> = {
    page: { bg: "rgba(139,92,246,0.15)", text: "#a78bfa" },
    section: { bg: "rgba(139,92,246,0.12)", text: "#a78bfa" },
    container: { bg: "rgba(100,116,139,0.15)", text: "#94a3b8" },
    nav: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
    header: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
    footer: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
    button: { bg: "rgba(249,115,22,0.12)", text: "#fb923c" },
    input: { bg: "rgba(249,115,22,0.12)", text: "#fb923c" },
    card: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
    image: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
    icon: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
    text: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
    decorative: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
    other: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
  };
  const c = ROLE_COLORS[role] ?? ROLE_COLORS.other;

  return (
    <span
      className={`shrink-0 rounded font-medium ${
        small ? "px-1 py-0.5 text-[8px]" : "px-1.5 py-0.5 text-[10px]"
      }`}
      style={{ backgroundColor: c.bg, color: c.text }}
    >
      {role}
    </span>
  );
}

// ================================================================
// formatComponentSpec — LLM-friendly text for single component copy
// ================================================================

function formatComponentSpec(comp: ComponentSpec): string {
  const lines: string[] = [];

  lines.push(`## ${comp.name}（${comp.role}）`);
  if (comp.description) lines.push(comp.description);
  lines.push("");

  lines.push(`尺寸: ${Math.round(comp.bounds.width)} × ${Math.round(comp.bounds.height)}`);
  lines.push(`位置: x=${Math.round(comp.bounds.x)}, y=${Math.round(comp.bounds.y)}`);
  if (comp.z_index != null) lines.push(`层级: z-index ${comp.z_index}`);
  lines.push("");

  if (comp.layout?.type) {
    const parts: string[] = [`布局: ${comp.layout.type}`];
    if (comp.layout.direction) parts.push(comp.layout.direction);
    lines.push(parts.join(" "));
    if (comp.layout.justify) lines.push(`  对齐: justify=${comp.layout.justify}`);
    if (comp.layout.align) lines.push(`  对齐: align=${comp.layout.align}`);
    if (comp.layout.gap != null) {
      const g = typeof comp.layout.gap === "object" ? (comp.layout.gap as { value: number }).value : comp.layout.gap;
      lines.push(`  间距: gap=${g}px`);
    }
    lines.push("");
  }

  if (comp.sizing) {
    if (comp.sizing.width) lines.push(`宽度: ${comp.sizing.width}`);
    if (comp.sizing.height) lines.push(`高度: ${comp.sizing.height}`);
    lines.push("");
  }

  if (comp.typography) {
    const t = comp.typography;
    lines.push("文字:");
    if (t.content) lines.push(`  内容: "${t.content}"`);
    if (t.font_family) lines.push(`  字体: ${t.font_family}`);
    if (t.font_size) lines.push(`  字号: ${t.font_size}px`);
    if (t.font_weight) lines.push(`  字重: ${t.font_weight}`);
    if (t.line_height) lines.push(`  行高: ${t.line_height}px`);
    if (t.color) lines.push(`  颜色: ${resolveColor(t.color)}`);
    lines.push("");
  }

  if (comp.design_analysis) {
    lines.push("设计解读:");
    lines.push(comp.design_analysis);
    lines.push("");
  }

  if (comp.children && comp.children.length > 0) {
    lines.push(`子组件: ${comp.children.length} 个`);
    for (const child of comp.children) {
      lines.push(`  - ${child.name}（${child.role}）${Math.round(child.bounds.width)}×${Math.round(child.bounds.height)}`);
    }
  }

  return lines.join("\n").trim();
}
