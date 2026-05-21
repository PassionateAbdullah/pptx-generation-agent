"""LLM-driven per-slide content authoring.

Pipeline (new, replaces hardcoded role fallbacks):

  1. ``build_outline_llm(prompt, topic, slide_count, research, llm)`` → one
     LLM call that returns a deck-level outline: title/subtitle/audience +
     a list of slide skeletons (role, layout, eyebrow, working title,
     focus_keywords, assigned_source_ids, needs_* flags). No blocks yet.

  2. ``author_slide(outline_entry, research, deck_meta, llm)`` → one LLM
     call per slide that returns the slide's typed blocks + final title,
     subtitle, speaker_notes, citations. Authored against the slide's
     assigned source excerpts only (so the LLM sees focused context).

  3. ``author_slides_parallel(...)`` → fan-out helper that runs author_slide
     for every slide in parallel via a ThreadPoolExecutor (LLM client uses
     blocking urllib so threads buy real concurrency on I/O).

Each step loads its prompt template from ``pptx_agent.prompts`` so the
prompt text lives outside Python and can be iterated without code changes.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterator

from .blocks import normalize_blocks
from .citations import cite_slide
from .claim_miner import mine_claims_from_text
from .llm import LLMClient
from .prompts import load as load_prompt

log = logging.getLogger("pptx_agent.slide_author")


# ---------------------------------------------------------------------------
# Outline pass
# ---------------------------------------------------------------------------


def build_outline_llm(
    prompt: str,
    topic: str,
    slide_count: int,
    research: dict[str, Any],
    llm: LLMClient,
) -> dict[str, Any]:
    """Single LLM call producing a deck outline. Raises on empty / invalid."""
    system = load_prompt("outline")
    user = json.dumps(
        {
            "task": prompt,
            "topic": topic,
            "slide_count": slide_count,
            "research": _compact_research(research, excerpt_chars=600),
        },
        ensure_ascii=False,
    )
    raw = llm.complete_json(
        system, user.replace("{slide_count}", str(slide_count)), max_tokens=1600
    )
    if not raw:
        raise RuntimeError("LLM outline returned empty result")
    slides = raw.get("slides") or []
    if not isinstance(slides, list) or len(slides) == 0:
        raise RuntimeError("LLM outline missing slides[]")
    return raw


# ---------------------------------------------------------------------------
# Per-slide authoring
# ---------------------------------------------------------------------------


def author_slide(
    outline_entry: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
) -> dict[str, Any]:
    """Single LLM call producing one slide's blocks + final content.

    Returns a slide dict ready to slot into deck['slides'][i].
    Raises if the LLM returns empty / unparseable JSON.
    """
    number = int(outline_entry.get("number") or 0)
    assigned_ids = outline_entry.get("assigned_source_ids") or []
    role = str(outline_entry.get("role") or outline_entry.get("layout") or "solution")
    layout = str(outline_entry.get("layout") or role)

    assigned_sources = _pick_sources(research, assigned_ids)
    # Mine verbatim claims (sentences carrying concrete numbers/entities) from
    # the assigned excerpts. These get handed to the LLM as pre-vetted
    # "signals" so chart/table values stay anchored to real source text
    # instead of hallucinated round numbers.
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
        raise RuntimeError(f"LLM author returned empty for slide {number}")

    title = str(raw.get("title") or outline_entry.get("title", "")) or f"Slide {number}"
    subtitle = str(raw.get("subtitle") or outline_entry.get("subtitle", ""))
    speaker_notes = str(raw.get("speaker_notes") or "")
    citations = [str(c) for c in (raw.get("citations") or []) if c]
    raw_blocks = raw.get("blocks") or []
    blocks = normalize_blocks(number, raw_blocks)
    if not blocks:
        raise RuntimeError(f"LLM author returned no usable blocks for slide {number}")

    # Grounding pass — drop chart/table/hero_stat/metric values that can't
    # be located in the assigned excerpts. Prevents hallucinated round
    # numbers from polluting the deck.
    before_types = [b.get("type") for b in blocks]
    blocks = _ground_blocks(blocks, assigned_sources)
    after_types = [b.get("type") for b in blocks]
    dropped = [t for t in before_types if before_types.count(t) > after_types.count(t)]

    # Re-author once if the validator killed any data block — preserves the
    # slide's intended visual. The retry uses a tighter prompt that tells
    # the LLM exactly which blocks it lost and why.
    if dropped and signals:
        retry_user = json.dumps(
            {
                "previous_blocks": raw_blocks,
                "dropped_types": dropped,
                "signals": signals,
                "sources": assigned_sources,
                "slide": {
                    "number": number, "role": role, "layout": layout,
                    "eyebrow": outline_entry.get("eyebrow", ""),
                    "working_title": outline_entry.get("title", ""),
                    "working_subtitle": outline_entry.get("subtitle", ""),
                },
                "instruction": (
                    "Your previous attempt was rejected because these block "
                    "types contained values not present in the source excerpts: "
                    f"{dropped}. Re-author ONLY those blocks, using values "
                    "verbatim from `signals[].text`. Return the same JSON shape; "
                    "keep correctly-grounded blocks unchanged."
                ),
            },
            ensure_ascii=False,
        )
        try:
            retry_raw = llm.complete_json(system, retry_user, max_tokens=1500)
        except Exception as exc:  # noqa: BLE001
            log.warning("slide %s retry failed: %s", number, exc)
            retry_raw = None
        if retry_raw:
            retry_blocks = normalize_blocks(number, retry_raw.get("blocks") or [])
            retry_blocks = _ground_blocks(retry_blocks, assigned_sources)
            if retry_blocks:
                blocks = retry_blocks
                if retry_raw.get("title"):
                    title = str(retry_raw["title"])
                if retry_raw.get("subtitle"):
                    subtitle = str(retry_raw["subtitle"])
                if retry_raw.get("citations"):
                    citations = [str(c) for c in retry_raw["citations"] if c]

    if not blocks:
        raise RuntimeError(f"slide {number}: all blocks dropped during grounding pass")

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
        "citations": citations or cite_slide({"title": title, "subtitle": subtitle, "bullets": [], "blocks": blocks}, research.get("sources") or []),
        "blocks": blocks,
        "accent_variant": (number - 1) % 4,
    }


def author_slides_parallel(
    outline_slides: list[dict[str, Any]],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
    max_workers: int = 6,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Author every outline slide in parallel.

    ``on_event`` is invoked for each completed (or failed) slide with
    ``{type: "slide_authored"|"slide_failed", number, slide?, error?}``.

    Failures don't abort the deck; the failed slide falls back to a minimal
    scaffold so the deck still ships with N slides.
    """
    n = len(outline_slides)
    results: list[dict[str, Any] | None] = [None] * n
    errors: dict[int, str] = {}

    def _do(idx: int, entry: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str | None]:
        try:
            slide = author_slide(entry, research, deck_meta, llm)
            return idx, slide, None
        except Exception as exc:  # noqa: BLE001
            log.warning("slide %s author failed: %s", entry.get("number"), exc)
            return idx, None, str(exc)

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, n))) as pool:
        futures = [pool.submit(_do, i, entry) for i, entry in enumerate(outline_slides)]
        for fut in as_completed(futures):
            idx, slide, err = fut.result()
            entry = outline_slides[idx]
            if slide is None:
                errors[idx] = err or "unknown"
                slide = _scaffold_slide(entry)
            results[idx] = slide
            if on_event:
                on_event(
                    {
                        "type": "slide_authored" if err is None else "slide_failed",
                        "number": slide["number"],
                        "slide": slide,
                        "error": err,
                    }
                )

    return [s for s in results if s is not None]


