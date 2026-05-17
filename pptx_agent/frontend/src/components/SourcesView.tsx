import type { JobState } from "../state";
import { trustTierFromUrl } from "../trust";
import type { SelectedView } from "./types";

interface Props {
  job: JobState;
  highlightSourceId?: string;
  onSelect: (view: SelectedView) => void;
}

export function SourcesView({ job, highlightSourceId, onSelect }: Props) {
  if (!job.research.sources.length) {
    return <p className="muted">No sources yet.</p>;
  }
  const sorted = [...job.research.sources].sort((a, b) => {
    const ca = (job.slidesBySource.get(a.source_id ?? "") ?? []).length;
    const cb = (job.slidesBySource.get(b.source_id ?? "") ?? []).length;
    return cb - ca;
  });

  return (
    <div className="sources-view">
      <p className="muted">
        {job.research.sources.length} unique sources · {job.slidesBySource.size} cited by slides
      </p>
      <ul className="sources-list">
        {sorted.map((source) => {
          const sid = source.source_id ?? "";
          const cited = job.slidesBySource.get(sid) ?? [];
          const trust = source.trust ?? trustTierFromUrl(source.url);
          const engines = source.engines ?? (source.engine ? [source.engine] : []);
          const isHighlight = sid && sid === highlightSourceId;
          return (
            <li key={sid || source.url}>
              <button
                type="button"
                className={`source-card${isHighlight ? " highlight" : ""}`}
                onClick={() => sid && onSelect({ kind: "source", sourceId: sid })}
              >
                <header>
                  {sid && <span className="source-id-pill">{sid}</span>}
                  <span className="source-title">{source.title || source.url}</span>
                  <TrustBadge tier={trust} />
                </header>
                <p className="result-host">{hostOf(source.url)}</p>
                <div className="result-engine-row">
                  {engines.map((engine) => (
                    <span key={engine} className="engine-tag">{engine}</span>
                  ))}
                </div>
                {source.excerpt && <p className="result-snippet">{truncate(source.excerpt, 220)}</p>}
                {!source.excerpt && source.snippet && (
                  <p className="result-snippet">{truncate(source.snippet, 220)}</p>
                )}
                <footer className="cited-row">
                  {cited.length > 0 ? (
                    <>
                      <span className="muted">Cited by:</span>
                      {cited.map((n) => (
                        <button
                          key={n}
                          type="button"
                          className="cite-pill"
                          onClick={(event) => {
                            event.stopPropagation();
                            onSelect({ kind: "slide", number: n });
                          }}
                        >
                          slide {n}
                        </button>
                      ))}
                    </>
                  ) : (
                    <span className="muted">Not cited by any slide.</span>
                  )}
                </footer>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TrustBadge({ tier }: { tier: string }) {
  if (!tier || tier === "unknown") return null;
  return <span className={`trust-badge trust-${tier}`}>{tier}</span>;
}

function truncate(text: string, max: number) {
  if (!text) return "";
  return text.length <= max ? text : text.slice(0, max - 1).trimEnd() + "…";
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
