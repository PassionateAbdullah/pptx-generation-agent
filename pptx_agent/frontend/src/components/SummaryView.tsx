import type { JobState } from "../state";

export function SummaryView({ job }: { job: JobState }) {
  if (job.status === "idle") {
    return (
      <div className="summary-view">
        <h2>Ready</h2>
        <p className="muted">
          Send a prompt to start. The agent will research with SearXNG, plan the deck, write
          per-slide content, and render an HTML preview. Click any timeline card on the left to
          inspect what was retrieved or generated at that step.
        </p>
      </div>
    );
  }
  return (
    <div className="summary-view">
      <h2>{job.deckMeta?.title ?? job.topic ?? "Generating…"}</h2>
      <ul className="summary-stats">
        <li>
          <strong>{job.research.queries.length}</strong>
          <span>queries</span>
        </li>
        <li>
          <strong>{job.research.sources.length}</strong>
          <span>sources</span>
        </li>
        <li>
          <strong>{job.outline.length}</strong>
          <span>outline slides</span>
        </li>
        <li>
          <strong>{job.slides.size}</strong>
          <span>drafted</span>
        </li>
      </ul>
      <p className="muted">Click a phase on the left to see its history.</p>
    </div>
  );
}
