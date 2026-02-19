"use client";

import { useState } from "react";
import type { ComponentSpec } from "@/lib/types/design-spec";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import { QualityIndicators, RoleBadge, formatComponentSpec } from "./SpecCardHeader";
import { LayoutSection, SizingSection } from "./SpecCardLayout";
import { StyleSection } from "./SpecCardStyles";
import { TypographySection, ContentSection, DesignAnalysisSection } from "./SpecCardContent";
import { InteractionSection, ChildrenSection } from "./SpecCardInteractions";

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
      <div className="sticky top-0 z-10 border-b border-border bg-card px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-foreground truncate">
            {component.name}
          </h2>
          <RoleBadge role={component.role} />
          {(isSpacer || isPlatform) && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-foreground">
              {isSpacer ? "Spacer" : "Platform"}
            </span>
          )}
          {component.z_index != null && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
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
          <p className="mt-1.5 text-[11px] leading-relaxed text-muted-foreground">
            {component.description}
          </p>
        )}
        {/* Bounds */}
        <div className="mt-1.5 flex gap-3 text-[10px] text-muted-foreground font-mono">
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
          <div className="rounded-lg border border-border/50 bg-card/50 px-3 py-2">
            <span className="text-[11px] text-muted-foreground">
              {component.children_collapsed} 个子节点已折叠（骨架层）
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ================================================================
// Collapsible Section (internal)
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
    <div className="rounded-lg border border-border/50 bg-card/50">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/30 transition-colors"
      >
        <span className="text-xs">{SECTION_ICONS[icon] || "\u2699\uFE0F"}</span>
        <span className="text-xs font-medium text-foreground">{title}</span>
        <span className="ml-auto text-muted-foreground">
          {open ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      </button>
      {open && <div className="border-t border-border/50 px-3 py-2">{children}</div>}
    </div>
  );
}
