# PPTX Generation Agent — Project Progress

Living log. Updated after every change.

## Goal

Manus-AI-grade pitch deck generator: live SearXNG research with cited results, streaming progress UI (left timeline + right "computer" panel), block-based slide JSON, per-slide fullscreen editor, multi-export (HTML/PPTX/PDF). Local-first, no cloud dependency.

## Architecture target (high-level)

```
Browser (SSE consumer + two-pane UI)
        ▲ event-stream
        │
HTTP server (BaseHTTPRequestHandler, ThreadingHTTPServer)
        │
pipeline.iter_pipeline()  ← generator yielding events
        │
        ├─ Researcher.iter_run()  → SearXNG queries + per-result events + summaries
        ├─ planner.iter_build_deck() → LLM or deterministic plan → outline + detail events
        ├─ html_renderer.render_*  → slides.html + preview fragment
        ├─ pptx_writer.write       → deferred until /api/jobs/<id>/deck.pptx hit
        └─ events.jsonl persisted under output/<job>/
```

## Build plan (8 ordered steps)

| # | Step | Status |
|---|------|--------|
| 1 | Refactor planner/research into generator pattern (yield events) | ✅ done |
| 2 | SSE endpoint + event log persistence | ✅ done |
| 3 | Two-pane frontend shell (left timeline cards, right contextual panel) | ✅ done |
| 4 | Live search citations + favicons | ✅ done |
| 5 | Block-based slide JSON schema + HTML renderer rewrite | ⏳ pending |
| 6 | Fullscreen slide editor (contenteditable + design panel) | ⏳ pending |
| 7 | PPTX writer block dispatcher | ⏳ pending |
| 8 | Phased generation w/ optimize pass | ⏳ pending |

---

## History (newest first)

### 2026-05-16 — Step 4 done: verifiable provenance (cite-back, trust tiers, dedupe)

**Goal** — turn "looks like research" into "verifiable research". Every slide bullet traceable to source IDs; every source labeled with trust tier and engine attribution.

**New backend module**
- [pptx_agent/pptx_agent/citations.py](pptx_agent/pptx_agent/citations.py) — pure heuristic matcher. `_tokens()` strips stopwords + lowercase + regex `[a-z][a-z0-9]{2,}`. `score_slide_against_sources()` computes cosine-style overlap between slide token set (title + subtitle + bullets + speaker notes) and each source token set (title + snippet + excerpt). `cite_slide()` returns top-N (default 3) source IDs above `min_score=0.04`. Deterministic, no LLM dependency.

**Backend modifications**
- [pptx_agent/pptx_agent/events.py](pptx_agent/pptx_agent/events.py)
  - Added `trust_tier(url)` returning one of `gov` / `edu` / `academic` / `news` / `reference` / `social` / `blog` / `unknown`. Hard-coded host sets for news (Reuters/AP/BBC/etc), reference (Wikipedia/Britannica), academic (arxiv/scholar/pubmed), social (X/Reddit/LinkedIn/etc).
  - Added `domain_of(url)` helper.
- [pptx_agent/pptx_agent/research.py](pptx_agent/pptx_agent/research.py)
  - `SearchResult` gained 4 fields: `source_id`, `engines: list[str]` (multi-engine dedupe), `queries: list[str]` (multi-query consolidation), `trust`. `as_dict()` exports them when set.
  - `_dedupe()` rewritten: instead of dropping duplicate URLs, merges them — accumulates engine list, query list, fills excerpt from any duplicate, preserves first-seen order via `seen: dict` + `order: list[key]`.
  - `iter_run()`: after final dedupe, stamps each retained source with `source_id="S{n}"` + `trust=trust_tier(url)`, then emits `source_excerpt` event for any source whose excerpt got fetched.
- [pptx_agent/pptx_agent/planner.py](pptx_agent/pptx_agent/planner.py)
  - Imported `cite_slide` from `citations`.
  - `iter_build_deck()` runs `cite_slide(slide, sources)` after deck assembly (skipped when slide already has explicit `citations` — LLM mode can supply them directly).
  - Per-slide `slide_citation` event emitted in content phase right after each `slide_detail`.
  - `normalize_deck()` preserves LLM-provided `citations` (also accepts `source_refs` alias) and always emits empty `citations: []` for fallback-padded slides.
  - LLM system prompt now requests `citations: ["S1", "S2"]` per slide and explains the rule.
