"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
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
      className={`flex items-center gap-3 rounded-lg px-4 py-3 text-sm font-medium transition-colors ${
        isActive
          ? "bg-blue-500 text-white"
          : "bg-slate-50 text-slate-500 hover:bg-slate-100"
      }`}
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </Link>
  );
}

interface SidebarProps {
  children?: ReactNode;
}

export function Sidebar({ children }: SidebarProps) {
  const pathname = usePathname();

  const isWorkflowPage = pathname === "/" || pathname.startsWith("/workflow");
  const isBatchBugsPage = pathname === "/batch-bugs";

  return (
    <aside className="flex w-[240px] shrink-0 flex-col border-r border-slate-200 bg-white">
      {/* Logo */}
      <div className="px-4 py-4">
        <h1 className="text-lg font-bold text-slate-800">工作流平台</h1>
      </div>

      {/* Navigation */}
      <div className="space-y-1 px-4">
        <NavItem
          href="/"
          icon={GitBranch}
          label="工作流"
          isActive={isWorkflowPage}
        />
        <NavItem
          href="/batch-bugs"
          icon={Bug}
          label="批量修复"
          isActive={isBatchBugsPage}
        />
      </div>

      {/* Divider */}
      <div className="mx-4 my-4 h-px bg-slate-200" />

      {/* Content area - workflow list or batch info */}
      <div className="flex-1 overflow-y-auto px-4">
        {children}
      </div>
    </aside>
  );
}
