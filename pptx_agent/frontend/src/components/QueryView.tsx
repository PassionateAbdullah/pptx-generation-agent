import type { JobState } from "../state";
import { ResultCard } from "./ResultCard";

export function QueryView({ job, query }: { job: JobState; query: string }) {
  const group = job.research.groups.find((g) => g.query === query);
  if (!group) return <p className="muted">No data for this query yet.</p>;

  return (
    <div className="query-view">
      <div className="query-head">
        <span className="badge">{group.index}/{group.total}</span>
        <h2>{group.query}</h2>
      </div>
      {group.summary && (
        <div className="engine-badges">
          {Object.entries(group.summary.engines).map(([engine, count]) => (
            <span key={engine} className="engine-badge">
              {engine} · {count}
            </span>
          ))}
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
      {group.summary && group.summary.unresponsive.length > 0 && (
        <details className="unresponsive-list">
          <summary>{group.summary.unresponsive.length} unresponsive engines</summary>
          <ul>
            {group.summary.unresponsive.map((entry, idx) => (
              <li key={idx}>
                <strong>{entry[0]}</strong> — {entry[1] ?? "no reason"}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
