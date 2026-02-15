"use client";

import { useState } from "react";
import type {
  ComponentSpec,
  ColorValue,
  SpacingValue,
  LayoutSpec,
  SizingSpec,
  StyleSpec,
  TypographySpec,
  ContentSpec,
  InteractionSpec,
  BackgroundSpec,
  ShadowSpec,
  GradientStop,
} from "@/lib/types/design-spec";
import { isTokenColor, resolveColor, isTokenSpacing, resolveSpacing } from "@/lib/types/design-spec";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";

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
        </div>
        {component.description && (
          <p className="mt-1.5 text-[11px] leading-relaxed text-slate-400">
            {component.description}
          </p>
        )}
        {/* Bounds */}
        <div className="mt-1.5 flex gap-3 text-[10px] text-slate-500 font-mono">
          <span>x:{component.bounds.x} y:{component.bounds.y}</span>
          <span>{component.bounds.width} x {component.bounds.height}</span>
          <span>id: {component.id}</span>
        </div>
      </div>

      {/* Sections */}
      <div className="flex-1 p-2 space-y-1">
        <Section title="Layout" icon="layout" defaultOpen>
          <LayoutSection layout={component.layout} />
        </Section>

        {component.sizing && (
          <Section title="Sizing" icon="sizing" defaultOpen>
            <SizingSection sizing={component.sizing} />
          </Section>
        )}

        <Section title="Style" icon="style" defaultOpen>
          <StyleSection style={component.style} />
        </Section>

        {component.typography && !isSpacer && (
          <Section title="Typography" icon="typography">
            <TypographySection typography={component.typography} />
          </Section>
        )}

        {component.content && !isSpacer && (
          <Section title="Content" icon="content">
            <ContentSection content={component.content} />
          </Section>
        )}

        {component.interaction && !isSpacer && (
          <Section title="Interaction" icon="interaction">
            <InteractionSection interaction={component.interaction} />
          </Section>
        )}

        {component.children && component.children.length > 0 && (
          <Section title={`Children (${component.children.length})`} icon="children">
            <ChildrenSection children={component.children} onNavigate={onNavigate} />
          </Section>
        )}
      </div>
    </div>
  );
}

// ================================================================
// Collapsible Section
// ================================================================

const SECTION_ICONS: Record<string, string> = {
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
  return (
    <div className="space-y-1">
      {layout.type && <PropRow label="type" value={layout.type} />}
      {layout.direction && <PropRow label="direction" value={layout.direction} />}
      {layout.justify && <PropRow label="justify" value={layout.justify} />}
      {layout.align && <PropRow label="align" value={layout.align} />}
      {layout.gap != null && (
        <PropRow label="gap" value={<SpacingDisplay value={layout.gap} />} />
      )}
      {layout.padding && (
        <PropRow
          label="padding"
          value={
            <span className="font-mono">
              [{layout.padding.map((p) => resolveSpacing(p)).join(", ")}]
            </span>
          }
        />
      )}
      {layout.wrap != null && <PropRow label="wrap" value={String(layout.wrap)} />}
      {layout.overflow && <PropRow label="overflow" value={layout.overflow} />}
    </div>
  );
}

function SizingSection({ sizing }: { sizing: SizingSpec }) {
  return (
    <div className="space-y-1">
      {sizing.width && <PropRow label="width" value={sizing.width} />}
      {sizing.height && <PropRow label="height" value={sizing.height} />}
      {sizing.min_width != null && <PropRow label="min-width" value={`${sizing.min_width}px`} />}
      {sizing.max_width != null && <PropRow label="max-width" value={`${sizing.max_width}px`} />}
      {sizing.min_height != null && <PropRow label="min-height" value={`${sizing.min_height}px`} />}
      {sizing.max_height != null && <PropRow label="max-height" value={`${sizing.max_height}px`} />}
      {sizing.aspect_ratio && <PropRow label="aspect-ratio" value={sizing.aspect_ratio} />}
    </div>
  );
}

