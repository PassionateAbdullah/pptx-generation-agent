"""slide.md emitter — Manus-style markdown source of truth.

Writes a plain markdown file that mirrors a deck's structure:

    # {Deck Title}: {Subtitle}

    ## Cover
    {title}
    {subtitle}
    Presented by: {audience}

    ## Slide 1
    {slide title}
    {slide subtitle}
    - {bullet 1}
    - {bullet 2}
    - {bullet 3}

The file ships as ``output/<job>/slide.md`` so users can edit it directly
and regenerate downstream artifacts (slides.html, pptx, structure) from
that single source.
"""

from __future__ import annotations

import re
from typing import Any


# Only escape characters that would mis-parse in flow text.
# Brackets/parens deliberately untouched because slide bullets carry
# inline source citations like ``[S1]`` and ``(WHO)`` that should render
# literally, not as link syntax.
_MD_ESCAPE_RE = re.compile(r"([\\`*_#|])")


def _esc(text: Any) -> str:
    """Escape markdown special characters so user titles or bullets carrying
    raw ``*`` / ``[`` / ``#`` don't break the rendered file."""
    if text is None:
        return ""
    return _MD_ESCAPE_RE.sub(r"\\\1", str(text))


def emit_slide_md(deck: dict[str, Any]) -> str:
    title = str(deck.get("title", "Deck"))
    subtitle = str(deck.get("subtitle", ""))
    audience = str(deck.get("audience", ""))
    topic = str(deck.get("topic", ""))
    family = str(deck.get("family", ""))

    lines: list[str] = []
    header = title
    if subtitle and subtitle not in title:
        header = f"{title}: {subtitle}"
    lines.append(f"# {_esc(header)}")
    lines.append("")
    if topic:
        lines.append(f"_Topic:_ {_esc(topic)}")
    if family:
        lines.append(f"_Family:_ {_esc(family)}")
    if audience:
        lines.append(f"_Audience:_ {_esc(audience)}")
    lines.append("")

    for slide in deck.get("slides", []):
        number = slide.get("number")
        layout = slide.get("layout", "")
        eyebrow = slide.get("eyebrow", "")
        heading = "Cover" if number == 1 else f"Slide {number}"
        lines.append(f"## {heading}")
        if eyebrow or layout:
            tag_parts = []
            if eyebrow:
                tag_parts.append(f"eyebrow: {_esc(eyebrow)}")
            if layout:
                tag_parts.append(f"layout: {_esc(layout)}")
            lines.append(f"_({' · '.join(tag_parts)})_")
        if slide.get("title"):
            lines.append(_esc(slide["title"]))
        if slide.get("subtitle"):
            lines.append(_esc(slide["subtitle"]))

        bullets = slide.get("bullets") or []
        if bullets:
            lines.append("")
            for b in bullets:
                lines.append(f"- {_esc(b)}")

        metrics = slide.get("metrics") or []
        if metrics:
            lines.append("")
            for m in metrics:
                if isinstance(m, dict):
                    label = m.get("label", "")
                    value = m.get("value", "")
                    lines.append(f"- **{_esc(value)}** — {_esc(label)}")

        citations = slide.get("citations") or []
        if citations:
            lines.append("")
            lines.append(f"Sources: {', '.join(_esc(c) for c in citations)}")

        if slide.get("speaker_notes"):
            lines.append("")
            lines.append(f"> Speaker notes: {_esc(slide['speaker_notes'])}")

        lines.append("")

    # Trim trailing blanks, ensure single trailing newline.
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"
