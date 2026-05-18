"""Dynamic block composition for slides.

Phase 8 replaces the "every slide is the same template" planner with
varied block compositions per slide. Each slide gets one of several
**recipes** chosen by its layout + position + topic. Recipes mix block
types so the deck visually varies: some slides chart-heavy, some
quote-driven, some metric-smash, some diagram-led.

Also extracts numeric series from research text to auto-populate chart
blocks with real data instead of leaving them empty.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Iterable


# ---------------------------------------------------------------------------
# Numeric extraction → chart blocks
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>%|percent|million|billion|m|bn|k)?",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
_LABEL_LEAD = re.compile(r"\b([A-Z][a-zA-Z]{2,16}(?:\s+[A-Z][a-zA-Z]{2,16}){0,2})\s*(?::|—|-)")


def _to_float(raw: str, unit: str | None) -> float:
    n = float(raw.replace(",", ""))
    if not unit:
        return n
    u = unit.lower()
    if u in {"m", "million"}:
        return n
    if u in {"bn", "billion"}:
        return n * 1000
    if u in {"k"}:
        return n / 1000
    if u in {"%", "percent"}:
        return n
    return n


def extract_numeric_series(texts: Iterable[str], max_points: int = 6) -> list[tuple[str, float]]:
    """Pull (label, value) pairs out of free-text research excerpts.

    Heuristics (best-effort, not exhaustive):
      - Year-prefixed numbers: ``"2023: 4.2 million subscribers"`` → ("2023", 4.2)
      - Percentage statements: ``"Adoption reached 47%"`` → uses preceding
        capitalized label.
      - Falls back to ordinal labels (``Point 1``, ``Point 2``) when no label
        can be teased out.
    """
    pairs: list[tuple[str, float]] = []
    seen_values: set[float] = set()

    for text in texts:
        if not text or not isinstance(text, str):
            continue
        # Strategy 1: year-leading sentences (good for time series).
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            year_match = _YEAR_RE.search(sentence)
            if not year_match:
                continue
            year = year_match.group(1)
            num_match = _NUMBER_RE.search(sentence[year_match.end():])
            if not num_match:
                continue
            value = _to_float(num_match.group("value"), num_match.group("unit"))
            if value in seen_values:
                continue
            pairs.append((year, value))
            seen_values.add(value)
            if len(pairs) >= max_points:
                return pairs

        # Strategy 2: labeled percentages.
        for m in re.finditer(r"([A-Z][\w\s-]{2,40}?)[\s,]+(\d{1,3}(?:\.\d+)?)\s*%", text):
            label = m.group(1).strip(" :—-")
            try:
                value = float(m.group(2))
            except ValueError:
                continue
            if value in seen_values or value > 1000:
                continue
            pairs.append((label[:32], value))
            seen_values.add(value)
            if len(pairs) >= max_points:
                return pairs

    return pairs


def chart_block_from_research(slide_number: int, research: dict[str, Any], kind: str = "bar") -> dict[str, Any] | None:
    """Build a chart block from research data if we can extract ≥3 numeric
    points; otherwise return None so the slide can pick a different recipe."""
    texts: list[str] = []
    for insight in research.get("insights", []) or []:
        if isinstance(insight, str):
            texts.append(insight)
    for source in research.get("sources", []) or []:
        if not isinstance(source, dict):
            continue
        texts.append(str(source.get("excerpt") or ""))
        texts.append(str(source.get("snippet") or ""))

    points = extract_numeric_series(texts, max_points=6)
    if len(points) < 3:
        return None
    labels = [label for label, _ in points]
    values = [value for _, value in points]
    title = "Data points from research"
    if all(re.match(r"^\d{4}$", label) for label in labels):
        title = "Trend over time"
        kind = "line"
    return {
        "id": f"s{slide_number}-bX-chart",
        "type": "chart",
        "props": {
            "kind": kind,
            "title": title,
            "series": [{"label": "Value", "values": values}],
            "labels": labels,
        },
    }


# ---------------------------------------------------------------------------
# Recipe registry — each function returns a list of block dicts
# ---------------------------------------------------------------------------

Recipe = Callable[[int, dict[str, Any], dict[str, Any]], list[dict[str, Any]]]


def _id(slide: int, idx: int, t: str) -> str:
    return f"s{slide}-b{idx}-{t}"


def _bullets_block(slide: int, idx: int, items: list[str]) -> dict[str, Any]:
    return {"id": _id(slide, idx, "bullets"), "type": "bullets", "props": {"items": [i for i in items if i][:5]}}


def _heading(slide: int, idx: int, text: str) -> dict[str, Any]:
    return {"id": _id(slide, idx, "heading"), "type": "heading", "props": {"text": text, "level": 1}}


def _eyebrow(slide: int, idx: int, text: str) -> dict[str, Any]:
    return {"id": _id(slide, idx, "eyebrow"), "type": "eyebrow", "props": {"text": text}}


def _subheading(slide: int, idx: int, text: str) -> dict[str, Any]:
    return {"id": _id(slide, idx, "subheading"), "type": "subheading", "props": {"text": text}}


def _paragraph(slide: int, idx: int, text: str) -> dict[str, Any]:
    return {"id": _id(slide, idx, "paragraph"), "type": "paragraph", "props": {"text": text}}


def _callout(slide: int, idx: int, text: str, tone: str = "info") -> dict[str, Any]:
    return {"id": _id(slide, idx, "callout"), "type": "callout", "props": {"tone": tone, "text": text}}


def _quote(slide: int, idx: int, text: str, attribution: str = "") -> dict[str, Any]:
    return {"id": _id(slide, idx, "quote"), "type": "quote", "props": {"text": text, "attribution": attribution}}


def _metric_row(slide: int, idx: int, metrics: list[dict[str, str]]) -> dict[str, Any]:
    return {"id": _id(slide, idx, "metric_row"), "type": "metric_row", "props": {"metrics": metrics[:4]}}


def _diagram(slide: int, idx: int, kind: str, labels: list[str]) -> dict[str, Any]:
    nodes = [{"label": l} for l in labels if l][:6]
    return {"id": _id(slide, idx, "diagram"), "type": "diagram", "props": {"kind": kind, "nodes": nodes}}


def _image_placeholder(slide: int, idx: int, alt: str) -> dict[str, Any]:
    return {"id": _id(slide, idx, "image"), "type": "image", "props": {"src": "", "alt": alt, "fit": "cover", "caption": ""}}


def _chart(slide: int, idx: int, kind: str, series: list[dict[str, Any]], labels: list[str], title: str = "") -> dict[str, Any]:
    return {
        "id": _id(slide, idx, "chart"),
        "type": "chart",
        "props": {"kind": kind, "series": series, "labels": labels, "title": title},
    }


def _spacer(slide: int, idx: int, size: str = "md") -> dict[str, Any]:
    return {"id": _id(slide, idx, "spacer"), "type": "spacer", "props": {"size": size}}


# Recipe implementations — each is (slide_number, slide_dict, research) → blocks.


def recipe_hero_cover(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Pitch deck"),
        _heading(n, 2, slide["title"]),
        _subheading(n, 3, slide.get("subtitle", "")),
        _metric_row(n, 4, slide.get("metrics") or [{"label": "Deck", "value": f"{n} slides"}]),
    ]


def recipe_stat_smash(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = slide.get("metrics") or [{"label": "Signal", "value": "—"}]
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Numbers"),
        _heading(n, 2, slide["title"]),
        _metric_row(n, 3, metrics),
        _bullets_block(n, 4, slide.get("bullets") or []),
    ]


def recipe_problem_callout(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    bullets = slide.get("bullets") or []
    callout_text = bullets[0] if bullets else slide.get("subtitle", "")
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Problem"),
        _heading(n, 2, slide["title"]),
        _callout(n, 3, callout_text, tone="warn"),
        _bullets_block(n, 4, bullets[1:] if bullets else []),
    ]


def recipe_chart_focus(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    chart = chart_block_from_research(n, research, kind="bar")
    if chart is None:
        # Fall back to stat smash so we never emit an empty chart block.
        return recipe_stat_smash(n, slide, research)
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Evidence"),
        _heading(n, 2, slide["title"]),
        chart,
        _bullets_block(n, 4, slide.get("bullets") or []),
    ]


def recipe_pie_breakdown(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    chart = chart_block_from_research(n, research, kind="bar")
    if chart is None:
        return recipe_chart_focus(n, slide, research)
    chart["props"]["kind"] = "pie"
    chart["props"]["title"] = "Distribution"
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Breakdown"),
        _heading(n, 2, slide["title"]),
        chart,
        _callout(n, 4, (slide.get("bullets") or [slide.get("subtitle", "")])[0], tone="info"),
    ]


def recipe_diagram_flow(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = slide.get("bullets") or ["Research", "Plan", "Build", "Ship"]
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "How it works"),
        _heading(n, 2, slide["title"]),
        _diagram(n, 3, "flow", nodes[:4]),
        _paragraph(n, 4, slide.get("subtitle", "")),
    ]


def recipe_matrix_compare(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = slide.get("bullets") or ["Quality", "Cost", "Speed", "Trust"]
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Comparison"),
        _heading(n, 2, slide["title"]),
        _diagram(n, 3, "matrix", nodes[:6]),
        _subheading(n, 4, slide.get("subtitle", "")),
    ]


def recipe_quote_lede(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    sources = research.get("sources") or []
    quote_text = ""
    attribution = ""
    for s in sources:
        if isinstance(s, dict) and s.get("excerpt"):
            quote_text = str(s["excerpt"])[:200]
            attribution = str(s.get("title") or s.get("source_id") or "research")[:80]
            break
    if not quote_text:
        quote_text = slide.get("subtitle", "") or "Evidence supports the narrative."
        attribution = "research synthesis"
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Voice from research"),
        _heading(n, 2, slide["title"]),
        _quote(n, 3, quote_text, attribution),
        _bullets_block(n, 4, slide.get("bullets") or []),
    ]


def recipe_image_split(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Context"),
        _heading(n, 2, slide["title"]),
        _image_placeholder(n, 3, slide.get("title", "context image")),
        _bullets_block(n, 4, slide.get("bullets") or []),
    ]


def recipe_paragraph_lede(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Why"),
        _heading(n, 2, slide["title"]),
        _paragraph(n, 3, slide.get("subtitle", "")),
        _callout(n, 4, (slide.get("bullets") or [""])[0], tone="info"),
    ]


def recipe_ask(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = slide.get("metrics") or [{"label": "Ask", "value": "—"}]
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "The ask"),
        _heading(n, 2, slide["title"]),
        _metric_row(n, 3, metrics),
        _paragraph(n, 4, slide.get("subtitle", "")),
        _callout(n, 5, (slide.get("bullets") or [""])[0] or "Next step: schedule a follow-up.", tone="success"),
    ]


def recipe_closing(n: int, slide: dict[str, Any], research: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _eyebrow(n, 1, slide.get("eyebrow") or "Close"),
        _heading(n, 2, slide["title"]),
        _quote(n, 3, slide.get("subtitle", ""), ""),
        _bullets_block(n, 4, slide.get("bullets") or []),
    ]


# Recipe selection by layout — first match wins; fallback if list exhausted.
_RECIPES_BY_LAYOUT: dict[str, list[Recipe]] = {
    "cover": [recipe_hero_cover, recipe_paragraph_lede, recipe_image_split],
    "problem": [recipe_problem_callout, recipe_quote_lede, recipe_image_split],
    "solution": [recipe_diagram_flow, recipe_paragraph_lede, recipe_image_split],
    "architecture": [recipe_diagram_flow, recipe_matrix_compare, recipe_chart_focus],
    "market": [recipe_chart_focus, recipe_pie_breakdown, recipe_image_split],
    "metrics": [recipe_stat_smash, recipe_chart_focus, recipe_pie_breakdown],
    "comparison": [recipe_matrix_compare, recipe_chart_focus, recipe_quote_lede],
    "team": [recipe_matrix_compare, recipe_image_split, recipe_paragraph_lede],
    "roadmap": [recipe_diagram_flow, recipe_matrix_compare, recipe_stat_smash],
    "ask": [recipe_ask, recipe_stat_smash, recipe_paragraph_lede],
    "closing": [recipe_closing, recipe_quote_lede, recipe_paragraph_lede],
}


# ---------------------------------------------------------------------------
# Public entry: compose blocks for one slide with deterministic variety
# ---------------------------------------------------------------------------

def compose_slide_blocks(
    slide: dict[str, Any],
    position: int,
    total: int,
    research: dict[str, Any],
    topic_seed: str = "",
) -> list[dict[str, Any]]:
    """Return a varied blocks list for ``slide``.

    Deterministic — same (layout, position, topic_seed) always picks the
    same recipe so re-rendering is stable. Variety achieved by rotating
    through the layout's recipe list using a topic-derived offset.
    """
    layout = str(slide.get("layout") or "solution").lower()
    n = int(slide.get("number") or position + 1)
    recipes = _RECIPES_BY_LAYOUT.get(layout, [recipe_paragraph_lede, recipe_stat_smash])
    seed_digest = hashlib.sha256(f"{topic_seed}|{layout}".encode("utf-8")).digest()
    offset = seed_digest[0]
    chosen = recipes[(position + offset) % len(recipes)]
    blocks = chosen(n, slide, research)
    return [b for b in blocks if b is not None]


def variety_score(decks_blocks: list[list[dict[str, Any]]]) -> float:
    """Return 0..1 — fraction of unique block-type tuples across slides.

    Used by the optimize pass to detect "every slide looks the same"."""
    if not decks_blocks:
        return 0.0
    shapes = ["-".join(b["type"] for b in blocks) for blocks in decks_blocks]
    return len(set(shapes)) / len(shapes)


def optimize_deck_variety(
    deck: dict[str, Any],
    research: dict[str, Any],
    topic_seed: str = "",
    min_variety: float = 0.55,
) -> tuple[bool, float]:
    """Critique pass: if the deck's block-shape variety score is below
    ``min_variety``, rotate slide recipes to increase distinctness.

    Returns ``(changed, score_after)``. Idempotent — calling twice gives the
    same result for the same input.
    """
    slides = deck.get("slides") or []
    if len(slides) < 4:
        return False, 1.0
    block_lists = [s.get("blocks") or [] for s in slides]
    before = variety_score(block_lists)
    if before >= min_variety:
        return False, before

    changed = False
    for idx, slide in enumerate(slides):
        layout = str(slide.get("layout") or "solution").lower()
        recipes = _RECIPES_BY_LAYOUT.get(layout) or []
        if len(recipes) < 2:
            continue
        # Re-pick using idx+1 offset to fight uniformity.
        seed_digest = hashlib.sha256(f"{topic_seed}|{layout}|opt".encode("utf-8")).digest()
        offset = seed_digest[0]
        chosen = recipes[(idx + offset + 1) % len(recipes)]
        new_blocks = chosen(int(slide.get("number") or idx + 1), slide, research)
        if new_blocks and new_blocks != slide.get("blocks"):
            slide["blocks"] = new_blocks
            changed = True

    after = variety_score([s.get("blocks") or [] for s in slides])
    return changed, after
