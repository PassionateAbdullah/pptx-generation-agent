"""Analyst-mode per-slide pipeline.

For one slide, the analyst pass runs the full agent loop:

  1. Author blocks (LLM call w/ signals)
  2. Ground numeric values against assigned excerpts
  3. If data-required blocks (chart/table/hero_stat) got dropped AND the
     slide flagged ``needs_chart/table/hero_stat`` AND research has room
     to grow, run a targeted search + deep-fetch, then re-author once
     with the fresh signals
  4. Render the slide's standalone HTML
  5. Run audit + visual-inspect on the rendered HTML
  6. If errors remain, call ``repair_slide`` (up to 2 repairs total)
  7. Return the final slide + per-slide quality score + event log

This is the "slide-by-slide content writing, quality content checking,
analyst mode" the user asked for. It's slower than parallel authoring
(serial LLM calls) but each slide ships closer to the topic and the data
contract.

Public surface:

- ``analyst_pass(outline_entry, research, deck_meta, llm, settings,
  on_event) -> dict`` — runs the loop and returns the final slide.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .agent_loop import quality_score, repair_slide
from .blocks import normalize_blocks
from .citations import cite_slide
from .config import Settings
from .deck_audit import audit_deck
from .events import make_event
from .fetch import fetch_url_body
from .html_renderer import render_single_slide_html
from .intake import targeted_queries
from .llm import LLMClient
from .prompts import load as load_prompt
from .slide_author import (
    _extract_bullets,
    _extract_metrics,
    _extract_signals,
    _ground_blocks,
    _pick_sources,
    _previous_slide_context,
)
from .visual_inspect import inspect_slide_html

log = logging.getLogger("pptx_agent.analyst")

# Block types that must appear when the outline flagged the slide as
# needing data. Used to detect when an LLM author result has been gutted
# by the grounding validator and we should hunt for new sources.
_DATA_BLOCK_TYPES = {"chart", "table", "hero_stat", "metric_row"}
_MAX_REPAIRS_PER_SLIDE = 2


# ---------------------------------------------------------------------------
# Public entry: one slide, full analyst loop
# ---------------------------------------------------------------------------


def analyst_pass(
    outline_entry: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
    settings: Settings,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the analyst loop for one slide. Returns the final slide dict."""

    def emit(evt: dict[str, Any]) -> None:
        if on_event:
            try:
                on_event(evt)
            except Exception:  # noqa: BLE001
                pass

    number = int(outline_entry.get("number") or 0)
    layout = str(outline_entry.get("layout") or "solution")
    needs_data = bool(
        outline_entry.get("needs_chart")
        or outline_entry.get("needs_table")
        or outline_entry.get("needs_hero_stat")
    )

    emit(make_event("analyst_slide_start", number=number, layout=layout, needs_data=needs_data))

    # 1. First author attempt.
    try:
        slide = _author_one(outline_entry, research, deck_meta, llm)
    except Exception as exc:  # noqa: BLE001
        log.warning("analyst: first author failed for slide %s: %s", number, exc)
        emit(make_event("analyst_author_failed", number=number, reason=str(exc)[:200]))
        return _scaffold_from_outline(outline_entry)

    # 2. Data-hungry analyst step: if the slide should carry data blocks but
    #    none survived grounding, fetch fresh material and try once more.
    block_types = {str(b.get("type") or "") for b in slide.get("blocks") or []}
    if needs_data and not (_DATA_BLOCK_TYPES & block_types):
        emit(make_event(
            "analyst_data_hunt", number=number,
            reason="needs_data but no chart/table/hero_stat/metric_row in output",
        ))
        added = _data_hunt(outline_entry, research, settings, on_event=on_event)
        if added:
            try:
                slide = _author_one(outline_entry, research, deck_meta, llm)
                emit(make_event("analyst_reauthored", number=number, after="data_hunt"))
            except Exception as exc:  # noqa: BLE001
                emit(make_event("analyst_reauthor_failed", number=number, reason=str(exc)[:200]))

    # 3. Quality check loop: audit + visual inspect on rendered HTML.
    repairs_used = 0
    pending_deck = {
        "title": deck_meta.get("title", ""),
        "theme": deck_meta.get("theme", ""),
        "topic": deck_meta.get("topic", ""),
        "research": research,
        "slides": [slide],
    }
    while repairs_used < _MAX_REPAIRS_PER_SLIDE:
        html = render_single_slide_html(pending_deck, slide)
        visual_findings = [
            {"code": f.code, "severity": f.severity,
             "message": f.message, "suggested_fix": f.suggested_fix}
            for f in inspect_slide_html(html, slide)
        ]
        audit = audit_deck({"title": deck_meta.get("title", ""),
                            "research": research,
                            "slides": [slide]})
        slide_findings = [
            f for f in audit.get("findings", [])
            if f.get("slide") == number and f.get("severity") in {"error", "warn"}
        ]
        score_info = quality_score(audit, {number: visual_findings})
        emit(make_event(
            "analyst_check", number=number, score=score_info["score"],
            audit_codes=[f.get("code") for f in slide_findings][:6],
            visual_codes=[f.get("code") for f in visual_findings][:6],
            repair_pass=repairs_used,
        ))

        if not slide_findings and not any(
            v.get("severity") == "error" for v in visual_findings
        ):
            # Clean enough — ship.
            break

        try:
            repaired = repair_slide(
                slide, slide_findings, visual_findings, research, deck_meta, llm,
            )
        except Exception as exc:  # noqa: BLE001
            emit(make_event("analyst_repair_failed", number=number, reason=str(exc)[:200]))
            break
        if not repaired:
            break
        slide = repaired
        pending_deck["slides"] = [slide]
        repairs_used += 1
        emit(make_event("analyst_repaired", number=number, repairs_used=repairs_used))

    emit(make_event("analyst_slide_done", number=number, repairs_used=repairs_used))
    return slide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _author_one(
    outline_entry: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
) -> dict[str, Any]:
    """Single LLM call → normalize → ground → return slide dict.

    Same shape as ``slide_author.author_slide`` but inlined so the analyst
    loop can run it multiple times against an evolving research dict
    without dragging in the original retry logic.
    """
    number = int(outline_entry.get("number") or 0)
    role = str(outline_entry.get("role") or outline_entry.get("layout") or "solution")
    layout = str(outline_entry.get("layout") or role)
    assigned_ids = outline_entry.get("assigned_source_ids") or []
    assigned_sources = _pick_sources(research, assigned_ids)
    signals = _extract_signals(assigned_sources)

    system = load_prompt("slide")
    user = json.dumps(
        {
            "deck": {
                "task": deck_meta.get("prompt", ""),
                "topic": deck_meta.get("topic", ""),
                "title": deck_meta.get("title", ""),
                "audience": deck_meta.get("audience", ""),
                "family": deck_meta.get("family", ""),
                "previous_slides": _previous_slide_context(deck_meta),
            },
            "slide": {
                "number": number,
                "role": role,
                "layout": layout,
                "eyebrow": outline_entry.get("eyebrow", ""),
                "working_title": outline_entry.get("title", ""),
                "working_subtitle": outline_entry.get("subtitle", ""),
                "focus_keywords": outline_entry.get("focus_keywords", []),
                "needs_chart": bool(outline_entry.get("needs_chart")),
                "needs_table": bool(outline_entry.get("needs_table")),
                "needs_diagram": bool(outline_entry.get("needs_diagram")),
                "needs_hero_stat": bool(outline_entry.get("needs_hero_stat")),
            },
            "sources": assigned_sources,
            "signals": signals,
        },
        ensure_ascii=False,
    )
    raw = llm.complete_json(system, user, max_tokens=1800)
    if not raw:
        raise RuntimeError("LLM author returned empty result")
    raw_blocks = raw.get("blocks") or []
    blocks = normalize_blocks(number, raw_blocks)
    if not blocks:
        raise RuntimeError("LLM author returned no usable blocks")
    grounded = _ground_blocks(blocks, assigned_sources)
    if grounded:
        blocks = grounded

    title = str(raw.get("title") or outline_entry.get("title", "")) or f"Slide {number}"
    subtitle = str(raw.get("subtitle") or outline_entry.get("subtitle", ""))
    speaker_notes = str(raw.get("speaker_notes") or "")
    citations = [str(c) for c in (raw.get("citations") or []) if c]

    return {
        "number": number,
        "id": f"slide-{number}",
        "layout": layout,
        "eyebrow": str(outline_entry.get("eyebrow", "")),
        "title": title,
        "subtitle": subtitle,
        "bullets": _extract_bullets(blocks),
        "metrics": _extract_metrics(blocks),
        "speaker_notes": speaker_notes,
        "citations": citations or cite_slide(
            {"title": title, "subtitle": subtitle, "bullets": [], "blocks": blocks},
            research.get("sources") or [],
        ),
        "blocks": blocks,
        "accent_variant": (number - 1) % 4,
    }


