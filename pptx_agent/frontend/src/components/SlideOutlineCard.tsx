/**
 * SlideOutlineCard — inline collapsible "Slides outline" panel rendered
 * inside the chat thread (Manus pattern). Shows a numbered list of slide
 * titles with subtitles; clicking a row opens it in the right-side drawer.
 */
import { useState } from "react";
import type { SlideData } from "../events";

interface Props {
  deckTitle: string;
  slides: SlideData[];
  onOpenSlide?: (n: number) => void;
  onPresent?: (startIndex: number) => void;
}

export function SlideOutlineCard({ deckTitle, slides, onOpenSlide, onPresent }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <section className="outline-card">
      <header className="outline-card-head">
        <span className="outline-card-icon" aria-hidden>
          ▦
        </span>
        <div className="outline-card-titlewrap">
          <span className="outline-card-title">Slides outline</span>
          <span className="outline-card-subtitle muted small">{deckTitle}</span>
        </div>
        <div className="outline-card-actions">
          {onPresent && slides.length > 0 && (
            <button type="button" className="btn ghost small" onClick={() => onPresent(0)}>
              ▶ Present
            </button>
          )}
          <button
            type="button"
            className="outline-card-collapse"
            onClick={() => setCollapsed((c) => !c)}
          >
            {collapsed ? "Expand ▾" : "Collapse ▴"}
          </button>
        </div>
      </header>

      {!collapsed && (
        <ol className="outline-card-list">
          {slides.map((slide) => (
            <li key={slide.id || slide.number}>
              <button
                type="button"
                className="outline-row"
                onClick={() => onOpenSlide?.(slide.number)}
                title="Open slide preview"
              >
                <span className="outline-row-num">{slide.number}</span>
                <span className="outline-row-body">
                  <span className="outline-row-title">{slide.title || `Slide ${slide.number}`}</span>
                  {slide.subtitle && (
                    <span className="outline-row-sub muted small">{slide.subtitle}</span>
                  )}
                </span>
                <span className="outline-row-layout muted small">{slide.layout}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
