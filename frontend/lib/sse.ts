import { AgentNodeStatus } from "@/components/agent-node";

export interface NodeUpdateEvent {
  node: string;
  status: AgentNodeStatus;
  timestamp?: string;
}

export interface NodeOutputEvent {
  node: string;
  output: string;
  timestamp?: string;
}

export type SSEEvent =
  | { type: "node_update"; data: NodeUpdateEvent }
  | { type: "node_output"; data: NodeOutputEvent };

export function connectSSE(
  workflowId: string,
  runId: string,
  onEvent: (event: SSEEvent) => void,
  options?: { demo?: boolean }
): () => void {
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const url = `${baseUrl}/api/v2/workflows/${workflowId}/runs/${runId}/stream${options?.demo ? "?demo=true" : ""}`;

  const eventSource = new EventSource(url);

  eventSource.addEventListener("node_update", (e) => {
    try {
      const data = JSON.parse(e.data) as NodeUpdateEvent;
      onEvent({ type: "node_update", data });
    } catch (err) {
      console.error("Failed to parse node_update event:", err);
    }
  });

  eventSource.addEventListener("node_output", (e) => {
    try {
      const data = JSON.parse(e.data) as NodeOutputEvent;
      onEvent({ type: "node_output", data });
    } catch (err) {
      console.error("Failed to parse node_output event:", err);
    }
  });

  eventSource.onerror = (err) => {
    console.error("SSE connection error:", err);
  };

  // Return cleanup function
  return () => {
    eventSource.close();
  };
}
