import type { JobState } from "../state";
import type { SelectedView } from "./types";

interface Props {
  job: JobState;
  onSelect?: (view: SelectedView) => void;
}

export function ContentView({ job, onSelect }: Props) {
  const slideNumbers = Array.from(job.slides.keys()).sort((a, b) => a - b);
  if (!slideNumbers.length) {
    return <p className="muted">Slide content not generated yet.</p>;
  }
  return (
    <div className="content-view">
      {slideNumbers.map((num) => {
        const slide = job.slides.get(num);
        if (!slide) return null;
        const citations = job.citationsBySlide.get(num) ?? slide.citations ?? [];
        return (
          <article key={num} className="slide-card">
            <header>
              <button
                type="button"
                className="slide-num as-button"
                onClick={() => onSelect?.({ kind: "slide", number: num })}
              >
                {num}/{job.slideCount}
              </button>
              <strong>{slide.title}</strong>
              <span className="layout-tag">{slide.layout}</span>
            </header>
            {slide.subtitle && <p className="muted">{slide.subtitle}</p>}
            {slide.bullets.length > 0 && (
              <ul className="bullet-list">
                {slide.bullets.map((bullet, idx) => (
                  <li key={idx}>{bullet}</li>
                ))}
              </ul>
            )}
            {citations.length > 0 && (
              <div className="cite-row">
                <span className="muted">Sources:</span>
                {citations.map((sid) => (
                  <button
                    key={sid}
                    type="button"
                    className="cite-pill"
                    onClick={() => onSelect?.({ kind: "source", sourceId: sid })}
                  >
                    {sid}
                  </button>
                ))}
              </div>
            )}
            {slide.metrics.length > 0 && (
              <div className="metric-row">
                {slide.metrics.map((m, idx) => (
                  <div key={idx} className="metric">
                    <strong>{m.value}</strong>
                    <span>{m.label}</span>
                  </div>
                ))}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
