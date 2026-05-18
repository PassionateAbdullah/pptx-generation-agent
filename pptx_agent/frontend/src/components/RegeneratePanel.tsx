import { useState } from "react";
import type { SlideData } from "../events";

interface Props {
  jobId: string;
  slideNumber: number;
  onUpdated: (slide: SlideData) => void;
}

const PRESETS: Array<{ label: string; instruction: string }> = [
  { label: "Shorter", instruction: "Shorten this slide. Trim bullets." },
  { label: "More numbers", instruction: "More numbers and concrete data." },
  { label: "Less corporate", instruction: "Less corporate, more human voice." },
  { label: "Add chart", instruction: "Add a chart showing data." },
  { label: "Add image", instruction: "Add an image for visual context." },
];

export function RegeneratePanel({ jobId, slideNumber, onUpdated }: Props) {
  const [instruction, setInstruction] = useState("");
  const [refresh, setRefresh] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (preset?: string) => {
    const body = preset || instruction.trim();
    if (!body && !refresh) {
      setError("Add an instruction or check 'refresh research'.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/jobs/${encodeURIComponent(jobId)}/slides/${slideNumber}/regenerate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instruction: body, refresh_research: refresh }),
        },
      );
      const data = await r.json();
      if (data.error) throw new Error(data.error);
      onUpdated(data.slide as SlideData);
      setInstruction("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="regen-panel">
      <textarea
        className="regen-input"
        rows={3}
        placeholder="e.g. 'Add a chart of user growth and shorten the bullets'"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        disabled={busy}
      />
      <label className="regen-toggle">
        <input
          type="checkbox"
          checked={refresh}
          onChange={(e) => setRefresh(e.target.checked)}
          disabled={busy}
        />
        <span>Re-search the web for this slide</span>
      </label>
      <div className="regen-presets">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="btn ghost small"
            onClick={() => submit(p.instruction)}
            disabled={busy}
          >
            {p.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="btn primary small block"
        onClick={() => submit()}
        disabled={busy}
      >
        {busy ? "Regenerating…" : "Regenerate this slide"}
      </button>
      {error && <p className="muted small" style={{ color: "var(--danger)" }}>{error}</p>}
    </div>
  );
}
