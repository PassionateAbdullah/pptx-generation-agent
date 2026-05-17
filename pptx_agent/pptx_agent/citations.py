from __future__ import annotations

import re
from typing import Any

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "by", "is", "are", "be", "as", "at", "from", "that", "this", "it",
    "its", "their", "our", "your", "we", "they", "you", "i", "he", "she",
    "his", "her", "them", "than", "then", "into", "out", "over", "under",
    "more", "most", "less", "least", "no", "not", "can", "will", "would",
    "should", "could", "may", "might", "must", "do", "does", "did", "have",
    "has", "had", "been", "was", "were", "use", "used", "using", "make",
    "made", "also", "via", "per", "vs", "across", "about", "any", "all",
    "some", "such", "each", "many", "much", "new", "now",
}


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", text.lower())
    return {token for token in raw if token not in _STOPWORDS}


def _source_blob(source: dict[str, Any]) -> str:
    parts = [str(source.get("title", "")), str(source.get("snippet", "")), str(source.get("excerpt", ""))]
    return " ".join(parts)


def score_slide_against_sources(slide_text: str, sources: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Return list of (source_id, score) sorted high to low, only sources with overlap > 0."""
    slide_tokens = _tokens(slide_text)
    if not slide_tokens:
        return []
    scored: list[tuple[str, float]] = []
    for source in sources:
        source_id = source.get("source_id")
        if not source_id:
            continue
        source_tokens = _tokens(_source_blob(source))
        if not source_tokens:
            continue
        overlap = slide_tokens & source_tokens
        if not overlap:
            continue
        score = len(overlap) / (len(slide_tokens) ** 0.5 * len(source_tokens) ** 0.5)
        scored.append((source_id, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def cite_slide(slide: dict[str, Any], sources: list[dict[str, Any]], top_n: int = 3, min_score: float = 0.04) -> list[str]:
    """Return up to top_n source IDs that best match this slide's text content."""
    text_parts = [
        str(slide.get("title", "")),
        str(slide.get("subtitle", "")),
        " ".join(str(b) for b in slide.get("bullets", []) or []),
        str(slide.get("speaker_notes", "")),
    ]
    scored = score_slide_against_sources(" ".join(text_parts), sources)
    picked = [sid for sid, score in scored if score >= min_score][:top_n]
    return picked