- [pptx_agent/pptx_agent/pipeline.py](pptx_agent/pptx_agent/pipeline.py)
  - New `_sources_markdown(deck, research)` writes a numbered bibliography: title, URL, trust tier, engines, "Cited by slides: 1, 3, 5", and a quoted excerpt block. Sources are listed in S1, S2… order so they match in-slide pills.
  - Render phase now writes `sources.md` to job dir and emits a `file` event with inline content.
  - Imported `domain_of` for trust fallback when source missing precomputed trust.
- [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py)
  - `sources.md` added to allowed job asset list so frontend can `GET /api/jobs/<id>/sources.md`.

**New event types (3)**
- `source_excerpt {source_id, url, excerpt}` — fired once per source whose page text was fetched by `_enrich_sources`. Lets frontend show "fetched excerpt" expandable after the initial result lands.
- `slide_citation {number, source_ids: ["S1", "S2"]}` — emitted right after each `slide_detail` if heuristic found any source matches above threshold.
- `file {path: "sources.md", content}` — bibliography artifact.

**Frontend updates**
- [frontend/src/events.ts](pptx_agent/frontend/src/events.ts) — added `SourceDict` interface with full source shape (engines list, source_id, trust), `SourceExcerptEvent`, `SlideCitationEvent`, extended `ResultEvent` with optional `source_id` + `trust`. Updated `AgentEvent` union.
- [frontend/src/trust.ts](pptx_agent/frontend/src/trust.ts) — mirror of backend `trust_tier()` so frontend can label results that arrive before the `sources` event lands.
- [frontend/src/state.ts](pptx_agent/frontend/src/state.ts)
  - `JobState` gained 3 derived maps: `sourcesById: Map<sid, SourceDict>`, `citationsBySlide: Map<slideNum, sid[]>`, `slidesBySource: Map<sid, slideNum[]>` (inverse index).
  - Reducer cases: `sources` populates `sourcesById`; `source_excerpt` patches the matching source in both `sourcesById` and `research.sources`; `slide_citation` writes both maps and patches the matching slide's `citations` field; `slide_detail` seeds `citationsBySlide` if the slide arrives with citations already set (LLM path).
- [frontend/src/components/types.ts](pptx_agent/frontend/src/components/types.ts) — added two new selected-view variants: `sources` (full bibliography) and `source` with specific `sourceId` for highlight.
- [frontend/src/components/ResultCard.tsx](pptx_agent/frontend/src/components/ResultCard.tsx) — accepts optional `source` prop. Renders: source-ID pill (`S1`/`S2`/…), `TrustBadge` colored by tier, engine-tag row (all engines that surfaced the URL), `<details>` element for fetched excerpt when available.
- [frontend/src/components/SourcesView.tsx](pptx_agent/frontend/src/components/SourcesView.tsx) — new right-panel view. Lists every unique source sorted by # slides citing it (most-cited first). Each card highlights when its source ID matches the selected view; cited-by row shows `slide N` pill buttons that switch to `SlideView`.
- [frontend/src/components/SlideView.tsx](pptx_agent/frontend/src/components/SlideView.tsx) + [ContentView.tsx](pptx_agent/frontend/src/components/ContentView.tsx) — render `Sources: [S1] [S2] [S3]` pill row after bullets. Each pill is a button that switches to `{kind: "source", sourceId}` — bidirectional navigation.
- [frontend/src/components/Timeline.tsx](pptx_agent/frontend/src/components/Timeline.tsx) — added `📚 Sources (N)` entry under the research card.
- [frontend/src/components/ComputerPanel.tsx](pptx_agent/frontend/src/components/ComputerPanel.tsx) — now passes `onSelect` down to `ContentView`/`SlideView`/`SourcesView` so pill clicks deep-link across views.
- [frontend/src/components/QueryView.tsx](pptx_agent/frontend/src/components/QueryView.tsx) + [ResearchView.tsx](pptx_agent/frontend/src/components/ResearchView.tsx) — lookup matching source by URL and forward to ResultCard so engine-list + excerpt + trust-badge show on every research result, not just bibliography view.
- [frontend/src/styles.css](pptx_agent/frontend/src/styles.css) — styles for `.source-id-pill`, `.trust-badge.trust-{gov,edu,academic,news,reference,social,blog}` (each tier has its own colored chip), `.result-excerpt` (collapsible block), `.cite-pill` (monospace mini-button), `.cite-row` (under bullets), `.sources-view` / `.source-card` / `.source-card.highlight` (highlight border + shadow when navigated to).

