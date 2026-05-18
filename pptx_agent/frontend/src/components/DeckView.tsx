/**
 * DeckView: vertical strip of every drafted slide rendered in place.
 *
 * Phase 12.5 (UX gap fill): when generation finishes the right panel shows
 * all slides 1..N stacked top-to-bottom so the user can scroll the whole
 * deck inline without flipping through timeline cards. Each slide is
 * clickable → opens the slide editor at that slide.
 */

import { useMemo } from "react";
import type { JobState } from "../state";
import { tokensToStyle, useThemes } from "../themes-client";
import { BlockRender } from "./BlockRender";

interface Props {
  job: JobState;
  onEditSlide?: (n: number) => void;
  onPresent?: (startIndex: number) => void;
}

export function DeckView({ job, onEditSlide, onPresent }: Props) {
  const { themes } = useThemes();
  const themeName = (job.deckMeta as { theme?: string } | null)?.theme || "slate";
  const activeTheme = themes.find((t) => t.name === themeName) || themes[0];
  const surfaceStyle = useMemo(() => tokensToStyle(activeTheme?.tokens), [activeTheme]);

  const orderedSlides = useMemo(() => {
    return Array.from(job.slides.values()).sort((a, b) => a.number - b.number);
  }, [job.slides]);

  if (orderedSlides.length === 0) {
    return <p className="muted">No slides drafted yet. Submit a prompt to start.</p>;
  }

  return (
    <div className="deck-view" style={surfaceStyle}>
      <div className="deck-view-header">
        <h2>{job.deckMeta?.title || job.topic || "Deck"}</h2>
        <span className="muted">{orderedSlides.length} slides · click any to edit</span>
        {onPresent && (
          <button type="button" className="btn ghost small" onClick={() => onPresent(0)}>
            Present from start
          </button>
        )}
      </div>
      <ol className="deck-strip">
        {orderedSlides.map((slide, i) => {
          const variant = ((slide as { accent_variant?: number }).accent_variant ?? (slide.number - 1)) % 4;
          const blocks = slide.blocks || [];
          return (
            <li key={slide.id || slide.number} className="deck-strip-item">
              <article
                className={`deck-slide slide-accent-${variant}`}
                data-theme={themeName}
                onClick={() => onEditSlide?.(slide.number)}
                onDoubleClick={() => onPresent?.(i)}
                title="Click to edit · double-click to present from here"
              >
                <header className="deck-slide-topline">
                  <span className="deck-slide-num">{String(slide.number).padStart(2, "0")}</span>
                  <span className="deck-slide-eyebrow">{slide.eyebrow}</span>
                  <span className="muted small">{slide.layout}</span>
                </header>
                <div className="deck-slide-body">
                  {blocks.length > 0
                    ? blocks.map((b) => <BlockRender key={b.id} block={b} />)
                    : (
                      <>
                        {slide.title && <h2>{slide.title}</h2>}
                        {slide.subtitle && <p className="subtitle">{slide.subtitle}</p>}
                        {slide.bullets.length > 0 && (
                          <ul>{slide.bullets.map((b, ix) => <li key={ix}>{b}</li>)}</ul>
                        )}
                      </>
                    )}
                </div>
                <div className="deck-slide-actions">
                  <button type="button" className="btn small primary" onClick={(e) => { e.stopPropagation(); onEditSlide?.(slide.number); }}>
                    Edit
                  </button>
                </div>
              </article>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
