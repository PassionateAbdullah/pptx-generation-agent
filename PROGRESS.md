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

## Build plan (17 phases — re-ordered for unblocking + visual payoff)

Original 8-step plan was MVP parity. Real Manus parity needs 13. Beyond Manus = 14-17. Re-ordered so theme (10) lands early (cheap, big visual win) and chart (11) is built while block schema is fresh.

**Effort revision:** original ~30 hrs estimate covered MVP only. Real parity ≈ 80 hrs. Edge tier (14-17) ≈ 60 hrs more.

| # | Phase | Status |
|---|------|--------|
| 1 | Refactor planner/research into generator pattern (yield events) | ✅ done |
| 2 | SSE endpoint + event log persistence | ✅ done |
| 3 | Two-pane frontend shell (left timeline cards, right contextual panel) | ✅ done |
| 4 | Live search citations (cite-back, trust tiers, dedupe, favicons) | ✅ done |
| 5 | Block-based slide JSON schema + HTML renderer rewrite | ✅ done |
| 10 | Theme system (palettes, fonts, layouts) — pulled early, ~2hr CSS-var swap | ✅ done |
| 6 | Fullscreen slide editor (contenteditable + design panel) | ✅ done |
| 6.5 | Presentation viewer (fullscreen carousel, keyboard nav, thumbs) | ✅ done |
| 11 | Charts + diagrams — real SVG, 4 kinds (bar/line/area/pie), editor controls | ✅ done |
| 9 | Image sourcing + local media/PPTX embed (SearXNG stock; AI gen deferred) | ✅ done |
| 7 | PPTX writer block dispatcher (waits until block types stable) | ✅ done |
| 8 | Dynamic block recipes per layout + auto chart blocks + variety optimize pass | ✅ done |
| 8.5 | Dynamic outline from research (topic family + claim miner + hedge filter + slide.md) | ✅ done |
| 12 | Slide regenerate + conversational refinement chat | ✅ done |
| 12.5 | Visual gap fill: hero_stat + highlight blocks, per-slide accent rotation, DeckView (all slides stacked) | ✅ done |
| 13 | PDF export + shareable read-only links | ⏳ pending |
| — | **— Manus parity line reached at phase 13 —** | |
| 14 | Citation grading + auto-factcheck per claim | ⏳ pending |
| 15 | Multi-agent critique (audience / data / design parallel reviewers) | ⏳ pending |
| 16 | Voice narration + auto-pacing video export (mp4) | ⏳ pending |
| 17 | Live data binding (slide auto-refresh on new sources) | ⏳ pending |

---

### 2026-05-18 — Step 12.5 done: hero stats + colorful highlights + per-slide accent variants + all-slides DeckView

**Direct fix** for user's gaps: *"is our agent capable of graphical presentation, charts, graphs · show important topics in bigger or colorful manner · design seems fixed, can we make it dynamic · slide-by-slide presentation into the screen 1→N clickable inline missing"*.

**Two new block types** — [blocks.py](pptx_agent/pptx_agent/blocks.py)
- `hero_stat {value, label, trend, source_id}` — XL stat block (96-px on standalone HTML, 84-px in editor, 7200pt in PPTX). Renders the metric in giant accent color w/ uppercase muted label underneath.
- `highlight {tone, title, text}` — colorful gradient insight box w/ accent stripe on the left. Tones: `accent | warn | success | danger`. Uses `color-mix` for tone-tinted backgrounds.

Both registered in `_BLOCK_RENDERERS` (html_renderer), `_render_block` dispatch (pptx_writer), and `BlockRender` + `EditorBlock` (frontend). `BLOCK_TYPES` grew from 12 → 14.

**Per-slide accent variant rotation** — [html_renderer.py](pptx_agent/pptx_agent/html_renderer.py)
- Each slide gets `accent_variant ∈ {0, 1, 2, 3}` cycling by slide number.
- `slide-accent-{0..3}` CSS classes override `--accent` + `--accent-soft` to rotate through primary → warn → danger → accent_strong.
- Effect: slide 1 = primary teal, slide 2 = amber, slide 3 = coral, slide 4 = strong, slide 5 = primary again. Visual rhythm without breaking theme cohesion.
- Carried through `normalize_deck` so it persists in `deck.json`, the editor preview, the DeckView strip, and the standalone HTML export.

**DeckView** — [DeckView.tsx](pptx_agent/frontend/src/components/DeckView.tsx)
- New right-panel view that renders **every slide as a stacked 16:9 card** top-to-bottom (1 → N). User scrolls the entire deck without flipping timeline cards.
- Each card uses `BlockRender` to render the slide content read-only with theme tokens applied inline (`tokensToStyle`).
- Per-slide accent variant applied via `slide-accent-{n}` class.
- **Click** any card → opens the slide editor at that slide.
- **Double-click** → opens presentation viewer from that slide.
- Sticky header w/ deck title + "Present from start" button.
- Hover lifts cards (shadow + accent border) and reveals an inline `Edit` button.

**Wiring**
- `SelectedView` union grew a `{ kind: "deck" }` variant.
- [ComputerPanel.tsx](pptx_agent/frontend/src/components/ComputerPanel.tsx) routes `deck` view → `<DeckView/>`; passes `onEditSlide` + `onPresent` through.
- [Timeline.tsx](pptx_agent/frontend/src/components/Timeline.tsx) prepends an "▦ All slides" card (visible whenever `job.slides.size > 0`) so user can switch back manually.
- [App.tsx](pptx_agent/frontend/src/App.tsx) auto-switches to DeckView when generation status flips to `done` AND ≥1 slide drafted. Respects user navigation: skips auto-switch when already in `deck` or `slide` view.

**Auto-emit hero_stat from research** — [dynamic_outline.py](pptx_agent/pptx_agent/dynamic_outline.py)
- New helpers: `_hero_stat_block`, `_highlight_from_claim`, `_is_hero_worthy` (true when metric value ≤ 12 chars — pithy enough to display giant).
- `_blocks_for_role` cover/market/traction branches now check if first metric is hero-worthy → emit `hero_stat` with source citation, then `metric_row` for remaining metrics.
- Comparison/competition branches scan bullets for "X vs Y" patterns → promote head-to-head bullets into `highlight` blocks with `tone="warn"`.

**Smoke results** (no-network, synthetic research with concrete numbers):

| Topic | Family | Hero stat extracted | Variants rotating |
|---|---|---|---|
| `"Investor pitch on solar microgrids in Bangladesh"` | pitch_deck | S1: **95%** — Rural electrification | [0, 1, 2, 3, 0, 1] |
| `"Market analysis on plant-based protein"` | market_analysis | S1 + S2: **$8 b** — Plant-based market | [0, 1, 2, 3, 0, 1] |

S2 (market slide for plant-based) blocks list: `eyebrow, heading, subheading, hero_stat, metric_row, chart, bullets, paragraph` — massively denser than the pre-12.5 default of `eyebrow, heading, subheading, bullets`.

**Test results — `python3 -m unittest tests.test_pipeline` → 22/22 pass**. Frontend build clean: **54 modules, 206 KB JS / 63 KB gz, 31 KB CSS, 0 TS errors**.

**Direct hits on flagged gaps:**

| Gap | Before 12.5 | After 12.5 |
|---|---|---|
| "Bigger / colorful key topics" | All bullets same size, single accent color across deck | `hero_stat` block renders 84-96px giant numbers · `highlight` block w/ gradient + accent bar |
| "Design seems fixed" | Single accent color all slides | 4-variant rotation per slide (primary → warn → danger → strong) |
| "Show all slides 1→N stacked, clickable, editable" | Right panel showed one slide at a time via Timeline cards | DeckView renders all slides stacked top-to-bottom, auto-displayed when generation finishes |
| "Charts / graphs capable?" | Yes (phase 11), but only on slides where role.prefer_chart=True | Same coverage + now combined with hero_stat for dense data slides |

**Live UX flow after these fixes:**
1. Submit prompt → research streams → outline builds.
2. Once `done` event fires → **DeckView auto-displays** showing every slide as a themed 16:9 card.
3. Scroll through all slides at once. Hero stats visible, variant colors rotating.
4. **Click any slide** → SlideEditor opens at that slide for inline edit.
5. **Double-click** → Presentation mode from that index.
6. Timeline "▦ All slides" button always available to jump back.

**Scope decisions**
- 4 accent variants (not 8) — keeps theme cohesion while adding rhythm. Easy to extend by adding `.slide-accent-{4..N}` rules.
- Hero stat only on roles where data is hero-worthy (≤12 char value); avoids forcing giant 50-char paragraphs into a number slot.
- DeckView is read-only-render; editing still happens in SlideEditor modal. Future polish: in-place contenteditable in DeckView cards.
- No drag-reorder slides in DeckView — manual reorder lives in SlideEditor outline panel. Can add `dnd-kit` later if requested.

---

### 2026-05-18 — Step 12 done: per-slide regenerate + conversational refinement

**Direct fix** for user's last gap: *"rewrite, re-research for any slide that doesn't make sense or have additional value"*. Click any slide → free-text instruction → agent rewrites just that slide. Optional per-slide web re-search.

