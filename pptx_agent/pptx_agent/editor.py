"""Post-generation deck editing.

Pure functions applied to a loaded deck dict to mutate slide content,
followed by re-rendering of artifacts via ``pipeline.write_deck_artifacts``.

The patch shape is intentionally permissive — only the fields a caller
sends are touched. ``blocks`` (if provided) is normalized through
``blocks.normalize_blocks``; legacy fields (``title``, ``bullets``, …)
are coerced through the same rules as ``planner.normalize_deck``.
"""

from __future__ import annotations

from typing import Any

from .blocks import normalize_blocks, slide_to_blocks
from .citations import cite_slide
from .themes import DEFAULT_THEME, get_theme

_SLIDE_SCALAR_FIELDS = ("layout", "eyebrow", "title", "subtitle", "speaker_notes")


def apply_slide_patch(deck: dict[str, Any], slide_number: int, patch: dict[str, Any]) -> dict[str, Any]:
    """Mutate ``deck`` in place by applying ``patch`` to slide ``slide_number``.

    Returns the updated slide dict. Raises ``KeyError`` if the slide is not
    found. ``patch`` is shallow-merged against the existing slide; ``blocks``
    fully replace the existing list when present.
    """
    slides = deck.get("slides") or []
    target: dict[str, Any] | None = None
    for slide in slides:
        if int(slide.get("number") or 0) == slide_number:
            target = slide
            break
    if target is None:
        raise KeyError(f"Slide {slide_number} not found")

    for field in _SLIDE_SCALAR_FIELDS:
        if field in patch:
            target[field] = str(patch[field] or "")

    # Preserve or update accent_variant (phase 12.5 visual rotation).
    if "accent_variant" in patch:
        try:
            target["accent_variant"] = int(patch["accent_variant"]) % 4
        except (TypeError, ValueError):
            pass
    elif "accent_variant" not in target:
        target["accent_variant"] = (slide_number - 1) % 4

    if "bullets" in patch:
        bullets = patch["bullets"] or []
        if isinstance(bullets, str):
            bullets = [bullets]
        target["bullets"] = [str(b) for b in bullets if str(b).strip()][:5]

    if "metrics" in patch:
        metrics = patch["metrics"] or []
        target["metrics"] = [
            {"label": str(m.get("label", "")), "value": str(m.get("value", ""))}
            for m in metrics
            if isinstance(m, dict)
        ][:4]

    if "citations" in patch:
        citations = patch["citations"] or []
        target["citations"] = [str(c) for c in citations if str(c).strip()]

    if "blocks" in patch:
        raw_blocks = patch["blocks"] or []
        target["blocks"] = normalize_blocks(slide_number, raw_blocks)
    elif any(field in patch for field in ("title", "subtitle", "eyebrow", "bullets", "metrics", "layout")):
        # Legacy-field edit: regenerate blocks from updated scalars/lists.
        target["blocks"] = slide_to_blocks(target)

    return target


def apply_deck_patch(deck: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply deck-level patch fields (title/subtitle/theme/audience)."""
    for key in ("title", "subtitle", "audience", "topic"):
        if key in patch:
            deck[key] = str(patch[key] or "")
    if "theme" in patch:
        deck["theme"] = get_theme(patch["theme"]).name
    if "theme" not in deck:
        deck["theme"] = DEFAULT_THEME
    return deck


def recompute_citations(deck: dict[str, Any]) -> None:
    """Re-run heuristic cite_slide for any slide that lost its citations."""
    sources = (deck.get("research") or {}).get("sources") or []
    if not sources:
        return
    for slide in deck.get("slides", []):
        existing = slide.get("citations")
        if isinstance(existing, list) and existing:
            continue
        slide["citations"] = cite_slide(slide, sources)
