import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { PromptForm } from "./components/PromptForm";
import { PresentationView } from "./components/PresentationView";
import { SlideEditor } from "./components/SlideEditor";
import { Timeline } from "./components/Timeline";
import { ComputerPanel } from "./components/ComputerPanel";
import type { SelectedView } from "./components/types";
import type { SlideData } from "./events";
import { reduceAll } from "./state";
import { useEventStream } from "./useEventStream";

export function App() {
  const stream = useEventStream();
  const baseJob = useMemo(() => reduceAll(stream.events), [stream.events]);
  const [selected, setSelected] = useState<SelectedView>({ kind: "summary" });
  const [theme, setTheme] = useState<string>("slate");
  const [editingSlide, setEditingSlide] = useState<number | null>(null);
  const [presentingFromIndex, setPresentingFromIndex] = useState<number | null>(null);
  // Optimistic local edits keyed by slide number. Overlay on top of stream-derived state.
  const [localSlideOverrides, setLocalSlideOverrides] = useState<Map<number, SlideData>>(new Map());

  // Reset overrides when a new job starts (jobId changes).
  useEffect(() => {
    setLocalSlideOverrides(new Map());
  }, [baseJob.jobId]);

  const job = useMemo(() => {
    if (localSlideOverrides.size === 0) return baseJob;
    const merged = new Map(baseJob.slides);
    for (const [num, slide] of localSlideOverrides.entries()) {
      merged.set(num, slide);
    }
    return { ...baseJob, slides: merged };
  }, [baseJob, localSlideOverrides]);

  const activeTheme = (job.deckMeta as { theme?: string } | null)?.theme || theme;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", activeTheme);
  }, [activeTheme]);

  // Auto-switch to deck view when generation completes and at least one slide drafted.
  useEffect(() => {
    if (stream.status === "done" && job.slides.size > 0 && selected.kind !== "deck" && selected.kind !== "slide") {
      setSelected({ kind: "deck" });
    }
  }, [stream.status, job.slides.size, selected.kind]);

  const onSubmit = async (
    event: FormEvent<HTMLFormElement>,
    prompt: string,
    slideCount: number,
    pickedTheme: string,
  ) => {
    event.preventDefault();
    setSelected({ kind: "phase", phaseId: "research" });
    await stream.start({ prompt, slide_count: slideCount, theme: pickedTheme });
  };

  const editingSlideData = editingSlide !== null ? job.slides.get(editingSlide) ?? null : null;

  const handleLocalSlideChange = (slide: SlideData) => {
    setLocalSlideOverrides((prev) => {
      const next = new Map(prev);
      next.set(slide.number, slide);
      return next;
    });
  };

  return (
    <div className="app-shell" data-theme={activeTheme}>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">P</span>
          <div>
            <p className="brand-eyebrow">PPTX Generation Agent</p>
            <h1>{job.deckMeta?.title ?? "Live research → slide deck"}</h1>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-pill status-${stream.status}`}>
            {stream.status === "idle" && "Idle"}
            {stream.status === "running" && "Running"}
            {stream.status === "done" && "Ready"}
            {stream.status === "error" && "Error"}
          </span>
          {job.slides.size > 0 && (
            <button
              type="button"
              className="btn ghost"
              onClick={() => setPresentingFromIndex(0)}
            >
              Present
            </button>
          )}
          {job.downloadUrl && (
            <a className="btn primary" href={job.downloadUrl} target="_blank" rel="noreferrer">
              Download PPTX
            </a>
          )}
          {job.htmlUrl && (
            <a className="btn ghost" href={job.htmlUrl} target="_blank" rel="noreferrer">
              Open HTML
            </a>
          )}
        </div>
      </header>

      <main className="app-main">
        <aside className="left-rail">
          <PromptForm
            disabled={stream.status === "running"}
            onSubmit={onSubmit}
            theme={theme}
            onThemeChange={setTheme}
          />
          <Timeline
            job={job}
            selected={selected}
            onSelect={setSelected}
          />
          {stream.error && <div className="error-banner">{stream.error}</div>}
        </aside>

        <section className="right-panel">
          <ComputerPanel
            job={job}
            selected={selected}
            onSelect={setSelected}
            onEditSlide={(n) => setEditingSlide(n)}
            onPresent={(start) => setPresentingFromIndex(start)}
          />
        </section>
      </main>

      {editingSlideData && job.jobId && (
        <SlideEditor
          jobId={job.jobId}
          slide={editingSlideData}
          themeName={activeTheme}
          onClose={() => setEditingSlide(null)}
          onLocalChange={handleLocalSlideChange}
        />
      )}

      {presentingFromIndex !== null && job.slides.size > 0 && (
        <PresentationView
          slides={Array.from(job.slides.values()).sort((a, b) => a.number - b.number)}
          startIndex={presentingFromIndex}
          themeName={activeTheme}
          onClose={() => setPresentingFromIndex(null)}
        />
      )}
    </div>
  );
}