**Verification (live SearXNG, deep mode, 2 queries × 2 results × 4 cap, prompt: "Create a 5-slide pitch deck about healthcare in Bangladesh")**
- 20 distinct event types fired (3 new ones added cleanly).
- `slide_citation` × 5 — one per slide. Sample: slide 1 → `[S2, S3, S1]`, slide 5 → `[S4, S3, S1]` (deterministic matcher correctly mapping closing slide to academic arxiv source S4).
- `source_excerpt` × 3 — fired for sources whose page text was fetched. Excerpts visible in `sources.md` blockquotes.
- Multi-engine dedupe verified: S2 surfaced via `duckduckgo, google` (single card, two engine tags).
- Trust labelling: S4 (arxiv) → `academic`, S3 (researchgate) → `unknown` (correct: researchgate isn't whitelisted), others `unknown`.
- `sources.md` written to job dir with proper structure: numbered S1-S4, trust tier, engines, "Cited by slides: …", quoted excerpt.
- `npm run build` clean: 43 modules, 168 KB JS (53 KB gz), 13 KB CSS.
- Backend tests: 5/5 pass — `SearchResult` field additions and `_dedupe` rewrite stayed compatible.

**Edge / known**
- Trust whitelist deliberately small; researchgate.net, ncbi.nlm subdomains, msn.com routes etc still classify `unknown`. Easy expansion later.
- Cite-back is heuristic — when slide titles share generic words with multiple sources, top-N can include weak matches. Mitigated by `min_score=0.04` threshold + token stopword list.
- LLM-mode citations: planner asks LLM to populate `citations`. When LLM omits or refuses, deterministic matcher runs as fallback (existing slide.citations check).

### 2026-05-16 — Step 3 done: Vite + React + TypeScript two-pane shell
**Decision recorded**
- User chose Vite + React + TypeScript over vanilla JS and TS-only options. Rationale: step 5 (block JSON) and step 6 (fullscreen editor) need a component model and reactive state — paying the toolchain cost once now beats rewriting an imperative DOM tree later.

**New frontend tree** at [pptx_agent/frontend/](pptx_agent/frontend/)
- Scaffold: [package.json](pptx_agent/frontend/package.json) (React 18, Vite 6, TS 5.7, `@types/node` for vite config), [tsconfig.json](pptx_agent/frontend/tsconfig.json), [vite.config.ts](pptx_agent/frontend/vite.config.ts) (output → `../web/dist`, dev proxy `/api → http://127.0.0.1:8787`), [index.html](pptx_agent/frontend/index.html).
- [src/events.ts](pptx_agent/frontend/src/events.ts) — discriminated union of every event the backend emits (17 types). `AgentEvent` covers `job_start` · `phase_start/end` · `provider` · `queries` · `query` · `log` · `result` (incl. `engine`/`favicon`) · `search_summary` · `insights` · `sources` · `deck_meta` · `slide_outline` · `slide_detail` · `file` · `deck_ready` · `done` · `error`.
- [src/useEventStream.ts](pptx_agent/frontend/src/useEventStream.ts) — React hook. `start({prompt, slide_count})` POSTs to `/api/generate/stream`, consumes response body as ReadableStream, parses SSE blocks split on `\n\n`, dispatches each event. Also exposes `replay(jobId)` hitting `GET /api/jobs/<id>/events.stream`, `reset()`, and tracked `status`/`error`/`events`. Uses `AbortController` so a second submit cancels the prior stream.
- [src/state.ts](pptx_agent/frontend/src/state.ts) — pure reducer `reduce(state, event)` + `reduceAll(events)` derives full `JobState` from event log. Groups research results by query, tracks phase progress/logs, slide outline + detail Map, files, deck readiness. Designed so any subset of events (replay or live) reconstructs identical UI state.

**Component tree**
- [src/App.tsx](pptx_agent/frontend/src/App.tsx) — top-level shell: header (brand + status pill + download/HTML buttons) + two-pane main (left rail + right computer panel) + selection state for which card is open in right panel.
- [src/components/PromptForm.tsx](pptx_agent/frontend/src/components/PromptForm.tsx) — prompt textarea + slide count (5-25 clamp) + Generate button. Disables during run.
- [src/components/Timeline.tsx](pptx_agent/frontend/src/components/Timeline.tsx) — left rail. One card per phase in `job.phaseOrder`. Cards mutate live: status icon (✓ done / ⟳ spinning), description ("3/7 queries · 12 sources"), last log line. Sub-rows under research (per-query) and render (per-file) become clickable to drill into right panel.
- [src/components/ComputerPanel.tsx](pptx_agent/frontend/src/components/ComputerPanel.tsx) — right panel. Switches view by `SelectedView`: summary / phase-research / phase-outline / phase-content / phase-render / phase-export / query / file / outline / slide.
- View components: [ResearchView](pptx_agent/frontend/src/components/ResearchView.tsx), [QueryView](pptx_agent/frontend/src/components/QueryView.tsx), [OutlineView](pptx_agent/frontend/src/components/OutlineView.tsx), [ContentView](pptx_agent/frontend/src/components/ContentView.tsx), [FileView](pptx_agent/frontend/src/components/FileView.tsx), [SlideView](pptx_agent/frontend/src/components/SlideView.tsx), [ExportView](pptx_agent/frontend/src/components/ExportView.tsx), [SummaryView](pptx_agent/frontend/src/components/SummaryView.tsx).
- [ResultCard](pptx_agent/frontend/src/components/ResultCard.tsx) — per-result card with `favicon` `<img>` (Google s2 service), title link, engine tag, snippet, hostname.
- Engine attribution chips + unresponsive engine count badges on each query group (collapsible details list of unresponsive engines).
- [src/styles.css](pptx_agent/frontend/src/styles.css) — dark theme matching Manus screenshots (deep navy `#0a1119`, elevated surfaces, electric-blue accent `#3aa0ff`, status pills, spin animation on running phases). Responsive: collapses to single column under 920 px.

**Backend changes**
- [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py)
  - Replaced hardcoded `web/index.html`, `web/app.js`, `web/styles.css` routes with `_serve_static(path)` — searches `web/dist/` (Vite build) first, falls back to `web/` (legacy), validates path stays inside the base dir, serves SPA fallback (any unknown path → `dist/index.html`) so client-side routing works in future steps.
  - Added `_CONTENT_TYPES` map + `_guess_content_type()` helper for proper MIME on hashed Vite assets (`*.js`, `*.css`, `*.map`, fonts, images).
  - `/api/*` paths still take priority; non-API paths fall to static handler.

**Cleanup**
- Removed obsolete vanilla files: `pptx_agent/web/app.js`, `pptx_agent/web/index.html`, `pptx_agent/web/styles.css`. Vite output `web/dist/` shadows them entirely.
- Updated [.gitignore](.gitignore): `**/node_modules/` and `pptx_agent/web/dist/` excluded.

**Verification**
- `npm run build` succeeds: 41 modules, output 162 KB JS (51 KB gz), 10 KB CSS (2.5 KB gz), 0.4 KB HTML.
- Python server (`PORT=8788`) serves built bundle: `GET /` returns React shell, hashed `/assets/index-*.css` → `200 text/css`, `/assets/index-*.js` → `200 text/javascript`.
- Live SSE end-to-end (`POST /api/generate/stream` from server): 52 events, full pipeline, clean disconnect on `done`.
- Python unit tests: 5/5 pass — backend untouched aside from static handler refactor.

**Dev workflow**
- Run backend: `cd pptx_agent && python3 run.py` (serves built bundle on :8787).
- Run frontend HMR: `cd pptx_agent/frontend && npm run dev` (Vite on :5173 with `/api` proxied to :8787).
- Production build: `cd pptx_agent/frontend && npm run build` → static bundle to `pptx_agent/web/dist/`; Python server picks it up automatically.

### 2026-05-16 — Step 2 done: SSE endpoint + replay
**New endpoints**
- `POST /api/generate/stream` — request `{prompt, slide_count}` → response `text/event-stream`. Streams every pipeline event live (`Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: close`, `X-Accel-Buffering: no`). Sets `self.close_connection = True` so server returns cleanly after `done` without hanging keep-alive.
- `GET /api/jobs/<id>/events.stream` — replay endpoint. Reads persisted `output/<id>/events.jsonl` and re-emits each line as SSE for reconnects or post-hoc viewing.

**Pipeline changes**
- [pptx_agent/pptx_agent/pipeline.py](pptx_agent/pptx_agent/pipeline.py)
  - `iter_pipeline()` now allocates `job_id` at the very start via `timestamp_id(topic)` (instead of after deck assembly). `job_id` emitted in the `job_start` event so consumers know the URL prefix from event #1.
  - Added `iter_pipeline_with_persist(prompt, slide_count, settings)` generator: wraps `iter_pipeline`, opens `output/<job>/events.jsonl` as soon as `job_start` fires, writes every yielded event as a JSON line with `flush()` so the file tail-follows in real time. File handle closed in `finally` even on client disconnect.
  - `run_pipeline_and_persist()` refactored to drain `iter_pipeline_with_persist` instead of doing its own bulk write. Removed the now-dead `_write_events_jsonl` helper and unused `pathlib.Path` import.

**Server changes**
- [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py)
  - Routed `POST /api/generate/stream` → `_generate_stream()`.
  - Routed `GET /api/jobs/<id>/events.stream` → `_replay_events_sse()`.
  - Added `_begin_sse()` (writes the SSE headers + forces connection close) and `_write_sse(event)` (formats `event: <type>\\ndata: <json>\\n\\n`, returns False on `BrokenPipeError`/`ConnectionResetError` so the handler can bail cleanly when the client disconnects).
  - `_generate_stream` iterates `iter_pipeline_with_persist` and streams each event; on exception, emits a final `error` event and stops.
  - `_replay_events_sse` validates the job dir is inside `output/`, reads `events.jsonl`, replays each parsed JSON line through `_write_sse`. Skips malformed lines silently.

**Verification (live SearXNG @ 8890, deep mode, 2 queries × 2 results)**
- `POST /api/generate/stream` → 52 SSE events (156 lines incl. blanks) covering full pipeline (`job_start` → research → outline → content → render → `done`). Curl `exit=0`, no keep-alive hang.
- Event type tally: `job_start`×1, `phase_start`×5, `phase_end`×4, `provider`×1, `queries`×1, `query`×2, `result`×4, `search_summary`×2, `log`×14, `insights`×1, `sources`×1, `deck_meta`×1, `slide_outline`×5, `slide_detail`×5, `file`×3, `deck_ready`×1, `done`×1.
- `output/<job>/events.jsonl` persisted in real time: 52 lines, 61 KB.
- `GET /api/jobs/<id>/events.stream` replays full 52 events identically.
- `POST /api/generate` (sync legacy) still works — same JSON shape (11 keys) for existing frontend.
- 5/5 unit tests pass.

### 2026-05-16 — Step 1 done: event-pipeline refactor

### 2026-05-16 — Step 1 done: event-pipeline refactor
**New files**
- [pptx_agent/pptx_agent/events.py](pptx_agent/pptx_agent/events.py) — `make_event(type, **fields)` factory, phase ID constants (`research`/`outline`/`content`/`render`/`export`), `favicon_url(url)` helper (Google s2 favicon).
- [pptx_agent/pptx_agent/pipeline.py](pptx_agent/pptx_agent/pipeline.py) — `iter_pipeline(prompt, slide_count, settings)` top-level generator, `run_pipeline_and_persist(...)` sync wrapper that drains + writes `events.jsonl` + returns JSON for `/api/generate`.

**Modified**
- [pptx_agent/pptx_agent/research.py](pptx_agent/pptx_agent/research.py)
  - `SearchResult` gained `engine: str` field; `as_dict()` exposes it when present.
  - `_search_searxng()` now records `engine` per result, tracks `engines_seen` counts + `unresponsive_engines`, stashes them on `self._last_search_meta`.
  - Added `iter_run(prompt, topic)` generator yielding `phase_start`/`provider`/`queries`/`query`/`result`/`search_summary`/`insights`/`sources`/`log`/`phase_end` events.
  - `run(...)` rewritten as thin drainer of `iter_run` — keeps existing sync callers (incl. tests) green.
- [pptx_agent/pptx_agent/planner.py](pptx_agent/pptx_agent/planner.py)
  - Added `iter_build_deck(prompt, slide_count, research, settings)` generator emitting `phase_start` (outline) → `log` → `deck_meta` → per-slide `slide_outline` → `phase_end` → `phase_start` (content) → per-slide `slide_detail` → `phase_end`.
  - `build_deck(...)` rewritten as thin drainer of `iter_build_deck`.
- [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py)
  - `_generate()` collapsed from ~55 lines → 8; delegates to `run_pipeline_and_persist`.
  - Dropped direct imports of `Researcher`, `build_deck`, `render_full_html`, etc.
  - Allowed asset list now includes `events.jsonl` (`application/x-ndjson`).

**Event vocabulary emitted (17 types)**
`job_start` · `phase_start` · `phase_end` · `provider` · `queries` · `query` · `log` · `result` (incl. `engine`, `favicon`) · `search_summary` (`engines`, `unresponsive`, `base_url`) · `insights` · `sources` · `deck_meta` · `slide_outline` · `slide_detail` · `file` · `deck_ready` · `done` · `error`

**Verification**
- 5/5 existing unit tests pass.
- Live smoke test against SearXNG @ 127.0.0.1:8890: 64 events per 10-slide job, 52 events per 8-slide job.
- Engine attribution observed across `google`, `duckduckgo`, `duckduckgo news`, `bing news`, `qwant news`, `arxiv`, `google scholar`.
- `output/<job>/events.jsonl` persists full replay log.
- Sync API response shape unchanged → existing frontend still works.

### 2026-05-16 — SearXNG diversity fix
- [pptx_agent/pptx_agent/research.py:182](pptx_agent/pptx_agent/research.py#L182) — changed `categories=general` → `categories=general,news,science`.
- Before: 2 engines respond (google, duckduckgo), ~16 results.
- After: 11 engines respond (adds bing news, qwant news, reuters, wikinews, arxiv, google scholar, pubmed, openaire*), ~117 raw results per query, ~30 after dedup cap.
- Verified: 5/5 unit tests pass; live smoke run shows multi-engine attribution.

### 2026-05-16 — SearXNG capability audit
- Container `pptx-agent-searxng` up at `127.0.0.1:8890`, JSON endpoint working.
- Healthy engines: `google`, `duckduckgo` (+ news/science variants once categories expanded).
- Broken/rate-limited: `brave`, `karmasearch`, `startpage`, `yahoo news`, `semantic scholar` (CAPTCHA / access denied / timeout). Non-fatal — SearXNG drops them silently.
- Audit only — no code change at this point.

### Pre-existing baseline (before this session)
- `pptx_agent/` Python package, stdlib-only (no pip deps).
- Components: [config.py](pptx_agent/pptx_agent/config.py), [research.py](pptx_agent/pptx_agent/research.py), [planner.py](pptx_agent/pptx_agent/planner.py), [llm.py](pptx_agent/pptx_agent/llm.py), [html_renderer.py](pptx_agent/pptx_agent/html_renderer.py), [pptx_writer.py](pptx_agent/pptx_agent/pptx_writer.py), [server.py](pptx_agent/pptx_agent/server.py), [utils.py](pptx_agent/pptx_agent/utils.py).
- Web UI: [pptx_agent/web/](pptx_agent/web/) — single-page, blocking POST `/api/generate`, tabs for preview/outline/notes/sources.
- Local SearXNG via [docker-compose.searxng.yml](docker-compose.searxng.yml) → port 8890.
- Pipeline: prompt → research (SearXNG/Brave/Serper/Tavily/DDG/local fallback) → deterministic-or-LLM planner → HTML render → on-download PPTX generation.
- Output: `output/<job-id>/` containing `deck.json`, `pitch_deck_structure.txt`, `slide_content.md`, `slides.html`, lazy `deck.pptx`.
- Last commits before session: `e49005c Finalize pptx_agent package rename` · `44c731b Rename manus_pptx_agent to pptx_generation_agent` · `7ad1fbe pptx generation agent : websearch first…`

---

## Open questions / decisions deferred

- **Block-based slide JSON schema (step 5):** exact shape per layout (cover / problem / metrics / market / comparison / team / ask) — to design when step 5 starts. Likely `{number, layout, blocks:[{id,type,props,bbox}]}`.
- **Edit persistence (step 6):** PATCH per-block vs full slide JSON replace. Lean toward block-level PATCH for diff history.
- **PPTX block dispatcher (step 7):** map each block type to python-pptx shapes; currently writer only handles title/body. Will need shape templates per block type.
- **Per-slide source citations:** every slide should track `source_ids` referenced. Schema TBD when block JSON lands.
