// ============================================================
// Design Spec v1.0 — TypeScript type definitions
// Generated from: backend/workflow/spec/design_spec_schema.json
// ============================================================

// ---- Enums / Union types ----

export type DesignTool = "figma" | "sketch" | "xd";

export type DeviceType = "mobile" | "tablet" | "desktop";

export type ResponsiveStrategy = "mobile-first" | "desktop-first" | "fixed-width";

export type SemanticRole =
  | "page"
  | "section"
  | "container"
  | "card"
  | "list"
  | "list-item"
  | "nav"
  | "header"
  | "footer"
  | "button"
  | "input"
  | "image"
  | "icon"
  | "text"
  | "divider"
  | "badge"
  | "overlay"
  | "decorative"
  | "other";

export type RenderHint = "full" | "spacer" | "platform";

export type LayoutType = "flex" | "grid" | "absolute" | "stack";

export type PageLayoutType = "flex" | "stack" | "absolute";

export type JustifyContent = "start" | "center" | "end" | "space-between" | "space-around";

export type AlignItems = "start" | "center" | "end" | "stretch" | "baseline";

export type Overflow = "visible" | "hidden" | "scroll";

export type BackgroundType = "solid" | "gradient-linear" | "gradient-radial" | "image" | "none";

export type ImageFit = "cover" | "contain" | "fill" | "none";

export type BorderStyle = "solid" | "dashed" | "dotted" | "none";

export type BorderSides = "all" | "top" | "bottom" | "left" | "right" | "top-bottom" | "left-right";

export type ShadowType = "drop" | "inner";

export type BlurType = "layer" | "background";

export type TextAlign = "left" | "center" | "right" | "justify";

export type TextDecoration = "none" | "underline" | "strikethrough";

export type TextTransform = "none" | "uppercase" | "lowercase" | "capitalize";

export type TextOverflow = "visible" | "ellipsis" | "clip";

export type ImagePlaceholder = "blur" | "color" | "skeleton" | "none";

export type InteractionTrigger = "click" | "hover" | "focus" | "scroll" | "load" | "swipe";

// ---- Value types with token references ----

/** Color: raw hex string OR object with resolved value + optional token name */
export type ColorValue = string | { value: string; token?: string };

/** Spacing: raw px number OR object with resolved value + optional token name */
export type SpacingValue = number | { value: number; token?: string };

/** Type guard: check if a ColorValue is a token reference object */
export function isTokenColor(c: ColorValue): c is { value: string; token?: string } {
  return typeof c === "object" && c !== null && "value" in c;
}

/** Type guard: check if a SpacingValue is a token reference object */
export function isTokenSpacing(s: SpacingValue): s is { value: number; token?: string } {
  return typeof s === "object" && s !== null && "value" in s;
}

/** Resolve a ColorValue to its hex string */
export function resolveColor(c: ColorValue): string {
  return isTokenColor(c) ? c.value : c;
}

/** Resolve a SpacingValue to its px number */
export function resolveSpacing(s: SpacingValue): number {
  return isTokenSpacing(s) ? s.value : s;
}

// ---- Corner radius (uniform or per-corner) ----

/** Uniform px value OR [top-left, top-right, bottom-right, bottom-left] */
export type CornerRadius = number | [number, number, number, number];

// ---- Top-level document ----

export interface DesignSpec {
  version: "1.0";
  source: SpecSource;
  page: SpecPage;
  design_tokens?: DesignTokens;
  components: ComponentSpec[];
}

// ---- Source ----

export interface SpecSource {
  tool: DesignTool;
  file_key: string;
  file_name?: string;
  exported_at?: string;
}

// ---- Page ----

export interface SpecPage {
  name?: string;
  node_id?: string;
  device?: DeviceInfo;
  description?: string;
  responsive_strategy?: ResponsiveStrategy;
  layout?: PageLayout;
}

export interface DeviceInfo {
  type?: DeviceType;
  width?: number;
  height?: number;
}

export interface PageLayout {
  type?: PageLayoutType;
  direction?: "row" | "column";
}

// ---- Design Tokens ----

export interface DesignTokens {
  colors?: Record<string, string>;
  typography?: TypographyTokens;
  spacing?: Record<string, number>;
  radii?: Record<string, number>;
}

export interface TypographyTokens {
  font_family?: string;
  scale?: Record<string, TypeScaleEntry>;
}

export interface TypeScaleEntry {
  size: number;
  weight: number;
  line_height: number;
}

// ---- Component Spec (recursive) ----

export interface ComponentSpec {
  // Required
  id: string;
  name: string;
  role: SemanticRole;
  bounds: Bounds;
  layout: LayoutSpec;
  style: StyleSpec;

  // Optional
  description?: string;
  z_index?: number;
  render_hint?: RenderHint;
  sizing?: SizingSpec;
  typography?: TypographySpec;
  content?: ContentSpec;
  interaction?: InteractionSpec;
  children?: ComponentSpec[];
  children_collapsed?: number;
  screenshot_path?: string;
}

// ---- Bounds ----

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

// ---- Layout ----

