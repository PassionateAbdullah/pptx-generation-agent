"""Smarter intake: source relevance scoring, story arc validation, and
targeted research-query generation.

These three helpers all run "before the slide author" — they tighten the
inputs so downstream authoring doesn't have to compensate for off-topic
sources, missing slide roles, or starved-of-data slides.

Pure stdlib. No new deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .citations import _tokens
from .events import trust_tier
from .topic_families import TopicFamily, family_by_name


# Trust-weight mapping. High-trust domains get up to 1.5× their raw
# overlap score so a reputable but lower-overlap source can beat a tightly
# matched blog. Anything unknown is neutral.
_TRUST_WEIGHT = {
    "gov": 1.5,
    "edu": 1.4,
    "academic": 1.4,
    "reference": 1.25,
    "news": 1.1,
    "unknown": 1.0,
    "social": 0.6,
    "blog": 0.7,
}

_HIGH_TRUST = {"gov", "edu", "academic", "reference"}


# ---------------------------------------------------------------------------
# Source relevance scoring
# ---------------------------------------------------------------------------


def score_source(
    source: dict[str, Any] | Any,
    topic: str,
    prompt: str = "",
) -> tuple[float, str]:
    """Return ``(score, trust)`` for one source.

    Score is token-overlap of ``title + snippet + excerpt`` against
    ``topic + prompt`` (Jaccard-style, normalised). Multiplied by the
    trust weight of the source's URL.
    """
    if hasattr(source, "as_dict"):
        source = source.as_dict()
    if not isinstance(source, dict):
        return 0.0, "unknown"

    url = str(source.get("url") or "")
    trust = trust_tier(url)

    topic_tokens = _tokens(f"{topic} {prompt}")
    src_blob = " ".join(
        str(source.get(k, "")) for k in ("title", "snippet", "excerpt")
    )
    src_tokens = _tokens(src_blob)
    if not topic_tokens or not src_tokens:
        return 0.0, trust

    overlap = topic_tokens & src_tokens
    if not overlap:
        return 0.0, trust
    # Normalise: overlap / sqrt(|topic| * |src|). Same shape as
    # citations.score_slide_against_sources.
    score = len(overlap) / (len(topic_tokens) ** 0.5 * len(src_tokens) ** 0.5)
    weighted = score * _TRUST_WEIGHT.get(trust, 1.0)
    return weighted, trust


def should_keep(score: float, trust: str, min_score: float = 0.05) -> bool:
    """Reject low-overlap sources unless they carry a high-trust domain."""
    if score >= min_score:
        return True
    return trust in _HIGH_TRUST


def filter_sources(
    sources: Iterable[Any], topic: str, prompt: str = "", min_score: float = 0.05
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Split sources into ``(kept, rejected)``.

    ``rejected`` is a list of ``{title, url, reason, score, trust}`` so the
    UI can render *why* a source was dropped. Operates on either the
    ``SearchResult`` dataclass (mutates ``score``/``trust`` attrs if
    present) or raw dicts.
    """
    kept: list[Any] = []
    rejected: list[dict[str, Any]] = []
    for src in sources:
        score, trust = score_source(src, topic, prompt)
        # Attach for later consumers (planner / UI).
        try:
            setattr(src, "score", score)
            setattr(src, "trust", trust)
        except (AttributeError, TypeError):
            if isinstance(src, dict):
                src.setdefault("score", score)
                src.setdefault("trust", trust)
        if should_keep(score, trust, min_score):
            kept.append(src)
        else:
            rejected.append(
                {
                    "title": (getattr(src, "title", None) or src.get("title") if isinstance(src, dict) else "") or "Untitled",
                    "url": (getattr(src, "url", None) or src.get("url") if isinstance(src, dict) else "") or "",
                    "reason": f"low relevance (score={score:.3f}, trust={trust})",
                    "score": round(score, 4),
                    "trust": trust,
                }
            )
    return kept, rejected


# ---------------------------------------------------------------------------
# Story arc validation
# ---------------------------------------------------------------------------


@dataclass
class StoryGap:
    role: str
    severity: str  # "error" | "warn" | "info"
    suggestion: str


def validate_story(
    outline: dict[str, Any] | None,
    family_name: str | None = None,
) -> list[StoryGap]:
    """Check that the outline covers the family's required slide roles.

    Returns a list of ``StoryGap`` — empty list means the arc is healthy.
    Required roles are those marked ``required=True`` on the family's
    checklist (``topic_families.SlideRole``). Optional roles never raise
    a gap.
    """
    if not outline:
        return []
    slides = outline.get("slides") or []
    family = family_by_name(family_name or outline.get("family") or "")
    if not family:
        return []
    present_roles = {str(s.get("role") or s.get("layout") or "").lower() for s in slides}
    gaps: list[StoryGap] = []
    for role in family.checklist:
        if not role.required:
            continue
        if role.role.lower() in present_roles:
            continue
        # Some families allow a role to satisfy via its layout name too.
        if role.layout.lower() in present_roles:
            continue
        gaps.append(
            StoryGap(
                role=role.role,
                severity="warn",
                suggestion=(
                    f"Insert a slide with role='{role.role}' (layout='{role.layout}', "
                    f"eyebrow='{role.eyebrow or role.role.title()}') covering "
                    f"{', '.join(role.theme_keywords) or 'this family checklist item'}."
                ),
            )
        )
    return gaps


def story_gap_repair_prompt(
    outline: dict[str, Any], gaps: list[StoryGap], slide_count: int
) -> str:
    """Build a JSON user prompt asking the LLM to patch in the missing roles."""
    payload = {
        "current_outline": outline,
        "missing_roles": [
            {"role": g.role, "severity": g.severity, "suggestion": g.suggestion}
            for g in gaps
        ],
        "slide_count": slide_count,
        "instruction": (
            "Insert one slide per missing role into `slides[]`, in a position that "
            "fits the deck's narrative. Renumber slides 1..N. Keep the deck length "
            "at slide_count by either replacing an existing weak slide OR (if the "
            "deck is already at slide_count) reassigning role to the weakest slide. "
            "Return the full outline JSON, same schema as the input."
        ),
    }
    import json as _json
    return _json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Targeted research queries
# ---------------------------------------------------------------------------


def targeted_queries(slide_outline: dict[str, Any], topic: str, max_n: int = 2) -> list[str]:
    """Produce 0-N focused queries for one slide.

    Fires only when the outline flagged the slide as data-heavy
    (``needs_chart`` / ``needs_table`` / ``needs_hero_stat``). Returns
    queries that ask for the kind of evidence the slide will need.
    """
    flags = []
    if slide_outline.get("needs_chart"):
        flags.append("statistics trend data 2023 2024")
    if slide_outline.get("needs_table"):
        flags.append("comparison segment breakdown")
    if slide_outline.get("needs_hero_stat"):
        flags.append("key statistic headline figure")
    if not flags:
        return []
    keywords = " ".join(str(k) for k in (slide_outline.get("focus_keywords") or [])[:4])
    title_hint = str(slide_outline.get("title") or "")[:80]
    base = f"{topic} {keywords}".strip()
    out: list[str] = []
    for flag in flags[:max_n]:
        if title_hint and title_hint.lower() not in base.lower():
            out.append(f"{base} {flag} — {title_hint}".strip())
        else:
            out.append(f"{base} {flag}".strip())
    return out[:max_n]


__all__ = [
    "StoryGap",
    "score_source",
    "should_keep",
    "filter_sources",
    "validate_story",
    "story_gap_repair_prompt",
    "targeted_queries",
]
