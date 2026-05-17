import type { JobState } from "../state";
import { ResultCard } from "./ResultCard";

export function ResearchView({ job }: { job: JobState }) {
  if (!job.research.groups.length && !job.research.insights.length) {
    return <p className="muted">Research has not started.</p>;
  }
  return (
    <div className="research-view">
      <div className="research-meta">
        <span className="chip">Provider: {job.research.provider || "—"}</span>
        <span className="chip">Queries: {job.research.queries.length}</span>
        <span className="chip">Sources: {job.research.sources.length}</span>
      </div>
      {job.research.groups.map((group) => (
        <section key={`${group.index}-${group.query}`} className="research-group">
          <header className="research-group-header">
            <span className="badge">{group.index}/{group.total}</span>
            <strong>{group.query}</strong>
            <span className="muted">{group.results.length} results</span>
          </header>
          {group.summary && (
            <div className="engine-badges">
              {Object.entries(group.summary.engines).map(([engine, count]) => (
                <span key={engine} className="engine-badge">
                  {engine} · {count}
                </span>
              ))}
              {group.summary.unresponsive.length > 0 && (
                <span className="engine-badge danger">
                  {group.summary.unresponsive.length} unresponsive
                </span>
              )}
            </div>
          )}
          <ul className="result-list">
            {group.results.map((result, idx) => {
              const source = job.research.sources.find((s) => s.url === result.url);
              return (
                <li key={`${result.url}-${idx}`}>
                  <ResultCard result={result} source={source} />
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {job.research.insights.length > 0 && (
        <section className="research-insights">
          <h3>Insights</h3>
          <ul>
            {job.research.insights.map((insight, idx) => (
              <li key={idx}>{insight}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