export interface LayoutSpec {
  type?: LayoutType;
  direction?: "row" | "column";
  justify?: JustifyContent;
  align?: AlignItems;
  gap?: SpacingValue;
  padding?: [SpacingValue, SpacingValue, SpacingValue, SpacingValue];
  wrap?: boolean;
  overflow?: Overflow;
}

// ---- Sizing ----

export interface SizingSpec {
  width?: string;
  height?: string;
  min_width?: number;
  max_width?: number;
  min_height?: number;
  max_height?: number;
  aspect_ratio?: string;
}

// ---- Style ----

export interface StyleSpec {
  background?: BackgroundSpec;
  border?: BorderSpec;
  corner_radius?: CornerRadius;
  shadow?: ShadowSpec[];
  opacity?: number;
  blur?: BlurSpec;
}

export interface BackgroundSpec {
  type: BackgroundType;
  color?: ColorValue;
  gradient?: GradientSpec;
  image?: BackgroundImageSpec;
}

export interface GradientSpec {
  angle?: number;
  stops?: GradientStop[];
}

export interface GradientStop {
  color: ColorValue;
  position: number;
}

export interface BackgroundImageSpec {
  url?: string;
  fit?: ImageFit;
}

export interface BorderSpec {
  width?: number;
  color?: ColorValue;
  style?: BorderStyle;
  sides?: BorderSides;
}

export interface ShadowSpec {
  type?: ShadowType;
  x?: number;
  y?: number;
  blur?: number;
  spread?: number;
  color?: ColorValue;
}

export interface BlurSpec {
  type?: BlurType;
  radius?: number;
}

// ---- Typography ----

export interface TypographySpec {
  content?: string;
  font_family?: string;
  font_size?: number;
  font_weight?: number;
  line_height?: number;
  letter_spacing?: number;
  color?: ColorValue;
  align?: TextAlign;
  decoration?: TextDecoration;
  transform?: TextTransform;
  overflow?: TextOverflow;
  max_lines?: number;
}

// ---- Content ----

export interface ContentSpec {
  image?: ImageContentSpec;
  icon?: IconContentSpec;
}

export interface ImageContentSpec {
  src?: string;
  alt?: string;
  fit?: ImageFit;
  aspect_ratio?: string;
  placeholder?: ImagePlaceholder;
}

export interface IconContentSpec {
  name?: string;
  size?: number;
  color?: ColorValue;
}

// ---- Interaction ----

export interface InteractionSpec {
  source_frame?: string;
  behaviors?: BehaviorSpec[];
  states?: StateSpec[];
  transitions?: TransitionSpec[];
  raw_notes?: string;
}

export interface BehaviorSpec {
  trigger?: InteractionTrigger;
  action?: string;
  target?: string;
}

export interface StateSpec {
  name?: string;
  style_overrides?: Partial<StyleSpec>;
  description?: string;
}

export interface TransitionSpec {
  property?: string;
  duration_ms?: number;
  easing?: string;
}

// ---- Code Generation types (Phase 3) ----

/** Technology stack configuration for code generation */
export interface TechStackConfig {
  framework: "react" | "vue";
  styling: "tailwind" | "css-modules" | "styled-components";
  language: "typescript" | "javascript";
}

/** Code generation result for a single component */
export interface CodeGenResult {
  component_id: string;
  component_name: string;
  file_name: string;
  code: string;
  dependencies?: string[];
  tailwind_classes_used?: string[];
  error?: string;
}

/** Page assembly result (Phase 4) */
export interface PageGenResult {
  page_name: string;
  file_name: string;
  code: string;
  component_imports: string[];
}

/** Full codegen output for a design spec */
export interface CodeGenOutput {
  tech_stack: TechStackConfig;
  components: CodeGenResult[];
  page?: PageGenResult;
}

// ---- SSE incremental update types ----

/** Partial component update from spec_analyzed SSE event */
export interface ComponentUpdate {
  id: string;
  role?: SemanticRole;
  description?: string;
  interaction?: InteractionSpec;
  render_hint?: RenderHint;
  children_updates?: ComponentUpdate[];
}

/** Apply incremental updates from spec_analyzed to the component tree */
export function applyComponentUpdates(
  components: ComponentSpec[],
  updates: ComponentUpdate[]
): ComponentSpec[] {
  const updateMap = new Map(updates.map((u) => [u.id, u]));
  return components.map((comp) => mergeComponentUpdate(comp, updateMap));
}

function mergeComponentUpdate(
  comp: ComponentSpec,
  updateMap: Map<string, ComponentUpdate>
): ComponentSpec {
  const update = updateMap.get(comp.id);
  let merged = comp;

  if (update) {
    const { id: _id, children_updates: _cu, ...fields } = update;
    merged = { ...comp, ...fields };

    // Collect children_updates into the map for recursive merge
    if (_cu && _cu.length > 0) {
      for (const cu of _cu) {
        updateMap.set(cu.id, cu);
      }
    }
  }

  if (merged.children) {
    merged = {
      ...merged,
      children: merged.children.map((child) =>
        mergeComponentUpdate(child, updateMap)
      ),
    };
  }

  return merged;
}
