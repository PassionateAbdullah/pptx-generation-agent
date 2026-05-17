import type { PhaseId } from "../events";
import type { JobState } from "../state";
import type { SelectedView } from "./types";

interface Props {
  job: JobState;
  selected: SelectedView;
  onSelect: (view: SelectedView) => void;
}

const PHASE_DESCRIPTIONS: Partial<Record<PhaseId, (job: JobState) => string>> = {
  research: (job) =>
    `${job.research.groups.length} / ${job.research.queries.length || "?"} queries · ${
      job.research.sources.length
    } sources`,
  outline: (job) => `${job.outline.length} slide outline`,
  content: (job) => `${job.slides.size} / ${job.outline.length || job.slideCount} slides drafted`,
  render: (job) => `${job.files.length} files written`,
  export: (job) => (job.downloadUrl ? "Ready to download" : "Pending"),
};

export function Timeline({ job, selected, onSelect }: Props) {
  if (!job.phaseOrder.length) {
    return (
      <div className="timeline empty">
        <p>Send a prompt to start the pipeline.</p>
      </div>
    );
  }

  return (
    <ol className="timeline">
      {job.phaseOrder.map((phaseId) => {
        const phase = job.phases[phaseId];
        if (!phase) return null;
        const active = selected.kind === "phase" && selected.phaseId === phaseId;
        const desc = PHASE_DESCRIPTIONS[phaseId]?.(job) ?? "";
        const statusIcon = phase.ended ? "✓" : "⟳";
        return (
          <li key={phaseId}>
            <button
              type="button"
              className={`timeline-card${active ? " active" : ""}${phase.ended ? " done" : " running"}`}
              onClick={() => onSelect({ kind: "phase", phaseId })}
            >
              <span className="timeline-status">{statusIcon}</span>
              <div className="timeline-body">
                <strong>{phase.label}</strong>
                {desc && <span className="timeline-desc">{desc}</span>}
                {phase.logs.length > 0 && (
                  <span className="timeline-lastlog" title={phase.logs[phase.logs.length - 1]}>
                    {phase.logs[phase.logs.length - 1]}
                  </span>
                )}
              </div>
            </button>
            {phaseId === "outline" && job.outline.length > 0 && (
              <button
                type="button"
                className={`timeline-sub${selected.kind === "outline" ? " active" : ""}`}
                onClick={() => onSelect({ kind: "outline" })}
              >
                Slides outline ({job.outline.length})
              </button>
            )}
            {phaseId === "render" && job.files.length > 0 && (
              <ul className="timeline-files">
                {job.files.map((file) => (
                  <li key={file.path}>
                    <button
                      type="button"
                      className={`timeline-sub${
                        selected.kind === "file" && selected.path === file.path ? " active" : ""
                      }`}
                      onClick={() => onSelect({ kind: "file", path: file.path })}
                    >
                      📄 {file.path}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {phaseId === "research" && job.research.groups.length > 0 && (
              <ul className="timeline-queries">
                {job.research.groups.map((group) => (
                  <li key={`${group.index}-${group.query}`}>
                    <button
                      type="button"
                      className={`timeline-sub${
                        selected.kind === "query" && selected.query === group.query ? " active" : ""
                      }`}
                      onClick={() => onSelect({ kind: "query", query: group.query })}
                    >
                      🔍 {truncate(group.query, 56)} ({group.results.length})
                    </button>
                  </li>
                ))}
                {job.research.sources.length > 0 && (
                  <li>
                    <button
                      type="button"
                      className={`timeline-sub${
                        selected.kind === "sources" || selected.kind === "source" ? " active" : ""
                      }`}
                      onClick={() => onSelect({ kind: "sources" })}
                    >
                      📚 Sources ({job.research.sources.length})
                    </button>
                  </li>
                )}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1) + "…";
}
