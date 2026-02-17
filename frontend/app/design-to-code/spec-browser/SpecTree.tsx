"use client";

import { useState, useMemo } from "react";
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

// ---- Analysis status types ----

export type AnalysisStatus = "pending" | "analyzing" | "complete" | "error";

// ---- Props ----

interface SpecTreeProps {
  components: ComponentSpec[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Per-component analysis status for real-time indication */
  analysisStatus?: Map<string, AnalysisStatus>;
}

// ---- Role group order (for grouped view) ----

const ROLE_GROUP_ORDER: { label: string; roles: SemanticRole[] }[] = [
  { label: "Structure", roles: ["page", "section", "container"] },
  { label: "Navigation", roles: ["nav", "header", "footer"] },
  { label: "Interactive", roles: ["button", "input"] },
  { label: "Content", roles: ["card", "list", "list-item", "image", "icon", "text", "badge"] },
  { label: "Utility", roles: ["divider", "overlay", "decorative", "other"] },
];

export function SpecTree({ components, selectedId, onSelect, analysisStatus }: SpecTreeProps) {
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<Set<SemanticRole>>(new Set());
  const [showRoleFilter, setShowRoleFilter] = useState(false);
  const [groupByRole, setGroupByRole] = useState(false);

  // Unique roles present in data
  const availableRoles = useMemo(() => {
    const roles = new Set<SemanticRole>();
    for (const comp of components) roles.add(comp.role);
    return Array.from(roles).sort();
  }, [components]);

  // Filtered components
  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim();
    return components.filter((comp) => {
      // Role filter
      if (roleFilter.size > 0 && !roleFilter.has(comp.role)) return false;
      // Search filter
      if (q) {
        const name = getDisplayName(comp).toLowerCase();
        const desc = (comp.description || "").toLowerCase();
        if (!name.includes(q) && !desc.includes(q)) return false;
      }
      return true;
    });
  }, [components, search, roleFilter]);

  // Grouped components (only computed when groupByRole is on)
  const grouped = useMemo(() => {
    if (!groupByRole) return null;
    const result: { label: string; components: ComponentSpec[] }[] = [];
    for (const group of ROLE_GROUP_ORDER) {
      const items = filtered.filter((c) => group.roles.includes(c.role));
      if (items.length > 0) {
        result.push({ label: group.label, components: items });
      }
    }
    return result;
  }, [groupByRole, filtered]);

  const toggleRoleFilter = (role: SemanticRole) => {
    setRoleFilter((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  };

  // Status summary counts
  const statusCounts = useMemo(() => {
    if (!analysisStatus || analysisStatus.size === 0) return null;
    let complete = 0;
    let analyzing = 0;
    let error = 0;
    for (const s of analysisStatus.values()) {
      if (s === "complete") complete++;
      else if (s === "analyzing") analyzing++;
      else if (s === "error") error++;
    }
    return { complete, analyzing, error, total: components.length };
  }, [analysisStatus, components.length]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-slate-700 px-3 py-2.5">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-300">
              Components
            </span>
            <span className="ml-2 text-[11px] text-slate-500">
              {filtered.length !== components.length
                ? `${filtered.length}/${components.length}`
                : `(${components.length})`}
            </span>
          </div>
          {/* Group toggle */}
          <button
            onClick={() => setGroupByRole((v) => !v)}
            className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
              groupByRole
                ? "bg-violet-500/20 text-violet-300"
                : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
            }`}
            title={groupByRole ? "Flat view" : "Group by role"}
          >
            {groupByRole ? "Grouped" : "Group"}
          </button>
        </div>

        {/* Status bar (when pipeline is running) */}
        {statusCounts && statusCounts.total > 0 && (
          <div className="mt-1.5 flex items-center gap-2 text-[10px]">
            {statusCounts.analyzing > 0 && (
              <span className="flex items-center gap-1 text-amber-400">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
                {statusCounts.analyzing}
              </span>
            )}
            <span className="text-emerald-400">
              {statusCounts.complete}/{statusCounts.total}
            </span>
            {statusCounts.error > 0 && (
              <span className="text-red-400">{statusCounts.error} err</span>
            )}
          </div>
        )}
      </div>

      {/* Search + Filter bar */}
      <div className="shrink-0 border-b border-slate-700/50 px-3 py-1.5 space-y-1.5">
        {/* Search input */}
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search..."
            className="w-full rounded bg-slate-800 border border-slate-600/50 px-2 py-1 text-[11px] text-slate-300 placeholder:text-slate-500 focus:outline-none focus:border-violet-500/50"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 text-[11px]"
            >
              x
            </button>
          )}
        </div>

        {/* Role filter chips */}
        <div className="flex items-center gap-1 flex-wrap">
          <button
            onClick={() => setShowRoleFilter((v) => !v)}
            className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
              roleFilter.size > 0
                ? "bg-violet-500/20 text-violet-300"
                : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
            }`}
          >
            Role{roleFilter.size > 0 ? ` (${roleFilter.size})` : ""}
          </button>
          {roleFilter.size > 0 && (
            <button
              onClick={() => setRoleFilter(new Set())}
              className="text-[10px] text-slate-500 hover:text-slate-300"
            >
              Clear
            </button>
          )}
        </div>

        {/* Role dropdown */}
        {showRoleFilter && (
          <div className="flex flex-wrap gap-1 pb-0.5">
            {availableRoles.map((role) => {
              const active = roleFilter.has(role);
              const color = getRoleColor(role);
              return (
                <button
                  key={role}
                  onClick={() => toggleRoleFilter(role)}
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors border ${
                    active
                      ? "border-current"
                      : "border-transparent opacity-60 hover:opacity-100"
                  }`}
                  style={{ backgroundColor: color.bg, color: color.text }}
                >
                  {role}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Component list */}
      <div className="flex-1 overflow-y-auto py-1">
        {grouped ? (
          // Grouped view
          grouped.map((group) => (
            <div key={group.label}>
              <div className="sticky top-0 z-10 bg-slate-900/90 backdrop-blur-sm px-3 py-1 text-[10px] font-semibold text-slate-400 uppercase tracking-wider border-b border-slate-700/30">
                {group.label}
                <span className="ml-1.5 text-slate-500 font-normal normal-case">
                  ({group.components.length})
                </span>
              </div>
              {group.components.map((comp) => (
                <ComponentRow
                  key={comp.id}
                  component={comp}
                  isSelected={selectedId === comp.id}
                  onSelect={onSelect}
                  status={analysisStatus?.get(comp.id)}
                />
              ))}
            </div>
          ))
        ) : (
          // Flat view
          filtered.map((comp) => (
            <ComponentRow
              key={comp.id}
              component={comp}
              isSelected={selectedId === comp.id}
              onSelect={onSelect}
              status={analysisStatus?.get(comp.id)}
            />
          ))
        )}

        {filtered.length === 0 && (
          <div className="px-3 py-4 text-center text-[11px] text-slate-500">
            No matches
          </div>
        )}
      </div>
    </div>
  );
}

// ---- Status indicator ----

const STATUS_STYLES: Record<AnalysisStatus, { dot: string; label: string }> = {
  pending: { dot: "bg-slate-500", label: "Pending" },
  analyzing: { dot: "bg-amber-400 animate-pulse", label: "Analyzing" },
  complete: { dot: "bg-emerald-400", label: "Done" },
  error: { dot: "bg-red-400", label: "Error" },
};

function StatusDot({ status }: { status: AnalysisStatus }) {
  const s = STATUS_STYLES[status];
  return (
    <span
      className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${s.dot}`}
      title={s.label}
    />
  );
}

// ---- Component row ----

function ComponentRow({
  component,
  isSelected,
  onSelect,
  status,
}: {
  component: ComponentSpec;
  isSelected: boolean;
  onSelect: (id: string) => void;
  status?: AnalysisStatus;
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
      {/* Top line: status + name + role badge */}
      <div className="flex items-center gap-1.5">
        {status && <StatusDot status={status} />}
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
        <span>{Math.round(component.bounds.width)} x {Math.round(component.bounds.height)}</span>
        {component.children && component.children.length > 0 && (
          <span className="text-slate-600">{component.children.length} children</span>
        )}
        {component.children_collapsed != null && component.children_collapsed > 0 && (
          <span className="text-slate-600">
            {component.children_collapsed} nodes
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
  return `${roleZh} ${Math.round(component.bounds.width)}x${Math.round(component.bounds.height)}`;
}
