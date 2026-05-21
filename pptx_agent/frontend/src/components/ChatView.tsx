/**
 * ChatView — single-column conversational layout (Manus-style).
 *
 * Replaces the prior two-panel rail+computer split. Agent activity streams
 * inline as a thread of collapsible task cards: Research → Outline →
 * Content → Render → Slides. Slides themselves render as clickable cards
 * after generation finishes — same pattern Manus uses (1/N, 2/N, ...).
 *
 * No left-right split. Everything lives in one scrollable column so the
 * user sees the agent's "computer" doing work and the resulting deck in
 * the same flow.
 */

import { useMemo, useState } from "react";
import type { PhaseId } from "../events";
import type { JobState } from "../state";
import { tokensToStyle, useThemes } from "../themes-client";
import { SlideOutlineCard } from "./SlideOutlineCard";

interface Props {
  job: JobState;
  onOpenSlide?: (n: number) => void;
  onPresent?: (startIndex: number) => void;
  onClarifyPick?: (slideNumber: number) => void;
}

const PHASE_LABELS: Record<PhaseId, string> = {
  research: "Research",
  outline: "Plan outline",
  content: "Write slide content",
  render: "Render HTML",
  export: "Awaiting PPTX export",
};

export function ChatView({ job, onOpenSlide, onPresent, onClarifyPick }: Props) {
  const { themes } = useThemes();
  const themeName = (job.deckMeta as { theme?: string } | null)?.theme || "betopia";
  const activeTheme = themes.find((t) => t.name === themeName) || themes[0];
  const surfaceStyle = useMemo(() => tokensToStyle(activeTheme?.tokens), [activeTheme]);

  const orderedSlides = useMemo(
    () => Array.from(job.slides.values()).sort((a, b) => a.number - b.number),
    [job.slides],
  );

  if (!job.jobId && job.phaseOrder.length === 0) {
    return (
      <div className="chat-empty">
        <h2>Ready</h2>
        <p className="muted">
          Send a prompt to start. Agent runs research with SearXNG, plans deck,
          drafts each slide, and renders preview. Task cards expand inline below
          your message to show what was retrieved or generated at each step.
        </p>
      </div>
    );
  }

  return (
    <div className="chat-thread" style={surfaceStyle}>
      {job.errors && job.errors.length > 0 && (
        <div className="chat-error-banner" role="alert">
          <strong>Pipeline emitted errors:</strong>
          <ul>
            {job.errors.map((e, i) => (
              <li key={i}><code>{e}</code></li>
            ))}
          </ul>
          {job.errors.some((e) => /LLM/i.test(e)) && (
            <p className="muted small">
              Check <code>.env</code>: <code>LLM_API_KEY</code> (lowercase prefix for OpenRouter
              keys), <code>LLM_BASE_URL</code> (e.g. <code>https://openrouter.ai/api/v1</code>),
              <code>LLM_MODEL</code> (e.g. <code>openai/gpt-4o-mini</code>). Restart the server
              after editing.
            </p>
          )}
        </div>
      )}

      {job.prompt && (
        <div className="chat-user-msg">
          <div className="chat-bubble">{job.prompt}</div>
        </div>
      )}

      <div className="chat-agent-msg">
        <div className="chat-agent-intro">
          <strong>Agent</strong>
          <span className="muted small">
            running pipeline — click any step to expand
          </span>
        </div>

        {job.phaseOrder.map((phaseId) => (
          <TaskCard key={phaseId} job={job} phaseId={phaseId} />
        ))}

        {job.editFeed && job.editFeed.length > 0 && (
          <ul className="edit-feed">
            {job.editFeed.map((entry, i) => (
              <li key={i} className={`edit-feed-row edit-feed-${entry.kind}`}>
                <span className="edit-feed-icon" aria-hidden>
                  {entry.kind === "intent" && "🎯"}
                  {entry.kind === "edit" && "✏️"}
                  {entry.kind === "query" && "🔍"}
                  {entry.kind === "clarify" && "❓"}
                  {entry.kind === "redirect" && "↻"}
                </span>
                <span className="edit-feed-text">{entry.text}</span>
                {entry.url && (
                  <a
                    className="edit-feed-link"
                    href={entry.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    open
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}

        {job.pendingClarify && (
          <div className="clarify-card" role="dialog" aria-label="Which slide?">
            <p className="clarify-question">{job.pendingClarify.question}</p>
            <div className="clarify-chips">
              {job.pendingClarify.slides.map((s) => (
                <button
                  key={s.number}
                  type="button"
                  className="clarify-chip"
                  onClick={() => onClarifyPick?.(s.number)}
                  title={s.title}
                >
                  <span className="clarify-chip-num">{s.number}</span>
                  <span className="clarify-chip-title">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {orderedSlides.length > 0 && (
          <SlideOutlineCard
            deckTitle={job.deckMeta?.title || `${orderedSlides.length}-slide deck`}
            slides={orderedSlides}
            onOpenSlide={onOpenSlide}
            onPresent={onPresent}
          />
        )}
      </div>
    </div>
  );
}

function TaskCard({ job, phaseId }: { job: JobState; phaseId: PhaseId }) {
  const phase = job.phases[phaseId];
  const [open, setOpen] = useState(false);
  if (!phase) return null;

  const status = phase.ended ? "done" : "running";
  const icon = phase.ended ? "✓" : "⟳";
  const label = phase.label || PHASE_LABELS[phaseId] || phaseId;
  const summary = summarize(job, phaseId);
  const hasContent = canExpand(job, phaseId);

  return (
    <div className={`task-card task-${status}`}>
      <button
        type="button"
        className="task-card-head"
        onClick={() => hasContent && setOpen(!open)}
        disabled={!hasContent}
      >
        <span className={`task-icon ${status}`}>{icon}</span>
        <span className="task-label">{label}</span>
        <span className="task-summary muted small">{summary}</span>
        {hasContent && <span className="task-toggle muted">{open ? "▼" : "▶"}</span>}
      </button>
      {open && hasContent && (
        <div className="task-card-body">
          <TaskBody job={job} phaseId={phaseId} />
        </div>
      )}
    </div>
  );
}

function summarize(job: JobState, phaseId: PhaseId): string {
  if (phaseId === "research") {
    const q = job.research.queries.length;
    const s = job.research.sources.length;
    return `${job.research.groups.length} / ${q || "?"} queries · ${s} sources`;
  }
  if (phaseId === "outline") return `${job.outline.length} slide outline`;
  if (phaseId === "content") return `${job.slides.size} / ${job.outline.length || job.slideCount} slides drafted`;
  if (phaseId === "render") return `${job.files.length} files written`;
  if (phaseId === "export") return job.downloadUrl ? "Ready to download" : "Pending";
  return "";
}

function canExpand(job: JobState, phaseId: PhaseId): boolean {
  if (phaseId === "research") return job.research.groups.length > 0 || job.research.sources.length > 0;
  if (phaseId === "outline") return job.outline.length > 0;
  if (phaseId === "content") return job.slides.size > 0;
  if (phaseId === "render") return job.files.length > 0;
  if (phaseId === "export") return Boolean(job.downloadUrl);
  return false;
}

function TaskBody({ job, phaseId }: { job: JobState; phaseId: PhaseId }) {
  if (phaseId === "research") {
    return (
      <div className="task-body-research">
        {job.research.groups.length > 0 && (
          <ol className="research-queries">
            {job.research.groups.map((g) => (
              <li key={`${g.index}-${g.query}`}>
                <strong>🔍 {g.query}</strong>
                <span className="muted small">{g.results.length} results</span>
                {g.results.length > 0 && (
                  <ul className="research-results">
                    {g.results.slice(0, 5).map((r, i) => (
                      <li key={i}>
                        <a href={r.url} target="_blank" rel="noreferrer" className="muted-link">
                          {r.title || r.url}
                        </a>
                        <span className="muted small"> · {r.engine}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ol>
        )}
        {job.research.sources.length > 0 && (
          <details className="research-sources" open>
            <summary>
              <strong>📚 Sources ({job.research.sources.length})</strong>
            </summary>
            <ol>
              {job.research.sources.map((s) => (
                <li key={s.source_id || s.url}>
                  <span className="chip">{s.source_id}</span>
                  <a href={s.url} target="_blank" rel="noreferrer" className="muted-link">
                    {s.title}
                  </a>
                  {s.trust && <span className="muted small"> · {s.trust}</span>}
                </li>
              ))}
            </ol>
          </details>
        )}
        {job.research.insights.length > 0 && (
          <details className="research-insights">
            <summary>
              <strong>💡 Synthesized insights ({job.research.insights.length})</strong>
            </summary>
            <ul>
              {job.research.insights.map((i, ix) => <li key={ix}>{i}</li>)}
            </ul>
          </details>
        )}
      </div>
    );
  }

  if (phaseId === "outline") {
    return (
      <ol className="outline-list">
        {job.outline.map((o) => (
          <li key={o.number}>
            <span className="chip">{o.number}</span>
            <strong>{o.title}</strong>
            {o.eyebrow && <span className="muted small"> · {o.eyebrow}</span>}
            {o.subtitle && <p className="muted small">{o.subtitle}</p>}
          </li>
        ))}
      </ol>
    );
  }

  if (phaseId === "content") {
    return (
      <ol className="content-list">
        {Array.from(job.slides.values())
          .sort((a, b) => a.number - b.number)
          .map((s) => (
            <li key={s.number}>
              <span className="chip">{s.number}</span>
              <strong>{s.title}</strong>
              <span className="muted small"> · {s.layout}</span>
              {s.bullets.length > 0 && (
                <span className="muted small"> · {s.bullets.length} bullets</span>
              )}
            </li>
          ))}
      </ol>
    );
  }

  if (phaseId === "render") {
    return (
      <ul className="files-list">
        {job.files.map((f) => (
          <li key={f.path}>
            <strong>{f.path}</strong>
            {f.url && (
              <a className="muted-link" href={f.url} target="_blank" rel="noreferrer">
                open
              </a>
            )}
            {f.content && (
              <pre className="file-preview">{f.content.slice(0, 800)}</pre>
            )}
          </li>
        ))}
      </ul>
    );
  }

  if (phaseId === "export") {
    return (
      <div className="export-body">
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
    );
  }

  return null;
}

