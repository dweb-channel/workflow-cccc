"use client";

import { useState, useCallback } from "react";
import type { ComponentSpec, SemanticRole, RenderHint } from "@/lib/types/design-spec";
import { ChevronDown, ChevronRight } from "lucide-react";

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
          ({countAll(components)})
        </span>
      </div>

      {/* Tree body */}
      <div className="flex-1 overflow-y-auto py-1">
        {components.map((comp) => (
          <TreeNode
            key={comp.id}
            component={comp}
            depth={0}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

// ---- Tree node (recursive) ----

function TreeNode({
  component,
  depth,
  selectedId,
  onSelect,
}: {
  component: ComponentSpec;
  depth: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = component.children && component.children.length > 0;
  const isSelected = selectedId === component.id;
  const isSpacer = component.render_hint === "spacer";
  const isPlatform = component.render_hint === "platform";
  const roleColor = getRoleColor(component.role);

  const handleToggle = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      setExpanded((p) => !p);
    },
    []
  );

  return (
    <>
      <button
        onClick={() => onSelect(component.id)}
        className={`flex w-full items-center gap-1 px-2 py-1 text-left transition-colors hover:bg-slate-700/40 ${
          isSelected ? "bg-violet-500/15" : ""
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {/* Expand/collapse chevron */}
        {hasChildren ? (
          <span
            onClick={handleToggle}
            className="flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-slate-600/50"
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3 text-slate-500" />
            ) : (
              <ChevronRight className="h-3 w-3 text-slate-500" />
            )}
          </span>
        ) : (
          <span className="h-4 w-4 shrink-0" />
        )}

        {/* Name */}
        <span
          className={`truncate text-[12px] ${
            isSelected
              ? "font-medium text-white"
              : isSpacer || isPlatform
                ? "text-slate-500 italic"
                : "text-slate-300"
          }`}
        >
          {component.name}
        </span>

        {/* Role badge */}
        <span
          className="ml-auto shrink-0 rounded px-1 py-0.5 text-[9px] font-medium"
          style={{ backgroundColor: roleColor.bg, color: roleColor.text }}
        >
          {component.role}
        </span>

        {/* render_hint indicator */}
        {isSpacer && (
          <span className="shrink-0 text-[9px] text-slate-600" title="Spacer element">
            SP
          </span>
        )}
        {isPlatform && (
          <span className="shrink-0 text-[9px] text-slate-600" title="Platform element">
            PL
          </span>
        )}

        {/* z_index if present and > 0 */}
        {component.z_index != null && component.z_index > 0 && (
          <span
            className="shrink-0 rounded bg-slate-700 px-1 text-[9px] text-slate-400"
            title={`z-index: ${component.z_index}`}
          >
            z{component.z_index}
          </span>
        )}
      </button>

      {/* Children */}
      {hasChildren && expanded && (
        <>
          {component.children!.map((child) => (
            <TreeNode
              key={child.id}
              component={child}
              depth={depth + 1}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </>
      )}
    </>
  );
}

// ---- Helpers ----

function countAll(components: ComponentSpec[]): number {
  let count = 0;
  for (const c of components) {
    count++;
    if (c.children) count += countAll(c.children);
  }
  return count;
}
