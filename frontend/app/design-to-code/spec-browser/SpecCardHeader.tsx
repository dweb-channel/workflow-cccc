import type { ComponentSpec } from "@/lib/types/design-spec";
import { resolveColor } from "@/lib/types/design-spec";

// ================================================================
// QualityIndicators — per-component header metrics
// ================================================================

export function QualityIndicators({ component }: { component: ComponentSpec }) {
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
      <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] ${
        hasAnalysis ? "bg-emerald-500/10 text-emerald-400" : "bg-muted/50 text-muted-foreground"
      }`}>
        {hasAnalysis ? "\u2713" : "\u2717"} 设计解读
      </span>

      {hasInteraction && (
        <span className="inline-flex items-center gap-1 rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] text-orange-400">
          {"\u2713"} 交互
        </span>
      )}

      {coveragePercent !== null && (
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] ${
          coveragePercent >= 80
            ? "bg-emerald-500/10 text-emerald-400"
            : coveragePercent >= 50
              ? "bg-yellow-500/10 text-yellow-400"
              : "bg-red-500/10 text-red-400"
        }`}>
          <span className="font-mono">{filledDesc}/{totalDesc}</span> 子描述
          <span className="ml-0.5 inline-block h-1 w-8 rounded-full bg-muted overflow-hidden">
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

      {component.role === "other" && (
        <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] text-red-400">
          ⚠ role=other
        </span>
      )}
    </div>
  );
}

// ================================================================
// RoleBadge
// ================================================================

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

export function RoleBadge({ role, small }: { role: string; small?: boolean }) {
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

export function formatComponentSpec(comp: ComponentSpec): string {
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
