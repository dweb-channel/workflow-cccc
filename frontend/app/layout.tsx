import "./globals.css";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Sidebar } from "@/components/sidebar/Sidebar";

export const metadata = {
  title: "工作流操作台",
  description: "工作流操作页面"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-hidden">
            {children}
          </main>
        </div>
        <Toaster />
      </body>
    </html>
  );
}
