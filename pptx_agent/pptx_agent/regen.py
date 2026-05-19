"""Per-slide regeneration with conversational instructions.

Phase 12: lets the user click a single slide and ask the agent to
rewrite it — optionally with a free-text instruction like *"add a chart
showing user growth"* or *"shorten this and make it less corporate"*.

Pipeline:

  1. Parse the instruction into typed **directives** (`shorten`, `add_chart`,
     `more_numbers`, `less_corporate`, `regenerate`, `use_keywords:[...]`,
     `swap_topic:"..."`).
  2. Optionally refresh research for this slide only via a focused SearXNG
     query keyed on the slide title + new keywords. Merges fresh sources
     into the deck's research dict (no global re-research).
  3. Rebuild the slide using ``dynamic_outline.blocks_for_role`` with
     directive-adjusted parameters (claim caps, theme-keyword reroute,
     mandatory chart block, hedge intensity).
  4. Return the new slide dict; caller writes back into the deck and
     re-renders artifacts.

No LLM needed — directives drive the existing deterministic block
composer. If ``LLM_API_KEY`` is set, downstream callers can use this
module's parsed directives to construct a more targeted prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .claim_miner import Claim, mine_claims, take_top_claims_for_theme
from .config import Settings
from .dynamic_outline import (
    ROLE_FALLBACK_BULLETS,
    blocks_for_role,
    build_subtitle,
    claims_to_bullets,
    fallback_bullets_for_role,
    metrics_from_claims,
    title_from_claim,
)
from .hedge_filter import assertive, scrub_bullets
from .research import Researcher, SearchResult
from .topic_families import SlideRole, detect_family, fill_title_template, primary_keyword


@dataclass
class Directives:
    """Parsed conversational directives for a regenerate request."""
    shorten: bool = False
    expand: bool = False
    add_chart: bool = False
    add_image: bool = False
    add_quote: bool = False
    more_numbers: bool = False
    less_corporate: bool = False
    use_keywords: list[str] = field(default_factory=list)
    swap_topic: str = ""
    refresh_research: bool = False
    raw: str = ""


_KEYWORD_HINT_RE = re.compile(r"(?:use|focus on|about|on)\s+([\w][\w\s,&-]{2,80})", re.IGNORECASE)
_SWAP_TOPIC_RE = re.compile(r"make (?:it|this slide) about\s+([\w][\w\s,&-]{2,80})", re.IGNORECASE)


def parse_directives(instruction: str) -> Directives:
    """Best-effort directive extraction from a free-text instruction."""
    text = (instruction or "").lower()
    d = Directives(raw=instruction or "")
    if any(w in text for w in ("shorten", "shorter", "trim", "less", "concise", "tighter")):
        d.shorten = True
    if any(w in text for w in ("expand", "longer", "more detail", "elaborate", "deepen")):
        d.expand = True
    if any(w in text for w in ("add a chart", "add chart", "show chart", "graph", "visualize", "bar chart", "line chart", "pie chart")):
        d.add_chart = True
    if any(w in text for w in ("add an image", "add image", "photo", "picture", "visual")):
        d.add_image = True
    if any(w in text for w in ("add quote", "quote", "testimonial", "voice")):
        d.add_quote = True
    if any(w in text for w in ("more numbers", "more data", "concrete", "specific", "factual", "with stats")):
        d.more_numbers = True
    if any(w in text for w in ("less corporate", "less formal", "casual", "human", "conversational", "plain english", "simpler")):
        d.less_corporate = True
    if any(w in text for w in ("rewrite", "redo", "regenerate", "different", "fresh", "new angle")):
        d.shorten = d.shorten  # marker — regeneration is implicit
    if any(w in text for w in ("refresh research", "new search", "re-search", "research again", "fresh sources", "more sources")):
        d.refresh_research = True
    m = _KEYWORD_HINT_RE.search(instruction or "")
    if m:
        raw = m.group(1)
        d.use_keywords = [w.strip().lower() for w in re.split(r"[,/]| and | or ", raw) if w.strip()]
        d.use_keywords = [w for w in d.use_keywords if len(w) >= 3][:6]
    m = _SWAP_TOPIC_RE.search(instruction or "")
    if m:
        d.swap_topic = m.group(1).strip()
    return d


def regenerate_slide(
    deck: dict[str, Any],
    slide_number: int,
    instruction: str,
    settings: Settings,
    refresh_research: bool = False,
) -> dict[str, Any]:
    """Rebuild one slide with optional instruction-driven adjustments.

    Mutates ``deck`` in place (sets ``deck["slides"][i]`` to the new slide)
    and returns the new slide dict.
    """
    directives = parse_directives(instruction)
    directives.refresh_research = directives.refresh_research or refresh_research

    slides = deck.get("slides") or []
    target_idx = next((i for i, s in enumerate(slides) if int(s.get("number") or 0) == slide_number), None)
    if target_idx is None:
        raise KeyError(f"Slide {slide_number} not found")
    old_slide = slides[target_idx]

    family = detect_family(deck.get("prompt") or deck.get("topic") or "")
    role = _resolve_role(family, old_slide.get("layout") or "", old_slide.get("eyebrow") or "")

    topic_label = directives.swap_topic or deck.get("topic") or ""
    pk = primary_keyword(topic_label, deck.get("prompt") or "")

    # Optionally refresh research for this slide only.
    research = deck.get("research") or {}
    if directives.refresh_research:
        focused_research = _refresh_slide_research(
            old_slide, topic_label, directives, settings, research,
        )
        if focused_research:
            research = _merge_research(research, focused_research)
            deck["research"] = research

    claims = mine_claims(research)
    theme_keywords = list(role.theme_keywords)
    if directives.use_keywords:
        theme_keywords = directives.use_keywords + theme_keywords

    max_claims = role.max_claims
    if directives.shorten:
        max_claims = max(1, max_claims - 2)
    if directives.expand:
        max_claims = min(6, max_claims + 1)

    themed = take_top_claims_for_theme(
        claims,
        theme_keywords,
        max_count=max_claims + 1,
        require_match=bool(directives.more_numbers and theme_keywords),
        used=set(),
    )
    if directives.more_numbers:
        themed = [c for c in themed if c.kind in {"currency", "percent", "head_to_head", "number", "time"}] or themed

    title = (
        title_from_claim(themed[0], role, topic_label, deck.get("prompt") or "")
        if themed
        else fill_title_template(role.title_template, topic_label, deck.get("prompt") or "")
    )
    subtitle = build_subtitle(themed, topic_label, fallback=old_slide.get("subtitle") or "")
    fallbacks = fallback_bullets_for_role(role, topic_label, pk, count=max_claims)
    bullets = claims_to_bullets(
        themed,
        min_n=max(1, role.min_claims),
        max_n=max_claims,
        fallbacks=fallbacks,
    )
    if directives.less_corporate:
        bullets = [_soften(b) for b in bullets]
    metrics = metrics_from_claims(themed)
    citations = sorted({c.source_id for c in themed if c.source_id})

    # Force structural changes per directives.
    forced_role = role
    if directives.add_chart and not role.prefer_chart:
        forced_role = SlideRole(
            role=role.role, layout=role.layout, title_template=role.title_template,
            theme_keywords=role.theme_keywords, eyebrow=role.eyebrow,
            min_claims=role.min_claims, max_claims=role.max_claims,
            prefer_chart=True, required=role.required,
        )
    if directives.add_quote and role.role not in {"closing"}:
        forced_role = SlideRole(
            role="closing", layout=role.layout, title_template=role.title_template,
            theme_keywords=role.theme_keywords, eyebrow=role.eyebrow,
            min_claims=role.min_claims, max_claims=role.max_claims,
            prefer_chart=role.prefer_chart, required=role.required,
        )

    new_slide: dict[str, Any] = {
        "number": slide_number,
        "id": old_slide.get("id") or f"slide-{slide_number}",
        "layout": role.layout,
        "eyebrow": role.eyebrow or role.role.replace("_", " ").title(),
        "title": title,
        "subtitle": subtitle,
        "bullets": bullets,
        "metrics": metrics,
        "speaker_notes": old_slide.get("speaker_notes", ""),
        "citations": citations,
        "regenerated_from": old_slide.get("title", ""),
        "regenerate_instruction": directives.raw,
    }
    new_slide["blocks"] = blocks_for_role(
        forced_role,
        number=slide_number,
        title=title,
        subtitle=subtitle,
        bullets=bullets,
        metrics=metrics,
        research=research,
        citations=citations,
    )
    if directives.add_chart and not any(b.get("type") == "chart" for b in new_slide["blocks"]):
        # Force chart even when chart_block_from_research returns None: build
        # one from claim-derived numeric series (or a placeholder).
        from .dynamic_blocks import chart_block_from_research
        chart = chart_block_from_research(slide_number, research, kind="bar")
        if chart is None:
            # Build a chart from numbers extracted from current bullets/metrics.
            values = []
            labels = []
            for m in metrics[:4]:
                v = m.get("value", "")
                num_match = re.search(r"\d+(?:\.\d+)?", v)
                if num_match:
                    values.append(float(num_match.group()))
                    labels.append(m.get("label", ""))
            if values:
                chart = {
                    "id": f"s{slide_number}-bChart-chart",
                    "type": "chart",
                    "props": {
                        "kind": "bar",
                        "title": "Metrics",
                        "series": [{"label": "Value", "values": values}],
                        "labels": labels,
                    },
                }
        if chart is None:
            chart = {
                "id": f"s{slide_number}-bChart-chart",
                "type": "chart",
                "props": {
                    "kind": "bar",
                    "title": "Chart placeholder — add data",
                    "series": [{"label": "Series A", "values": [1, 2, 3, 4]}],
                    "labels": ["A", "B", "C", "D"],
                },
            }
        new_slide["blocks"].append(chart)
    if directives.add_image:
        # Append image placeholder block if not already present.
        if not any(b.get("type") == "image" for b in new_slide["blocks"]):
            new_slide["blocks"].append({
                "id": f"s{slide_number}-bImg-image",
                "type": "image",
                "props": {"src": "", "alt": title, "fit": "cover", "caption": ""},
            })

    slides[target_idx] = new_slide
    deck["slides"] = slides
    return new_slide


def _resolve_role(family, layout: str, eyebrow: str) -> SlideRole:
    """Match a slide layout/eyebrow back to its family checklist entry.

    Falls back to a generic role if not found so legacy decks still work.
    """
    layout = (layout or "").lower()
    eyebrow_l = (eyebrow or "").lower()
    for role in family.checklist:
        if role.layout == layout and (
            not eyebrow_l or role.eyebrow.lower() == eyebrow_l or role.role == eyebrow_l
        ):
            return role
    for role in family.checklist:
        if role.layout == layout:
            return role
    return SlideRole(
        role="generic",
        layout=layout or "solution",
        title_template="{topic}",
        theme_keywords=[],
        eyebrow=eyebrow or "Slide",
    )


def _refresh_slide_research(
    slide: dict[str, Any],
    topic_label: str,
    directives: Directives,
    settings: Settings,
    existing_research: dict[str, Any],
) -> dict[str, Any]:
    """Issue a focused SearXNG search keyed on the slide's title + theme.

    Returns a research dict shaped like the global one (`sources`,
    `insights`). Empty if search disabled or fails.
    """
    query_parts: list[str] = []
    if directives.swap_topic:
        query_parts.append(directives.swap_topic)
    elif topic_label:
        query_parts.append(topic_label)
    if directives.use_keywords:
        query_parts.append(" ".join(directives.use_keywords))
    elif slide.get("title"):
        query_parts.append(re.sub(r"\[S\d+\]", "", slide["title"]).strip())
    query = " ".join(p for p in query_parts if p).strip()
    if not query:
        return {}

    researcher = Researcher(settings)
    try:
        provider = researcher._resolve_provider()
        if provider == "none":
            return {}
        results: list[SearchResult] = researcher._search(provider, query)[: settings.max_results_per_query]
    except Exception:
        return {}
    if not results:
        return {}

    # Stamp source_id following the next-available index in existing research.
    existing_sources = existing_research.get("sources") or []
    next_idx = len(existing_sources) + 1
    enriched: list[dict[str, Any]] = []
    for i, r in enumerate(results, start=next_idx):
        r.source_id = f"S{i}"
        # Best-effort excerpt fetch for the top 2 to keep the call cheap.
        if i - next_idx < 2:
            try:
                excerpt = researcher._fetch_source_excerpt(r.url) if hasattr(researcher, "_fetch_source_excerpt") else ""
                if excerpt:
                    r.excerpt = excerpt
            except Exception:
                pass
        enriched.append(r.as_dict())
    return {"sources": enriched, "insights": []}


def _merge_research(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Append new sources/insights into base research without dropping fields."""
    out = dict(base)
    out["sources"] = (base.get("sources") or []) + (extra.get("sources") or [])
    out["insights"] = (base.get("insights") or []) + (extra.get("insights") or [])
    return out


def _soften(text: str) -> str:
    """Light tone-softening for `less corporate` directive.

    Drops a small set of corporate buzzwords; leaves data + facts intact.
    """
    if not text:
        return text
    out = text
    for pattern in (
        r"\bleverag(?:e|ing|ed)\b", r"\bsynerg(?:y|ies)\b", r"\bbest-in-class\b",
        r"\bmission-critical\b", r"\bgame[- ]chang(?:er|ing)\b", r"\bvalue[- ]add\b",
        r"\bturn[- ]?key\b", r"\benterprise[- ]grade\b",
    ):
        out = re.sub(pattern, "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out
