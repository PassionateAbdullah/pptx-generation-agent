import { useState } from "react";

interface ImageSearchResult {
  title: string;
  url: string;
  thumbnail_url: string;
  source?: string;
  width?: number;
  height?: number;
}

interface DownloadResult {
  filename: string;
  local_url: string;
  mime: string;
  size: number;
  sha: string;
  source_url: string;
}

interface Props {
  props: Record<string, unknown>;
  onChange: (p: Record<string, unknown>) => void;
  jobId?: string;
}

export function ImageBlockEditor({ props, onChange, jobId }: Props) {
  const src = String(props.src || "");
  const alt = String(props.alt || "");
  const caption = String(props.caption || "");

  const [query, setQuery] = useState(alt || "");
  const [results, setResults] = useState<ImageSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadingUrl, setDownloadingUrl] = useState<string | null>(null);
  const [paste, setPaste] = useState("");

  const search = async () => {
    setError(null);
    if (!query.trim()) return;
    setSearching(true);
    try {
      const r = await fetch(`/api/images?q=${encodeURIComponent(query)}&n=12`);
      const data = await r.json();
      if (data.error) {
        setError(data.error);
        setResults([]);
      } else {
        setResults(data.results || []);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  };

  const pick = async (imageUrl: string, title?: string) => {
    if (!jobId) {
      // No job — just set the URL directly. Will not embed in PPTX (external URL).
      onChange({ ...props, src: imageUrl, alt: title || alt });
      return;
    }
    setDownloadingUrl(imageUrl);
    setError(null);
    try {
      const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/images`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: imageUrl }),
      });
      const data: DownloadResult & { error?: string } = await r.json();
      if (data.error) throw new Error(data.error);
      onChange({ ...props, src: data.local_url, alt: title || alt });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDownloadingUrl(null);
    }
  };

  const clearImage = () => onChange({ ...props, src: "" });

  return (
    <div className="image-edit">
      <div className="image-preview">
        {src ? (
          <img src={src} alt={alt} />
        ) : (
          <div className="image-placeholder">No image yet — search or paste URL below.</div>
        )}
      </div>

      <div className="image-controls">
        <div className="image-search-row">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); search(); } }}
            placeholder="search images, e.g. 'solar panels rural'"
          />
          <button type="button" className="btn small primary" onClick={search} disabled={searching || !query.trim()}>
            {searching ? "Searching…" : "Search"}
          </button>
          {src && (
            <button type="button" className="btn small ghost" onClick={clearImage}>Clear</button>
          )}
        </div>

        {error && <p className="muted small image-error">Error: {error}</p>}
        {results.length === 0 && !searching && !error && (
          <p className="muted small">
            Tip: use a SearXNG instance for free image search (set <code>SEARCH_PROVIDER=searxng</code>).
            Or paste a direct image URL below.
          </p>
        )}

        {results.length > 0 && (
          <ol className="image-results">
            {results.map((r, i) => (
              <li key={`${r.url}-${i}`}>
                <button
                  type="button"
                  className={`image-thumb ${downloadingUrl === r.url ? "downloading" : ""}`}
                  onClick={() => pick(r.url, r.title)}
                  disabled={!!downloadingUrl}
                  title={r.title || r.url}
                >
                  <img src={r.thumbnail_url || r.url} alt={r.title} loading="lazy" />
                  {downloadingUrl === r.url && <span className="thumb-loading">Embedding…</span>}
                </button>
                {r.source && <span className="image-source">{r.source}</span>}
              </li>
            ))}
          </ol>
        )}

        <div className="image-paste-row">
          <input
            type="text"
            value={paste}
            onChange={(e) => setPaste(e.target.value)}
            placeholder="paste direct image URL (jpg/png/webp)…"
          />
          <button
            type="button"
            className="btn small primary"
            onClick={() => { if (paste.trim()) { pick(paste.trim()); setPaste(""); } }}
            disabled={!paste.trim() || !!downloadingUrl}
          >
            Use URL
          </button>
        </div>

        <div className="image-meta">
          <label>
            <span>Alt</span>
            <input
              type="text"
              value={alt}
              onChange={(e) => onChange({ ...props, alt: e.target.value })}
              placeholder="describe the image"
            />
          </label>
          <label>
            <span>Caption</span>
            <input
              type="text"
              value={caption}
              onChange={(e) => onChange({ ...props, caption: e.target.value })}
              placeholder="optional caption"
            />
          </label>
        </div>
      </div>
    </div>
  );
}
