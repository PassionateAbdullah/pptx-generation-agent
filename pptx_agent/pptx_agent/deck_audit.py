"""Deck audit — quality gates that run AFTER the LLM finishes authoring.

The author prompt (``prompts/slide.md``) tells the LLM what the rules are.
This module verifies the LLM actually followed them. Findings are surfaced
as a JSON artifact and a warnings panel in the rendered HTML so the user
sees what the model got wrong without grep'ing logs.

Three severity levels:

- ``error``   contract violation a downstream consumer probably can't fix
              (e.g. chart with no data points, hero_stat with no number).
- ``warn``    rule break worth flagging but not blocking
              (e.g. cover with citations, missing visual block).
- ``info``    measurement / metric that's informational only.

Each finding is:

    {
      "slide": int | None,  # None for deck-level findings
      "severity": "error" | "warn" | "info",
      "code": "stable-string",
      "message": "human-readable explanation",
    }
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER_RE = re.compile(r"\d")
_CITATION_RE = re.compile(r"\[S\d+\]")
# Junk-title detector. A slide title that opens with a nav verb or contains
# site-chrome tokens is almost certainly leaked boilerplate, not authored
# copy. Flag it so the repair loop re-authors.
_JUNK_TITLE_PREFIX_RE = re.compile(
    r"^\s*(?:download|sign\s*in|log\s*in|subscribe|toggle|read\s+more|"
    r"upload|click|accept|share|home\s*\||main\s+menu|search)\b",
    re.IGNORECASE,
)
_JUNK_TITLE_TOKENS_RE = re.compile(
    r"\b(?:toggle\s+navigation|0\s+ratings?|0%\s+found|free\s+for\s+30\s+days|"
    r"full\s+description|uploaded\s+by|sign\s*in\s+upload|cookie\s+policy|"
    r"toggle\s+navigation\s+english|read\s+more\s+download)\b",
    re.IGNORECASE,
)


# Layout → required-visual contract. Mirrors prompts/slide.md.
_VISUAL_BY_LAYOUT: dict[str, set[str]] = {
    "market": {"chart", "hero_stat"},
    "metrics": {"chart", "hero_stat"},
    "traction": {"chart", "hero_stat"},
    "results": {"chart", "hero_stat"},
    "comparison": {"table", "diagram"},
    "competition": {"table", "diagram"},
    "segments": {"table", "diagram"},
    "solution": {"diagram"},
    "architecture": {"diagram"},
    "roadmap": {"diagram", "flow"},
    "problem": {"callout", "highlight"},
    "risks": {"callout", "highlight"},
}

# "Visual" blocks for the "every slide should have one" density rule.
_VISUAL_BLOCKS = {
    "chart", "table", "diagram", "hero_stat", "metric_row",
    "highlight", "callout", "quote", "image",
}


_audit_deck_topic_cache: dict[int, str] = {}


def audit_deck(deck: dict[str, Any]) -> dict[str, Any]:
    """Return ``{findings: [...], stats: {...}}`` for a finished deck."""
    findings: list[dict[str, Any]] = []
    slides = deck.get("slides") or []
    sources_by_id = {
        str(s.get("source_id") or ""): s
        for s in (deck.get("research") or {}).get("sources") or []
        if isinstance(s, dict)
    }

    # Stash the deck topic keyed by each slide's id() so _audit_slide can
    # read it without a signature change (used by topic-alignment check).
    deck_topic = str(deck.get("topic") or "")
    _audit_deck_topic_cache.clear()
    for slide in slides:
        _audit_deck_topic_cache[id(slide)] = deck_topic

    for slide in slides:
        findings.extend(_audit_slide(slide, sources_by_id))

    findings.extend(_audit_deck_level(deck, slides))

    stats = _stats(slides, findings)
    return {"findings": findings, "stats": stats}


def render_audit_html(audit: dict[str, Any]) -> str:
    """Render audit findings as an HTML fragment for embedding in slides.html."""
    findings = audit.get("findings") or []
    if not findings:
        return ""
    by_severity: dict[str, list[dict[str, Any]]] = {"error": [], "warn": [], "info": []}
    for f in findings:
        sev = str(f.get("severity") or "info")
        by_severity.setdefault(sev, []).append(f)

    rows: list[str] = []
    for sev in ("error", "warn", "info"):
        for f in by_severity.get(sev, []):
            slide = f.get("slide")
            slide_label = f"Slide {slide}" if slide else "Deck"
            rows.append(
                f'<tr class="audit-{sev}">'
                f'<td class="audit-slide">{slide_label}</td>'
                f'<td class="audit-sev audit-sev-{sev}">{sev.upper()}</td>'
                f'<td class="audit-code"><code>{f.get("code", "")}</code></td>'
                f'<td class="audit-msg">{_escape(str(f.get("message", "")))}</td>'
                f'</tr>'
            )
    body = "\n".join(rows) or '<tr><td colspan="4">No issues found.</td></tr>'
    counts = audit.get("stats", {}).get("by_severity", {})
    return f"""