function StyleSection({ style }: { style: StyleSpec }) {
  return (
    <div className="space-y-1">
      {style.background && <BackgroundDisplay bg={style.background} />}
      {style.border && (
        <>
          {style.border.width != null && (
            <PropRow label="border-width" value={`${style.border.width}px`} />
          )}
          {style.border.color && (
            <PropRow label="border-color" value={<ColorDisplay value={style.border.color} />} />
          )}
          {style.border.style && <PropRow label="border-style" value={style.border.style} />}
          {style.border.sides && <PropRow label="border-sides" value={style.border.sides} />}
        </>
      )}
      {style.corner_radius != null && (
        <PropRow
          label="corner-radius"
          value={
            typeof style.corner_radius === "number"
              ? `${style.corner_radius}px`
              : `[${style.corner_radius.join(", ")}]px`
          }
        />
      )}
      {style.shadow && style.shadow.length > 0 && (
        <div>
          <span className="text-[10px] text-slate-500">shadow:</span>
          {style.shadow.map((s, i) => (
            <ShadowDisplay key={i} shadow={s} />
          ))}
        </div>
      )}
      {style.opacity != null && style.opacity !== 1 && (
        <PropRow label="opacity" value={String(style.opacity)} />
      )}
      {style.blur && (
        <PropRow
          label="blur"
          value={`${style.blur.type || "layer"} ${style.blur.radius || 0}px`}
        />
      )}
    </div>
  );
}

function TypographySection({ typography }: { typography: TypographySpec }) {
  return (
    <div className="space-y-1">
      {typography.content && (
        <div className="rounded bg-slate-900 px-2 py-1.5 mb-2">
          <span className="text-[11px] text-slate-300">
            &ldquo;{typography.content}&rdquo;
          </span>
        </div>
      )}
      {typography.font_family && <PropRow label="font-family" value={typography.font_family} />}
      {typography.font_size != null && <PropRow label="font-size" value={`${typography.font_size}px`} />}
      {typography.font_weight != null && <PropRow label="font-weight" value={String(typography.font_weight)} />}
      {typography.line_height != null && <PropRow label="line-height" value={`${typography.line_height}px`} />}
      {typography.letter_spacing != null && typography.letter_spacing !== 0 && (
        <PropRow label="letter-spacing" value={`${typography.letter_spacing}px`} />
      )}
      {typography.color && (
        <PropRow label="color" value={<ColorDisplay value={typography.color} />} />
      )}
      {typography.align && <PropRow label="text-align" value={typography.align} />}
      {typography.decoration && typography.decoration !== "none" && (
        <PropRow label="decoration" value={typography.decoration} />
      )}
      {typography.transform && typography.transform !== "none" && (
        <PropRow label="transform" value={typography.transform} />
      )}
      {typography.overflow && <PropRow label="overflow" value={typography.overflow} />}
      {typography.max_lines != null && <PropRow label="max-lines" value={String(typography.max_lines)} />}
    </div>
  );
}

function ContentSection({ content }: { content: ContentSpec }) {
  return (
    <div className="space-y-2">
      {content.image && (
        <div className="space-y-1">
          <span className="text-[10px] font-medium text-slate-400">Image</span>
          {content.image.src && <PropRow label="src" value={content.image.src} />}
          {content.image.alt && <PropRow label="alt" value={content.image.alt} />}
          {content.image.fit && <PropRow label="fit" value={content.image.fit} />}
          {content.image.aspect_ratio && <PropRow label="aspect-ratio" value={content.image.aspect_ratio} />}
          {content.image.placeholder && <PropRow label="placeholder" value={content.image.placeholder} />}
        </div>
      )}
      {content.icon && (
        <div className="space-y-1">
          <span className="text-[10px] font-medium text-slate-400">Icon</span>
          {content.icon.name && <PropRow label="name" value={content.icon.name} />}
          {content.icon.size != null && <PropRow label="size" value={`${content.icon.size}px`} />}
          {content.icon.color && (
            <PropRow label="color" value={<ColorDisplay value={content.icon.color} />} />
          )}
        </div>
      )}
    </div>
  );
}

