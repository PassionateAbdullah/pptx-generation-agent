import type { PhaseId } from "../events";

export type SelectedView =
  | { kind: "summary" }
  | { kind: "deck" }
  | { kind: "phase"; phaseId: PhaseId }
  | { kind: "query"; query: string }
  | { kind: "file"; path: string }
  | { kind: "slide"; number: number }
  | { kind: "outline" }
  | { kind: "sources" }
  | { kind: "source"; sourceId: string };
