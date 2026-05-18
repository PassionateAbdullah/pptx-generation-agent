import { useEffect, useMemo, useState } from "react";
import type { SlideData } from "../events";
import { tokensToStyle, useThemes } from "../themes-client";
import { BlockRender } from "./BlockRender";

interface Props {
  slides: SlideData[];
  startIndex: number;
  themeName: string;
  onClose: () => void;
}

export function PresentationView({ slides, startIndex, themeName, onClose }: Props) {
  const [index, setIndex] = useState(() =>
    Math.max(0, Math.min(startIndex, slides.length - 1)),
  );
  const { themes } = useThemes();
  const activeTheme = useMemo(
    () => themes.find((t) => t.name === themeName) || themes[0],
    [themes, themeName],
  );
  const style = useMemo(() => tokensToStyle(activeTheme?.tokens), [activeTheme]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") return onClose();
      if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
        e.preventDefault();
        setIndex((i) => Math.min(slides.length - 1, i + 1));
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        setIndex((i) => Math.max(0, i - 1));
      } else if (e.key === "Home") {
        setIndex(0);
      } else if (e.key === "End") {
        setIndex(slides.length - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose, slides.length]);

  if (!slides.length) {
    return (
      <div className="present-modal" role="dialog" aria-modal="true">
        <div className="present-empty">
          <p>No slides to present.</p>
          <button type="button" className="btn primary" onClick={onClose}>Close</button>
        </div>
      </div>
    );
  }

  const slide = slides[index];
  const blocks = slide.blocks || [];

  return (
    <div className="present-modal" role="dialog" aria-modal="true">
      <div className="present-topbar">
        <span className="present-counter">{index + 1} / {slides.length}</span>
        <span className="present-title">{slide.title}</span>
        <div className="present-actions">
          <button
            type="button"
            className="btn ghost small"
            disabled={index === 0}
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
          >
            ← Prev
          </button>
          <button
            type="button"
            className="btn ghost small"
            disabled={index >= slides.length - 1}
            onClick={() => setIndex((i) => Math.min(slides.length - 1, i + 1))}
          >
            Next →
          </button>
          <button type="button" className="btn ghost small" onClick={onClose}>Close (Esc)</button>
        </div>
      </div>

      <main className="present-stage" style={style}>
        <div className="present-surface slide" data-theme={themeName}>
          <div className="slide-topline">
            <span>{String(slide.number).padStart(2, "0")}</span>
            <span>{slide.eyebrow}</span>
          </div>
          <div className="slide-body">
            {blocks.length > 0
              ? blocks.map((b) => <BlockRender key={b.id} block={b} />)
              : <LegacyFallback slide={slide} />}
          </div>
        </div>
      </main>

      <nav className="present-thumbs" aria-label="Slides">
        {slides.map((s, i) => (
          <button
            key={s.id || s.number}
            type="button"
            className={`thumb ${i === index ? "active" : ""}`}
            onClick={() => setIndex(i)}
            title={s.title}
          >
            <span className="thumb-num">{s.number}</span>
            <span className="thumb-title">{s.title}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function LegacyFallback({ slide }: { slide: SlideData }) {
  return (
    <>
      {slide.eyebrow && <p className="eyebrow">{slide.eyebrow}</p>}
      <h2>{slide.title}</h2>
      {slide.subtitle && <p className="subtitle">{slide.subtitle}</p>}
      {slide.bullets.length > 0 && (
        <ul>{slide.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
      )}
      {slide.metrics.length > 0 && (
        <div className="metric-row">
          {slide.metrics.map((m, i) => (
            <div className="metric" key={i}>
              <strong>{m.value}</strong>
              <span>{m.label}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
