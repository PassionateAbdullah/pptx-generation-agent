# Quality Gap Plan (PDF/PPTX/DOCX)

## Scope

This plan focuses on production-quality output parity against real-world business decks/documents:

- `pptx` export fidelity
- `pdf` export quality and determinism
- `docx` narrative quality and layout consistency
- alignment, clipping, and cross-format consistency checks

## What Was Fixed First

1. Non-LLM mode no longer ships scaffold-only slides.
   - Planner now falls back to deterministic research-based deck construction when `LLM_API_KEY` / `LLM_MODEL` are missing or LLM probe fails.
2. Alignment validation is now explicit.
   - Every run writes:
     - `layout_report.json`
     - `layout_report.md`
   - Report checks estimated overflow/clipping risk and HTML/PPTX block-type consistency.

## Test Cases Executed

1. Backend regression suite:
   - `python3 -B -m unittest discover -s tests`
   - Result: `29 tests, OK`
2. No-key runtime smoke:
   - `run_pipeline_and_persist()` with `LLM_API_KEY=""`, `search_provider=none`
   - Verified:
     - deterministic deck generated
     - `layout_report.md` and `layout_report.json` created
     - layout audit summary returned in API result

## Real-World Gap Comparison

### PPTX

Current:
- Strong block coverage (`heading`, `bullets`, `chart`, `table`, `highlight`, `hero_stat`, etc.)
- Theme tokens and accent variants are exported.
- Static layout audit exists.

Gaps vs real-world decks:
- No font metric-based text fitting (only heuristic heights).
- Some blocks can still be truncated by aggressive content growth.
- Limited advanced chart semantics (axes labels, annotations, combo charts).

Proposed solution:
1. Add per-block text-fit solver with font-aware line estimation and fallback truncation.
2. Add overflow auto-remediation pass before PPTX write:
   - shrink heading/subheading
   - convert long paragraphs to bullets
   - split oversized slide into continuation slide
3. Add golden-pptx fixture checks (XML assertions for shape bounds/text runs).

### PDF

Current:
- No first-class PDF pipeline parity artifact yet.

Gaps vs real-world reports/decks:
- No deterministic server-side PDF renderer contract.
- No cross-check that PDF matches the final PPTX/HTML structure.

Proposed solution:
1. Implement PDF export path from the same deck JSON (single source of truth).
2. Add page-level snapshot tests:
   - stable page count
   - no clipped text areas
   - key block presence checks
3. Add `pdf_layout_report.json` with page overflow metrics.

### DOCX

Current:
- Deck markdown/source artifacts exist, but no fully validated DOCX quality contract in this repo path.

Gaps vs real-world documents:
- No style-guide enforcement for long-form narrative outputs.
- No section-level consistency checks (heading hierarchy, table style, figure captions).

Proposed solution:
1. Add structured DOCX authoring pipeline from normalized sections:
   - title, executive summary, findings, evidence, recommendations, appendix
2. Enforce style lint rules:
   - max heading depth
   - paragraph length
   - citation presence where numeric claims appear
3. Add DOCX smoke tests with XML checks for styles and section order.

## Cross-Format Quality Gate (Recommended)

Add a single command:

```bash
python3 -B -m pptx_agent.quality_gate --job <job_id>
```

Gate validates:
1. Content parity:
   - same slide/section count across HTML, PPTX, PDF/DOCX
2. Layout safety:
   - no critical overflow in `layout_report`
3. Citation parity:
   - every numeric claim maps to at least one source id
4. Export integrity:
   - generated files open and contain expected structural parts

## Implementation Priority

1. `P0` (immediate)
   - Font-aware text fitting + overflow auto-remediation for PPTX
   - PDF export baseline + page overflow checks
2. `P1`
   - DOCX structured authoring + style lint
   - Cross-format parity checker command
3. `P2`
   - Visual golden regression (reference snapshots)
   - Advanced chart annotation features

## Acceptance Criteria

1. No-key path produces topic-relevant deterministic content (no LLM setup callout text).
2. `layout_report.summary.status == "pass"` for baseline test prompts.
3. Cross-format parity checks pass on a fixed benchmark prompt set.
4. Snapshot/golden tests catch regressions in alignment or clipping before release.
