import type {
  AgentEvent,
  DeckReadyEvent,
  PhaseId,
  ResultEvent,
  SearchSummaryEvent,
  SlideData,
  SlideOutlineEvent,
  SourceDict,
} from "./events";

export interface ResearchQueryGroup {
  query: string;
  index: number;
  total: number;
  results: ResultEvent[];
  summary?: SearchSummaryEvent;
}

export interface ResearchState {
  provider: string;
  queries: string[];
  groups: ResearchQueryGroup[];
  insights: string[];
  sources: SourceDict[];
}

export interface PhaseState {
  id: PhaseId;
  label: string;
  started: boolean;
  ended: boolean;
  logs: string[];
  startedAt?: number;
  endedAt?: number;
}

export interface FileRecord {
  path: string;
  content?: string;
  url?: string;
}

export interface JobState {
  jobId: string | null;
  prompt: string;
  topic: string;
  slideCount: number;
  status: "idle" | "running" | "done" | "error";
  error: string | null;
  errors: string[];

  phases: Record<PhaseId, PhaseState>;
  phaseOrder: PhaseId[];

  research: ResearchState;
  deckMeta: { title: string; subtitle: string; topic: string; theme?: string } | null;
  outline: SlideOutlineEvent[];
  slides: Map<number, SlideData>;
  files: FileRecord[];
  deckReady: DeckReadyEvent | null;
  downloadUrl: string | null;
  htmlUrl: string | null;

  /** index by source_id -> source dict (populated from sources event, patched by source_excerpt) */
  sourcesById: Map<string, SourceDict>;
  /** slide_number -> [source_id, ...] */
  citationsBySlide: Map<number, string[]>;
  /** source_id -> [slide_number, ...] inverse */
  slidesBySource: Map<string, number[]>;
}

export function emptyJob(): JobState {
  return {
    jobId: null,
    prompt: "",
    topic: "",
    slideCount: 0,
    status: "idle",
    error: null,
    errors: [],
    phases: {} as Record<PhaseId, PhaseState>,
    phaseOrder: [],
    research: {
      provider: "",
      queries: [],
      groups: [],
      insights: [],
      sources: [],
    },
    deckMeta: null,
    outline: [],
    slides: new Map(),
    files: [],
    deckReady: null,
    downloadUrl: null,
    htmlUrl: null,
    sourcesById: new Map(),
    citationsBySlide: new Map(),
    slidesBySource: new Map(),
  };
}

const PHASE_LABELS: Record<PhaseId, string> = {
  research: "Research",
  outline: "Write outline",
  content: "Write slide content",
  render: "Render HTML slides",
  export: "Awaiting PPTX export",
};