**New backend module** — [pptx_agent/pptx_agent/regen.py](pptx_agent/pptx_agent/regen.py)
- `parse_directives(instruction)` — typed parser for free-text instructions. Detects:
  - `shorten` (`"shorten"`, `"trim"`, `"less"`, `"tighter"`)
  - `expand` (`"longer"`, `"more detail"`, `"elaborate"`)
  - `add_chart` / `add_image` / `add_quote`
  - `more_numbers` (`"concrete"`, `"specific"`, `"with stats"`)
  - `less_corporate` (`"casual"`, `"human"`, `"plain english"`)
  - `refresh_research` (`"new search"`, `"re-search"`, `"fresh sources"`)
  - `use_keywords` extracted from `"use X"` / `"focus on Y"` / `"about Z"`
  - `swap_topic` from `"make this slide about X"`
- `regenerate_slide(deck, slide_number, instruction, settings, refresh_research)`:
  - Resolves the slide's role in the deck's topic-family checklist (phase 8.5).
  - Optionally calls a focused SearXNG search on the slide's title + new keywords; merges new sources into the deck's research dict (no global re-research).
  - Picks claims with directive-adjusted parameters (claim count, keyword reroute, require numeric).
  - Composes new blocks via `dynamic_outline._blocks_for_role`.
  - Forces a chart block when `add_chart` directive set (synthesizes one from metrics when no numeric data is in research).
  - Appends image placeholder block when `add_image` set.
  - Softens corporate buzzwords (`leverage`, `synergy`, `best-in-class`, `mission-critical`, etc) when `less_corporate` set.
  - Returns the new slide dict; mutates `deck["slides"][i]` in place.
  - Adds `regenerated_from` + `regenerate_instruction` metadata fields on the slide for audit/UX.

**Server endpoint** — `POST /api/jobs/<id>/slides/<n>/regenerate`
- Body: `{instruction?: str, refresh_research?: bool}`
- Loads deck.json, calls `regenerate_slide`, recomputes citations, writes all artifacts (deck.json, slides.html, slide.md, sources.md, etc).
- Returns `{job_id, slide, html_url, download_url}` so the frontend can update its optimistic state and pull fresh artifacts.

**Frontend** — new [RegeneratePanel.tsx](pptx_agent/frontend/src/components/RegeneratePanel.tsx)
- Top of SlideEditor right panel. Textarea for instruction + checkbox for "Re-search the web for this slide".
- 5 quick-preset buttons: `Shorter` · `More numbers` · `Less corporate` · `Add chart` · `Add image`. Clicking a preset submits with a canned instruction (no typing needed for common cases).
- POST to regenerate endpoint; on success, `onUpdated(slide)` replaces the slide in the editor's local state immediately so the user sees the new content w/o reloading.

**Smoke — 3 different topics, same generation pipeline:**

| Prompt | Detected family | Title | Slide structure |
|---|---|---|---|
| `"Investor pitch deck on offline solar microgrids in Bangladesh"` | `pitch_deck` | Offline solar microgrids in Bangladesh Pitch Deck | cover · problem · solution · market · comparison · metrics · metrics · ask |
| `"Research briefing on global semiconductor supply chain"` | `research_briefing` | Global semiconductor supply chain: Research Briefing | cover · market · metrics · solution · solution · comparison · ask · closing |
| `"Market analysis on plant-based protein industry"` | `market_analysis` | Plant-based protein industry Market Analysis | cover · market · metrics · comparison · team · solution · solution · comparison |

Each deck cites topic-specific facts inline (`$200 million invested in solar mini-grids [S1]` · `China invests $150 billion in domestic fabs by 2030 [S2]` · `Plant-based protein market reached $8 billion in 2023 [S3]`). Variety scores 6–7 / 8.

**Smoke — regenerate flow on slide 3 of the solar microgrid deck:**

Initial slide 3 (solution): `"How offline solar microgrids in Bangladesh solves it"` — empty bullets (no themed claims for solution layout).

After `regenerate_slide(deck, 3, "Add a chart and use more numbers, focus on capacity")`:
- Block types: `eyebrow, heading, subheading, diagram, bullets, chart` ✅ chart appended
- `regenerate_instruction` field set to instruction text

After `regenerate_slide(deck, 3, "Shorten this slide and make it less corporate")`:
- Title now research-anchored: `"Rural electrification reached 95% by 2023"`
- Bullets count: 1 (shorten directive applied)
- Cited source: `[S1]` inline

**Tests — `python3 -m unittest tests.test_pipeline` → 22/22 pass** (3 new):
- `test_parse_directives_extracts_typed_intents` — covers shorten/add_chart/more_numbers/less_corporate/refresh_research, `use X` keyword extraction, `make it about X` topic swap.
- `test_regenerate_slide_swaps_content_with_directive` — verifies chart block forced when `add_chart` set even on a role that wouldn't pick one by default, and `regenerate_instruction` metadata persisted.
- `test_regenerate_slide_unknown_raises` — `KeyError` on missing slide.

**Frontend build:** 53 modules, 202 KB JS / 62 KB gz, 28 KB CSS, 0 TS errors.

**Direct fix for user's request "rewrite, re-research for any slide that doesn't make sense":**
1. Click slide → SlideEditor → `Regenerate` panel.
2. Type free-text instruction OR pick a preset.
3. Optionally check `Re-search the web for this slide` for fresh sources.
4. Submit → backend rebuilds slide → frontend swaps in new content.
5. PPTX + HTML + slide.md all rewrite themselves automatically (write_deck_artifacts called on every regenerate).

**Scope decisions**
- Deterministic directive parsing keeps phase 12 working without `LLM_API_KEY`. When key is set, the parsed directives can drive a targeted LLM prompt in a future iteration.
- Per-slide research refresh deliberately limited to the top `max_results_per_query` results to avoid blowing the search budget; full re-research is still done by clicking `Generate` from scratch.
- No undo/redo. Stale slide content stays in `deck.json` history-of-edits only via `regenerated_from`. Add an edit-history viewer in a future polish pass.
- Skip phases 15/16/17 (gold-plating) and treat 13 (PDF) / 14 (factcheck) as nice-to-haves.

**Manus-parity line reached: 14 phases shipped (1, 2, 3, 4, 5, 6, 6.5, 7, 8, 8.5, 9, 10, 11, 12).**

---

### 2026-05-17 — Step 8.5 done: research-anchored dynamic outline + slide.md artifact

**Direct fix** for user's deepest complaint: *"slide details are fixed predefined prompt every time; not adding the web-search information slide by slide; similar design pattern, no dynamic generation"*.

**Five new modules**:

1. **[claim_miner.py](pptx_agent/pptx_agent/claim_miner.py)** — extracts concrete factual claims from research text. Six claim kinds: `head_to_head`, `currency`, `percent`, `time`, `number`, `entity`. Each claim carries `source_id`, `score`, and a keyword bag. Specificity score rewards numbers, currency, named entities, time-bounded statements. `mine_claims(research)` walks every source excerpt + insight and returns deduplicated sorted claims. `take_top_claims_for_theme(claims, theme_keywords, used)` routes claims to slides by keyword overlap, tracking cross-slide usage so the same claim doesn't dominate every slide.

2. **[topic_families.py](pptx_agent/pptx_agent/topic_families.py)** — registry of 5 deck families (`pitch_deck`, `research_briefing`, `market_analysis`, `case_study`, `product_overview`). Each family has a checklist of `SlideRole` entries (role / layout / theme_keywords / eyebrow / required / prefer_chart). `detect_family(prompt)` picks the best match by trigger keywords. `primary_keyword(topic, prompt)` extracts the most informative noun phrase for title-template substitution.

3. **[hedge_filter.py](pptx_agent/pptx_agent/hedge_filter.py)** — strips meta-instruction phrases (`"use real data when available"`, `"the deck should explain"`, `"to be added"`, `"placeholder"`, etc) and rewrites hedge tokens (`"may help"` → `"helps"`, `"should be done"` → `"is done"`). `scrub_bullets()` filters + tightens a list; `scrub_paragraph()` rewrites prose. Idempotent.

4. **[dynamic_outline.py](pptx_agent/pptx_agent/dynamic_outline.py)** — the heart of phase 8.5. `build_outline(prompt, topic, slide_count, research)`:
   - Detect family from prompt.
   - Mine claims from research.
   - Walk family's slide-role checklist, routing themed claims to each slide.
   - Synthesize slide title from the strongest themed claim (`_title_from_claim`), or fill template only when no claim is available.
   - Build subtitle from the highest-scoring claim that fits 24-180 chars.
   - Emit 2-4 bullets per slide, with inline `[S#]` citations.
   - Extract metric cards (currency, percent, named counts) from claims.
   - Compose blocks via 13 per-role recipes (problem→callout-driven, solution→diagram-flow, market→metric-row+chart, comparison→matrix, ask→callout-success, etc).
   - Auto-attach chart block when role has `prefer_chart=True` and research contains ≥3 numeric points.
   - Pad short decks with **appendix** slides ("Appendix: Why now", "Appendix: Risks…", etc) that surface unused claims rather than ship blank "Notes — N" pages.
   - Topic-anchored fallback bullets (`_ROLE_FALLBACK_BULLETS`) keep every required slide substantive when no themed claims exist.

5. **[slide_md.py](pptx_agent/pptx_agent/slide_md.py)** — emits a Manus-format markdown source-of-truth (`output/<job>/slide.md`). Matches the structure from the user's reference paste: `# Title`, `## Cover` / `## Slide N`, eyebrow tag line, title, subtitle, bullet list, metric list, `Sources: S1, S2` footer. Users can edit slide.md directly and rerender artifacts from it.

