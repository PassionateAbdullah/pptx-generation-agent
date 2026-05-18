"""Claim mining from research excerpts.

Pulls **concrete factual claims** out of free-text research so the planner
can use real numbers, named entities, comparisons, currency amounts, and
time-bounded statements as slide bullets — instead of falling back to
generic "use real data when available" hedge text.

A ``Claim`` carries:

- ``text``: the rendered claim sentence (trimmed, hedge-stripped)
- ``kind``: one of ``number``, ``entity``, ``time``, ``head_to_head``,
  ``currency``, ``percent``, ``sentence``
- ``source_id``: the originating ``S{n}`` source identifier (empty if
  derived from an insight, not a source)
- ``score``: 0..1 specificity score — higher = more concrete / specific
- ``keywords``: bag of lowercase keyword tokens for theme clustering

Pure regex + heuristic; no LLM, no third-party deps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


_CURRENCY_RE = re.compile(r"\$\s?\d{1,3}(?:[,\d]{0,12})?(?:\.\d+)?\s*(?:[bmk]|billion|million|trillion|thousand)?", re.IGNORECASE)
_PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%")
_HEAD_TO_HEAD_RE = re.compile(
    r"\b\d{1,3}(?:\.\d+)?\s*%?\s*(?:vs\.?|versus|compared to|against)\s*\d{1,3}(?:\.\d+)?\s*%?",
    re.IGNORECASE,
)
_TIME_BOUND_RE = re.compile(
    r"\b(?:in|by|since|during|after|before|within|over|by the end of)\s+\d{4}\b"
    r"|\bwithin\s+\d+\s+(?:days?|weeks?|months?|years?|quarters?)\b"
    r"|\b\d+\s+(?:months?|years?|quarters?)\s+(?:after|later|ago)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"\b\d{1,3}(?:[,\d]{0,12})?(?:\.\d+)?\s*"
    r"(?:%|billion|million|thousand|trillion|users?|people|customers?|patients?|"
    r"countries|partners?|employees|seats?|deals?|companies|companies?|cities?|"
    r"hospitals?|schools?|clinics?|pilots?|times?|x|per\s+\w+|days?|weeks?|months?|years?)\b",
    re.IGNORECASE,
)
_NAMED_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9&'-]{1,32}(?:\s+(?:of|the|and|for|in|at|on|to|de|del|la|le))?\s+)+"
    r"[A-Z][a-zA-Z0-9&'-]{1,32}\b"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "by", "is", "are", "be", "as", "at", "from", "that", "this", "it",
    "its", "their", "our", "your", "we", "they", "you", "i", "he", "she", "his",
    "her", "them", "than", "then", "into", "out", "over", "under", "more", "most",
    "less", "least", "no", "not", "can", "will", "would", "should", "could", "may",
    "might", "must", "do", "does", "did", "have", "has", "had", "been", "was",
    "were", "use", "used", "using", "make", "made", "also", "via", "per", "vs",
    "across", "about", "any", "all", "some", "such", "each", "many", "much", "new",
    "now", "people", "year", "years", "first", "second", "third",
}


@dataclass
class Claim:
    text: str
    kind: str
    source_id: str = ""
    score: float = 0.5
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def to_bullet(self) -> str:
        suffix = f" [{self.source_id}]" if self.source_id else ""
        return f"{self.text.rstrip('. ')}.{suffix}"


# ---------------------------------------------------------------------------
# Tokenization + keyword extraction
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z][a-z0-9]{2,}")


def _keywords(text: str) -> tuple[str, ...]:
    return tuple(
        tok for tok in _WORD_RE.findall(text.lower()) if tok not in _STOPWORDS
    )


def _clean_sentence(sentence: str) -> str:
    """Trim whitespace, drop leading bullet glyphs, and cap length."""
    s = re.sub(r"\s+", " ", sentence).strip()
    s = re.sub(r"^[-•\*\.•\d\.\)]+\s*", "", s)
    return s[:240]


def _is_too_generic(sentence: str) -> bool:
    """Detect sentences that are meta-instructions or template hedge text."""
    lower = sentence.lower()
    if not lower or len(lower) < 24:
        return True
    bad_phrases = (
        "use real data", "should be", "needs to", "the deck should", "use source",
        "this slide", "should explain", "should describe", "where available",
        "if available", "when available", "to be added", "tbd", "placeholder",
        "should clearly", "needs to clearly",
    )
    return any(p in lower for p in bad_phrases)


# ---------------------------------------------------------------------------
# Public extraction
# ---------------------------------------------------------------------------


def _score_specificity(sentence: str) -> float:
    """Higher = more concrete. Numbers, currency, named entities push score up."""
    score = 0.3
    if _CURRENCY_RE.search(sentence):
        score += 0.25
    if _PERCENT_RE.search(sentence):
        score += 0.2
    if _HEAD_TO_HEAD_RE.search(sentence):
        score += 0.2
    if _TIME_BOUND_RE.search(sentence):
        score += 0.15
    if _NUMBER_RE.search(sentence):
        score += 0.1
    entities = _NAMED_ENTITY_RE.findall(sentence)
    if entities:
        score += min(0.15, 0.05 * len(entities))
    return min(score, 1.0)


def _classify(sentence: str) -> str:
    if _HEAD_TO_HEAD_RE.search(sentence):
        return "head_to_head"
    if _CURRENCY_RE.search(sentence):
        return "currency"
    if _PERCENT_RE.search(sentence):
        return "percent"
    if _TIME_BOUND_RE.search(sentence):
        return "time"
    if _NUMBER_RE.search(sentence):
        return "number"
    if _NAMED_ENTITY_RE.search(sentence):
        return "entity"
    return "sentence"


def mine_claims_from_text(text: str, source_id: str = "") -> list[Claim]:
    """Return claims found in a single block of text."""
    if not text or not isinstance(text, str):
        return []
    claims: list[Claim] = []
    for raw in _SENTENCE_SPLIT.split(text):
        sentence = _clean_sentence(raw)
        if _is_too_generic(sentence):
            continue
        if len(sentence) < 20 or len(sentence) > 240:
            continue
        kind = _classify(sentence)
        if kind == "sentence":
            # Skip plain prose sentences without any concrete signal — they
            # rarely make for great slide bullets.
            continue
        score = _score_specificity(sentence)
        claims.append(
            Claim(
                text=sentence,
                kind=kind,
                source_id=source_id,
                score=score,
                keywords=_keywords(sentence),
            )
        )
    return claims


def mine_claims(research: dict[str, Any]) -> list[Claim]:
    """Mine claims from every research source + insight string in a deck's research dict."""
    out: list[Claim] = []
    for insight in research.get("insights", []) or []:
        if isinstance(insight, str):
            out.extend(mine_claims_from_text(insight, source_id=""))
    for source in research.get("sources", []) or []:
        if not isinstance(source, dict):
            continue
        sid = str(source.get("source_id", ""))
        # Mine from excerpt + snippet only. Source titles ("WHO Bangladesh
        # Country Profile") are document names, not factual claims, and
        # cluttered earlier slide bodies.
        for key in ("excerpt", "snippet"):
            value = source.get(key)
            if not value:
                continue
            out.extend(mine_claims_from_text(str(value), source_id=sid))
    # Deduplicate by text
    seen: set[str] = set()
    deduped: list[Claim] = []
    for c in sorted(out, key=lambda c: c.score, reverse=True):
        key = c.text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


