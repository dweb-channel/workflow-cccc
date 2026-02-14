import React from "react";

export interface TabBarProps {
  /** Tab labels, first is active by default */
  tabs?: string[];
  /** Index of the active tab (default 0) */
  activeIndex?: number;
}

/**
 * TabBar — molecule component
 * Horizontal tab navigation with active yellow underline indicator
 * Design node: 1:20, width 393px, height 38px
 *
 * CSS Variables used:
 *   --color-bg-white (#FFFFFF), --color-text-primary (#000000),
 *   --color-text-secondary (#666666), --color-brand-primary (#FFDD4C),
 *   --color-border (#EEEEEE), --spacing-page-padding (16px),
 *   --font-family (PingFang SC)
 */
export function TabBar({
  tabs = ["推荐", "发现"],
  activeIndex = 0,
}: TabBarProps) {
  return (
    <nav
      className="flex items-end w-full h-[38px] border-b border-[var(--color-border,#EEEEEE)] bg-[var(--color-bg-white,#FFFFFF)]"
      style={{
        fontFamily: "var(--font-family, 'PingFang SC', sans-serif)",
      }}
    >
      {/* Tabs container — starts at page-padding, 16px gap between tabs */}
      <div
        className="flex items-end h-full pl-[var(--spacing-page-padding,16px)]"
        style={{ gap: "16px" }}
      >
        {tabs.map((label, i) => {
          const isActive = i === activeIndex;
          return (
            <div
              key={label}
              className="flex items-center justify-center h-full relative"
              style={{ width: "60px" }}
            >
              <span
                className="leading-normal"
                style={{
                  fontSize: "16px",
                  fontWeight: isActive ? 600 : 400,
                  color: isActive
                    ? "var(--color-text-primary, #000000)"
                    : "var(--color-text-secondary, #666666)",
                }}
              >
                {label}
              </span>
              {/* Active indicator — yellow underline */}
              {isActive && (
                <div
                  className="absolute bottom-0 left-1/2 -translate-x-1/2 rounded-full"
                  style={{
                    width: "24px",
                    height: "3px",
                    backgroundColor:
                      "var(--color-brand-primary, #FFDD4C)",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
