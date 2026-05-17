import type { JobState } from "../state";

export function OutlineView({ job }: { job: JobState }) {
  if (!job.outline.length) {
    return <p className="muted">Outline not generated yet.</p>;
  }
  return (
    <div className="outline-view">
      {job.deckMeta && (
        <header className="outline-head">
          <h2>{job.deckMeta.title}</h2>
          {job.deckMeta.subtitle && <p className="muted">{job.deckMeta.subtitle}</p>}
        </header>
      )}
      <ol className="outline-list">
        {job.outline.map((slide) => (
          <li key={slide.number}>
            <span className="outline-num">{String(slide.number).padStart(2, "0")}</span>
            <div className="outline-body">
              <strong>{slide.title}</strong>
              {slide.subtitle && <span className="muted">{slide.subtitle}</span>}
              <span className="layout-tag">{slide.layout}</span>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
