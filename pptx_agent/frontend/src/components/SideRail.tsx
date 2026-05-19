/**
 * SideRail — left navigation panel modeled on Manus chat shell.
 *
 * Shows a "New task" button, a "Library" link, and a list of recent jobs
 * read from localStorage. Selecting a job opens its rendered HTML in a new
 * tab (V1) — replay-in-place is a follow-up.
 */
import { useEffect, useState } from "react";

const JOBS_KEY = "pptx_agent_jobs";

export interface JobEntry {
  jobId: string;
  prompt: string;
  ts: number;
  title?: string;
}

export function readJobs(): JobEntry[] {
  try {
    const raw = localStorage.getItem(JOBS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((j) => j && typeof j.jobId === "string");
  } catch {
    return [];
  }
}

export function recordJob(entry: JobEntry) {
  const existing = readJobs();
  const filtered = existing.filter((j) => j.jobId !== entry.jobId);
  filtered.unshift(entry);
  const trimmed = filtered.slice(0, 25);
  try {
    localStorage.setItem(JOBS_KEY, JSON.stringify(trimmed));
    window.dispatchEvent(new CustomEvent("pptx-jobs-changed"));
  } catch {
    /* quota — ignore */
  }
}

interface Props {
  currentJobId: string | null;
  onNewTask: () => void;
}

export function SideRail({ currentJobId, onNewTask }: Props) {
  const [jobs, setJobs] = useState<JobEntry[]>(() => readJobs());

  useEffect(() => {
    const handler = () => setJobs(readJobs());
    window.addEventListener("pptx-jobs-changed", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("pptx-jobs-changed", handler);
      window.removeEventListener("storage", handler);
    };
  }, []);

  return (
    <aside className="side-rail">
      <div className="side-rail-top">
        <button type="button" className="side-rail-new" onClick={onNewTask}>
          <span className="side-rail-plus">+</span>
          <span>New task</span>
        </button>
        <a className="side-rail-link" href="/api/jobs/" target="_blank" rel="noreferrer">
          <span className="side-rail-ico" aria-hidden>📚</span>
          <span>Library</span>
        </a>
      </div>

      <div className="side-rail-section">
        <p className="side-rail-section-label">Recent</p>
        {jobs.length === 0 ? (
          <p className="side-rail-empty muted small">No tasks yet.</p>
        ) : (
          <ul className="side-rail-jobs">
            {jobs.map((j) => (
              <li
                key={j.jobId}
                className={j.jobId === currentJobId ? "current" : ""}
              >
                <a
                  href={`/api/jobs/${encodeURIComponent(j.jobId)}/slides.html`}
                  target="_blank"
                  rel="noreferrer"
                  title={j.prompt}
                >
                  <span className="side-rail-job-title">
                    {j.title || j.prompt.slice(0, 48) || j.jobId}
                  </span>
                  <span className="side-rail-job-meta muted small">
                    {formatTs(j.ts)}
                  </span>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function formatTs(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts);
  const now = Date.now();
  const diffH = (now - ts) / 3_600_000;
  if (diffH < 1) return "just now";
  if (diffH < 24) return `${Math.round(diffH)}h ago`;
  return d.toLocaleDateString();
}
