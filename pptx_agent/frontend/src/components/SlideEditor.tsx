import { useEffect, useMemo, useState } from "react";
import type { BlockType, SlideBlock, SlideData } from "../events";
import { tokensToStyle, useThemes } from "../themes-client";
import { useSlidePatch } from "../useSlidePatch";
import { EditorBlock } from "./EditorBlock";
import { RegeneratePanel } from "./RegeneratePanel";

interface Props {
  jobId: string;
  slide: SlideData;
  themeName: string;
  onClose: () => void;
  onLocalChange: (slide: SlideData) => void;
}

interface ImageSearchResult {
  title: string;
  url: string;
  thumbnail_url: string;
  source: string;
  width?: number;
  height?: number;
  mime?: string;
}

const LAYOUTS = [
  "cover", "problem", "solution", "metrics", "market", "architecture",
  "comparison", "roadmap", "team", "ask", "closing",
];

const ADDABLE_BLOCKS: BlockType[] = [
  "heading", "subheading", "paragraph", "bullets", "metric_row",
  "hero_stat", "highlight", "table", "quote", "callout", "image", "chart", "diagram", "spacer",
];

export function SlideEditor({ jobId, slide, themeName, onClose, onLocalChange }: Props) {
  const { themes } = useThemes();
  const [local, setLocal] = useState<SlideData>(slide);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(
    slide.blocks && slide.blocks.length ? slide.blocks[0].id : null,
  );
  const [imageQuery, setImageQuery] = useState("");
  const [imageResults, setImageResults] = useState<ImageSearchResult[]>([]);
  const [imageStatus, setImageStatus] = useState<"idle" | "searching" | "downloading" | "error">("idle");
  const [imageError, setImageError] = useState("");
  const patch = useSlidePatch();

  useEffect(() => {
    setLocal(slide);
  }, [slide]);

  // Flush any pending debounced patch before the editor unmounts.
  // Without this, typing then hitting Esc within 400ms loses the last edit.
  const handleClose = () => {
    patch.flush().finally(onClose);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      // Defensive: flush on unmount in case the parent removed the modal
      // via state change rather than handleClose.
      void patch.flush();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeTheme = themes.find((t) => t.name === (local.layout && (local as { theme?: string }).theme) || t.name === themeName) || themes.find((t) => t.name === themeName);
  const surfaceStyle = useMemo(() => tokensToStyle(activeTheme?.tokens), [activeTheme]);

  const commit = (next: SlideData) => {
    setLocal(next);
    onLocalChange(next);
    patch.send(jobId, next.number, {
      title: next.title,
      subtitle: next.subtitle,
      eyebrow: next.eyebrow,
      layout: next.layout,
      bullets: next.bullets,
      metrics: next.metrics,
      speaker_notes: next.speaker_notes,
      citations: next.citations,
      blocks: next.blocks,
    });
  };

  const updateBlock = (id: string, props: Record<string, unknown>) => {
    const blocks = (local.blocks || []).map((b) => (b.id === id ? { ...b, props } : b));
    commit({ ...local, blocks });
  };

  const selectedBlock = useMemo(
    () => (local.blocks || []).find((b) => b.id === selectedBlockId) || null,
    [local.blocks, selectedBlockId],
  );

  useEffect(() => {
    const block = (local.blocks || []).find((b) => b.id === selectedBlockId);
    if (block?.type === "image") {
      const props = block.props as Record<string, unknown>;
      setImageQuery(String(props.alt || local.title || local.subtitle || ""));
      setImageError("");
    }
  }, [selectedBlockId]);

  const searchImages = async () => {
    const query = imageQuery.trim();
    if (!query) return;
    setImageStatus("searching");
    setImageError("");
    try {
      const response = await fetch(`/api/images?q=${encodeURIComponent(query)}&n=12`);
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "Image search failed");
      setImageResults(Array.isArray(data.results) ? data.results : []);
      setImageStatus("idle");
    } catch (err) {
      setImageResults([]);
      setImageStatus("error");
      setImageError(err instanceof Error ? err.message : "Image search failed");
    }
  };

  const attachImage = async (result: ImageSearchResult) => {
    if (!selectedBlock || selectedBlock.type !== "image") return;
    setImageStatus("downloading");
    setImageError("");
    try {
      const response = await fetch(`/api/jobs/${jobId}/images`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: result.url }),
      });
      const data = await response.json();
      if (!response.ok || data.error || !data.local_url) throw new Error(data.error || "Image download failed");
      const currentProps = selectedBlock.props as Record<string, unknown>;
      updateBlock(selectedBlock.id, {
        ...currentProps,
        src: data.local_url,
        alt: currentProps.alt || result.title || "Slide image",
        caption: currentProps.caption || result.source || result.title || "",
        source_url: result.url,
      });
      setImageStatus("idle");
    } catch (err) {
      setImageStatus("error");
      setImageError(err instanceof Error ? err.message : "Image download failed");
    }
  };

  const deleteBlock = (id: string) => {
    const blocks = (local.blocks || []).filter((b) => b.id !== id);
    commit({ ...local, blocks });
    setSelectedBlockId(blocks[0]?.id ?? null);
  };

  const moveBlock = (id: string, direction: -1 | 1) => {
    const blocks = [...(local.blocks || [])];
    const idx = blocks.findIndex((b) => b.id === id);
    const target = idx + direction;
    if (idx < 0 || target < 0 || target >= blocks.length) return;
    [blocks[idx], blocks[target]] = [blocks[target], blocks[idx]];
    commit({ ...local, blocks });
  };

  const addBlock = (type: BlockType) => {
    const blocks = local.blocks || [];
    const newId = `s${local.number}-b${blocks.length + 1}-${type}`;
    const defaults: Record<BlockType, Record<string, unknown>> = {
      eyebrow: { text: "Eyebrow" },
      heading: { text: "Heading", level: 1 },
      subheading: { text: "Subheading" },
      paragraph: { text: "Body paragraph." },
      bullets: { items: ["Point one", "Point two"] },
      metric_row: { metrics: [{ label: "Label", value: "1" }] },
      quote: { text: "Quote text.", attribution: "" },
      callout: { tone: "info", text: "Callout text." },
      image: { src: "", alt: "", fit: "cover", caption: "" },
      chart: {
        kind: "bar",
        series: [{ label: "Series A", values: [3, 5, 8, 6] }],
        labels: ["Q1", "Q2", "Q3", "Q4"],
        title: "Sample chart",
      },
      diagram: { kind: "flow", nodes: [{ label: "Start" }, { label: "Middle" }, { label: "End" }] },
      spacer: { size: "md" },
      hero_stat: { value: "42%", label: "key metric", trend: "", source_id: "" },
      highlight: { tone: "accent", title: "KEY INSIGHT", text: "Why this matters in one sentence." },
      table: { headers: ["Metric", "Value"], rows: [["Users", "10K"], ["Growth", "+12%"]], caption: "" },
    };
    const newBlock: SlideBlock = { id: newId, type, props: defaults[type] };
    commit({ ...local, blocks: [...blocks, newBlock] });
    setSelectedBlockId(newId);
  };

  return (
    <div className="editor-modal" role="dialog" aria-modal="true">
      <div className="editor-shell" style={surfaceStyle}>
        <header className="editor-header">
          <div>
            <span className="slide-pill">Slide {local.number}</span>
            <select
              value={local.layout}
              onChange={(e) => commit({ ...local, layout: e.target.value })}
              className="layout-select"
            >
              {LAYOUTS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div className="editor-status">
            {patch.status === "saving" && <span className="muted small">Saving…</span>}
            {patch.status === "saved" && <span className="ok small">Saved ✓</span>}
            {patch.status === "error" && <span className="danger small">Save failed: {patch.error}</span>}
            <button type="button" className="btn ghost" onClick={handleClose}>Close (Esc)</button>
          </div>
        </header>

        <div className="editor-body">
          <aside className="editor-left">
            <h3>Blocks</h3>
            <ol className="block-outline">
              {(local.blocks || []).map((b) => (
                <li
                  key={b.id}
                  className={selectedBlockId === b.id ? "selected" : ""}
                  onClick={() => setSelectedBlockId(b.id)}
                >
                  <span className="block-type-tag">{b.type}</span>
                  <span className="block-preview">{summary(b)}</span>
                </li>
              ))}
            </ol>
            <details className="add-block">
              <summary>+ Add block</summary>
              <div className="add-block-grid">
                {ADDABLE_BLOCKS.map((t) => (
                  <button key={t} type="button" onClick={() => addBlock(t)}>{t}</button>
                ))}
              </div>
            </details>
          </aside>

          <main className="editor-stage">
            <div className="editor-surface slide" data-theme={themeName}>
              {(local.blocks || []).map((b, i, arr) => (
                <EditorBlock
                  key={b.id}
                  block={b}
                  selected={selectedBlockId === b.id}
                  onSelect={() => setSelectedBlockId(b.id)}
                  onChange={(props) => updateBlock(b.id, props)}
                  onDelete={() => deleteBlock(b.id)}
                  onMoveUp={() => moveBlock(b.id, -1)}
                  onMoveDown={() => moveBlock(b.id, 1)}
                  isFirst={i === 0}
                  isLast={i === arr.length - 1}
                  jobId={jobId}
                />
              ))}
            </div>
          </main>

          <aside className="editor-right">
            <h3>Regenerate</h3>
            <RegeneratePanel
              jobId={jobId}
              slideNumber={local.number}
              onUpdated={(slide) => { setLocal(slide); onLocalChange(slide); }}
            />
            <h3>Design</h3>
            <label className="form-row">
              <span>Layout</span>
              <select value={local.layout} onChange={(e) => commit({ ...local, layout: e.target.value })}>
                {LAYOUTS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
            <label className="form-row">
              <span>Accent override</span>
              <input
                type="color"
                defaultValue={activeTheme?.tokens.accent || "#3aa0ff"}
                onChange={(e) => {
                  const accent = e.target.value;
                  // Apply visually via style attr on surface; persisted only if user hits "save accent" — simple inline override
                  const surface = document.querySelector(".editor-surface") as HTMLElement | null;
                  if (surface) surface.style.setProperty("--accent", accent);
                }}
              />
            </label>
            <label className="form-row">
              <span>Speaker notes</span>
              <textarea
                rows={4}
                value={local.speaker_notes || ""}
                onChange={(e) => commit({ ...local, speaker_notes: e.target.value })}
              />
            </label>
            {local.citations && local.citations.length > 0 && (
              <div className="form-row">
                <span>Cited sources</span>
                <div className="cite-row">
                  {local.citations.map((sid) => <span key={sid} className="cite-pill">{sid}</span>)}
                </div>
              </div>
            )}
            {selectedBlock?.type === "image" && (
              <ImageSourcePanel
                block={selectedBlock}
                query={imageQuery}
                results={imageResults}
                status={imageStatus}
                error={imageError}
                onQueryChange={setImageQuery}
                onSearch={searchImages}
                onAttach={attachImage}
                onPropsChange={(props) => updateBlock(selectedBlock.id, props)}
              />
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

function ImageSourcePanel({
  block,
  query,
  results,
  status,
  error,
  onQueryChange,
  onSearch,
  onAttach,
  onPropsChange,
}: {
  block: SlideBlock;
  query: string;
  results: ImageSearchResult[];
  status: "idle" | "searching" | "downloading" | "error";
  error: string;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  onAttach: (result: ImageSearchResult) => void;
  onPropsChange: (props: Record<string, unknown>) => void;
}) {
  const props = block.props as Record<string, unknown>;
  return (
    <section className="image-source-panel">
      <h3>Image</h3>
      <label className="form-row">
        <span>Source</span>
        <input
          type="text"
          value={String(props.src || "")}
          onChange={(e) => onPropsChange({ ...props, src: e.target.value })}
          placeholder="/api/jobs/.../media/image.png"
        />
      </label>
      <label className="form-row">
        <span>Alt text</span>
        <input
          type="text"
          value={String(props.alt || "")}
          onChange={(e) => onPropsChange({ ...props, alt: e.target.value })}
          placeholder="Descriptive image text"
        />
      </label>
      <label className="form-row">
        <span>Fit</span>
        <select value={String(props.fit || "cover")} onChange={(e) => onPropsChange({ ...props, fit: e.target.value })}>
          <option value="cover">cover</option>
          <option value="contain">contain</option>
        </select>
      </label>
      <form
        className="image-search"
        onSubmit={(e) => {
          e.preventDefault();
          onSearch();
        }}
      >
        <label className="form-row">
          <span>Search</span>
          <input
            type="text"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="product photo, market, team"
          />
        </label>
        <button type="submit" className="btn ghost small" disabled={status === "searching" || !query.trim()}>
          {status === "searching" ? "Searching..." : "Search images"}
        </button>
      </form>
      {status === "downloading" && <p className="muted small">Downloading image...</p>}
      {error && <p className="danger small">{error}</p>}
      {results.length > 0 && (
        <div className="image-results">
          {results.map((result) => (
            <button
              key={`${result.url}-${result.thumbnail_url}`}
              type="button"
              className="image-result"
              onClick={() => onAttach(result)}
              disabled={status === "downloading"}
              title={result.title || result.source}
            >
              <img src={result.thumbnail_url || result.url} alt="" loading="lazy" />
              <span>{truncate(result.title || result.source || "Image", 42)}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function summary(block: SlideBlock): string {
  const p = block.props as Record<string, unknown>;
  switch (block.type) {
    case "heading":
    case "subheading":
    case "eyebrow":
    case "paragraph":
    case "callout":
    case "quote":
      return truncate(String(p.text || ""), 40);
    case "bullets":
      return truncate(((p.items as string[]) || []).join(" · "), 40);
    case "metric_row":
      return `${((p.metrics as unknown[]) || []).length} metrics`;
    case "image":
      return p.src ? "image set" : "(no source)";
    case "chart":
      return `${p.kind || "bar"} chart`;
    case "diagram":
      return `${p.kind || "flow"} diagram`;
    case "spacer":
      return p.size as string || "md";
    default:
      return block.type;
  }
}

function truncate(text: string, n: number): string {
  if (text.length <= n) return text;
  return text.slice(0, n - 1) + "…";
}
