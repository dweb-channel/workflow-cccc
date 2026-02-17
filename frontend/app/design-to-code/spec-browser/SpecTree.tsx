"use client";

import type { ComponentSpec, SemanticRole } from "@/lib/types/design-spec";

// ---- Role badge colors (5 groups) ----

const ROLE_COLORS: Record<string, { bg: string; text: string }> = {
  // Structure
  page: { bg: "rgba(139,92,246,0.15)", text: "#a78bfa" },
  section: { bg: "rgba(139,92,246,0.12)", text: "#a78bfa" },
  container: { bg: "rgba(100,116,139,0.15)", text: "#94a3b8" },
  // Navigation
  nav: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
  header: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
  footer: { bg: "rgba(6,182,212,0.12)", text: "#22d3ee" },
  // Interactive
  button: { bg: "rgba(249,115,22,0.12)", text: "#fb923c" },
  input: { bg: "rgba(249,115,22,0.12)", text: "#fb923c" },
  // Content
  card: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  list: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  "list-item": { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  image: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  icon: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  text: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  badge: { bg: "rgba(34,197,94,0.12)", text: "#4ade80" },
  // Utility
  divider: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
  overlay: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
  decorative: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
  other: { bg: "rgba(100,116,139,0.1)", text: "#64748b" },
};

function getRoleColor(role: SemanticRole) {
  return ROLE_COLORS[role] ?? ROLE_COLORS.other;
}

// ---- Props ----

interface SpecTreeProps {
  components: ComponentSpec[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function SpecTree({ components, selectedId, onSelect }: SpecTreeProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-700 px-3 py-2.5">
        <span className="text-xs font-semibold text-slate-300">
          Components
        </span>
        <span className="ml-2 text-[11px] text-slate-500">
          ({components.length})
        </span>
      </div>

      {/* Flat component list */}
      <div className="flex-1 overflow-y-auto py-1">
        {components.map((comp) => (
          <ComponentRow
            key={comp.id}
            component={comp}
            isSelected={selectedId === comp.id}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

// ---- Component row ----

function ComponentRow({
  component,
  isSelected,
  onSelect,
}: {
  component: ComponentSpec;
  isSelected: boolean;
  onSelect: (id: string) => void;
}) {
  const isSpacer = component.render_hint === "spacer";
  const isPlatform = component.render_hint === "platform";
  const roleColor = getRoleColor(component.role);
  const displayName = getDisplayName(component);

  return (
    <button
      onClick={() => onSelect(component.id)}
      className={`flex w-full flex-col gap-0.5 px-3 py-2 text-left transition-colors hover:bg-slate-700/40 border-b border-slate-700/30 ${
        isSelected ? "bg-violet-500/15" : ""
      }`}
    >
      {/* Top line: name + role badge */}
      <div className="flex items-center gap-1.5">
        <span
          className={`truncate text-[12px] ${
            isSelected
              ? "font-medium text-white"
              : isSpacer || isPlatform
                ? "text-slate-500 italic"
                : "text-slate-300"
          }`}
        >
          {displayName}
        </span>

        {/* Role badge */}
        <span
          className="ml-auto shrink-0 rounded px-1 py-0.5 text-[9px] font-medium"
          style={{ backgroundColor: roleColor.bg, color: roleColor.text }}
        >
          {component.role}
        </span>
      </div>

      {/* Description line (truncated) */}
      {component.description && (
        <div className="text-[10px] text-slate-500 truncate leading-tight">
          {component.description.slice(0, 60)}{component.description.length > 60 ? "..." : ""}
        </div>
      )}

      {/* Bottom line: size */}
      <div className="flex items-center gap-2 text-[10px] font-mono text-slate-500">
        <span>{Math.round(component.bounds.width)} × {Math.round(component.bounds.height)}</span>
        {component.children && component.children.length > 0 && (
          <span className="text-slate-600">{component.children.length} 子组件</span>
        )}
        {component.children_collapsed != null && component.children_collapsed > 0 && (
          <span className="text-slate-600">
            {component.children_collapsed} 节点
          </span>
        )}
      </div>
    </button>
  );
}

// ---- Helpers ----

const ROLE_NAMES_ZH: Record<string, string> = {
  page: "页面",
  section: "区块",
  container: "容器",
  nav: "导航",
  header: "头部",
  footer: "底部",
  button: "按钮",
  input: "输入框",
  card: "卡片",
  list: "列表",
  "list-item": "列表项",
  image: "图片",
  icon: "图标",
  text: "文本",
  badge: "徽章",
  divider: "分割线",
  overlay: "遮罩",
  decorative: "装饰",
};

/** Get a human-readable display name for a component */
function getDisplayName(component: ComponentSpec): string {
  // If name is meaningful (not "Frame" / "Rectangle" / "Group" etc.), use it
  const genericNames = new Set(["Frame", "Rectangle", "Group", "Vector", "Ellipse", "Line", "Component"]);
  if (component.name && !genericNames.has(component.name)) {
    return component.name;
  }
  // Fallback: use Chinese role name + dimensions
  const roleZh = ROLE_NAMES_ZH[component.role] || component.role;
  return `${roleZh} ${Math.round(component.bounds.width)}×${Math.round(component.bounds.height)}`;
}
