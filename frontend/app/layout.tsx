import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "工作流操作台",
  description: "工作流操作页面"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        {children}
      </body>
    </html>
  );
}
