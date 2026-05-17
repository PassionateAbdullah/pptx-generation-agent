import type { ResultEvent, SourceDict } from "../events";
import { trustTierFromUrl } from "../trust";

interface Props {
  result: ResultEvent;
  source?: SourceDict;
}

export function ResultCard({ result, source }: Props) {
  let host = "";
  try {
    host = new URL(result.url).hostname.replace(/^www\./, "");
  } catch {
    host = result.url;
  }
  const trust = source?.trust ?? result.trust ?? trustTierFromUrl(result.url);
  const engines = source?.engines && source.engines.length > 0
    ? source.engines
    : (result.engine ? [result.engine] : []);
  const excerpt = source?.excerpt;
  const sid = source?.source_id ?? result.source_id;

  return (
    <article className="result-card">
      <header className="result-card-head">
        {result.favicon ? (
          <img src={result.favicon} alt="" width={16} height={16} loading="lazy" />
        ) : (
          <span className="favicon-fallback" aria-hidden>
            🔗
          </span>
        )}
        <a className="result-title" href={result.url} target="_blank" rel="noreferrer">
          {result.title}
        </a>
        {sid && <span className="source-id-pill">{sid}</span>}
        <TrustBadge tier={trust} />
      </header>
      <div className="result-engine-row">
        {engines.map((engine) => (
          <span key={engine} className="engine-tag">{engine}</span>
        ))}
      </div>
      <p className="result-snippet">{result.snippet}</p>
      {excerpt && (
        <details className="result-excerpt">
          <summary>Fetched excerpt</summary>
          <p>{excerpt}</p>
        </details>
      )}
      <p className="result-host">{host}</p>
    </article>
  );
}

function TrustBadge({ tier }: { tier: string }) {
  if (!tier || tier === "unknown") return null;
  return <span className={`trust-badge trust-${tier}`}>{tier}</span>;
}
