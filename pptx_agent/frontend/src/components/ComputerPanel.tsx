import type { JobState } from "../state";
import { ResearchView } from "./ResearchView";
import { QueryView } from "./QueryView";
import { OutlineView } from "./OutlineView";
import { ContentView } from "./ContentView";
import { FileView } from "./FileView";
import { SlideView } from "./SlideView";
import { ExportView } from "./ExportView";
import { SummaryView } from "./SummaryView";
import { SourcesView } from "./SourcesView";
import { DeckView } from "./DeckView";
import type { SelectedView } from "./types";

interface Props {
  job: JobState;
  selected: SelectedView;
  onSelect: (view: SelectedView) => void;
  onEditSlide?: (number: number) => void;
  onPresent?: (startIndex: number) => void;
}

export function ComputerPanel({ job, selected, onSelect, onEditSlide, onPresent }: Props) {
  return (
    <div className="computer-panel">
      <header className="computer-header">
        <span className="computer-dot" />
        <span className="computer-title">{titleFor(job, selected)}</span>
      </header>
      <div className="computer-body">{bodyFor(job, selected, onSelect, onEditSlide, onPresent)}</div>
    </div>
  );
}

function titleFor(job: JobState, view: SelectedView): string {
  switch (view.kind) {
    case "deck":
      return `Deck · ${job.slides.size} slides`;
    case "phase":
      if (view.phaseId === "research") return "Research history";
      if (view.phaseId === "outline") return "Slide outline";
      if (view.phaseId === "content") return "Slide content";
      if (view.phaseId === "render") return "Files";
      if (view.phaseId === "export") return "Export";
      return view.phaseId;
    case "query":
      return `Search · ${view.query}`;
    case "outline":
      return "Slide outline";
    case "file":
      return view.path;
    case "slide":
      return `Slide ${view.number}`;
    case "sources":
      return "Sources bibliography";
    case "source":
      return `Source ${view.sourceId}`;
    default:
      return job.prompt || "Manus's Computer";
  }
}

function bodyFor(
  job: JobState,
  view: SelectedView,
  onSelect: (v: SelectedView) => void,
  onEditSlide?: (n: number) => void,
  onPresent?: (startIndex: number) => void,
) {
  switch (view.kind) {
    case "deck":
      return <DeckView job={job} onEditSlide={onEditSlide} onPresent={onPresent} />;
    case "phase":
      if (view.phaseId === "research") return <ResearchView job={job} />;
      if (view.phaseId === "outline") return <OutlineView job={job} />;
      if (view.phaseId === "content") return <ContentView job={job} onSelect={onSelect} />;
      if (view.phaseId === "render") return <FilesIndex job={job} />;
      if (view.phaseId === "export") return <ExportView job={job} />;
      return null;
    case "query":
      return <QueryView job={job} query={view.query} />;
    case "outline":
      return <OutlineView job={job} />;
    case "file":
      return <FileView job={job} path={view.path} />;
    case "slide":
      return <SlideView job={job} number={view.number} onSelect={onSelect} onEdit={onEditSlide} onPresent={onPresent} />;
    case "sources":
      return <SourcesView job={job} onSelect={onSelect} />;
    case "source":
      return <SourcesView job={job} highlightSourceId={view.sourceId} onSelect={onSelect} />;
    default:
      return <SummaryView job={job} />;
  }
}

function FilesIndex({ job }: { job: JobState }) {
  if (!job.files.length) return <p className="muted">No files written yet.</p>;
  return (
    <ul className="files-list">
      {job.files.map((file) => (
        <li key={file.path}>
          <strong>{file.path}</strong>
          {file.url ? (
            <a className="muted-link" href={file.url} target="_blank" rel="noreferrer">
              open
            </a>
          ) : null}
          {file.content && <pre className="file-preview">{file.content.slice(0, 800)}</pre>}
        </li>
      ))}
    </ul>
  );
}