# ---------------------------------------------------------------------------
# Fallback scaffolds (only when LLM disabled or per-slide call hard-fails)
# ---------------------------------------------------------------------------


def scaffold_outline(
    prompt: str,
    topic: str,
    slide_count: int,
) -> dict[str, Any]:
    """Minimal outline used when LLM is not configured.

    Honest scaffold: titled slides only, no fake bullets. Author flow stops
    here when LLM is disabled — the user gets blank slides that say "Configure
    LLM_API_KEY to author this deck" instead of hardcoded template prose.
    """
    slides: list[dict[str, Any]] = []
    for i in range(1, slide_count + 1):
        if i == 1:
            role, layout = "cover", "cover"
        elif i == slide_count:
            role, layout = "closing", "closing"
        else:
            role, layout = "solution", "solution"
        slides.append(
            {
                "number": i,
                "role": role,
                "layout": layout,
                "eyebrow": role.title(),
                "title": topic if i == 1 else f"Slide {i}",
                "subtitle": "",
                "focus_keywords": [],
                "assigned_source_ids": [],
                "needs_chart": False,
                "needs_table": False,
                "needs_diagram": False,
                "needs_hero_stat": False,
            }
        )
    return {
        "title": topic or prompt[:60] or "Deck",
        "subtitle": "",
        "audience": "Stakeholders",
        "family": "report",
        "slides": slides,
    }


