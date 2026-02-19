import * as React from "react";

import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {}

const Badge = React.forwardRef<HTMLDivElement, BadgeProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary",
        className
      )}
      {...props}
    />
  )
);
Badge.displayName = "Badge";

export { Badge };