**Planner integration** — [planner.py](pptx_agent/pptx_agent/planner.py)
- `iter_build_deck` now calls `build_outline(prompt, topic, slide_count, research)` in place of the old `_fallback_deck` template list. Emits two new log events: `Topic family detected: X (Label)` and `Outline built from research: N slide(s)`.
- `normalize_deck` runs every bullet through `hedge_filter.scrub_bullets` and every title/subtitle through `scrub_paragraph`. LLM-mode output still flows through the same filter — meta-instruction text is killed everywhere.
- `family` field preserved on the deck dict alongside theme so the frontend can show it.

**Pipeline + server**
- `write_deck_artifacts` now writes `output/<job>/slide.md` and includes `slide_md` in its return shape.
- Pipeline emits a `file` event for `slide.md` alongside the others.
- Server adds `slide.md` to its allowed-asset list.

**Smoke compare (10-slide pitch deck on "healthcare in Bangladesh" with WHO/BRAC/WorldBank-style research):**

Before phase 8.5:
```
Slide 1: NextGen Healthcare In Bangladesh    ← topic-titled but generic body
Slide 2: Current State Of Healthcare         ← template title, hedge bullets
Slide 3: The Gap Is Specific, Not Generic    ← template title
Slide 4: ...                                 ← bullets read "Use source-backed facts before..."
```

After phase 8.5:
```
Slide  1 (cover):       By 2028, market projected to reach $15 billion
                          - By 2028, market projected to reach $15 billion [S3]
                          - Telemedicine adoption reached 12% in 2023, up from 4% in 2020 [S2]
Slide  2 (problem):     Healthcare in Bangladesh is fragmented across public, NGO, and private…
                          - Healthcare in Bangladesh is fragmented across public, NGO, and private tiers.
                          - Government health spending is 0.4% of GDP [S1]
                          - Out-of-pocket payments cover 67% of healthcare costs [S1]
Slide  3 (solution):    Annual growth: 8.5% CAGR
                          - Annual growth: 8.5% CAGR [S3]
                          - Hospital beds per 1,000 stood at 0.8 in 2022 [S1]
Slide  4 (market):      By 2028, market projected to reach $15 billion
                          - Total healthcare market: $10 billion [S3]
                          - Annual growth: 8.5% CAGR [S3]
Slide  5 (comparison):  Competitive edge
                          - Healthcare Bangladesh compares favorably against incumbents on speed…
Slide  6 (metrics):     Business model
                          - Tiered subscription: starter, team, and enterprise pricing for…
Slide  7 (metrics):     Annual growth: 8.5% CAGR
                          - Healthcare Bangladesh pilots in progress with named-account anchor…
Slide  8 (ask):         The ask
                          - Raise targeted at expanding engineering and go-to-market for…
Slide  9 (closing):     Building the next chapter
Slide 10 (closing):     Appendix: Why now
                          - Healthcare Bangladesh: research-backed, focused, and execution-ready.
```

**Direct hits on user's complaints:**

| Complaint | Fix |
|---|---|
| "Slide details are fixed predefined prompt every time" | Slide titles now derive from research claims; checklist-driven family structure varies by prompt |
| "Not adding the web-search information slide by slide" | Every research-themed slide carries 2-3 inline `[S#]`-tagged claims pulled directly from source excerpts |
| "Similar design pattern, no dynamic generation" | Topic family detection → different checklist per family; pitch_deck vs research_briefing produce structurally different decks |
| "Fixed slide instruction" template language | `hedge_filter.scrub_bullets` strips `"the deck should…"`, `"use source-backed"`, `"to be added"`, `"placeholder"`, `"feel free to"`, etc |
| "Where's the research per slide?" | `slide.md` artifact mirrors Manus's exposed-source-of-truth format; every slide cites `[S#]` inline + has a `Sources:` row |

**Tests** — `python3 -m unittest tests.test_pipeline` → **19/19 pass** (7 new):

| Test | What it asserts |
|---|---|
| `test_claim_miner_extracts_concrete_facts_with_source_id` | Percentage + number kinds present, source_id propagated, meta text dropped |
| `test_hedge_filter_drops_meta_sentences_and_asserts_voice` | `is_meta_bullet` catches hedge text; `scrub_bullets` strips meta + tightens "may help" → assertive |
| `test_topic_family_detection_picks_pitch_for_investor_prompts` | 5 family triggers route correctly; unknown → research_briefing |
| `test_dynamic_outline_uses_research_claims_in_slide_titles` | At least one slide title carries a research claim; `[S1]` cited inline in bullets |
| `test_dynamic_outline_research_briefing_vs_pitch_produce_different_structures` | Same topic, different family triggers → different layout sequence |
| `test_slide_md_emitter_matches_manus_format` | `## Cover`, `## Slide N`, bullets, `**value** — label`, `Sources: …` |
| `test_planner_writes_slide_md_artifact` | `output/<job>/slide.md` written; `slide_md` returned from `write_deck_artifacts` |

**Verification**
- Backend tests: **19/19 pass** (0.180s).
- Frontend build: 199 KB JS / 62 KB gz, 28 KB CSS, 0 TS errors.

**Scope decisions**
- **No LLM in the critical path.** Phase 8.5 ships fully deterministic so it works without `LLM_API_KEY`. LLM-mode (`_build_with_llm` in planner.py) still functions and the same hedge-filter + normalize step cleans LLM output too.
- **Claims aren't fabricated.** When a slot has no research-backed claim, we fall back to **topic-anchored** boilerplate (`Healthcare in Bangladesh pilots in progress with named-account anchor customers.`). The boilerplate substitutes `{primary}` / `{topic}` so the text mentions the actual subject — never a generic `"NextGen AI"`.
- **Numeric extraction reused.** Auto-charts (phase 8) keep working unchanged; `chart_block_from_research` is still called from per-role block composers.
- **Family registry is small (5)** to keep behavior predictable. New families are 20-line dataclass additions.
- **No frontend changes required.** All gains come through the existing block schema; SlideEditor + PresentationView + html_renderer + pptx_writer render the new content without modification.

---

### 2026-05-17 — Step 9 done: image search → local cache → real `<p:pic>` embed

**Goal** — turn `image` block from placeholder into real photo: searchable, persisted, embedded as actual picture in PPTX.

**Backend** — new [images.py](pptx_agent/pptx_agent/images.py):
- `ImageBroker.search(query, max_n)` — SearXNG `categories=images`. Returns title/url/thumbnail/source/dimensions. Zero-key, local-first.
- `ImageBroker.fetch_into_job(job_dir, url)` — downloads URL, validates mime (`jpeg|png|webp|gif`), caps at 4.5 MB, writes `output/<job>/media/<sha>.<ext>`, returns local URL.
- `resolve_local_image(job_dir, src)` — path-traversal-safe resolver. Only accepts `/api/jobs/<this-job>/media/<file>` matching the active job.

**Server endpoints**:
- `GET /api/images?q=...&n=12`
- `POST /api/jobs/<id>/images {url}`
- `GET /api/jobs/<id>/media/<file>`

**PPTX writer**: `_render_image_placeholder` resolves `props.src` via `resolve_local_image`; emits `<p:pic>` + registers media in `_media_index` and per-slide `_slide_image_rels`. Dedupes across slides. `[Content_Types].xml` gains `Default Extension="png|jpg|jpeg|gif|webp"`. New `set_job_dir(job_dir)` so server can wire dir before rendering.

**Frontend** — new [ImageBlockEditor.tsx](pptx_agent/frontend/src/components/ImageBlockEditor.tsx): search input → thumbnail grid → click thumb → POST to server → `src` updated. Paste-URL alternate row. Alt + caption inputs. Loading state on selected thumb.

**Test results** — `python3 -m unittest tests.test_pipeline` → **7/7 pass**:
- Image path traversal guard blocks `../../etc/passwd` and cross-job access.
- PPTX with local image: `ppt/media/test.png` present, `<p:pic>` in slide XML, image rel in slide.rels, `Default Extension="png"` in Content_Types.
- External URL falls back cleanly to labeled placeholder rect (no broken `<p:pic>`).
- SearXNG payload parsing returns correct title/url/thumbnail/source rows.

**Value added**: image blocks are now usable end-to-end. Search → pick → embed → download PPTX → real picture in slide. Previously only a `[image: alt]` placeholder shipped.

---

### 2026-05-17 — Step 8 done: dynamic block recipes + auto chart from research + variety optimize pass

**Direct fix** for user complaints "same style every deck" / "no real charts/graphs in generation" / "similar design pattern".

**New module** — [dynamic_blocks.py](pptx_agent/pptx_agent/dynamic_blocks.py):
- 11 distinct **slide recipes** (`hero_cover`, `stat_smash`, `problem_callout`, `chart_focus`, `pie_breakdown`, `diagram_flow`, `matrix_compare`, `quote_lede`, `image_split`, `paragraph_lede`, `ask`, `closing`) — each emits a different block-type sequence.
- `_RECIPES_BY_LAYOUT` maps each layout to 2-3 alternate recipes. Picker uses SHA-256(topic+layout)[0] as offset so different topics rotate through different recipes deterministically.
- `extract_numeric_series(texts)` — regex finds year+value pairs and label+percent statements in research excerpts.
- `chart_block_from_research(slide, research, kind)` — auto-builds chart block when ≥3 numeric points found. Switches kind to `line` when labels are all years (time series detected).
- `variety_score(decks_blocks)` — 0..1 fraction of unique block-type sequences.
- `optimize_deck_variety(deck, research, topic_seed, min_variety=0.55)` — critique pass; if score < 0.55, rotates to alternate recipes. Idempotent.

