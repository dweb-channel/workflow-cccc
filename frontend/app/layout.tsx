import "./globals.css";
import type { ReactNode } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Sidebar } from "@/components/sidebar/Sidebar";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata = {
  title: "工作流操作台",
  description: "工作流操作页面"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{
          __html: `
            (function() {
              var theme = localStorage.getItem('theme');
              if (theme === 'dark') {
                document.documentElement.classList.add('dark');
              }
            })();
          `
        }} />
      </head>
      <body className="min-h-screen bg-background text-foreground">
        <ThemeProvider>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <main className="flex-1 overflow-hidden">
              {children}
            </main>
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
