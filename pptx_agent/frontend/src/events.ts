export type PhaseId = "research" | "outline" | "content" | "render" | "export";

export interface BaseEvent {
  type: string;
  ts: number;
}

export interface JobStartEvent extends BaseEvent {
  type: "job_start";
  job_id: string;
  prompt: string;
  slide_count: number;
  topic: string;
}

export interface PhaseStartEvent extends BaseEvent {
  type: "phase_start";
  id: PhaseId;
  label: string;
}

export interface PhaseEndEvent extends BaseEvent {
  type: "phase_end";
  id: PhaseId;
}

export interface ProviderEvent extends BaseEvent {
  type: "provider";
  phase: PhaseId;
  provider: string;
}

export interface QueriesEvent extends BaseEvent {
  type: "queries";
  phase: PhaseId;
  items: string[];
}

export interface QueryEvent extends BaseEvent {
  type: "query";
  phase: PhaseId;
  query: string;
  index: number;
  total: number;
}

export interface LogEvent extends BaseEvent {
  type: "log";
  phase: PhaseId;
  text: string;
}

export interface ResultEvent extends BaseEvent {
  type: "result";
  phase: PhaseId;
  query: string;
  title: string;
  url: string;
  snippet: string;
  engine: string;
  favicon: string;
  source_id?: string;
  trust?: string;
}

export interface SearchSummaryEvent extends BaseEvent {
  type: "search_summary";
  phase: PhaseId;
  query: string;
  engines: Record<string, number>;
  unresponsive: [string, string][];
  base_url: string;
}

export interface InsightsEvent extends BaseEvent {
  type: "insights";
  phase: PhaseId;
  items: string[];
}

export interface SourceDict {
  title: string;
  url: string;
  snippet: string;
  engine?: string;
  engines?: string[];
  query?: string;
  queries?: string[];
  excerpt?: string;
  source_id?: string;
  trust?: string;
}

export interface SourcesEvent extends BaseEvent {
  type: "sources";
  phase: PhaseId;
  items: SourceDict[];
}

export interface SourceExcerptEvent extends BaseEvent {
  type: "source_excerpt";
  phase: PhaseId;
  source_id: string;
  url: string;
  excerpt: string;
}

export interface SlideCitationEvent extends BaseEvent {
  type: "slide_citation";
  phase: PhaseId;
  number: number;
  source_ids: string[];
}

export interface DeckMetaEvent extends BaseEvent {
  type: "deck_meta";
  phase: PhaseId;
  title: string;
  subtitle: string;
  slide_count: number;
  topic: string;
  theme?: string;
}

export interface SlideOutlineEvent extends BaseEvent {
  type: "slide_outline";
  phase: PhaseId;
  number: number;
  title: string;
  subtitle: string;
  eyebrow: string;
  layout: string;
}

export type BlockType =
  | "eyebrow"
  | "heading"
  | "subheading"
  | "paragraph"
  | "bullets"
  | "metric_row"
  | "quote"
  | "callout"
  | "image"
  | "chart"
  | "diagram"
  | "spacer"
  | "hero_stat"
  | "highlight";

export interface SlideBlock {
  id: string;
  type: BlockType;
  props: Record<string, unknown>;
}

export interface SlideData {
  number: number;
  id: string;
  layout: string;
  eyebrow: string;
  title: string;
  subtitle: string;
  bullets: string[];
  metrics: Array<{ label: string; value: string }>;
  speaker_notes: string;
  citations?: string[];
  blocks?: SlideBlock[];
  accent_variant?: number;
}

export interface SlideDetailEvent extends BaseEvent {
  type: "slide_detail";
  phase: PhaseId;
  number: number;
  slide: SlideData;
}

export interface FileEvent extends BaseEvent {
  type: "file";
  phase: PhaseId;
  path: string;
  content?: string;
  url?: string;
}

export interface DeckReadyEvent extends BaseEvent {
  type: "deck_ready";
  job_id: string;
  title: string;
  slide_count: number;
  slides: Array<{ number: number; title: string; subtitle: string }>;
  sources: Array<{ title: string; url: string; snippet: string }>;
  structure: string;
  slide_content: string;
  preview_html: string;
  download_url: string;
  html_url: string;
}

export interface DoneEvent extends BaseEvent {
  type: "done";
  job_id: string;
  download_url: string;
  html_url: string;
}

export interface ErrorEvent extends BaseEvent {
  type: "error";
  phase?: PhaseId;
  message: string;
}

export type AgentEvent =
  | JobStartEvent
  | PhaseStartEvent
  | PhaseEndEvent
  | ProviderEvent
  | QueriesEvent
  | QueryEvent
  | LogEvent
  | ResultEvent
  | SearchSummaryEvent
  | SourceExcerptEvent
  | InsightsEvent
  | SourcesEvent
  | DeckMetaEvent
  | SlideOutlineEvent
  | SlideDetailEvent
  | SlideCitationEvent
  | FileEvent
  | DeckReadyEvent
  | DoneEvent
  | ErrorEvent;