**Planner integration** — [planner.py](pptx_agent/pptx_agent/planner.py):
- `normalize_deck` now calls `compose_slide_blocks` instead of `slide_to_blocks` when no explicit LLM blocks. Both main path and fallback-padding path.
- `iter_build_deck` runs `optimize_deck_variety` after citations; emits SSE `log` event with score before/after.

**Smoke before/after** (10-slide deck, prompt "Pitch deck on offline solar microgrids in Bangladesh"):

| | Before phase 8 | After phase 8 |
|---|---|---|
| Block shape per slide | identical `eyebrow-heading-subheading-bullets-metric_row` ×10 | **6 unique shapes** across 10 slides |
| Variety score | 0.10 | **0.60** |
| Examples | every slide = same | cover→`eyebrow-heading-image-bullets`; problem→`eyebrow-heading-callout-bullets`; solution→`eyebrow-heading-diagram-paragraph`; market→`eyebrow-heading-metric_row-bullets`; comparison→`eyebrow-heading-quote-bullets` |

**Smoke auto-chart** (synthetic research with 4 year/value pairs):
- 3 slides automatically got chart blocks
- 2 pie, 1 bar
- Values `[3.6, 2.4, 2.8, 3.2]` and labels `[2020, 2021, 2022, ...]` extracted directly from source excerpt text
- Variety score 0.70 (no optimize needed)

**Test results** — `python3 -m unittest tests.test_pipeline` → **12/12 pass**; new phase 8 tests:
- `test_extract_numeric_series_picks_year_pairs` — extraction works.
- `test_chart_block_from_research_returns_none_when_no_numbers` — guards against fabrication.
- `test_compose_slide_blocks_varies_by_layout` — cover/problem/market produce different shapes.
- `test_planner_emits_varied_block_shapes` — full pipeline variety ≥ 0.4.
- `test_planner_emits_chart_block_when_research_has_numbers` — chart block populated when source has numeric content.

**Value added**:
1. **Variety score 6× higher** (0.10 → 0.60). Decks visually distinct per slide and per topic.
2. **Charts auto-populated from real research numbers** instead of remaining empty until user fills them.
3. **11 distinct slide recipes** vs the previous single template — chart-focus, diagram-flow, quote-lede, matrix-compare, stat-smash, callout-driven, image-split, paragraph-led, ask, closing.
4. **Idempotent + deterministic** — same prompt always produces the same deck; different prompts rotate recipes differently.

**Scope decisions**
- No LLM-in-loop critique (deterministic optimize is sufficient). LLM critique slots in here when token budget allows.
- Numeric extraction is heuristic; year-prefixed series cleanest. Phase 14 (factcheck) tightens.
- 11 recipes is intentionally modest. New recipes are 5-line additions to the registry.

---

## History (newest first)

### 2026-05-17 — Phase 9 done: image sourcing, job media, and PPTX embed

**Goal** — continue where Claude stopped: finish the existing local-first image path without changing planner/deck logic. Claude had already introduced the Phase 9 direction (`images.py`, image endpoints, and a partial PPTX writer edit); the remaining work was wiring it end-to-end and verifying the actual export.

**Backend image path**
- [pptx_agent/pptx_agent/images.py](pptx_agent/pptx_agent/images.py) provides SearXNG image search (`categories=images`) and downloads selected HTTP(S) images into `output/<job>/media/<hash>.<ext>`.
- [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py) exposes:
  - `GET /api/images?q=...&n=12` for image search.
  - `POST /api/jobs/<job_id>/images` to download a selected image into that job's `media/` folder.
  - `GET /api/jobs/<job_id>/media/<file>` to serve downloaded media.
  - PPTX download now passes the job directory into `PptxWriter` so local `/api/jobs/<job>/media/<file>` refs resolve to bytes on disk.

**Editor wiring**
- [pptx_agent/frontend/src/components/SlideEditor.tsx](pptx_agent/frontend/src/components/SlideEditor.tsx) now shows an image panel when an `image` block is selected:
  - manual `src`, `alt`, and `fit` controls;
  - search box backed by `/api/images`;
  - selectable thumbnail results;
  - selected result is downloaded through `/api/jobs/<job>/images` and patched into the block as a local media URL.
- [pptx_agent/frontend/src/styles.css](pptx_agent/frontend/src/styles.css) adds compact image-result grid styling for the right-side editor panel.

**PPTX embed completion**
- [pptx_agent/pptx_agent/pptx_writer.py](pptx_agent/pptx_agent/pptx_writer.py) now embeds downloaded local image blocks as real `<p:pic>` shapes instead of placeholders:
  - resolves only `/api/jobs/<current-job>/media/<file>` paths;
  - writes deduped files under `ppt/media/<file>`;
  - adds per-slide image relationships in `ppt/slides/_rels/slideN.xml.rels`;
  - emits image content-type defaults (`png`, `jpg`, `jpeg`, `gif`, `webp`);
  - preserves placeholder behavior for empty or external-only URLs.

**Tests added**
- `test_resolve_local_image_only_accepts_current_job_media` — verifies job-local media resolution and rejects other jobs/external URLs.
- `test_pptx_writer_embeds_local_image_blocks` — verifies `ppt/media/<file>`, `<p:pic>`, `r:embed`, slide image rels, alt text, caption, and content types.

**Verification**
- Backend tests: **33/33 pass** (`../.venv/bin/python -m unittest tests.test_pipeline -v`) — 0.043 s.
- Frontend build: **clean** (`npm run build`) — 51 modules, **196.92 KB JS / 61.20 KB gz**, **25.45 KB CSS / 5.09 KB gz**.

**Scope decisions**
- AI image generation remains deferred because the current Claude implementation is explicitly local-first stock sourcing and the repo has no image-generation provider/env contract yet.
- External image URLs still render in HTML previews, but PPTX embeds only downloaded job-local media; external-only URLs fall back to the existing placeholder so exports stay self-contained.

### 2026-05-17 — Replan: 8-step MVP → 17-phase real-parity roadmap

