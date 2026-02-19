"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ExecutionLogProps {
  events: Array<{ time: string; type: string; message: string }>;
}

export function ExecutionLog({ events }: ExecutionLogProps) {
  if (events.length === 0) return null;

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">执行日志</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="max-h-48 overflow-y-auto rounded bg-background p-3 text-xs font-mono">
          {events.map((event, idx) => (
            <div key={`evt-${event.time}-${idx}`} className={`${event.type === 'error' ? 'text-red-400' : event.type === 'completed' ? 'text-emerald-400' : 'text-muted-foreground'}`}>
              <span className="text-muted-foreground/70">[{event.time}]</span> {event.message}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
