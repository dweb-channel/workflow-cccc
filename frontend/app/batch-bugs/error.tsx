"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function BatchBugsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Batch bugs error:", error);
  }, [error]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-6 py-4 max-w-lg text-center">
        <h2 className="text-lg font-semibold text-foreground mb-2">
          Bug Fix module error
        </h2>
        <p className="text-sm text-muted-foreground mb-4">
          {error.message || "An unexpected error occurred in the batch bug fix module"}
        </p>
        <Button onClick={reset} variant="outline" size="sm">
          Try again
        </Button>
      </div>
    </div>
  );
}
