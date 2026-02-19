import type { TypographySpec, ContentSpec } from "@/lib/types/design-spec";
import { ColorDisplay } from "./SpecCardStyles";

// ================================================================
// TypographySection
// ================================================================

export function TypographySection({ typography }: { typography: TypographySpec }) {
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
      {typography.content && (
        <div className="rounded bg-background px-2 py-1.5">
          <span className="text-[11px] text-foreground">
            &ldquo;{typography.content}&rdquo;
          </span>
        </div>
      )}
      {fontParts.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-foreground">{fontParts.join(" ")}</span>
          {typography.color && <ColorDisplay value={typography.color} />}
        </div>
      )}
      {details.length > 0 && (
        <div className="text-[11px] text-muted-foreground">{details.join("  |  ")}</div>
      )}
    </div>
  );
}

// ================================================================
// ContentSection
// ================================================================

export function ContentSection({ content }: { content: ContentSpec }) {
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
          <span className="text-[10px] font-medium text-muted-foreground">图片</span>
          {content.image.alt && (
            <div className="text-[11px] text-foreground">描述: {content.image.alt}</div>
          )}
          {content.image.src && (
            <div className="text-[10px] text-muted-foreground truncate">来源: {content.image.src}</div>
          )}
          <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
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
          <span className="text-[10px] font-medium text-muted-foreground">图标</span>
          <div className="flex items-center gap-2 text-[11px] text-foreground">
            {content.icon.name && <span>{content.icon.name}</span>}
            {content.icon.size != null && <span>{content.icon.size}px</span>}
            {content.icon.color && <ColorDisplay value={content.icon.color} />}
          </div>
        </div>
      )}
    </div>
  );
}

// ================================================================
// DesignAnalysisSection — markdown-like rendering
// ================================================================

export function DesignAnalysisSection({ text }: { text: string }) {
  const lines = text.split("\n");

  return (
    <div className="space-y-1 text-[11px] leading-relaxed text-foreground">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={`line-${i}`} className="h-1" />;

        if (trimmed.startsWith("## ")) {
          return (
            <div key={`line-${i}`} className="font-semibold text-foreground text-[12px] mt-2 first:mt-0">
              {renderInline(trimmed.slice(3))}
            </div>
          );
        }
        if (trimmed.startsWith("### ")) {
          return (
            <div key={`line-${i}`} className="font-medium text-foreground text-[11px] mt-1.5">
              {renderInline(trimmed.slice(4))}
            </div>
          );
        }
        if (trimmed.startsWith("- ")) {
          return (
            <div key={`line-${i}`} className="flex gap-1.5 pl-2">
              <span className="text-muted-foreground shrink-0">•</span>
              <span>{renderInline(trimmed.slice(2))}</span>
            </div>
          );
        }
        const numberedMatch = trimmed.match(/^(\d+)\.\s+(.+)/);
        if (numberedMatch) {
          return (
            <div key={`line-${i}`} className="flex gap-1.5 pl-2">
              <span className="text-muted-foreground shrink-0 tabular-nums">{numberedMatch[1]}.</span>
              <span>{renderInline(numberedMatch[2])}</span>
            </div>
          );
        }
        return <div key={`line-${i}`}>{renderInline(trimmed)}</div>;
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
          return <strong key={`fmt-${i}`} className="text-foreground font-medium">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={`fmt-${i}`} className="rounded bg-muted/80 px-1 py-0.5 text-[10px] font-mono text-emerald-400">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={`fmt-${i}`}>{part}</span>;
      })}
    </>
  );
}