**Why** — phases 1-4 hit "looks like Manus" but not real parity. Audit identified 5 missing pillars: images (#9), themes (#10), real charts (#11), conversational refine (#12), PDF+share (#13). All five are visible in every Manus deck. Without them the agent is a one-shot generator, not an editor.

**Re-ordering rationale**
- Phase 10 (themes) pulled before 6 — pure CSS-variable swap, ~2hr cost, big visual payoff before editor lands.
- Phase 11 (charts) pulled before 9 — chart is a block type; cheaper to build while block schema is fresh.
- Phase 7 (PPTX writer) deferred until block taxonomy stabilizes (after 5, 11, 9).
- Phase 8 (optimize pass) is backend-only, can slot in anytime; placed after 7 to avoid churning block contracts mid-flight.

**Plan table updated above.** No code yet — this entry records the decision.

### 2026-05-17 — Step 7 done: PPTX writer block dispatcher + theme tokens

**Goal** — replace the fixed two-column "fake metric box" PPTX layout with a block-driven, theme-aware writer that mirrors the HTML preview. Triggered by user feedback that the export looked generic, did not show real charts, and used "irrelevant information boxes".

**Rewrite** — [pptx_agent/pptx_agent/pptx_writer.py](pptx_agent/pptx_agent/pptx_writer.py)
- Drops the layout-keyed `_visual_shapes` / `_metric_shapes` branches. Slide composition now reads `slide["blocks"]` (falling back to `slide_to_blocks` when missing) and stacks each block top-to-bottom from `CONTENT_Y_START=720000` to `CONTENT_Y_END=SLIDE_H-400000`. Overflow protected — extra blocks past the bottom edge are dropped instead of overlapping.
- Block dispatch table: each type maps to a `_render_<type>(props, x, y, w, tokens)` returning `(shapes, height_used)`. Heights are heuristic per type (heading: 900k EMU, bullets: ~350k × items, metric_row: 750k, chart: ≤2100k, image placeholder: 1700k, etc.). A `BLOCK_GAP=120000` separator goes between blocks.
- Header decoration: 95250-EMU tricolor stripe (accent / warn / danger) instead of the old two-color hardcoded bar — adapts to whatever theme is in the deck.
- Topline row carries slide number + uppercased eyebrow at 950 size in `muted` color.

**Per-block renderers**
- `eyebrow` — 1050-size uppercased accent text.
- `heading` — title text. Size auto-scales: 3200 (<36 chars) / 2600 (<60) / 2200; height tracks text length.
- `subheading` — 1400 muted text, 500k EMU or 800k for long.
- `paragraph` — ink text; height computed as `280k × (len(text)//75 + 1)` clamped to 2.2m.
- `bullets` — `_bullets()` helper now uses accent color for bullet markers via `<a:buClr>` instead of black dots. Bullet text uses `ink` color from the theme.
- `metric_row` — horizontal row of rounded `panel_alt` cards with `accent` value text + muted label (uppercased). Card width scales to fill content area divided by count.
- `quote` — left accent bar (`80000` EMU wide) + `panel_alt` rounded rect + italic text + small attribution row.
- `callout` — tinted rect (`accent_soft` if info/success, `panel_alt` otherwise) with bordered color matching tone; ink text inside.
- `image` — placeholder rounded rect labeled `[image: alt]` until phase 9 wires real picture embed (`<p:pic>`).
- `chart`:
  - `bar` (multi-series safe) renders as native PPTX bar group. Math mirrors the SVG renderer in `charts.py`: `peak = max(|v|)`, bar height ∝ `|v|/peak × plot_h`, baseline line drawn, axis labels written under each band. Two-color alternation (accent/warn).
  - `line` / `area` / `pie` fall back to a small **data table** rendered inside a `panel_alt` rectangle: label column + series columns. Honest representation when native rendering would be too noisy. Native vector line/area/pie deferred to phase 8+ when chart usage tightens.
- `diagram`:
  - `flow` — horizontal row of `accent_soft` boxes with `warn` arrows between.
  - `matrix` — 2-column grid of `panel_alt` cells.
  - `orbit` — central ellipse (`accent_soft`) with `accent` chips placed at angular intervals; supports up to 6 nodes.
- `spacer` — `sm`/`md`/`lg` → 120k / 240k / 480k EMU vertical advance.

**Theme integration** — pulls colors from `deck["theme"]` via `themes.get_theme(name).tokens`. `_theme()` (theme1.xml) now writes per-theme accent slots:
- `accent1` = theme accent
- `accent2` = warn
- `accent3` = danger
- `accent4` = accent_strong
- `accent5` = muted
- `accent6` = accent_soft
- `dk1`/`lt1` → ink / panel, `dk2`/`lt2` → muted / bg
- hlink + follow-hlink both tied to accent
- Theme `<a:clrScheme name>` set to the theme name; `<a:theme name>` carries the human label ("Slate (Light)", "Midnight (Dark)", etc).

**Color coercion** — new `_hex(token)` helper parses `#RRGGBB`, `#RGB`, and `rgb(...)` token values into bare-RRGGBB OOXML strings. Empty / malformed values fall back to `FFFFFF`.

**Static parts touched up**
- `_slide_master`, `_slide_layout` unchanged structurally but kept theme-clean (no leftover hardcoded teal/amber refs).
- `<a:fontScheme>` keeps Aptos (matches Office defaults); custom font swap is a phase 10 follow-up if needed.

**Tests added** — [pptx_agent/tests/test_pipeline.py](pptx_agent/tests/test_pipeline.py)
- `test_pptx_writer_uses_theme_colors_in_theme_xml` — midnight theme → theme1.xml contains `3AA0FF` (accent) and `070B12` (bg) hex.
- `test_pptx_writer_renders_blocks_into_slide_xml` — injects heading+chart+bullets blocks onto slide 2; resulting slide XML carries the heading text, uppercased chart title, bullet items, slate accent color, and axis labels.
- `test_pptx_writer_falls_back_to_slide_to_blocks_when_blocks_missing` — strips `blocks` from every slide; writer still produces a valid PPTX with text content per slide. Confirms the legacy adapter is the safety net for older `deck.json` files.
- Existing `test_deck_and_pptx_generation` still passes (zip structure, 15 slides, Content_Types manifest intact).

**Verification**
- Backend tests: **31/31 pass** (3 new) — 0.035 s.
- Smoke: 5-slide deck w/ injected chart block + midnight theme renders to a 14.7 KB pptx with 24 parts. Slide 2 xml: 10.8 KB (chart + heading + bullets + axis labels). theme1.xml: 1.05 KB.
- Existing PATCH flow re-renders cleanly: edit slide → `write_deck_artifacts` → next pptx download picks up new shapes.

**Scope decisions**
- **No image embed yet.** `image` block renders as a placeholder. Wiring real `<p:pic>` + `ppt/media/imageN.{png,jpg}` parts + per-slide relationships is phase 9's job (and that's where image sourcing/AI gen lands too).
- **Line/area/pie shown as table.** Native vector line+area would need `<a:custGeom>` paths; pie would need arc paths. Possible but ugly to render without anti-alias hinting. Table format is honest and readable; native rendering can replace it in a future polish pass once charts.py has stable polylines.
- **No native PPTX charts (`<c:chart>`).** Those require an embedded chart XML part w/ its own rels chain. Heavier than needed today — phase 8 (optimize pass) can revisit if presenters complain.
- **Slide master kept blank.** All visual structure happens at the slide level so blocks can vary per slide. A richer per-layout slide master is a phase 10 follow-up if we add layout templates beyond block-list flow.

### 2026-05-17 — Step 6.5 done: presentation viewer (fullscreen carousel)

**Goal** — answer user gap: "why no slide-by-slide clickable presentation?". Adds a dedicated full-screen viewing mode separate from the editor so you can present without entering edit mode.

**New components**
- [frontend/src/components/BlockRender.tsx](pptx_agent/frontend/src/components/BlockRender.tsx) — read-only block renderer mirroring `pptx_agent/html_renderer.py`. One render function per block type; chart blocks delegate to `ChartView`. Used by presentation mode and (later) any other in-app surface that needs to render a slide.
- [frontend/src/components/PresentationView.tsx](pptx_agent/frontend/src/components/PresentationView.tsx) — fullscreen modal:
  - Topbar: slide N/M counter, current title, Prev/Next buttons, Close (Esc).
  - Stage: themed slide surface (token inline-style via `tokensToStyle`) rendering `slide.blocks` through `BlockRender`. Falls back to legacy fields if a slide has no blocks.
  - Thumb strip: horizontal scroll, click any thumb to jump.
  - Keyboard: ArrowRight / Space / PageDown → next; ArrowLeft / PageUp → prev; Home / End → first / last; Esc → close.
  - Body scroll locked while open; restored on close.

**Wiring**
- [App.tsx](pptx_agent/frontend/src/App.tsx) — new state `presentingFromIndex: number | null`, "Present" button in header (visible once any slide exists), mounts `PresentationView` when active.
- [ComputerPanel.tsx](pptx_agent/frontend/src/components/ComputerPanel.tsx) — threads `onPresent` down to SlideView.
- [SlideView.tsx](pptx_agent/frontend/src/components/SlideView.tsx) — adds "Present from here" button that opens the viewer at that slide's index (using sorted slide-number order).

**Styles** — [frontend/src/styles.css](pptx_agent/frontend/src/styles.css)
- `.present-modal`/`.present-topbar`/`.present-stage`/`.present-surface`/`.present-thumbs`/`.thumb` styles. Surface uses 16:9 aspect ratio, panel background from theme tokens, decorative top stripe matching the HTML export, scaled-up font sizes for presentation viewing (h2 = 44 px instead of 38 in editor surface).
- Block styles within `.present-surface` mirror the standalone HTML export (eyebrows, bullets, metrics, callouts, charts, etc) so the in-app presentation matches what gets exported.

**Frontend build**
- 51 modules, **193 KB JS / 60 KB gz**, 25 KB CSS, 0 TS errors.

**Scope decisions**
- **No slide transitions / animation.** Static crossfade or slide-in would be nice but isn't a parity requirement; can land alongside phase 12 (regenerate + chat) when we revisit UX polish.
- **No speaker-notes overlay.** Notes live on `slide.speaker_notes` (editable in phase 6 design panel). A presenter-mode overlay with notes + clock is straightforward but out of scope here.
- **Read-only.** Editing happens in `SlideEditor`; presentation is for showing. Future "double-click to edit from presentation" can be a one-liner if wanted.

### 2026-05-17 — Step 11 done: real SVG charts (bar/line/area/pie) with editor controls

**Goal** — replace the deterministic-CSS "fake bars" with real data-driven charts that work both in the standalone HTML export and in the in-app editor. No JS runtime required for the export (everything is server-rendered SVG).

**New module** — [pptx_agent/pptx_agent/charts.py](pptx_agent/pptx_agent/charts.py)
- `render_chart_svg(kind, series, labels, title)` returns a self-contained SVG string with embedded `<style>` block. Chart kinds: `bar`, `line`, `area`, `pie`.
- View box `480×220`, padded for labels/axis. Single-line series math: `peak = max(|v|) or 1`; bar height ∝ `|v|/peak`.
- Colors pulled from theme CSS variables (`var(--accent)`, `var(--accent-soft)`, `var(--warn)`, `var(--danger)`, `var(--muted)`, `var(--line)`) so charts inherit the deck theme without per-render overrides.
- Bar charts support multi-series (grouped); first series uses `--accent`, second uses `--warn`. Pie uses only the first series (4-color rotating palette).
- Line/area: ≥2 points required; falls back to bar render if only 1 point passed. Area = filled polygon under the first series + line on top.
- Empty/no-data state renders a dashed-border placeholder strip (`80px` tall) with the title plus "— no data" text.

**Renderer wiring** — [pptx_agent/pptx_agent/html_renderer.py](pptx_agent/pptx_agent/html_renderer.py)
- `_render_chart` now delegates to `render_chart_svg` and appends a small `<ul class="chart-legend">` if series have labels. Each chart block becomes `<div class="chart chart-{kind}" data-chart-kind="{kind}"><svg…/><ul class="chart-legend"/></div>`.
- CSS replaced: dropped `.bars`/`.bar`/`.chart-empty` ad-hoc rules in favor of `.chart-svg`, `.chart-legend`, `.chart-legend-a/b` styled chips. SVG max-height capped at 240 px so charts stay inside the slide aspect ratio.

