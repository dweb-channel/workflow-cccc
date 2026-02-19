"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GitBranch, Bug, Palette, Sun, Moon, type LucideIcon } from "lucide-react";
import { useTheme } from "@/components/theme-provider";

interface NavItemProps {
  href: string;
  icon: LucideIcon;
  label: string;
  isActive: boolean;
}

function NavItem({ href, icon: Icon, label, isActive }: NavItemProps) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-3 rounded-r-lg px-3 py-2.5 text-sm font-medium transition-all duration-150 ${
        isActive
          ? "bg-primary/10 text-primary border-l-2 border-primary"
          : "text-sidebar-foreground hover:bg-muted hover:text-foreground border-l-2 border-transparent"
      }`}
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </Link>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-sidebar-foreground hover:bg-muted hover:text-foreground transition-all duration-150 w-full"
      title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      <span>{theme === "dark" ? "浅色模式" : "深色模式"}</span>
    </button>
  );
}

// TODO: Replace static navItems with dynamic API: GET /api/workflows/nav
const navItems = [
  { title: "工作流编辑器", path: "/", icon: GitBranch },
  { title: "批量 Bug 修复", path: "/batch-bugs", icon: Bug },
  { title: "设计转代码", path: "/design-to-code", icon: Palette },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-sidebar">
      {/* Logo */}
      <div className="px-4 py-4">
        <h1 className="text-lg font-bold text-foreground">工作流平台</h1>
      </div>

      {/* Navigation — workflow directory */}
      <nav className="flex-1 space-y-1 px-3">
        {navItems.map((item) => {
          const isActive =
            item.path === "/"
              ? pathname === "/" || pathname.startsWith("/workflow")
              : pathname === item.path || pathname.startsWith(item.path + "/");
          return (
            <NavItem
              key={item.path}
              href={item.path}
              icon={item.icon}
              label={item.title}
              isActive={isActive}
            />
          );
        })}
      </nav>

      {/* Theme toggle */}
      <div className="border-t border-border px-3 py-3">
        <ThemeToggle />
      </div>
    </aside>
  );
}