function InteractionSection({ interaction }: { interaction: InteractionSpec }) {
  return (
    <div className="space-y-2">
      {interaction.behaviors && interaction.behaviors.length > 0 && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">Behaviors</span>
          {interaction.behaviors.map((b, i) => (
            <div key={i} className="mt-1 rounded bg-slate-900 px-2 py-1.5 text-[11px]">
              <span className="text-orange-400">{b.trigger}</span>
              <span className="text-slate-500"> &rarr; </span>
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
          <span className="text-[10px] font-medium text-slate-400">States</span>
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
          <span className="text-[10px] font-medium text-slate-400">Transitions</span>
          {interaction.transitions.map((t, i) => (
            <div key={i} className="mt-1 text-[11px] text-slate-400 font-mono">
              {t.property} {t.duration_ms}ms {t.easing}
            </div>
          ))}
        </div>
      )}
      {interaction.raw_notes && (
        <div>
          <span className="text-[10px] font-medium text-slate-400">Raw Notes</span>
          <p className="mt-1 text-[11px] text-slate-500 italic">{interaction.raw_notes}</p>
        </div>
      )}
    </div>
  );
}

function ChildrenSection({
  children,
  onNavigate,
}: {
  children: ComponentSpec[];
  onNavigate?: (id: string) => void;
}) {
  return (
    <div className="space-y-1">
      {children.map((child) => (
        <button
          key={child.id}
          onClick={() => onNavigate?.(child.id)}
          className="flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-slate-700/40 transition-colors"
        >
          <span className="text-[11px] text-slate-300 truncate flex-1">
            {child.name}
          </span>
          <RoleBadge role={child.role} small />
          <span className="text-[10px] text-violet-400">&rarr;</span>
        </button>
      ))}
    </div>
  );
}

// ================================================================
// Shared display components
// ================================================================

function PropRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline gap-2 py-0.5">
      <span className="shrink-0 text-[10px] text-slate-500 w-24 text-right font-mono">
        {label}
      </span>
      <span className="text-[11px] text-slate-300 font-mono break-all">{value}</span>
    </div>
  );
}

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

function SpacingDisplay({ value }: { value: SpacingValue }) {
  const px = resolveSpacing(value);
  const token = isTokenSpacing(value) ? value.token : undefined;

  return (
    <span className="inline-flex items-center gap-1.5 font-mono">
      <span>{px}px</span>
      {token && (
        <span className="rounded bg-cyan-500/15 px-1 py-0.5 text-[9px] text-cyan-400">
          {token}
        </span>
      )}
    </span>
  );
}

function BackgroundDisplay({ bg }: { bg: BackgroundSpec }) {
  if (bg.type === "none") {
    return <PropRow label="background" value="none" />;
  }
  if (bg.type === "solid" && bg.color) {
    return <PropRow label="background" value={<ColorDisplay value={bg.color} />} />;
  }
  if ((bg.type === "gradient-linear" || bg.type === "gradient-radial") && bg.gradient) {
    return (
      <div>
        <PropRow label="background" value={bg.type} />
        {bg.gradient.angle != null && (
          <PropRow label="  angle" value={`${bg.gradient.angle}deg`} />
        )}
        {bg.gradient.stops?.map((stop, i) => (
          <PropRow
            key={i}
            label={`  stop[${i}]`}
            value={
              <span className="inline-flex items-center gap-1.5">
                <ColorDisplay value={stop.color} />
                <span className="text-slate-500">@ {(stop.position * 100).toFixed(0)}%</span>
              </span>
            }
          />
        ))}
      </div>
    );
  }
  if (bg.type === "image" && bg.image) {
    return (
      <div>
        <PropRow label="background" value="image" />
        {bg.image.url && <PropRow label="  url" value={bg.image.url} />}
        {bg.image.fit && <PropRow label="  fit" value={bg.image.fit} />}
      </div>
    );
  }
  return <PropRow label="background" value={bg.type} />;
}

function ShadowDisplay({ shadow }: { shadow: ShadowSpec }) {
  return (
    <div className="ml-4 text-[10px] text-slate-400 font-mono py-0.5">
      {shadow.type || "drop"} {shadow.x ?? 0} {shadow.y ?? 0} {shadow.blur ?? 0} {shadow.spread ?? 0}
      {shadow.color && (
        <span className="ml-1">
          <ColorDisplay value={shadow.color} />
        </span>
      )}
    </div>
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
