"use client";

import { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { ScanFrameItem } from "@/lib/api";
import {
  Smartphone,
  Tablet,
  Monitor,
  FileText,
  Palette,
  Trash2,
  Check,
  ChevronDown,
  ChevronRight,
  Link2Off,
  Play,
} from "lucide-react";

/* ================================================================
   ScanResults — Displays classified Figma frames for user
   confirmation before pipeline execution.
   ================================================================ */

interface ScanResultsProps {
  pageName: string;
  candidates: ScanFrameItem[];
  interactionSpecs: ScanFrameItem[];
  designSystem: ScanFrameItem[];
  excluded: ScanFrameItem[];
  onConfirm: (
    selectedScreens: { node_id: string; interaction_note_ids: string[] }[]
  ) => void;
  onBack: () => void;
}

const TYPE_ICONS: Record<string, typeof Smartphone> = {
  mobile: Smartphone,
  tablet: Tablet,
  desktop: Monitor,
  other: Monitor,
};

const TYPE_LABELS: Record<string, string> = {
  mobile: "Mobile",
  tablet: "Tablet",
  desktop: "Desktop",
  other: "Other",
};

export function ScanResults({
  pageName,
  candidates,
  interactionSpecs,
  designSystem,
  excluded,
  onConfirm,
  onBack,
}: ScanResultsProps) {
  // Track selected UI screens (node_ids)
  const [selectedScreens, setSelectedScreens] = useState<Set<string>>(
    () => new Set(candidates.map((c) => c.node_id))
  );
  // Track selected interaction specs (node_ids)
  const [selectedSpecs, setSelectedSpecs] = useState<Set<string>>(
    () => new Set(interactionSpecs.map((s) => s.node_id))
  );
  // Track selected design system items
  const [selectedDesignSys, setSelectedDesignSys] = useState<Set<string>>(
    () => new Set(designSystem.map((d) => d.node_id))
  );
  // Excluded section collapsed
  const [excludedExpanded, setExcludedExpanded] = useState(false);

  // Build the confirmation payload
  const handleConfirm = () => {
    const screens = candidates
      .filter((c) => selectedScreens.has(c.node_id))
      .map((c) => {
        // Find associated interaction specs
        const noteIds = interactionSpecs
          .filter(
            (s) =>
              selectedSpecs.has(s.node_id) && s.related_to === c.node_id
          )
          .map((s) => s.node_id);
        return { node_id: c.node_id, interaction_note_ids: noteIds };
      });
    onConfirm(screens);
  };

  const totalSelected = selectedScreens.size;

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto pr-1">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-white">
            扫描结果 — {pageName}
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            检测到 {candidates.length} 个 UI 屏幕，
            {interactionSpecs.length} 条交互说明，
            {designSystem.length} 个设计系统元素
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={onBack}>
            返回
          </Button>
          <Button
            size="sm"
            className="h-8 text-xs bg-violet-500 hover:bg-violet-400 text-white"
            onClick={handleConfirm}
            disabled={totalSelected === 0}
          >
            <Play className="mr-1 h-3 w-3" />
            确认开始 ({totalSelected})
          </Button>
        </div>
      </div>

      {/* UI Screens */}
      <SectionHeader
        icon="📱"
        title="UI 屏幕"
        count={candidates.length}
        selectedCount={selectedScreens.size}
        onToggleAll={() => {
          if (selectedScreens.size === candidates.length) {
            setSelectedScreens(new Set());
          } else {
            setSelectedScreens(new Set(candidates.map((c) => c.node_id)));
          }
        }}
      />
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {candidates.map((item) => (
          <ScreenCard
            key={item.node_id}
            item={item}
            selected={selectedScreens.has(item.node_id)}
            onToggle={() =>
              setSelectedScreens((prev) => {
                const next = new Set(prev);
                if (next.has(item.node_id)) next.delete(item.node_id);
                else next.add(item.node_id);
                return next;
              })
            }
            associatedSpecs={interactionSpecs.filter(
              (s) => s.related_to === item.node_id
            )}
          />
        ))}
      </div>

      {/* Interaction Specs */}
      {interactionSpecs.length > 0 && (
        <>
          <SectionHeader
            icon="📝"
            title="交互说明"
            count={interactionSpecs.length}
            selectedCount={selectedSpecs.size}
            subtitle="自动关联到 UI 屏幕，作为生成上下文"
            onToggleAll={() => {
              if (selectedSpecs.size === interactionSpecs.length) {
                setSelectedSpecs(new Set());
              } else {
                setSelectedSpecs(
                  new Set(interactionSpecs.map((s) => s.node_id))
                );
              }
            }}
          />
          <div className="space-y-2">
            {interactionSpecs.map((item) => (
              <InteractionSpecCard
                key={item.node_id}
                item={item}
                selected={selectedSpecs.has(item.node_id)}
                relatedScreenName={
                  candidates.find((c) => c.node_id === item.related_to)?.name
                }
                onToggle={() =>
                  setSelectedSpecs((prev) => {
                    const next = new Set(prev);
                    if (next.has(item.node_id)) next.delete(item.node_id);
                    else next.add(item.node_id);
                    return next;
                  })
                }
              />
            ))}
          </div>
        </>
      )}

      {/* Design System */}
      {designSystem.length > 0 && (
        <>
          <SectionHeader
            icon="🎨"
            title="设计系统"
            count={designSystem.length}
            selectedCount={selectedDesignSys.size}
            subtitle="提取为 design tokens"
            onToggleAll={() => {
              if (selectedDesignSys.size === designSystem.length) {
                setSelectedDesignSys(new Set());
              } else {
                setSelectedDesignSys(
                  new Set(designSystem.map((d) => d.node_id))
                );
              }
            }}
          />
          <div className="space-y-2">
            {designSystem.map((item) => (
              <DesignSystemCard
                key={item.node_id}
                item={item}
                selected={selectedDesignSys.has(item.node_id)}
                onToggle={() =>
                  setSelectedDesignSys((prev) => {
                    const next = new Set(prev);
                    if (next.has(item.node_id)) next.delete(item.node_id);
                    else next.add(item.node_id);
                    return next;
                  })
                }
              />
            ))}
          </div>
        </>
      )}

      {/* Excluded */}
      {excluded.length > 0 && (
        <>
          <button
            onClick={() => setExcludedExpanded((p) => !p)}
            className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-300 transition-colors mt-2"
          >
            {excludedExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
            <Trash2 className="h-3 w-3" />
            已排除 ({excluded.length})
          </button>
          {excludedExpanded && (
            <div className="space-y-1 ml-5">
              {excluded.map((item) => (
                <div
                  key={item.node_id}
                  className="flex items-center gap-2 text-xs text-slate-500 py-1"
                >
                  <span className="truncate flex-1">{item.name}</span>
                  <span className="shrink-0 text-slate-600">
                    {item.size}
                  </span>
                  {item.exclude_reason && (
                    <span className="shrink-0 rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-500">
                      {item.exclude_reason}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ================================================================
   Section Header
   ================================================================ */

function SectionHeader({
  icon,
  title,
  count,
  selectedCount,
  subtitle,
  onToggleAll,
}: {
  icon: string;
  title: string;
  count: number;
  selectedCount: number;
  subtitle?: string;
  onToggleAll: () => void;
}) {
  const allSelected = selectedCount === count;
  return (
    <div className="flex items-center gap-2 mt-2">
      <span className="text-base">{icon}</span>
      <span className="text-sm font-semibold text-white">{title}</span>
      <span className="text-xs text-slate-500">
        ({selectedCount}/{count})
      </span>
      {subtitle && (
        <span className="text-[11px] text-slate-500 italic">{subtitle}</span>
      )}
      <button
        onClick={onToggleAll}
        className="ml-auto text-[11px] text-violet-400 hover:text-violet-300 transition-colors"
      >
        {allSelected ? "取消全选" : "全选"}
      </button>
    </div>
  );
}

/* ================================================================
   Screen Card — UI screen with thumbnail + checkbox
   ================================================================ */

function ScreenCard({
  item,
  selected,
  onToggle,
  associatedSpecs,
}: {
  item: ScanFrameItem;
  selected: boolean;
  onToggle: () => void;
  associatedSpecs: ScanFrameItem[];
}) {
  const TypeIcon = TYPE_ICONS[item.device_type || "other"] || Monitor;

  return (
    <button
      onClick={onToggle}
      className={`relative flex flex-col rounded-lg border text-left transition-all ${
        selected
          ? "border-violet-500 bg-violet-500/10"
          : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
      }`}
    >
      {/* Thumbnail */}
      <div className="relative h-36 w-full overflow-hidden rounded-t-lg bg-slate-900">
        {item.thumbnail_url ? (
          <img
            src={item.thumbnail_url}
            alt={item.name}
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-600">
            <TypeIcon className="h-8 w-8" />
          </div>
        )}
        {/* Checkbox overlay */}
        <div
          className={`absolute top-2 right-2 flex h-5 w-5 items-center justify-center rounded border transition-colors ${
            selected
              ? "border-violet-500 bg-violet-500"
              : "border-slate-500 bg-slate-800/80"
          }`}
        >
          {selected && <Check className="h-3 w-3 text-white" />}
        </div>
      </div>
      {/* Info */}
      <div className="p-2.5 space-y-1">
        <p className="text-xs font-medium text-slate-200 truncate">
          {item.name}
        </p>
        <div className="flex items-center gap-1.5">
          <span className="inline-flex items-center gap-1 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300">
            <TypeIcon className="h-2.5 w-2.5" />
            {TYPE_LABELS[item.device_type || "other"]}
          </span>
          <span className="text-[10px] text-slate-500">{item.size}</span>
        </div>
        {associatedSpecs.length > 0 && (
          <p className="text-[10px] text-violet-400">
            📝 {associatedSpecs.length} 条交互说明
          </p>
        )}
      </div>
    </button>
  );
}

/* ================================================================
   Interaction Spec Card
   ================================================================ */

function InteractionSpecCard({
  item,
  selected,
  relatedScreenName,
  onToggle,
}: {
  item: ScanFrameItem;
  selected: boolean;
  relatedScreenName?: string;
  onToggle: () => void;
}) {
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors ${
        selected
          ? "border-violet-500/40 bg-violet-500/5"
          : "border-slate-700 bg-slate-800/30"
      }`}
    >
      <button
        onClick={onToggle}
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
          selected
            ? "border-violet-500 bg-violet-500"
            : "border-slate-500 bg-slate-800"
        }`}
      >
        {selected && <Check className="h-2.5 w-2.5 text-white" />}
      </button>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-slate-300 truncate">
            {item.name}
          </span>
          {relatedScreenName && (
            <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] text-violet-400">
              → {relatedScreenName}
            </span>
          )}
        </div>
        {item.text_content && (
          <p className="mt-1 text-[11px] text-slate-500 line-clamp-2">
            {item.text_content}
          </p>
        )}
      </div>
    </div>
  );
}

/* ================================================================
   Design System Card
   ================================================================ */

function DesignSystemCard({
  item,
  selected,
  onToggle,
}: {
  item: ScanFrameItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border px-3 py-2 transition-colors ${
        selected
          ? "border-violet-500/40 bg-violet-500/5"
          : "border-slate-700 bg-slate-800/30"
      }`}
    >
      <button
        onClick={onToggle}
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
          selected
            ? "border-violet-500 bg-violet-500"
            : "border-slate-500 bg-slate-800"
        }`}
      >
        {selected && <Check className="h-2.5 w-2.5 text-white" />}
      </button>
      <Palette className="h-3.5 w-3.5 text-amber-400 shrink-0" />
      <span className="text-xs text-slate-300 truncate flex-1">
        {item.name}
      </span>
      <span className="text-[10px] text-slate-500">{item.size}</span>
    </div>
  );
}
