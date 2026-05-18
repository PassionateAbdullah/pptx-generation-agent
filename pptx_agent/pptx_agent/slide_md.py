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

from typing import Any


def emit_slide_md(deck: dict[str, Any]) -> str:
    title = deck.get("title", "Deck")
    subtitle = deck.get("subtitle", "")
    audience = deck.get("audience", "")
    topic = deck.get("topic", "")
    family = deck.get("family", "")

    lines: list[str] = []
    header = title
    if subtitle and subtitle not in title:
        header = f"{title}: {subtitle}"
    lines.append(f"# {header}")
    lines.append("")
    if topic:
        lines.append(f"_Topic:_ {topic}")
    if family:
        lines.append(f"_Family:_ {family}")
    if audience:
        lines.append(f"_Audience:_ {audience}")
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
                tag_parts.append(f"eyebrow: {eyebrow}")
            if layout:
                tag_parts.append(f"layout: {layout}")
            lines.append(f"_({' · '.join(tag_parts)})_")
        if slide.get("title"):
            lines.append(slide["title"])
        if slide.get("subtitle"):
            lines.append(slide["subtitle"])

        bullets = slide.get("bullets") or []
        if bullets:
            lines.append("")
            for b in bullets:
                lines.append(f"- {b}")

        metrics = slide.get("metrics") or []
        if metrics:
            lines.append("")
            for m in metrics:
                if isinstance(m, dict):
                    label = m.get("label", "")
                    value = m.get("value", "")
                    lines.append(f"- **{value}** — {label}")

        citations = slide.get("citations") or []
        if citations:
            lines.append("")
            lines.append(f"Sources: {', '.join(citations)}")

        if slide.get("speaker_notes"):
            lines.append("")
            lines.append(f"> Speaker notes: {slide['speaker_notes']}")

        lines.append("")

    # Trim trailing blanks, ensure single trailing newline.
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines) + "\n"
