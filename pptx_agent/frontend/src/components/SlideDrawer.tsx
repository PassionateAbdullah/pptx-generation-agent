/**
 * SlideDrawer — right-anchored preview pane (Manus "computer window" style).
 *
 * Two view modes:
 *   - "preview" — iframes the per-slide standalone HTML emitted by the
 *     backend (``/api/jobs/<id>/slide-NN.html``). What the user sees here
 *     is byte-identical to what gets exported.
 *   - "html"    — raw HTML source for the same file, for copy/inspect.
 *
 * Falls back to an inline ``BlockRender`` preview when no jobId is known
 * (e.g. before the deck has been persisted to disk).
 */
import { useEffect, useMemo, useState } from "react";
import type { SlideData } from "../events";
import { BlockRender } from "./BlockRender";

interface Props {
  slide: SlideData;
  themeName: string;
  totalSlides: number;
  startIndex: number;
  jobId: string | null;
  onClose: () => void;
  onOpenEditor: () => void;
  onPresent: () => void;
}

type Mode = "preview" | "html";

export function SlideDrawer({
  slide,
  themeName,
  totalSlides,
  startIndex,
  jobId,
  onClose,
  onOpenEditor,
  onPresent,
}: Props) {
  const [mode, setMode] = useState<Mode>("preview");
  const [htmlSource, setHtmlSource] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);

  const slidePath = useMemo(() => {
    if (!jobId) return null;
    const padded = String(slide.number).padStart(2, "0");
    return `/api/jobs/${encodeURIComponent(jobId)}/slide-${padded}.html`;
  }, [jobId, slide.number]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setHtmlSource(null);
    setSourceError(null);
    if (mode !== "html" || !slidePath) return;
    let cancelled = false;
    fetch(slidePath)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((text) => {
        if (!cancelled) setHtmlSource(text);
      })
      .catch((err) => {
        if (!cancelled) setSourceError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, slidePath]);

  const variant =
    ((slide as { accent_variant?: number }).accent_variant ?? (slide.number - 1)) % 4;
  const blocks = slide.blocks || [];

  return (
    <aside className="slide-drawer" data-theme={themeName} role="dialog" aria-label="Slide preview">
      <header className="slide-drawer-head">
        <div className="slide-drawer-titlewrap">
          <span className="slide-drawer-num">
            {String(slide.number).padStart(2, "0")} / {String(totalSlides).padStart(2, "0")}
          </span>
          <div>
            {slide.eyebrow && <p className="slide-drawer-eyebrow">{slide.eyebrow}</p>}
            <h3 className="slide-drawer-title">{slide.title || `Slide ${slide.number}`}</h3>
          </div>
        </div>
        <div className="slide-drawer-actions">
          <button type="button" className="btn ghost small" onClick={onPresent}>
            ▶ Present
          </button>
          <button type="button" className="btn primary small" onClick={onOpenEditor}>
            Edit
          </button>
          <button
            type="button"
            className="slide-drawer-close"
            onClick={onClose}
            aria-label="Close preview"
          >
            ✕
          </button>
        </div>
      </header>

      <div className="slide-drawer-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "preview"}
          className={`slide-drawer-tab ${mode === "preview" ? "active" : ""}`}
          onClick={() => setMode("preview")}
        >
          Preview
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "html"}
          className={`slide-drawer-tab ${mode === "html" ? "active" : ""}`}
          onClick={() => setMode("html")}
          disabled={!slidePath}
          title={slidePath ? "View slide HTML source" : "HTML not yet rendered"}
        >
          HTML
        </button>
        {slidePath && (
          <a
            className="slide-drawer-tab-link"
            href={slidePath}
            target="_blank"
            rel="noreferrer"
            title="Open standalone HTML in a new tab"
          >
            ↗ open
          </a>
        )}
      </div>

      <div className="slide-drawer-body">
        {mode === "preview" && slidePath && (
          <iframe
            key={slidePath}
            className="slide-drawer-iframe"
            src={slidePath}
            title={`Slide ${slide.number} preview`}
            sandbox="allow-same-origin"
          />
        )}

        {mode === "preview" && !slidePath && (
          <div className={`slide-drawer-stage slide-accent-${variant}`} data-theme={themeName}>
            <div className="slide-drawer-canvas">
              {blocks.length > 0 ? (
                blocks.map((b) => <BlockRender key={b.id} block={b} />)
              ) : (
                <>
                  {slide.title && <h2>{slide.title}</h2>}
                  {slide.subtitle && <p className="subtitle">{slide.subtitle}</p>}
                  {slide.bullets.length > 0 && (
                    <ul>
                      {slide.bullets.map((b, i) => <li key={i}>{b}</li>)}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {mode === "html" && (
          <div className="slide-drawer-source">
            {sourceError && <p className="muted small">Couldn't load HTML: {sourceError}</p>}
            {!sourceError && htmlSource === null && (
              <p className="muted small">Loading…</p>
            )}
            {htmlSource !== null && (
              <pre className="slide-drawer-pre">{htmlSource}</pre>
            )}
          </div>
        )}

        {slide.speaker_notes && (
          <section className="slide-drawer-notes">
            <p className="slide-drawer-section-label">Speaker notes</p>
            <p>{slide.speaker_notes}</p>
          </section>
        )}

        {slide.citations && slide.citations.length > 0 && (
          <section className="slide-drawer-citations">
            <p className="slide-drawer-section-label">Citations</p>
            <ul>
              {slide.citations.map((c) => (
                <li key={c}><span className="chip">{c}</span></li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <footer className="slide-drawer-foot">
        <span className="muted small">
          slide {startIndex + 1} of {totalSlides}
        </span>
      </footer>
    </aside>
  );
}
