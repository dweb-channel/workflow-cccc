import type { InteractionSpec, ComponentSpec } from "@/lib/types/design-spec";
import { ArrowRight } from "lucide-react";
import { RoleBadge } from "./SpecCardHeader";

// ================================================================
// InteractionSection
// ================================================================

export function InteractionSection({ interaction }: { interaction: InteractionSpec }) {
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
            <div key={`${b.trigger}-${b.action}-${i}`} className="mt-1 rounded bg-slate-900 px-2 py-1.5 text-[11px]">
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
            <div key={s.name || `state-${i}`} className="mt-1 rounded bg-slate-900 px-2 py-1.5">
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
            <div key={`${t.property}-${t.duration_ms}-${i}`} className="mt-1 text-[11px] text-slate-400">
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

// ================================================================
// ChildrenSection
// ================================================================

export function ChildrenSection({
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
