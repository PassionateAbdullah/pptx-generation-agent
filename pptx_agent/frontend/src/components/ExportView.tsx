import type { JobState } from "../state";

export function ExportView({ job }: { job: JobState }) {
  return (
    <div className="export-view">
      {job.deckReady ? (
        <>
          <h2>{job.deckReady.title}</h2>
          <p className="muted">{job.deckReady.slide_count} slides ready.</p>
          <div className="cta-row">
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
          {job.deckReady.preview_html && (
            <div
              className="deck-preview"
              dangerouslySetInnerHTML={{ __html: job.deckReady.preview_html }}
            />
          )}
        </>
      ) : (
        <p className="muted">Deck not ready yet.</p>
      )}
    </div>
  );
}
