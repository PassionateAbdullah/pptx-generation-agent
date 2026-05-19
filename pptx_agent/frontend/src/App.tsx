import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ChatView } from "./components/ChatView";
import { PromptForm } from "./components/PromptForm";
import { PresentationView } from "./components/PresentationView";
import { SideRail, recordJob } from "./components/SideRail";
import { SlideDrawer } from "./components/SlideDrawer";
import { SlideEditor } from "./components/SlideEditor";
import type { SlideData } from "./events";
import { reduceAll } from "./state";
import { useEventStream } from "./useEventStream";

export function App() {
  const stream = useEventStream();
  const baseJob = useMemo(() => reduceAll(stream.events), [stream.events]);
  const [theme, setTheme] = useState<string>("betopia");
  const [editingSlide, setEditingSlide] = useState<number | null>(null);
  const [previewingSlide, setPreviewingSlide] = useState<number | null>(null);
  const [presentingFromIndex, setPresentingFromIndex] = useState<number | null>(null);
  const [localSlideOverrides, setLocalSlideOverrides] = useState<Map<number, SlideData>>(new Map());

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

  useEffect(() => {
    if (!job.jobId) return;
    recordJob({
      jobId: job.jobId,
      prompt: job.prompt || "",
      ts: Date.now(),
      title: job.deckMeta?.title || "",
    });
  }, [job.jobId, job.prompt, job.deckMeta?.title]);

  const orderedSlides = useMemo(
    () => Array.from(job.slides.values()).sort((a, b) => a.number - b.number),
    [job.slides],
  );

  const onSubmit = async (
    event: FormEvent<HTMLFormElement>,
    prompt: string,
    slideCount: number,
    pickedTheme: string,
  ) => {
    event.preventDefault();
    await stream.start({ prompt, slide_count: slideCount, theme: pickedTheme });
  };

  const editingSlideData = editingSlide !== null ? job.slides.get(editingSlide) ?? null : null;
  const previewingSlideData =
    previewingSlide !== null ? job.slides.get(previewingSlide) ?? null : null;
  const previewIndex = previewingSlideData
    ? orderedSlides.findIndex((s) => s.number === previewingSlideData.number)
    : -1;

  const handleLocalSlideChange = (slide: SlideData) => {
    setLocalSlideOverrides((prev) => {
      const next = new Map(prev);
      next.set(slide.number, slide);
      return next;
    });
  };

  const handleNewTask = () => {
    setPreviewingSlide(null);
    setEditingSlide(null);
    setPresentingFromIndex(null);
    stream.reset?.();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="app-shell chat-shell" data-theme={activeTheme}>
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">b</span>
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

      <SideRail currentJobId={job.jobId ?? null} onNewTask={handleNewTask} />

      <main className="chat-main">
        <div className="chat-scroll">
          <ChatView
            job={job}
            onOpenSlide={(n) => setPreviewingSlide(n)}
            onPresent={(start) => setPresentingFromIndex(start)}
          />
          {stream.error && <div className="error-banner">{stream.error}</div>}
        </div>

        <div className="chat-composer">
          <PromptForm
            disabled={stream.status === "running"}
            onSubmit={onSubmit}
            theme={theme}
            onThemeChange={setTheme}
          />
        </div>
      </main>

      {previewingSlideData && (
        <SlideDrawer
          slide={previewingSlideData}
          themeName={activeTheme}
          totalSlides={orderedSlides.length}
          startIndex={previewIndex >= 0 ? previewIndex : 0}
          jobId={job.jobId ?? null}
          onClose={() => setPreviewingSlide(null)}
          onOpenEditor={() => {
            setEditingSlide(previewingSlideData.number);
          }}
          onPresent={() => {
            setPresentingFromIndex(previewIndex >= 0 ? previewIndex : 0);
          }}
        />
      )}

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
          slides={orderedSlides}
          startIndex={presentingFromIndex}
          themeName={activeTheme}
          onClose={() => setPresentingFromIndex(null)}
        />
      )}
    </div>
  );
}