# ---------------------------------------------------------------------------
# Theme keyword scoring
# ---------------------------------------------------------------------------

def claim_matches_theme(claim: Claim, theme_keywords: Iterable[str]) -> int:
    """Count how many theme keywords appear in this claim. Used by the
    dynamic outline builder to route claims to the right slide cluster."""
    if not theme_keywords:
        return 0
    needle = set(k.lower() for k in theme_keywords)
    return sum(1 for k in claim.keywords if k in needle)


def take_top_claims_for_theme(
    claims: list[Claim],
    theme_keywords: Iterable[str],
    max_count: int = 4,
    require_match: bool = False,
    used: set[str] | None = None,
) -> list[Claim]:
    """Return the top-scoring claims that overlap a theme's keyword set.

    ``used`` is a cross-slide tracker (claim_text.lower()) updated in place
    so the outline builder doesn't repeat the same claim on every slide.
    Strategy:
      1. Take claims with theme overlap > 0 first, sorted by score.
      2. If still under ``max_count`` and ``require_match`` is False, take
         unused top-scoring global claims to fill.
    """
    theme_set = set(k.lower() for k in theme_keywords)
    used = used if used is not None else set()
    matched: list[tuple[int, float, Claim]] = []
    for c in claims:
        overlap = sum(1 for k in c.keywords if k in theme_set)
        if overlap > 0:
            matched.append((overlap, c.score, c))
    matched.sort(key=lambda t: (t[0], t[1]), reverse=True)

    out: list[Claim] = []
    out_keys: set[str] = set()
    # Theme-matched claims: claims belong to their thematic slide. Allow even
    # if previously used on another slide — but never include the same claim
    # twice on the same slide (out_keys guard).
    for _, _, claim in matched:
        key = claim.text.lower()
        if key in out_keys:
            continue
        out_keys.add(key)
        used.add(key)
        out.append(claim)
        if len(out) >= max_count:
            return out

    if require_match:
        return out

    # Global fallback: only fill from unused claims. This is where we enforce
    # cross-slide deduplication for non-thematic content.
    for c in sorted(claims, key=lambda c: c.score, reverse=True):
        key = c.text.lower()
        if key in used or key in out_keys:
            continue
        used.add(key)
        out_keys.add(key)
        out.append(c)
        if len(out) >= max_count:
            break
    return out
