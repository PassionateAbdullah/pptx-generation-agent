import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { PromptForm } from "./components/PromptForm";
import { Timeline } from "./components/Timeline";
import { ComputerPanel } from "./components/ComputerPanel";
import type { SelectedView } from "./components/types";
import { reduceAll } from "./state";
import { useEventStream } from "./useEventStream";

export function App() {
  const stream = useEventStream();
  const job = useMemo(() => reduceAll(stream.events), [stream.events]);
  const [selected, setSelected] = useState<SelectedView>({ kind: "summary" });

  const onSubmit = async (event: FormEvent<HTMLFormElement>, prompt: string, slideCount: number) => {
    event.preventDefault();
    setSelected({ kind: "phase", phaseId: "research" });
    await stream.start({ prompt, slide_count: slideCount });
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">P</span>
          <div>
            <p className="brand-eyebrow">PPTX Generation Agent</p>
            <h1>{job.deckMeta?.title ?? "Live research → slide deck"}</h1>
          </div>
        </div>
        <div className="header-actions">
          <span className={`status-pill status-${stream.status}`}>
            {stream.status === "idle" && "Idle"}
            {stream.status === "running" && "Running"}
            {stream.status === "done" && "Ready"}
            {stream.status === "error" && "Error"}
          </span>
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
      </header>

      <main className="app-main">
        <aside className="left-rail">
          <PromptForm
            disabled={stream.status === "running"}
            onSubmit={onSubmit}
          />
          <Timeline
            job={job}
            selected={selected}
            onSelect={setSelected}
          />
          {stream.error && <div className="error-banner">{stream.error}</div>}
        </aside>

        <section className="right-panel">
          <ComputerPanel job={job} selected={selected} onSelect={setSelected} />
        </section>
      </main>
    </div>
  );
}