export function reduce(prev: JobState, event: AgentEvent): JobState {
  const state: JobState = {
    ...prev,
    phases: { ...prev.phases },
    phaseOrder: [...prev.phaseOrder],
    research: { ...prev.research, groups: [...prev.research.groups] },
    outline: prev.outline,
    slides: prev.slides,
    files: prev.files,
    sourcesById: prev.sourcesById,
    citationsBySlide: prev.citationsBySlide,
    slidesBySource: prev.slidesBySource,
  };

  switch (event.type) {
    case "job_start": {
      state.jobId = event.job_id;
      state.prompt = event.prompt;
      state.topic = event.topic;
      state.slideCount = event.slide_count;
      state.status = "running";
      return state;
    }
    case "phase_start": {
      const id = event.id as PhaseId;
      if (!state.phaseOrder.includes(id)) state.phaseOrder.push(id);
      state.phases[id] = {
        id,
        label: event.label || PHASE_LABELS[id] || id,
        started: true,
        ended: false,
        logs: state.phases[id]?.logs ?? [],
        startedAt: event.ts,
      };
      return state;
    }
    case "phase_end": {
      const id = event.id as PhaseId;
      const existing = state.phases[id];
      if (existing) {
        state.phases[id] = { ...existing, ended: true, endedAt: event.ts };
      }
      return state;
    }
    case "provider": {
      state.research = { ...state.research, provider: event.provider };
      return state;
    }
    case "queries": {
      state.research = { ...state.research, queries: event.items };
      return state;
    }
    case "query": {
      const groups = [...state.research.groups];
      groups.push({ query: event.query, index: event.index, total: event.total, results: [] });
      state.research = { ...state.research, groups };
      return state;
    }
    case "result": {
      const groups = state.research.groups.map((g) =>
        g.query === event.query ? { ...g, results: [...g.results, event] } : g,
      );
      state.research = { ...state.research, groups };
      return state;
    }
    case "search_summary": {
      const groups = state.research.groups.map((g) =>
        g.query === event.query ? { ...g, summary: event } : g,
      );
      state.research = { ...state.research, groups };
      return state;
    }
    case "insights": {
      state.research = { ...state.research, insights: event.items };
      return state;
    }
    case "sources": {
      state.research = { ...state.research, sources: event.items };
      const sourcesById = new Map(state.sourcesById);
      for (const item of event.items) {
        if (item.source_id) {
          sourcesById.set(item.source_id, { ...sourcesById.get(item.source_id), ...item });
        }
      }
      state.sourcesById = sourcesById;
      return state;
    }
    case "source_excerpt": {
      const sourcesById = new Map(state.sourcesById);
      const existing = sourcesById.get(event.source_id) ?? {
        title: "",
        url: event.url,
        snippet: "",
        source_id: event.source_id,
      };
      sourcesById.set(event.source_id, { ...existing, url: event.url, excerpt: event.excerpt });
      state.sourcesById = sourcesById;
      state.research = {
        ...state.research,
        sources: state.research.sources.map((s) =>
          s.source_id === event.source_id ? { ...s, excerpt: event.excerpt } : s,
        ),
      };
      return state;
    }
    case "slide_citation": {
      const citationsBySlide = new Map(state.citationsBySlide);
      citationsBySlide.set(event.number, [...event.source_ids]);
      const slidesBySource = new Map(state.slidesBySource);
      for (const sid of event.source_ids) {
        const arr = slidesBySource.get(sid) ?? [];
        if (!arr.includes(event.number)) {
          slidesBySource.set(sid, [...arr, event.number].sort((a, b) => a - b));
        }
      }
      state.citationsBySlide = citationsBySlide;
      state.slidesBySource = slidesBySource;
      const existing = state.slides.get(event.number);
      if (existing) {
        const slides = new Map(state.slides);
        slides.set(event.number, { ...existing, citations: [...event.source_ids] });
        state.slides = slides;
      }
      return state;
    }
    case "log": {
      const phaseId = event.phase as PhaseId;
      const existing = state.phases[phaseId];
      if (existing) {
        state.phases[phaseId] = { ...existing, logs: [...existing.logs, event.text] };
      }
      return state;
    }
    case "deck_meta": {
      state.deckMeta = {
        title: event.title,
        subtitle: event.subtitle,
        topic: event.topic,
        theme: event.theme,
      };
      return state;
    }
    case "slide_outline": {
      state.outline = [...state.outline, event];
      return state;
    }
    case "slide_detail": {
      const slides = new Map(state.slides);
      slides.set(event.number, event.slide);
      state.slides = slides;
      if (event.slide.citations && event.slide.citations.length > 0) {
        const citationsBySlide = new Map(state.citationsBySlide);
        citationsBySlide.set(event.number, [...event.slide.citations]);
        const slidesBySource = new Map(state.slidesBySource);
        for (const sid of event.slide.citations) {
          const arr = slidesBySource.get(sid) ?? [];
          if (!arr.includes(event.number)) {
            slidesBySource.set(sid, [...arr, event.number].sort((a, b) => a - b));
          }
        }
        state.citationsBySlide = citationsBySlide;
        state.slidesBySource = slidesBySource;
      }
      return state;
    }
    case "file": {
      state.files = [...state.files, { path: event.path, content: event.content, url: event.url }];
      return state;
    }
    case "deck_ready": {
      state.deckReady = event;
      state.downloadUrl = event.download_url;
      state.htmlUrl = event.html_url;
      return state;
    }
    case "done": {
      state.status = "done";
      state.downloadUrl = event.download_url;
      state.htmlUrl = event.html_url;
      return state;
    }
    case "error": {
      // Collect errors but do not flip status — the pipeline may still
      // complete the rest of the deck (e.g. scaffold mode after LLM probe
      // fails). The stream-level status from useEventStream tracks network
      // failures separately.
      const msg = event.message || "(no message)";
      state.errors = state.errors.includes(msg) ? state.errors : [...state.errors, msg];
      state.error = msg;
      return state;
    }
  }
  return state;
}

export function reduceAll(events: AgentEvent[]): JobState {
  let state = emptyJob();
  for (const event of events) state = reduce(state, event);
  return state;
}
