"""LLM-driven single-slide edit on user feedback.

Public entry: ``iter_edit_slide(deck, slide_number, instruction, research,
settings, llm)`` — a generator of events the SSE layer can stream
directly, mirroring the ``iter_pipeline`` / ``iter_authoring_events``
pattern already used in the project.

Flow:

  1. ``edit_started`` event.
  2. Optional targeted research (when the instruction implies new data).
     New sources appended to ``research["sources"]`` with fresh ``S{N}`` ids.
  3. Single LLM call against ``prompts/edit_slide.md``.
  4. ``_ground_blocks`` (re-uses the same validator the author flow uses)
     drops any chart/table/hero/metric value the LLM invented.
  5. ``apply_slide_patch`` + ``recompute_citations`` mutate the deck.
  6. ``slide_edited`` event with the updated slide dict.
  7. ``edit_finished`` event with a one-line summary.

The caller is responsible for re-rendering ``slide-NN.html`` and writing
``deck.json`` (see ``pipeline.write_deck_artifacts(only_slides=[n])``).
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator

from .blocks import normalize_blocks
from .config import Settings
from .editor import apply_slide_patch, recompute_citations
from .events import make_event
from .intake import targeted_queries
from .llm import LLMClient
from .prompts import load as load_prompt
from .slide_author import _extract_signals, _ground_blocks, _pick_sources

log = logging.getLogger("pptx_agent.slide_edit")

# Regexes that say "the user wants new data" — drives optional research.
_NEW_DATA_RE = re.compile(
    r"\b(add|latest|recent|missing|\d{4}|q[1-4]\s*\d{4}|"
    r"more.{0,12}(data|numbers|stats|statistics)|"
    r"newest|update.{0,12}(stat|number|figure)|"
    r"cite|source|citation)\b",
    re.IGNORECASE,
)


def needs_research(instruction: str) -> bool:
    return bool(_NEW_DATA_RE.search(instruction or ""))


def iter_edit_slide(
    deck: dict[str, Any],
    slide_number: int,
    instruction: str,
    research: dict[str, Any],
    settings: Settings,
    llm: LLMClient,
) -> Iterator[dict[str, Any]]:
    """Stream events as a single slide is edited per user feedback."""
    slides_by_num = {int(s.get("number") or 0): s for s in (deck.get("slides") or [])}
    slide = slides_by_num.get(int(slide_number))
    if slide is None:
        yield make_event(
            "error",
            message=f"slide {slide_number} not found in deck",
        )
        return

    yield make_event(
        "edit_started",
        slide_number=slide_number,
        instruction=instruction[:240],
    )

    # 1. Optional targeted research.
    if needs_research(instruction):
        added = _run_targeted_research(slide, instruction, research, settings)
        for evt in added:
            yield evt

    # 2. Assemble LLM input.
    assigned_ids = slide.get("citations") or []
    if not assigned_ids:
        assigned_ids = [
            s.get("source_id") for s in (research.get("sources") or [])[:4]
            if s.get("source_id")
        ]
    sources = _pick_sources(research, [str(c) for c in assigned_ids])
    signals = _extract_signals(sources)

    system = load_prompt("edit_slide")
    user = json.dumps(
        {
            "deck": {
                "topic": deck.get("topic", ""),
                "title": deck.get("title", ""),
                "audience": deck.get("audience", ""),
                "family": deck.get("family", ""),
            },
            "slide": {
                "number": int(slide.get("number") or slide_number),
                "layout": str(slide.get("layout") or "solution"),
                "eyebrow": slide.get("eyebrow", ""),
                "title": slide.get("title", ""),
                "subtitle": slide.get("subtitle", ""),
                "citations": list(slide.get("citations") or []),
                "blocks": slide.get("blocks") or [],
            },
            "instruction": instruction,
            "sources": sources,
            "signals": signals,
        },
        ensure_ascii=False,
    )

    try:
        raw = llm.complete_json(system, user, max_tokens=1500)
    except Exception as exc:  # noqa: BLE001
        yield make_event(
            "error",
            slide_number=slide_number,
            message=f"LLM edit failed: {str(exc)[:240]}",
        )
        yield make_event("edit_finished", slide_number=slide_number, ok=False)
        return

    if not isinstance(raw, dict):
        yield make_event(
            "error",
            slide_number=slide_number,
            message="LLM edit returned no JSON",
        )
        yield make_event("edit_finished", slide_number=slide_number, ok=False)
        return

    raw_blocks = raw.get("blocks") or []
    blocks = normalize_blocks(int(slide_number), raw_blocks)
    if not blocks:
        yield make_event(
            "error",
            slide_number=slide_number,
            message="LLM edit produced no usable blocks",
        )
        yield make_event("edit_finished", slide_number=slide_number, ok=False)
        return

    grounded = _ground_blocks(blocks, sources)
    if not grounded:
        yield make_event(
            "log",
            slide_number=slide_number,
            text="Grounding pass dropped every block; keeping LLM blocks ungrounded.",
        )
        grounded = blocks

    # 3. Patch the deck via the existing editor surface.
    patch: dict[str, Any] = {"blocks": grounded}
    if raw.get("title"):
        patch["title"] = str(raw["title"])
    if raw.get("subtitle"):
        patch["subtitle"] = str(raw["subtitle"])
    if raw.get("speaker_notes"):
        patch["speaker_notes"] = str(raw["speaker_notes"])
    if raw.get("citations"):
        patch["citations"] = [str(c) for c in raw["citations"] if c]

    try:
        updated = apply_slide_patch(deck, int(slide_number), patch)
        recompute_citations(deck)
    except Exception as exc:  # noqa: BLE001
        yield make_event(
            "error",
            slide_number=slide_number,
            message=f"Patch failed: {str(exc)[:240]}",
        )
        yield make_event("edit_finished", slide_number=slide_number, ok=False)
        return

    yield make_event(
        "slide_edited",
        number=int(slide_number),
        slide=updated,
        instruction=instruction[:240],
    )
    yield make_event(
        "edit_finished",
        slide_number=slide_number,
        ok=True,
        block_count=len(grounded),
    )


# ---------------------------------------------------------------------------
# Targeted research helper
# ---------------------------------------------------------------------------


def _run_targeted_research(
    slide: dict[str, Any],
    instruction: str,
    research: dict[str, Any],
    settings: Settings,
) -> list[dict[str, Any]]:
    """Spawn ≤2 focused queries and append fresh sources to ``research``.

    Returns a list of events the caller should yield. We collect them here
    (rather than yielding mid-helper) because ThreadPoolExecutor results
    arrive out of order.
    """
    # Local import keeps the module-level import graph small.
    from .research import Researcher

    topic = str(research.get("topic") or "") or str(slide.get("title") or "")[:80]

    # Build a synthetic outline-entry so we can reuse intake.targeted_queries.
    synthetic = {
        "title": slide.get("title", ""),
        "focus_keywords": instruction.split()[:6],
        "needs_chart": "chart" in instruction.lower() or "graph" in instruction.lower(),
        "needs_table": "table" in instruction.lower(),
        "needs_hero_stat": "stat" in instruction.lower() or "number" in instruction.lower(),
    }
    # Ensure at least one flag is set so targeted_queries fires.
    if not any((synthetic["needs_chart"], synthetic["needs_table"], synthetic["needs_hero_stat"])):
        synthetic["needs_chart"] = True

    queries = targeted_queries(synthetic, topic)
    if not queries:
        return []

    events: list[dict[str, Any]] = []
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
                events.append(make_event(
                    "log",
                    slide_number=slide.get("number"),
                    text=f"Targeted search failed for '{q}': {exc}",
                ))
                continue
            events.append(make_event(
                "targeted_query",
                slide=slide.get("number"),
                query=q,
                hits=len(hits),
            ))
            for r in hits[:3]:
                if not r.url or r.url.lower() in existing_urls:
                    continue
                existing_urls.add(r.url.lower())
                new_sources.append({
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "excerpt": r.snippet,
                    "query": q,
                })

    if new_sources:
        # Deep-fetch each new source's full body so the LLM edit doesn't
        # have to ground its numbers on a 200-char snippet.
        _deep_fetch_new_sources(new_sources, settings, events, slide.get("number"))
        start_idx = len(research.get("sources") or []) + 1
        for i, s in enumerate(new_sources, start=start_idx):
            s["source_id"] = f"S{i}"
        research.setdefault("sources", []).extend(new_sources)
        events.append(make_event(
            "log",
            slide_number=slide.get("number"),
            text=f"Targeted research added {len(new_sources)} source(s) for the edit.",
        ))

    return events


def _deep_fetch_new_sources(
    new_sources: list[dict[str, Any]],
    settings: Settings,
    events: list[dict[str, Any]],
    slide_number: int | None,
) -> None:
    """Replace the snippet-as-excerpt with full body text via fetch_url.

    Falls back to the original snippet on fetch failure (caller still has
    something to ground on). Appends per-source fetch events for
    transparency. In-place edit of ``new_sources``.
    """
    from .fetch import fetch_url_body

    max_chars = int(getattr(settings, "max_source_chars", 6000) or 6000)
    with ThreadPoolExecutor(max_workers=min(3, len(new_sources))) as pool:
        futs = {
            pool.submit(fetch_url_body, src["url"], max_chars): src
            for src in new_sources
            if src.get("url")
        }
        for fut in as_completed(futs):
            src = futs[fut]
            try:
                body, err = fut.result()
            except Exception as exc:  # noqa: BLE001
                body, err = "", f"[fetch_url worker crash: {exc}]"
            if body:
                src["excerpt"] = body
            elif err:
                # Keep the snippet as fallback excerpt; surface the reason.
                events.append(make_event(
                    "source_fetch_error",
                    slide_number=slide_number,
                    url=src.get("url"),
                    reason=err,
                ))


__all__ = ["iter_edit_slide", "needs_research"]