def _scaffold_slide(entry: dict[str, Any]) -> dict[str, Any]:
    n = int(entry.get("number") or 0)
    layout = str(entry.get("layout") or entry.get("role") or "solution")
    title = str(entry.get("title") or f"Slide {n}")
    subtitle = str(entry.get("subtitle") or "")
    eyebrow = str(entry.get("eyebrow") or "")
    blocks = [
        {"id": f"s{n}-b1-eyebrow", "type": "eyebrow", "props": {"text": eyebrow}},
        {"id": f"s{n}-b2-heading", "type": "heading", "props": {"text": title, "level": 1}},
    ]
    if subtitle:
        blocks.append(
            {"id": f"s{n}-b3-subheading", "type": "subheading", "props": {"text": subtitle}}
        )
    blocks.append(
        {
            "id": f"s{n}-b4-callout",
            "type": "callout",
            "props": {
                "tone": "info",
                "text": "Configure LLM_API_KEY to author this slide from research.",
            },
        }
    )
    return {
        "number": n,
        "id": f"slide-{n}",
        "layout": layout,
        "eyebrow": eyebrow,
        "title": title,
        "subtitle": subtitle,
        "bullets": [],
        "metrics": [],
        "speaker_notes": "",
        "citations": [],
        "blocks": blocks,
        "accent_variant": (n - 1) % 4,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compact_research(research: dict[str, Any], excerpt_chars: int = 600) -> dict[str, Any]:
    sources_out: list[dict[str, Any]] = []
    for src in (research.get("sources") or [])[:14]:
        if not isinstance(src, dict):
            continue
        excerpt = str(src.get("excerpt") or src.get("snippet") or "")[:excerpt_chars]
        sources_out.append(
            {
                "source_id": str(src.get("source_id") or ""),
                "title": str(src.get("title") or "")[:140],
                "url": str(src.get("url") or ""),
                "excerpt": excerpt,
            }
        )
    return {
        "sources": sources_out,
        "insights": list(research.get("insights") or [])[:8],
    }


def _pick_sources(research: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    """Return assigned sources with full excerpts. Falls back to top-3 when
    the LLM assigned no ids (rare). Excerpts intentionally NOT truncated
    here — the per-slide call gets the full excerpt for the few sources it
    asked for, so the model can lift real numbers and entities."""
    if not ids:
        ids = [str(s.get("source_id") or "") for s in (research.get("sources") or [])[:3]]
        ids = [i for i in ids if i]
    by_id: dict[str, dict[str, Any]] = {}
    for src in research.get("sources") or []:
        if not isinstance(src, dict):
            continue
        sid = str(src.get("source_id") or "")
        if sid:
            by_id[sid] = src
    out: list[dict[str, Any]] = []
    for sid in ids:
        src = by_id.get(sid)
        if not src:
            continue
        out.append(
            {
                "source_id": sid,
                "title": str(src.get("title") or "")[:200],
                "url": str(src.get("url") or ""),
                "excerpt": str(src.get("excerpt") or src.get("snippet") or "")[:2400],
            }
        )
    return out


def _extract_signals(assigned_sources: list[dict[str, Any]], max_per_source: int = 8) -> list[dict[str, Any]]:
    """Pre-mine concrete claim sentences from each assigned source.

    Each signal is ``{source_id, kind, text}`` with ``text`` lifted verbatim
    from the excerpt — no paraphrasing. The slide LLM uses these as the
    sole grounded statements it can quote when building chart values, table
    rows, hero stats, and bullet citations.
    """
    out: list[dict[str, Any]] = []
    for src in assigned_sources:
        sid = str(src.get("source_id") or "")
        excerpt = str(src.get("excerpt") or "")
        if not sid or not excerpt:
            continue
        claims = mine_claims_from_text(excerpt, source_id=sid)
        for c in claims[:max_per_source]:
            out.append({"source_id": sid, "kind": c.kind, "text": c.text})
    return out


_NUM_TOKEN_RE = re.compile(r"\d[\d,.]*")


def _ground_blocks(
    blocks: list[dict[str, Any]],
    assigned_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop any block whose numeric values don't appear in the assigned excerpts.

    Strict for: chart, table, hero_stat, metric_row. Other block types pass
    through because text-only blocks are validated by citation linting
    elsewhere. A block is dropped (not edited) — partial trust is worse than
    a missing block, and the author re-runs cheap enough to retry.
    """
    excerpt_blob = " ".join(str(s.get("excerpt") or "") for s in assigned_sources)
    excerpt_norm = _normalize_numeric(excerpt_blob)
    if not excerpt_blob:
        return blocks

    out: list[dict[str, Any]] = []
    for b in blocks:
        t = b.get("type")
        props = b.get("props") or {}
        if t == "chart":
            values = []
            for s in props.get("series") or []:
                for v in s.get("values") or []:
                    values.append(v)
            labels = props.get("labels") or []
            if not _values_present(values, excerpt_norm) or not _labels_present(labels, excerpt_blob):
                log.info("dropping chart block — values not found in excerpts")
                continue
        elif t == "hero_stat":
            v = str(props.get("value") or "")
            if not _value_present(v, excerpt_norm, excerpt_blob):
                log.info("dropping hero_stat — value '%s' not in excerpts", v)
                continue
        elif t == "metric_row":
            kept_metrics = []
            for m in props.get("metrics") or []:
                v = str(m.get("value") or "")
                if _value_present(v, excerpt_norm, excerpt_blob):
                    kept_metrics.append(m)
            if not kept_metrics:
                log.info("dropping metric_row — no values found in excerpts")
                continue
            props["metrics"] = kept_metrics
        elif t == "table":
            rows = props.get("rows") or []
            kept_rows = []
            for row in rows:
                if not isinstance(row, (list, tuple)):
                    continue
                # Row passes if at least half its cells appear in excerpts.
                hits = sum(1 for cell in row if _value_present(str(cell), excerpt_norm, excerpt_blob))
                if hits * 2 >= len(row):
                    kept_rows.append(list(row))
            if len(kept_rows) < 2:
                log.info("dropping table — only %d row(s) survived grounding", len(kept_rows))
                continue
            props["rows"] = kept_rows
        out.append(b)
    return out


def _normalize_numeric(text: str) -> str:
    """Lowercase + strip commas/spaces so '7,900' and '7900' both match."""
    return re.sub(r"[\s,]", "", text.lower())


def _value_present(value: str, excerpt_norm: str, excerpt_raw: str) -> bool:
    v = value.strip()
    if not v:
        return True
    # Allow short integer labels like '2024' to match either form.
    if v.lower() in excerpt_raw.lower():
        return True
    return _normalize_numeric(v) in excerpt_norm


def _values_present(values: list[Any], excerpt_norm: str) -> bool:
    if not values:
        return True
    hits = 0
    for v in values:
        token = _normalize_numeric(str(v))
        if token and token in excerpt_norm:
            hits += 1
    # Require ≥60% of chart values to land in the excerpts.
    return hits * 5 >= len(values) * 3


def _labels_present(labels: list[Any], excerpt_raw: str) -> bool:
    if not labels:
        return True
    blob = excerpt_raw.lower()
    hits = sum(1 for l in labels if str(l).strip() and str(l).strip().lower() in blob)
    return hits * 2 >= len(labels)


def _extract_bullets(blocks: list[dict[str, Any]]) -> list[str]:
    for b in blocks:
        if b.get("type") == "bullets":
            items = b.get("props", {}).get("items") or []
            return [str(i) for i in items if i]
    return []


def _extract_metrics(blocks: list[dict[str, Any]]) -> list[dict[str, str]]:
    for b in blocks:
        if b.get("type") == "metric_row":
            return list(b.get("props", {}).get("metrics") or [])
    return []


_AUTHORING_SENTINEL = object()


def iter_authoring_events(
    outline: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
    max_workers: int = 6,
) -> Iterator[dict[str, Any]]:
    """Stream events as slides finish authoring.

    Yields one ``slide_authored`` (or ``slide_failed``) event per slide as
    it completes, then a final ``slides_ready`` event with the assembled
    list in slide-number order.
    """
    outline_slides = outline.get("slides") or []
    if not outline_slides:
        yield {"type": "slides_ready", "slides": []}
        return

    q: queue.Queue[Any] = queue.Queue()
    results: list[dict[str, Any] | None] = [None] * len(outline_slides)

    def worker_done(idx: int, slide: dict[str, Any], err: str | None) -> None:
        results[idx] = slide
        q.put(
            {
                "type": "slide_authored" if err is None else "slide_failed",
                "number": slide["number"],
                "slide": slide,
                "error": err,
            }
        )

    def run_pool() -> None:
        try:
            with ThreadPoolExecutor(
                max_workers=min(max_workers, max(1, len(outline_slides)))
            ) as pool:
                fut_to_idx = {}
                for i, entry in enumerate(outline_slides):
                    fut = pool.submit(_author_or_scaffold, entry, research, deck_meta, llm)
                    fut_to_idx[fut] = i
                for fut in as_completed(fut_to_idx):
                    idx = fut_to_idx[fut]
                    slide, err = fut.result()
                    worker_done(idx, slide, err)
        finally:
            q.put(_AUTHORING_SENTINEL)

    t = threading.Thread(target=run_pool, daemon=True)
    t.start()

    while True:
        item = q.get()
        if item is _AUTHORING_SENTINEL:
            break
        yield item

    slides_sorted = [s for s in results if s is not None]
    slides_sorted.sort(key=lambda s: s.get("number") or 0)
    yield {"type": "slides_ready", "slides": slides_sorted}


def _author_or_scaffold(
    entry: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
) -> tuple[dict[str, Any], str | None]:
    try:
        return author_slide(entry, research, deck_meta, llm), None
    except Exception as exc:  # noqa: BLE001
        log.warning("slide %s author failed: %s", entry.get("number"), exc)
        return _scaffold_slide(entry), str(exc)


def iter_analyst_authoring_events(
    outline: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
    settings: Any,
) -> Iterator[dict[str, Any]]:
    """Sequential analyst pipeline: one slide at a time, with per-slide
    data hunt + validate + repair before moving to the next slide.

    Drops into the same event protocol the parallel path uses
    (``slide_authored``/``slide_failed``/``slides_ready``) so the planner
    only needs to swap the call site.
    """
    # Local import: analyst imports back into slide_author for shared
    # helpers, so resolve it lazily.
    from .analyst import analyst_pass

    outline_slides = outline.get("slides") or []
    if not outline_slides:
        yield {"type": "slides_ready", "slides": []}
        return

    slides_out: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def collect(evt: dict[str, Any]) -> None:
        pending.append(evt)

    for entry in outline_slides:
        try:
            slide = analyst_pass(entry, research, deck_meta, llm, settings, on_event=collect)
        except Exception as exc:  # noqa: BLE001
            log.warning("analyst_pass crashed on slide %s: %s", entry.get("number"), exc)
            slide = _scaffold_slide(entry)
            pending.append({
                "type": "slide_failed",
                "number": int(entry.get("number") or 0),
                "error": str(exc)[:240],
                "slide": slide,
            })
        for evt in pending:
            yield evt
        pending.clear()
        slides_out.append(slide)
        yield {
            "type": "slide_authored",
            "number": int(slide.get("number") or 0),
            "slide": slide,
        }

    yield {"type": "slides_ready", "slides": slides_out}