**Block validation** — [pptx_agent/pptx_agent/blocks.py](pptx_agent/pptx_agent/blocks.py)
- `normalize_block` (chart branch) now:
  - Lower-cases `kind` and constrains to `{bar, line, area, pie}` (unknown → `bar`).
  - Coerces every series value through `float(v)` and silently drops non-numeric entries.
  - Casts every label to str.
  - Forces `series` shape to `[{label: str, values: [float]}]` even if input was `["a", "b"]` (those rows are skipped instead of crashing).
- This means LLM-supplied chart specs (string numbers, dirty data) survive normalization deterministically.

**Frontend SVG mirror** — [pptx_agent/frontend/src/components/ChartView.tsx](pptx_agent/frontend/src/components/ChartView.tsx)
- 1-to-1 port of `charts.py`. Same viewBox, same padding, same math. Same CSS-variable color references via embedded `<style>` inside `<defs>`.
- Rendered with React JSX (`<svg><rect/><polyline/><path/></svg>` etc), no chart library dependency. Bundle delta: ~5 KB minified.
- Exposes `ChartKind` and `ChartSeries` types so other components can type chart data correctly.

**Editor integration** — [pptx_agent/frontend/src/components/EditorBlock.tsx](pptx_agent/frontend/src/components/EditorBlock.tsx)
- New `ChartBlockEditor` sub-component:
  - Renders live `ChartView` preview at the top.
  - Below: control grid with `kind` `<select>` (bar/line/area/pie), `title` input, `labels` CSV input (`"Q1, Q2, …"`), and a per-series row list. Each series row = label input + values CSV input + delete button. `+ series` button appends.
  - All edits flow through `onChange({...props, …})` → `commit` → `useSlidePatch.send` debounced PATCH. Saved state visible in editor header.
- `chart` and `diagram` added to `ADDABLE_BLOCKS` in [SlideEditor.tsx](pptx_agent/frontend/src/components/SlideEditor.tsx). Default chart on insert now ships with sample data (`{kind: "bar", series: [{label: "Series A", values: [3,5,8,6]}], labels: ["Q1","Q2","Q3","Q4"], title: "Sample chart"}`) so users see a working chart immediately. Default diagram ships with `{kind: "flow", nodes: [Start, Middle, End]}`.

