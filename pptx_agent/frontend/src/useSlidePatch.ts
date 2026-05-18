import { useCallback, useRef, useState } from "react";
import type { SlideData } from "./events";

export type PatchStatus = "idle" | "saving" | "saved" | "error";

export interface SlidePatchResponse {
  job_id: string;
  slide: SlideData;
  html_url: string;
  download_url: string;
}

interface PendingPatch {
  jobId: string;
  slideNumber: number;
  payload: Record<string, unknown>;
}

/**
 * Debounced PATCH /api/jobs/<jobId>/slides/<n>. Coalesces rapid edits
 * (e.g. typing) into a single request fired ~400ms after the last change.
 */
export function useSlidePatch(): {
  status: PatchStatus;
  error: string | null;
  lastSavedAt: number | null;
  send: (jobId: string, slideNumber: number, payload: Record<string, unknown>) => void;
  flush: () => Promise<void>;
} {
  const [status, setStatus] = useState<PatchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const pendingRef = useRef<PendingPatch | null>(null);
  const timerRef = useRef<number | null>(null);
  const inflightRef = useRef<AbortController | null>(null);

  const dispatch = useCallback(async (): Promise<void> => {
    const pending = pendingRef.current;
    if (!pending) return;
    pendingRef.current = null;
    timerRef.current = null;

    inflightRef.current?.abort();
    const controller = new AbortController();
    inflightRef.current = controller;
    setStatus("saving");
    try {
      const response = await fetch(
        `/api/jobs/${encodeURIComponent(pending.jobId)}/slides/${pending.slideNumber}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(pending.payload),
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
      }
      setStatus("saved");
      setLastSavedAt(Date.now());
      setError(null);
    } catch (err) {
      if ((err as { name?: string }).name === "AbortError") return;
      setError((err as Error).message);
      setStatus("error");
    }
  }, []);

  const send = useCallback(
    (jobId: string, slideNumber: number, payload: Record<string, unknown>) => {
      pendingRef.current = { jobId, slideNumber, payload };
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        void dispatch();
      }, 400);
      setStatus("saving");
    },
    [dispatch],
  );

  const flush = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    await dispatch();
  }, [dispatch]);

  return { status, error, lastSavedAt, send, flush };
}
