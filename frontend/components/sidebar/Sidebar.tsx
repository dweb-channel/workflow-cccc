"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GitBranch, Bug, type LucideIcon } from "lucide-react";

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
      className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-150 ${
        isActive
          ? "bg-white/10 text-white shadow-sm shadow-black/10"
          : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-200"
      }`}
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </Link>
  );
}

// TODO: Replace static navItems with dynamic API: GET /api/workflows/nav
const navItems = [
  { title: "工作流编辑器", path: "/", icon: GitBranch },
  { title: "批量 Bug 修复", path: "/batch-bugs", icon: Bug },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-white/[0.06] bg-[#0f172a]">
      {/* Logo */}
      <div className="px-4 py-4">
        <h1 className="text-lg font-bold text-white/90">工作流平台</h1>
      </div>

      {/* Navigation — workflow directory */}
      <nav className="space-y-1 px-3">
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
    </aside>
  );
}