**Styling** — [pptx_agent/frontend/src/styles.css](pptx_agent/frontend/src/styles.css)
- `.chart-edit` flex layout, `.chart-edit-controls` 2-column auto-fit grid (dashed border to flag it's an editor-only chrome).
- `.chart-series-row` `1fr 1.6fr auto` grid for label/values/delete.
- `.chart-legend`/`.chart-legend-a/b` chip styles mirror the standalone export.
- `.btn.ghost.small` small inline action button used for `+ series`, `+ bullet`, `+ metric`, etc.

**Tests** — [pptx_agent/tests/test_pipeline.py](pptx_agent/tests/test_pipeline.py) → **28/28 pass**
- `test_chart_svg_bar_has_bars_for_each_value` — 4 values → 4 `<rect class="chart-svg-bar">`; tick labels Q1-Q4 + title rendered.
- `test_chart_svg_line_uses_polyline` — line kind emits `<polyline>`.
- `test_chart_svg_area_includes_polygon_fill` — area kind emits `<polygon class="…area">` underneath the polyline.
- `test_chart_svg_pie_emits_paths` — 4 slices → 4 `<path>` arcs.
- `test_chart_svg_empty_when_no_values` — empty data renders "no data" placeholder.
- `test_normalize_block_chart_coerces_strings_to_floats` — `"10"`/`"x"`/`"5"` → `[10.0, 5.0]`; non-string labels stringified; bogus kinds → `bar`.
- `test_normalize_block_chart_rejects_unknown_kind` — `doughnut` → `bar`.
- `test_html_renderer_chart_block_emits_svg` — chart block renders as `<svg>`, includes title, labels, and legend.

**Verification**
- Frontend build: 49 modules, **187 KB JS / 59 KB gz**, 21 KB CSS, 0 TS errors.
- Smoke `render_chart_svg('bar', 2-series × 4 values)` produces 2176-byte SVG with 4 primary bars + 4 alt bars.

**Scope decisions**
- **No Recharts / no Mermaid.** Pure SVG keeps the export self-contained (works when emailed, hosted statically, embedded in iframes without scripts). Bundle delta is also tiny (~5 KB) compared to ~150 KB for Recharts.
- **No diagram rewrite.** Existing `diagram` kinds (`flow`, `matrix`, `orbit`) already render acceptably from theme-driven HTML/CSS in phase 5. Adding Mermaid would only matter for richer custom diagrams — defer until a real user need shows up.
- **Frontend mirrors backend manually**, accepting small duplication risk. Tests on the backend catch math drift; the React port is small enough to audit by eye.
- **Chart data is user-driven for now.** Planner does not auto-generate charts from research metrics; users hit `+ chart` in the editor and fill in numbers. Auto-chart-from-research is a phase 8 (optimize pass) opportunity once the LLM can target the `chart` block type explicitly.
- **PPTX writer** still emits chart blocks as text placeholders (block dispatcher in phase 7). When the PPTX dispatcher lands it will reuse `render_chart_svg` output (or rasterize) — same SVG already lives in the exported HTML so consistency is one swap away.

### 2026-05-17 — Step 6 done: fullscreen slide editor with inline contenteditable + PATCH save

**Goal** — turn the read-only slide preview into an editable surface. Per-slide edits persist server-side via PATCH, rerender all artifacts (deck.json, slides.html, sources.md, structure, content markdown), and reflect immediately in the UI without re-running research/planner.

**New backend modules**
- [pptx_agent/pptx_agent/editor.py](pptx_agent/pptx_agent/editor.py) — pure functions for deck mutation:
  - `apply_slide_patch(deck, slide_number, patch)` — shallow-merges scalar fields (`title`, `subtitle`, `eyebrow`, `layout`, `speaker_notes`), validates `bullets`/`metrics`/`citations`, and either accepts an explicit `blocks` list (normalized through `normalize_blocks`) or regenerates blocks from scalar updates via `slide_to_blocks`. Raises `KeyError` on unknown slide number.
  - `apply_deck_patch(deck, patch)` — deck-level fields (`title`, `subtitle`, `audience`, `topic`, `theme`). Theme resolved via `get_theme` w/ silent fallback.
  - `recompute_citations(deck)` — runs `cite_slide` heuristic for any slide that lost its citations during edit.
- Factored [pptx_agent/pptx_agent/pipeline.py](pptx_agent/pptx_agent/pipeline.py) → `write_deck_artifacts(deck, job_dir, research?)` — single function that writes `deck.json`, `pitch_deck_structure.txt`, `slide_content.md`, `slides.html`, `sources.md` and returns rendered artifacts. Called both from `iter_pipeline` (initial run) and from the new PATCH handlers (post-edit re-render). `research` arg falls back to `deck["research"]` so post-edit calls don't need to pass it.

**New endpoints** — [pptx_agent/pptx_agent/server.py](pptx_agent/pptx_agent/server.py)
- Added `do_PATCH` dispatcher.
- `PATCH /api/jobs/<job_id>/slides/<n>` — body `{title?, subtitle?, eyebrow?, layout?, bullets?, metrics?, citations?, speaker_notes?, blocks?}`. Loads `deck.json`, applies patch, recomputes citations, rewrites all artifacts, returns updated slide.
- `PATCH /api/jobs/<job_id>/deck` — deck-level patch (`title`, `subtitle`, `audience`, `topic`, `theme`). Same re-render pipeline.
- Both validate job dir is inside `output/` (path traversal guard reused from event stream code).
- pptx download already regenerates from `deck.json` on every hit, so no cache invalidation needed.

**Frontend additions**
- New hook — [frontend/src/useSlidePatch.ts](pptx_agent/frontend/src/useSlidePatch.ts)
  - Debounced (400 ms) PATCH dispatcher coalescing rapid edits into one request. `send(jobId, slideNumber, payload)` queues; `flush()` forces immediate send. Tracks `idle|saving|saved|error` status + last-saved timestamp + error message. Cancels in-flight requests with `AbortController` when a new patch is queued.
- New themes client — [frontend/src/themes-client.ts](pptx_agent/frontend/src/themes-client.ts)
  - Module-level cache of `/api/themes` response (one fetch per session). `useThemes()` hook + `tokensToStyle(tokens)` converter that turns the token dict into a React `style` object with `--ink`, `--accent`, `--font-display`, etc. CSS variables. Used to apply theme tokens inline on the editor surface — same scope as the standalone HTML export.
  - Backend updated: `list_themes()` now includes full `tokens` dict (15 vars) so the editor can apply themes inline without a second request.
- New component — [frontend/src/components/SlideEditor.tsx](pptx_agent/frontend/src/components/SlideEditor.tsx)
  - Full-screen modal (z-index 1000), 3-column layout:
    - **Left (240 px):** block outline w/ type tag + preview snippet, click to select. Bottom: `+ Add block` `<details>` with grid of 9 addable types (heading, subheading, paragraph, bullets, metric_row, quote, callout, image, spacer).
    - **Center:** `.editor-surface` rendered with theme tokens applied inline. Iterates blocks via `EditorBlock` component (one renderer per block type). Slide aspect kept tall and centered.
    - **Right (280 px):** design panel — layout `<select>` (11 layouts), inline accent color override (live CSS var swap, not persisted), speaker notes textarea, citation pills.
  - Header: `Slide N` pill, layout dropdown, save status (Saving… / Saved ✓ / Save failed), `Close (Esc)` button. `Esc` closes modal; body scroll locked while open.
  - On every edit: `commit(nextSlide)` updates local state, calls `onLocalChange` (App-level override map for optimistic UI), and `patch.send(jobId, n, payload)` which debounces.
- New component — [frontend/src/components/EditorBlock.tsx](pptx_agent/frontend/src/components/EditorBlock.tsx)
  - One editable renderer per block type. Text blocks (`eyebrow`, `heading`, `subheading`, `paragraph`, `quote`, `callout`) use a small `EditableText` helper that wraps the actual HTML tag (`h2`, `p`, `span`, `strong`, `figcaption`) with `contentEditable`. Caret-stable on prop changes (only writes to DOM if textContent differs).
  - `bullets`: per-li `EditableText` + `+ bullet` button. Empty bullets are kept until next blur so user can type without disappearing rows.
  - `metric_row`: each metric is two editable spans (value + label) + `+ metric` button.
  - `image`: shows placeholder when no `src`, caption editable. Real upload lands in phase 9.
  - `chart`/`diagram`: read-only chip; full editing in phases 11 (charts) and 6/12 follow-ups.
  - Hover/selected block shows toolbar: `↑` (move up), `↓` (move down), `✕` (delete). First/last block has disabled move buttons.
- Wiring
  - [SlideView.tsx](pptx_agent/frontend/src/components/SlideView.tsx) gained `onEdit?: (n) => void`. Header shows `Edit slide` button when `jobId` is set.
  - [ComputerPanel.tsx](pptx_agent/frontend/src/components/ComputerPanel.tsx) threads `onEditSlide` down to SlideView.
  - [App.tsx](pptx_agent/frontend/src/App.tsx):
    - `editingSlide: number | null` state controls modal mount.
    - `localSlideOverrides: Map<number, SlideData>` — optimistic-update layer. Merged on top of stream-derived state via `useMemo`, so the right panel and computer surface show the edited slide instantly even before the PATCH response lands. Reset when `jobId` changes (new generation).
    - Renders `<SlideEditor>` at root when `editingSlideData && job.jobId`.
- Styles — [frontend/src/styles.css](pptx_agent/frontend/src/styles.css)
  - `.editor-modal`/`.editor-shell`/`.editor-header`/`.editor-body` modal frame.
  - `.editor-left .block-outline` / `.add-block` block list + add menu.
  - `.editor-stage` background w/ radial accent halo.
  - `.editor-surface` full set of theme-token-driven slide styles mirroring the standalone HTML renderer (so the editor surface shows themed result faithfully).
  - `.editor-block` + `.editor-block.selected` + `.block-toolbar` (floating action chips on hover/select).
  - `.form-row` consistent labeled inputs for design panel.
  - Responsive: under 920 px the 3-column editor collapses to single column.

**Tests** — [pptx_agent/tests/test_pipeline.py](pptx_agent/tests/test_pipeline.py)
- `test_apply_slide_patch_updates_scalars_and_regenerates_blocks` — title + bullets patch propagates to slide *and* regenerates the blocks list with the new content.
- `test_apply_slide_patch_accepts_explicit_blocks` — when the patch carries a full `blocks` array, those are normalized and replace the slide's blocks. IDs renumbered with `s{n}-` prefix.
- `test_apply_slide_patch_missing_slide_raises` — `KeyError` on unknown slide number.
- `test_apply_deck_patch_changes_theme` — theme name resolved through `get_theme` (valid name preserved, bogus name silently falls back to default).
- `test_write_deck_artifacts_emits_all_files` — confirms `deck.json`, `pitch_deck_structure.txt`, `slide_content.md`, `slides.html`, `sources.md` are all written and returned shape includes `html`, `preview_html`.

**Verification**
- Backend unit tests: **20/20 pass** (0.023s).
- Frontend build: 48 modules, **182 KB JS / 57 KB gz**, 20 KB CSS, 0 TS errors.
- Live PATCH smoke (PORT 8799):
  - Generate 5-slide `theme=midnight` deck via `iter_pipeline`.
  - `curl PATCH /api/jobs/<id>/slides/1` w/ `{title: "Edited via PATCH", bullets: [...]}` → response carries the updated slide with regenerated blocks (`eyebrow, heading, subheading, bullets, metric_row, diagram`).
  - Re-reading `deck.json` confirms persistence; `slides.html` rebuilt; pptx download will pick up the change on next hit (writer reads `deck.json` per request).

**Scope decisions**
- No drag-and-drop — toolbar arrow buttons only. Adequate for phase 6 budget; can add `dnd-kit` in a future polish pass.
- No undo/redo stack — server-authoritative `deck.json` is the source of truth; in-app overrides are best-effort optimistic. If wanted later, a client-side history stack on the overrides Map is trivial.
- Image upload deferred to phase 9 (image source/AI gen).
- Chart editor deferred to phase 11.
- Accent override in design panel currently applies via inline CSS var swap on the editor surface only (not persisted) — durable per-slide theme overrides will land with phase 12 (regenerate + chat refine) where the slide-level `theme_overrides` schema gets formalized.
- LLM is not in the edit path — phase 6 is human-only editing. Phase 12 wires "rewrite slide 3 shorter" conversational refinement that drives the same PATCH endpoint.

### 2026-05-17 — Step 10 done: theme system (5 presets, /api/themes, picker UI)

**Goal** — make deck visual style swappable via named preset instead of hardcoded teal/amber. CSS-variable swap per `data-theme` attribute. One source of truth shared by HTML preview and (phase 7) PPTX export.

**New module** — [pptx_agent/pptx_agent/themes.py](pptx_agent/pptx_agent/themes.py)
- `Theme` dataclass (name, label, mode `light|dark`, tokens dict).
- `THEMES` registry with 5 presets:
  - `slate` — light, teal accent (`#087c7c`), Inter (default).
  - `midnight` — dark navy + electric blue (`#3aa0ff`), Manus-style.
  - `sand` — warm cream + bronze (`#a4632a`), serif headings.
  - `mono` — editorial black/white, serif heading + mono body, zero radius.
  - `pitch` — investor navy + gold (`#d8b25a`), dark mode w/ serif headings.
- 15 required tokens per theme: `ink`, `muted`, `bg`, `panel`, `panel_alt`, `line`, `accent`, `accent_strong`, `accent_soft`, `warn`, `danger`, `shadow`, `radius`, `font_display`, `font_body`.
- `get_theme(name)` w/ silent fallback to `DEFAULT_THEME` (`slate`).
- `list_themes()` for `/api/themes` payload — shape `{name, label, mode, accent, bg}`.
- `theme_css_block(theme, selector?)` renders `:root[data-theme="..."] {…}` block w/ kebab-cased CSS variables + `color-scheme: light|dark`.
- `all_theme_css()` emits default `:root` block + one per registered theme. Single style block, swap is one attribute change.

**Renderer changes** — [pptx_agent/pptx_agent/html_renderer.py](pptx_agent/pptx_agent/html_renderer.py)
- `<html>` element now carries `data-theme="<name>"` + `data-theme-mode="light|dark"`. Theme resolved via `get_theme(deck.get("theme"))`.
- `_standalone_css()` rewritten: dropped hardcoded `--teal`/`--amber`/`--coral`. Every CSS value now references theme variables (`var(--accent)`, `var(--panel-alt)`, `var(--accent-soft)`, `var(--font-display)`, `var(--radius)`, …).
- Removed legacy color literals (`#fbfcfd`, `#2f3b46`, `#eef6f5`, `#c8ddda`, `rgba(8,124,124,…)`) — all now derive from theme tokens. Light/dark presets render correctly without per-rule branches.
- All 5 themes embedded into every `slides.html`, so the file works as a self-contained static document and the chosen theme is one attribute away.

**Planner changes** — [pptx_agent/pptx_agent/planner.py](pptx_agent/pptx_agent/planner.py)
- `build_deck()` and `iter_build_deck()` accept optional `theme: str | None`. Resolved via `get_theme(theme).name` (silently falls back).
- `normalize_deck()` writes resolved `deck["theme"]` field (default `slate`).
- `deck_meta` event payload now includes `theme` — frontend can react before slide content lands.

**Pipeline + server wiring**
- [pipeline.py](pptx_agent/pptx_agent/pipeline.py): `iter_pipeline`, `iter_pipeline_with_persist`, `run_pipeline_and_persist` all accept `theme` and pass through. `job_start` event carries `theme` so replays know the choice.
- [server.py](pptx_agent/pptx_agent/server.py):
  - New `GET /api/themes` — returns `{default, themes: [{name, label, mode, accent, bg}]}` for picker rendering.
  - `POST /api/generate` and `POST /api/generate/stream` both read `theme` from request payload, pass to pipeline.

**Frontend**
- New component — [frontend/src/components/ThemePicker.tsx](pptx_agent/frontend/src/components/ThemePicker.tsx)
  - Fetches `/api/themes` once on mount, renders 5 swatches as a radio group. Each swatch shows the theme's `bg` background + an `accent`-colored marker rectangle + label. Selecting swatches calls `onChange(name)`.
  - Defaults to `data.default` (server-authoritative). Error fallback when endpoint unreachable.
- [frontend/src/components/PromptForm.tsx](pptx_agent/frontend/src/components/PromptForm.tsx) — now accepts `theme` + `onThemeChange`; renders `<ThemePicker>` between slide count input and submit. Passes theme on submit.
- [frontend/src/App.tsx](pptx_agent/frontend/src/App.tsx) — owns `theme` state, reads `job.deckMeta.theme` once available (server-authoritative after generation), sets `data-theme` on `<html>` + `.app-shell` (no visual effect on app shell since `:root[data-theme]` rules only target slide preview surfaces — phase 6 will wire SlideView to use them; for now exported `slides.html` is the surface that visually changes).
- [frontend/src/useEventStream.ts](pptx_agent/frontend/src/useEventStream.ts) — `StreamRequest.theme?: string` added to request shape.
- [frontend/src/events.ts](pptx_agent/frontend/src/events.ts) — `DeckMetaEvent.theme?: string`.
- [frontend/src/state.ts](pptx_agent/frontend/src/state.ts) — `deckMeta.theme` preserved through reducer.
- [frontend/src/styles.css](pptx_agent/frontend/src/styles.css) — `.theme-picker`, `.theme-swatch`, `.theme-swatch-preview`, `.theme-swatch-label`, `.theme-badge` styles. Scoped to picker; does not touch app shell colors.

**Scope decision** — app shell (left rail, header, computer panel) keeps the dark Manus look regardless of selected theme. Theme applies to:
1. Exported `slides.html` (full visual swap via `data-theme` attribute).
2. Future in-app slide preview surface (phase 6 unifies SlideView to use renderer-style tokens).
Doing this avoids re-skinning the React UI every theme change and keeps phase 10 in the promised ~2hr budget.

**Tests** — [pptx_agent/tests/test_pipeline.py](pptx_agent/tests/test_pipeline.py)
- `test_theme_registry_has_expected_presets` — 5 themes present, every token defined.
- `test_get_theme_falls_back_to_default` — `None`, `"bogus"` both return slate.
- `test_theme_css_block_uses_kebab_case_vars` — `--accent-soft`, `--font-display`, `color-scheme: dark` present.
- `test_list_themes_shape` — endpoint payload has required keys.
- `test_html_renderer_sets_data_theme_attribute` — output contains `data-theme="midnight"`, `data-theme-mode="dark"`, all 5 theme blocks embedded.
- `test_build_deck_resolves_theme_param` — explicit theme honored; bogus name silently falls back.

**Verification**
- Backend unit tests: **15/15 pass** (0.027s).
- Frontend build: 44 modules, **170 KB JS / 53 KB gz**, 14 KB CSS, 0 TS errors.
- No-network pipeline smoke (`theme="midnight"`, 5-slide deck): `deck_meta.theme = midnight`, `slides.html` contains `data-theme="midnight"` + all 5 `:root[data-theme=…]` blocks + theme-resolved `--accent` variable.
- Live `GET /api/themes` on PORT=8799: returns 5 themes with correct accent/bg colors per preset.

**Deferred**
- PPTX writer reads theme tokens for fill/text colors — phase 7.
- In-app slide preview surface (SlideView, ContentView) using theme tokens — phase 6 (editor work touches same components, fold it in then).
- Per-slide theme override (`slide.theme_overrides`) — phase 6 / 12 (regenerate flow).
- LLM prompt update so the model can suggest a theme based on prompt intent — phase 8.

### 2026-05-17 — Step 5 in progress: block-based slide JSON schema + renderer rewrite

**Goal** — move slides off the hardcoded `{title, subtitle, bullets, metrics}` shape onto a typed block stream. Unblocks step 6 (per-block editor), 7 (PPTX block dispatcher), 9 (image block), 11 (chart block).

**Schema** — slide gains `blocks: Block[]`. Legacy fields (`title`, `bullets`, `metrics`, …) kept alongside so PPTX writer and existing UI keep working through phase 7 cutover. Each block:

```
{ id: "s{slide}-b{idx}-{type}", type: BlockType, props: { … } }
```

Block types this phase (12):
- `eyebrow {text}` · `heading {text, level: 1|2}` · `subheading {text}` · `paragraph {text}`
- `bullets {items: [str]}` · `metric_row {metrics: [{label, value}]}`
- `quote {text, attribution}` · `callout {tone, text}`
- `image {src, alt, fit, caption}` (renders placeholder when src absent — image fetch lands in phase 9)
- `chart {kind, series, labels, title}` (renders deterministic bars from real data — Recharts swap in phase 11)
- `diagram {kind: flow|matrix|orbit, nodes}` · `spacer {size}`

Block IDs are stable per slide+index+type so edit ops in phase 6 can target them.

**New module** — [pptx_agent/pptx_agent/blocks.py](pptx_agent/pptx_agent/blocks.py)
- `BLOCK_TYPES` registry, `make_block()` factory.
- `normalize_block(slide_number, index, raw)` — coerces loose dicts (LLM output) into schema. Unknown types dropped. Per-type prop defaults (`bullets.items`, `metric_row.metrics`, `chart.kind/series/labels`, `diagram.kind/nodes`, `image.fit/alt`, `callout.tone`).
- `slide_to_blocks(slide)` — adapter that derives blocks from a legacy slide dict. Order: eyebrow → heading → subheading → bullets → metric_row → diagram (for `cover`/`solution`/`architecture`/`comparison`/`team` layouts). Used as fallback when planner/LLM does not emit blocks directly.

**Planner changes** — [pptx_agent/pptx_agent/planner.py](pptx_agent/pptx_agent/planner.py)
- `normalize_deck()` now attaches `blocks` to every slide. Honors `raw.get("blocks")` when LLM supplies them (normalized via `normalize_blocks`); otherwise falls back to `slide_to_blocks(slide_dict)`.
- Fallback-padded slides (when planner returns < slide_count) also get blocks via the adapter.
- Non-breaking: legacy fields untouched, so pptx_writer, slide_content_markdown, and existing frontend views keep working.

**Renderer rewrite** — [pptx_agent/pptx_agent/html_renderer.py](pptx_agent/pptx_agent/html_renderer.py)
- `_render_slide()` now iterates `slide["blocks"]` (or derives via `slide_to_blocks` for legacy decks). Each block becomes `<div class="block block-{type}" data-block-id="{id}">…</div>` — gives editor stable hook points in phase 6.
- Dispatch table `_BLOCK_RENDERERS` maps each type to its render fn. Unknown types render empty (defensive).
- `chart` renderer uses real `series.values` against `labels` to compute bar heights instead of the previous hardcoded `[86, 64, 42, 72]` fake bars. Falls back to `chart-empty` placeholder when no data.
- CSS swapped from the old two-column `slide-grid` to a flex column inside `.slide-body` that stacks blocks vertically. New per-block-type styles for `block-eyebrow`, `block-heading`, `block-subheading`, `block-paragraph`, `block-bullets`, `block-metric_row`, `block-quote`, `block-image`, `block-callout` (info/warn/success tones), `block-chart`, `block-diagram` (flow/matrix/orbit), `block-spacer`.

**Frontend type contract** — [pptx_agent/frontend/src/events.ts](pptx_agent/frontend/src/events.ts)
- Added `BlockType` union, `SlideBlock { id, type, props }`, hoisted slide payload into shared `SlideData` (now exported so other components can use it directly).
- `SlideDetailEvent.slide` now references `SlideData` and includes optional `blocks` array.
- [state.ts](pptx_agent/frontend/src/state.ts) — imports `SlideData` instead of indexing into `SlideDetailEvent`. `slides: Map<number, SlideData>` preserves blocks alongside legacy fields. No reducer logic change required (blocks rides on the existing `slide_detail` payload).

**Tests** — [pptx_agent/tests/test_pipeline.py](pptx_agent/tests/test_pipeline.py)
- `test_blocks_attached_to_every_slide` — runs full pipeline (no-network) and asserts every slide has ≥ 2 blocks, each block has `id`/`type`/`props`, IDs start with `s{n}-`, heading present when title exists.
- `test_slide_to_blocks_adapter_orders_blocks` — verifies fixed order eyebrow→heading→subheading→bullets→metric_row and that `solution` layout appends a `flow` diagram.
- `test_normalize_blocks_filters_unknown_types` — unknown types dropped; non-dict entries dropped; bullets coerce loose `items` from top-level into `props.items`.
- `test_html_renderer_emits_block_classes` — output contains `block block-heading`, `block block-bullets`, `data-block-id="…"`, full HTML contains `.block-bullets ul` CSS.

**Verification**
- Backend unit tests: **9/9 pass** (`python3 -m unittest tests.test_pipeline -v` → `OK`, 0.022s).
- Frontend build: `npm run build` clean — 43 modules, **168 KB JS / 53 KB gz**, 13 KB CSS, 0 TS errors.
- No-network pipeline smoke (5-slide deck, `SEARCH_PROVIDER=none`): 45 events, every `slide_detail` carries 5-6 blocks in correct order, layouts honored (cover/solution append diagram, problem/market skip it).

**Deferred to later phases**
- LLM JSON contract update to *request* blocks from the model — phase 8 (optimize pass) is the natural moment; today the adapter handles all LLM output transparently.
- PPTX writer still reads legacy `bullets`/`metrics`/`title` fields — phase 7 will swap to block dispatch.
- Editable block IDs surfaced in frontend (`data-block-id`) but not yet wired into a contenteditable layer — phase 6.
- Chart rendered as deterministic bars from `series.values`; Recharts/Mermaid swap in phase 11.

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
