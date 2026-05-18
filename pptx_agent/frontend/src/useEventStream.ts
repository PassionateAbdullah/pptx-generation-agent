import { useCallback, useRef, useState } from "react";
import type { AgentEvent } from "./events";

export interface StreamRequest {
  prompt: string;
  slide_count: number;
  theme?: string;
}

export type StreamStatus = "idle" | "running" | "done" | "error";

export interface UseEventStream {
  status: StreamStatus;
  error: string | null;
  events: AgentEvent[];
  start: (req: StreamRequest) => Promise<void>;
  replay: (jobId: string) => Promise<void>;
  reset: () => void;
}

export function useEventStream(onEvent?: (event: AgentEvent) => void): UseEventStream {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
    setError(null);
    setEvents([]);
  }, []);

  const consume = useCallback(async (response: Response) => {
    if (!response.ok || !response.body) {
      throw new Error(`Stream HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sepIndex = buffer.indexOf("\n\n");
      while (sepIndex !== -1) {
        const block = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);
        const event = parseSseBlock(block);
        if (event) {
          setEvents((prev) => [...prev, event]);
          onEventRef.current?.(event);
        }
        sepIndex = buffer.indexOf("\n\n");
      }
    }
  }, []);

  const start = useCallback(
    async (req: StreamRequest) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setEvents([]);
      setError(null);
      setStatus("running");
      try {
        const response = await fetch("/api/generate/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(req),
          signal: controller.signal,
        });
        await consume(response);
        setStatus("done");
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") return;
        setError((err as Error).message);
        setStatus("error");
      }
    },
    [consume],
  );

  const replay = useCallback(
    async (jobId: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setEvents([]);
      setError(null);
      setStatus("running");
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/events.stream`, {
          signal: controller.signal,
        });
        await consume(response);
        setStatus("done");
      } catch (err) {
        if ((err as { name?: string }).name === "AbortError") return;
        setError((err as Error).message);
        setStatus("error");
      }
    },
    [consume],
  );

  return { status, error, events, start, replay, reset };
}

function parseSseBlock(block: string): AgentEvent | null {
  let dataParts: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) {
      dataParts.push(line.slice(5).trimStart());
    }
  }
  if (!dataParts.length) return null;
  try {
    return JSON.parse(dataParts.join("\n")) as AgentEvent;
  } catch {
    return null;
  }
}
