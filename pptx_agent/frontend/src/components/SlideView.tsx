import type { JobState } from "../state";
import type { SelectedView } from "./types";

interface Props {
  job: JobState;
  number: number;
  onSelect?: (view: SelectedView) => void;
  onEdit?: (number: number) => void;
  onPresent?: (startIndex: number) => void;
}

export function SlideView({ job, number, onSelect, onEdit, onPresent }: Props) {
  const slide = job.slides.get(number);
  if (!slide) return <p className="muted">Slide not yet drafted.</p>;
  const citations = job.citationsBySlide.get(number) ?? slide.citations ?? [];
  const orderedNumbers = Array.from(job.slides.keys()).sort((a, b) => a - b);
  const presentIndex = orderedNumbers.indexOf(number);
  return (
    <div className="slide-detail">
      <header>
        <span className="slide-num">{slide.number}/{job.slideCount}</span>
        <h2>{slide.title}</h2>
        <span className="layout-tag">{slide.layout}</span>
        {onEdit && job.jobId && (
          <button type="button" className="btn small primary" onClick={() => onEdit(number)}>
            Edit slide
          </button>
        )}
        {onPresent && presentIndex >= 0 && (
          <button type="button" className="btn small ghost" onClick={() => onPresent(presentIndex)}>
            Present from here
          </button>
        )}
      </header>
      {slide.subtitle && <p className="lead">{slide.subtitle}</p>}
      {slide.bullets.length > 0 && (
        <ul className="bullet-list">
          {slide.bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
      {citations.length > 0 && (
        <section className="cite-row">
          <span className="muted">Sources:</span>
          {citations.map((sid) => {
            const source = job.sourcesById.get(sid);
            return (
              <button
                key={sid}
                type="button"
                className="cite-pill"
                onClick={() => onSelect?.({ kind: "source", sourceId: sid })}
                title={source?.title || sid}
              >
                {sid}
              </button>
            );
          })}
        </section>
      )}
      {slide.metrics.length > 0 && (
        <div className="metric-row">
          {slide.metrics.map((m, i) => (
            <div key={i} className="metric">
              <strong>{m.value}</strong>
              <span>{m.label}</span>
            </div>
          ))}
        </div>
      )}
      {slide.speaker_notes && (
        <section className="speaker-notes">
          <h3>Speaker notes</h3>
          <p>{slide.speaker_notes}</p>
        </section>
      )}
    </div>
  );
}