<section class="audit-panel" aria-label="Deck audit findings">
  <header class="audit-head">
    <h2>Deck audit</h2>
    <p class="audit-summary">
      <span class="audit-pill audit-sev-error">{counts.get("error", 0)} error</span>
      <span class="audit-pill audit-sev-warn">{counts.get("warn", 0)} warn</span>
      <span class="audit-pill audit-sev-info">{counts.get("info", 0)} info</span>
    </p>
  </header>
  <table class="audit-table">
    <thead><tr><th>Where</th><th>Severity</th><th>Code</th><th>Issue</th></tr></thead>
    <tbody>
      {body}
    </tbody>
  </table>
</section>
""".strip()


def audit_panel_css() -> str:
    return """
.audit-panel { margin: 28px auto; padding: 18px 20px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: 0 12px 28px var(--shadow); max-width: 1100px; }
.audit-head { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; margin-bottom: 12px; }
.audit-head h2 { margin: 0; font-size: 20px; }
.audit-summary { margin: 0; display: flex; gap: 8px; }
.audit-pill { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; }
.audit-sev-error { background: rgba(201, 87, 70, 0.15); color: #a02e2e; }
.audit-sev-warn { background: rgba(217, 143, 31, 0.18); color: #8a5a0d; }
.audit-sev-info { background: rgba(58, 160, 255, 0.15); color: #1f5d96; }
.audit-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.audit-table th { text-align: left; padding: 8px 10px; background: var(--panel-alt); color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; }
.audit-table td { padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
.audit-slide { white-space: nowrap; color: var(--muted); font-weight: 600; }
.audit-sev { white-space: nowrap; font-weight: 800; font-size: 11px; text-transform: uppercase; }
.audit-code code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; background: var(--panel-alt); padding: 1px 6px; border-radius: 4px; }
.audit-msg { color: var(--ink); }
""".strip()


# ---------------------------------------------------------------------------
# Slide-level checks
# ---------------------------------------------------------------------------


def _audit_slide(
    slide: dict[str, Any], sources_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    number = int(slide.get("number") or 0)
    layout = str(slide.get("layout") or "").lower()
    role = str(slide.get("role") or layout).lower()
    blocks = slide.get("blocks") or []
    citations = slide.get("citations") or []
    bullets = slide.get("bullets") or []

    block_types = [str(b.get("type") or "") for b in blocks]
    types_set = set(block_types)

    # --- Bullets+paragraph tail (the LLM's safety-net wall-of-text closer) ---
    if len(block_types) >= 2 and block_types[-2:] == ["bullets", "paragraph"]:
        findings.append(_f(
            number, "warn", "bullets-paragraph-tail",
            "slide closes with bullets+paragraph — pick one closer (drop the paragraph "
            "or replace it with a callout/highlight)",
        ))
    if block_types.count("paragraph") + block_types.count("bullets") >= 3:
        findings.append(_f(
            number, "warn", "too-much-prose",
            "slide has 3+ text-only blocks; swap at least one for a visual block",
        ))

    # --- Default subheading abuse ---
    # If the slide carries a subheading whose text barely adds anything beyond
    # the heading, flag it so the LLM drops the redundant block on repair.
    if "subheading" in block_types:
        head_text = ""
        sub_text = ""
        for b in blocks:
            t = b.get("type")
            if t == "heading":
                head_text = str((b.get("props") or {}).get("text") or "")
            elif t == "subheading":
                sub_text = str((b.get("props") or {}).get("text") or "")
        if head_text and sub_text:
            from .citations import _tokens
            h = _tokens(head_text)
            s = _tokens(sub_text)
            if s and h and len(s - h) <= 1:
                findings.append(_f(
                    number, "info", "redundant-subheading",
                    "subheading mostly repeats heading tokens; consider removing it",
                ))

    # --- Junk-title detector ---
    title_text = str(slide.get("title") or "").strip()
    if _JUNK_TITLE_PREFIX_RE.search(title_text) or _JUNK_TITLE_TOKENS_RE.search(title_text):
        findings.append(_f(
            number, "error", "title-looks-like-site-chrome",
            f"slide title appears to be scraped nav/upload boilerplate: '{title_text[:80]}'",
        ))

    # --- Topic alignment: token overlap between slide text and deck topic ---
    deck_topic = _audit_deck_topic_cache.get(id(slide), "")
    if deck_topic and layout not in {"cover", "closing", "ask"}:
        slide_blob = " ".join([
            title_text,
            str(slide.get("subtitle") or ""),
            " ".join(str(b) for b in (slide.get("bullets") or [])),
        ])
        score = _topic_overlap(slide_blob, deck_topic)
        if score < 0.10:
            findings.append(_f(
                number, "warn", "off-topic-slide",
                f"slide text shows weak overlap with deck topic (score={score:.2f})",
            ))

    # --- Block-count density rules ---
    if len(blocks) < 3:
        findings.append(_f(number, "warn", "block-count-low",
                           f"slide has only {len(blocks)} block(s); aim for 3-6"))
    if len(blocks) > 7:
        findings.append(_f(number, "warn", "block-count-high",
                           f"slide has {len(blocks)} blocks; trim to 3-6"))

    # --- First two blocks must be eyebrow + heading ---
    if block_types[:2] != ["eyebrow", "heading"]:
        findings.append(_f(number, "warn", "block-order-prefix",
                           f"first two blocks should be eyebrow + heading, got {block_types[:2]}"))

    # --- Layout-block contract ---
    required = _VISUAL_BY_LAYOUT.get(layout) or _VISUAL_BY_LAYOUT.get(role)
    if required and not (required & types_set):
        findings.append(_f(number, "warn", "missing-required-visual",
                           f"layout '{layout}' should include one of {sorted(required)}, got {block_types}"))

    # --- Density: at least one visual block ---
    if not (_VISUAL_BLOCKS & types_set) and layout not in {"cover"}:
        findings.append(_f(number, "warn", "no-visual-block",
                           "slide has no visual block (chart/table/diagram/hero_stat/metric_row/highlight/callout)"))

    # --- Cover rules ---
    if layout == "cover":
        if citations:
            findings.append(_f(number, "warn", "cover-has-citations",
                               f"cover slide should not carry citations: {citations}"))
        allowed_cover = {"eyebrow", "heading", "subheading", "metric_row", "hero_stat"}
        extras = [t for t in block_types if t not in allowed_cover]
        if extras:
            findings.append(_f(number, "warn", "cover-extra-blocks",
                               f"cover slide has unexpected blocks: {extras}"))

    # --- Closing rules ---
    if layout == "closing":
        if "quote" not in types_set and "highlight" not in types_set and "callout" not in types_set:
            findings.append(_f(number, "info", "closing-no-quote",
                               "closing slide is missing a quote/highlight/callout"))

    # --- Block-specific contracts ---
    for b in blocks:
        bt = b.get("type")
        props = b.get("props") or {}

        if bt == "chart":
            labels = props.get("labels") or []
            series = props.get("series") or []
            data_points = sum(len(s.get("values") or []) for s in series if isinstance(s, dict))
            if data_points < 3:
                findings.append(_f(number, "error", "chart-too-few-points",
                                   f"chart has {data_points} data point(s); need ≥3"))
            if not labels:
                findings.append(_f(number, "warn", "chart-missing-labels",
                                   "chart has no x-axis labels"))

        elif bt == "hero_stat":
            value = str(props.get("value") or "").strip()
            if not value:
                findings.append(_f(number, "error", "hero-stat-empty",
                                   "hero_stat has empty value"))
            elif not _NUMBER_RE.search(value):
                findings.append(_f(number, "error", "hero-stat-non-numeric",
                                   f"hero_stat value '{value}' contains no digit"))
            sid = str(props.get("source_id") or "")
            if sid and sid not in sources_by_id:
                findings.append(_f(number, "warn", "hero-stat-bad-source",
                                   f"hero_stat source_id '{sid}' not in research.sources"))

        elif bt == "table":
            headers = props.get("headers") or []
            rows = props.get("rows") or []
            if len(rows) < 3:
                findings.append(_f(number, "warn", "table-too-few-rows",
                                   f"table has {len(rows)} row(s); aim for ≥3"))
            if headers and rows:
                header_w = len(headers)
                for i, r in enumerate(rows):
                    if isinstance(r, (list, tuple)) and len(r) != header_w:
                        findings.append(_f(number, "warn", "table-row-width-mismatch",
                                           f"table row {i+1} has {len(r)} cells, headers has {header_w}"))
                        break

        elif bt == "metric_row":
            metrics = props.get("metrics") or []
            empty = [i for i, m in enumerate(metrics) if not str(m.get("value") or "").strip()]
            if empty:
                findings.append(_f(number, "warn", "metric-row-empty-values",
                                   f"metric_row has {len(empty)} empty value(s)"))

        elif bt == "diagram":
            nodes = props.get("nodes") or []
            if len(nodes) < 2:
                findings.append(_f(number, "warn", "diagram-too-few-nodes",
                                   f"diagram has {len(nodes)} node(s); need ≥2"))

        elif bt == "bullets":
            items = props.get("items") or []
            if layout not in {"cover", "agenda"} and items:
                missing = [i for i, item in enumerate(items) if not _CITATION_RE.search(str(item))]
                # Only flag if >50% of bullets miss citations — single uncited
                # call-to-action bullets are fine.
                if missing and len(missing) * 2 > len(items):
                    findings.append(_f(number, "warn", "bullets-missing-citations",
                                       f"{len(missing)}/{len(items)} bullets lack [S#] citation"))
            long_items = [i for i, item in enumerate(items) if len(str(item).split()) > 20]
            if long_items:
                findings.append(_f(number, "info", "bullets-too-long",
                                   f"{len(long_items)} bullet(s) over 20 words"))

        elif bt == "paragraph":
            text = str(props.get("text") or "")
            word_count = len(text.split())
            if word_count > 70:
                findings.append(_f(number, "warn", "paragraph-too-long",
                                   f"paragraph is {word_count} words; cap at 60"))

    # --- Citation hygiene: every citation must resolve ---
    for cid in citations:
        if str(cid) not in sources_by_id:
            findings.append(_f(number, "error", "citation-unresolved",
                               f"citation '{cid}' not in research.sources"))

    # --- Bullet-citation source-id consistency ---
    bullet_cite_ids = set()
    for item in bullets:
        for m in _CITATION_RE.findall(str(item)):
            bullet_cite_ids.add(m.strip("[]"))
    for cid in bullet_cite_ids:
        if cid not in sources_by_id:
            findings.append(_f(number, "warn", "bullet-cites-unknown-source",
                               f"bullet cites '{cid}' but it is not in research.sources"))

    return findings


# ---------------------------------------------------------------------------
# Deck-level checks
# ---------------------------------------------------------------------------


def _audit_deck_level(deck: dict[str, Any], slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not slides:
        findings.append(_f(None, "error", "no-slides", "deck has zero slides"))
        return findings

    # Cover/closing sandwich.
    if slides[0].get("layout") != "cover":
        findings.append(_f(None, "warn", "missing-cover", "first slide is not a cover"))
    if slides[-1].get("layout") not in {"closing", "ask", "recommendations"}:
        findings.append(_f(None, "info", "missing-closing",
                           "last slide is not closing/ask/recommendations"))

    # Variety: how many distinct block-shape signatures? Threshold tightened
    # — at least 70% of slides must show a distinct block shape, otherwise
    # the deck reads like a template copy-paste.
    shapes = ["-".join(str(b.get("type") or "") for b in (s.get("blocks") or [])) for s in slides]
    unique = len(set(shapes))
    if len(slides) >= 4 and unique * 10 < len(slides) * 7:
        findings.append(_f(
            None, "warn", "low-variety",
            f"only {unique}/{len(slides)} distinct block shapes — slides repeat the same structure",
        ))

    # Consecutive-shape repeat: two adjacent slides with the identical block
    # sequence is the most visible "every slide looks the same" symptom.
    for i in range(1, len(shapes)):
        if shapes[i] and shapes[i] == shapes[i - 1]:
            findings.append(_f(
                int((slides[i].get("number") or 0)),
                "warn", "shape-repeat-with-prev",
                "block-type sequence is identical to the previous slide — vary the closer",
            ))
            break  # one flag is enough; loop quality_score doesn't need a per-slide spam

    # Source coverage: how many sources are actually cited?
    cited: set[str] = set()
    for s in slides:
        for c in s.get("citations") or []:
            cited.add(str(c))
        for item in s.get("bullets") or []:
            for m in _CITATION_RE.findall(str(item)):
                cited.add(m.strip("[]"))
    sources = (deck.get("research") or {}).get("sources") or []
    if sources:
        coverage = len(cited) / max(1, len(sources))
        findings.append(_f(None, "info", "source-coverage",
                           f"{len(cited)} / {len(sources)} sources cited ({coverage:.0%})"))

    return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _topic_overlap(text: str, topic: str) -> float:
    """Lightweight token-Jaccard between slide text and deck topic."""
    from .citations import _tokens
    t = _tokens(text)
    p = _tokens(topic)
    if not t or not p:
        return 1.0  # don't flag empty topic / empty slide
    overlap = t & p
    if not overlap:
        return 0.0
    return len(overlap) / (len(t) ** 0.5 * len(p) ** 0.5)


def _f(slide: int | None, severity: str, code: str, message: str) -> dict[str, Any]:
    return {"slide": slide, "severity": severity, "code": code, "message": message}


def _stats(slides: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        sev = str(f.get("severity") or "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "slides": len(slides),
        "by_severity": by_severity,
        "total_findings": len(findings),
    }


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