def _data_hunt(
    outline_entry: dict[str, Any],
    research: dict[str, Any],
    settings: Settings,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> int:
    """Run 1-2 targeted searches + deep-fetch for this slide. Mutates
    ``research["sources"]`` in place. Returns count of new sources added."""

    def emit(evt: dict[str, Any]) -> None:
        if on_event:
            try:
                on_event(evt)
            except Exception:  # noqa: BLE001
                pass

    # Local import to dodge import cycles at module load.
    from .research import Researcher

    topic = str(research.get("topic") or outline_entry.get("title") or "")[:80]
    queries = targeted_queries(outline_entry, topic, max_n=2)
    if not queries:
        return 0

    researcher = Researcher(settings)
    provider = researcher._resolve_provider()
    new_sources: list[dict[str, Any]] = []
    existing_urls = {str(s.get("url", "")).lower() for s in research.get("sources") or []}

    with ThreadPoolExecutor(max_workers=min(2, len(queries))) as pool:
        futs = {pool.submit(researcher._search, provider, q): q for q in queries}
        for fut in as_completed(futs):
            q = futs[fut]
            try:
                hits = fut.result() or []
            except Exception as exc:  # noqa: BLE001
                emit(make_event(
                    "targeted_query", slide=outline_entry.get("number"),
                    query=q, hits=0, error=str(exc)[:200],
                ))
                continue
            emit(make_event(
                "targeted_query", slide=outline_entry.get("number"),
                query=q, hits=len(hits),
            ))
            for r in hits[:3]:
                if not r.url or r.url.lower() in existing_urls:
                    continue
                existing_urls.add(r.url.lower())
                new_sources.append({
                    "title": r.title, "url": r.url,
                    "snippet": r.snippet, "excerpt": r.snippet, "query": q,
                })

    if not new_sources:
        return 0

    # Deep-fetch each new source's body so the LLM has real text.
    max_chars = int(getattr(settings, "max_source_chars", 6000) or 6000)
    with ThreadPoolExecutor(max_workers=min(3, len(new_sources))) as pool:
        futs = {pool.submit(fetch_url_body, s["url"], max_chars): s for s in new_sources}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                body, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                body, err = "", f"[deep-fetch crashed: {exc}]"
            if body:
                s["excerpt"] = body

    # Assign fresh source_ids + append.
    start_idx = len(research.get("sources") or []) + 1
    for i, s in enumerate(new_sources, start=start_idx):
        s["source_id"] = f"S{i}"
    research.setdefault("sources", []).extend(new_sources)

    # Auto-assign new sources to this slide so the re-author can pick them up.
    assigned = list(outline_entry.get("assigned_source_ids") or [])
    for s in new_sources:
        assigned.append(s["source_id"])
    outline_entry["assigned_source_ids"] = assigned

    emit(make_event(
        "analyst_data_added", number=outline_entry.get("number"),
        sources=[{"source_id": s["source_id"], "title": s["title"][:80], "url": s["url"]}
                 for s in new_sources],
    ))
    return len(new_sources)


def _scaffold_from_outline(entry: dict[str, Any]) -> dict[str, Any]:
    """Minimal slide when the analyst flow fails outright."""
    n = int(entry.get("number") or 0)
    layout = str(entry.get("layout") or "solution")
    title = str(entry.get("title") or f"Slide {n}")
    return {
        "number": n,
        "id": f"slide-{n}",
        "layout": layout,
        "eyebrow": str(entry.get("eyebrow") or ""),
        "title": title,
        "subtitle": str(entry.get("subtitle") or ""),
        "bullets": [],
        "metrics": [],
        "speaker_notes": "",
        "citations": [],
        "blocks": [
            {"id": f"s{n}-b1-eyebrow", "type": "eyebrow",
             "props": {"text": str(entry.get("eyebrow") or "")}},
            {"id": f"s{n}-b2-heading", "type": "heading",
             "props": {"text": title, "level": 1}},
            {"id": f"s{n}-b3-callout", "type": "callout",
             "props": {"tone": "warn", "text": "Authoring failed for this slide."}},
        ],
        "accent_variant": (n - 1) % 4,
    }


__all__ = ["analyst_pass"]
