import type { JobState } from "../state";

export function FileView({ job, path }: { job: JobState; path: string }) {
  const file = job.files.find((f) => f.path === path);
  if (!file) return <p className="muted">File not yet written.</p>;
  return (
    <div className="file-view">
      <header className="file-head">
        <strong>{file.path}</strong>
        {file.url && (
          <a className="muted-link" href={file.url} target="_blank" rel="noreferrer">
            open in new tab
          </a>
        )}
      </header>
      {file.content ? (
        <pre className="file-preview large">{file.content}</pre>
      ) : (
        <p className="muted">No inline preview available.</p>
      )}
    </div>
  );
}
