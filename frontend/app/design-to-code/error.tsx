"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function DesignToCodeError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Design-to-code error:", error);
  }, [error]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-6 py-4 max-w-lg text-center">
        <h2 className="text-lg font-semibold text-foreground mb-2">
          Design-to-Code module error
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          {error.message || "An unexpected error occurred in the design-to-code module"}
        </p>
        <Button onClick={reset} variant="outline" size="sm">
          Try again
        </Button>
      </div>
    </div>
  );
}
