"""Hedge filter.

Strips meta-instruction phrases that leaked from earlier template-driven
generation (``"use real data when available"``, ``"the deck should..."``)
out of slide text. Also rewrites mild hedges to assertive voice where
safe (``"may help"`` → drop hedge token).

Pure regex; idempotent.
"""

from __future__ import annotations

import re


# Entire sentence is dropped if any of these phrases appear.
_DROP_SENTENCE_PHRASES = (
    "use real data",
    "use source-backed",
    "use source-aware",
    "the deck should",
    "this slide should",
    "needs to be added",
    "to be added",
    "tbd",
    "placeholder",
    "use concrete",
    "where available",
    "if available",
    "when available",
    "use updated source",
    "before presenting externally",
    "should be informed",
    "should clearly",
    "should describe",
    "should explain",
    "should connect",
    "use research to",
    "use real company",
    "feel free to",
    "stop summarizing",
    "do not include",
)

# Specific phrases scrubbed in place (kept sentence, dropped phrase).
# Each pattern is conservative: avoid touching nouns like "may" the month or
# "just" in "just-in-time". We anchor on a following verb so legitimate noun
# usage doesn't get mangled (previous version of this list rewrote "may
# delivery" → "s delivery" because `\bmay\s+(\w+)\b` matched any noun).
_SCRUB_INPLACE = [
    (re.compile(r"\bcould\s+be\s+([a-z]+ed)\b", re.IGNORECASE), r"is \1"),
    # Rewrite "may/might/could" only when followed by one of a small set of
    # common hedge verbs we know are verbs (not nouns). "May delivery" stays
    # intact because "delivery" isn't on this list.
    (
        re.compile(r"\b(?:may|might|could)\s+(help|enable|allow|improve|reduce|increase|grow|drive|support|provide|deliver|address|solve|create|build|expand|accelerate|unlock|generate|bring|offer)\b", re.IGNORECASE),
        r"\1s",
    ),
    (re.compile(r"\b(?:we|our team|the team)\s+should\b", re.IGNORECASE), "we"),
    (re.compile(r"\bin our view\b", re.IGNORECASE), ""),
    (re.compile(r"\bone could argue\b", re.IGNORECASE), ""),
    (re.compile(r"\bnot necessarily\b", re.IGNORECASE), ""),
    (re.compile(r"\bbroadly speaking\b", re.IGNORECASE), ""),
    (re.compile(r"\bappears?\s+to\s+be\b", re.IGNORECASE), "is"),
    (re.compile(r"\bseems?\s+to\s+be\b", re.IGNORECASE), "is"),
    (re.compile(r"\bsomewhat\b", re.IGNORECASE), ""),
    (re.compile(r"\bpotentially\b", re.IGNORECASE), ""),
    (re.compile(r"\bbasically\b", re.IGNORECASE), ""),
    # Drop "actually/really/just" only when followed by a verb-ish form,
    # so phrases like "just-in-time" or "the real estate" survive.
    (re.compile(r"\b(?:actually|really)\s+(?=[a-z]+(?:ed|ing|s)\b)", re.IGNORECASE), ""),
    (re.compile(r"\s{2,}"), " "),
]


def drop_meta_sentences(text: str) -> str:
    """Drop entire sentences containing meta-instruction phrases.

    Used on body paragraphs where a sentence might be hedge-only; bullets
    use ``is_meta_bullet`` instead so the whole bullet is filtered upstream.
    """
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    keep: list[str] = []
    for sentence in sentences:
        lower = sentence.lower()
        if any(p in lower for p in _DROP_SENTENCE_PHRASES):
            continue
        keep.append(sentence)
    return " ".join(keep).strip()


def is_meta_bullet(text: str) -> bool:
    """True if the bullet is meta-instruction noise that shouldn't ship."""
    if not text:
        return True
    lower = text.lower()
    return any(p in lower for p in _DROP_SENTENCE_PHRASES)


def assertive(text: str) -> str:
    """Replace hedge tokens with stronger forms; collapse whitespace; strip
    trailing punctuation duplicates. Idempotent."""
    if not text:
        return ""
    out = text
    for pattern, replacement in _SCRUB_INPLACE:
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = out.strip()
    # Capitalize first letter if lost during scrubbing.
    if out and out[0].islower():
        out = out[0].upper() + out[1:]
    return out


def scrub_bullets(bullets: list[str]) -> list[str]:
    """Filter and tighten a list of bullets."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in bullets or []:
        if not isinstance(raw, str):
            continue
        if is_meta_bullet(raw):
            continue
        tight = assertive(raw)
        if not tight or len(tight) < 8:
            continue
        key = tight.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tight)
    return out


def scrub_paragraph(text: str) -> str:
    """Drop meta sentences and assertify the survivor."""
    cleaned = drop_meta_sentences(text)
    return assertive(cleaned)
