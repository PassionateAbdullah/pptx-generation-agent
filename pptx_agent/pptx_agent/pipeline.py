from __future__ import annotations

import json
from typing import Any, Iterator

from .config import Settings
from .events import PHASE_CONTENT, PHASE_EXPORT, PHASE_RENDER, PHASE_RESEARCH, domain_of, make_event
from .html_renderer import render_full_html, render_preview_fragment
from .planner import (
    deck_structure_text,
    extract_slide_count,
    extract_topic,
    iter_build_deck,
    slide_content_markdown,
)
from .research import Researcher
from .utils import timestamp_id, write_json


def iter_pipeline(
    prompt: str,
    explicit_slide_count: int | None,
    settings: Settings,
) -> Iterator[dict[str, Any]]:
    slide_count = extract_slide_count(prompt, explicit_slide_count)
    topic = extract_topic(prompt)
    job_id = timestamp_id(topic or "deck")
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    yield make_event(
        "job_start",
        job_id=job_id,
        prompt=prompt,
        slide_count=slide_count,
        topic=topic,
    )

    research: dict[str, Any] | None = None
    for event in Researcher(settings).iter_run(prompt, topic):
        yield event
        if event.get("type") == "phase_end" and event.get("id") == PHASE_RESEARCH:
            research = event.get("result")
    if research is None:
        research = {"queries": [], "sources": [], "insights": [], "provider": "none"}

    deck: dict[str, Any] | None = None
    for event in iter_build_deck(prompt, slide_count, research, settings):
        yield event
        if event.get("type") == "phase_end" and event.get("id") == PHASE_CONTENT:
            deck = event.get("result")
    if deck is None:
        yield make_event("error", phase=PHASE_CONTENT, message="Planner returned no deck.")
        return

    yield make_event("phase_start", id=PHASE_RENDER, label="Render HTML")
    structure = deck_structure_text(deck)
    markdown = slide_content_markdown(deck)
    html = render_full_html(deck)
    preview_fragment = render_preview_fragment(deck)
    sources_md = _sources_markdown(deck, research)

    write_json(job_dir / "deck.json", deck)
    (job_dir / "pitch_deck_structure.txt").write_text(structure, encoding="utf-8")
    (job_dir / "slide_content.md").write_text(markdown, encoding="utf-8")
    (job_dir / "slides.html").write_text(html, encoding="utf-8")
    (job_dir / "sources.md").write_text(sources_md, encoding="utf-8")

    yield make_event("file", phase=PHASE_RENDER, path="pitch_deck_structure.txt", content=structure)
    yield make_event("file", phase=PHASE_RENDER, path="slide_content.md", content=markdown)
    yield make_event(
        "file",
        phase=PHASE_RENDER,
        path="slides.html",
        url=f"/api/jobs/{job_id}/slides.html",
    )
    yield make_event("file", phase=PHASE_RENDER, path="sources.md", content=sources_md)
    yield make_event(
        "log",
        phase=PHASE_RENDER,
        text="Saved structure, slide notes, and HTML preview.",
    )
    yield make_event("phase_end", id=PHASE_RENDER)

    yield make_event(
        "phase_start",
        id=PHASE_EXPORT,
        label="Awaiting PPTX export",
    )
    yield make_event(
        "log",
        phase=PHASE_EXPORT,
        text="PPTX will be generated when Download PPTX is clicked.",
    )
    yield make_event(
        "deck_ready",
        job_id=job_id,
        title=deck["title"],
        slide_count=deck["slide_count"],
        slides=[
            {
                "number": slide["number"],
                "title": slide["title"],
                "subtitle": slide["subtitle"],
            }
            for slide in deck["slides"]
        ],
        sources=research.get("sources", []),
        structure=structure,
        slide_content=markdown,
        preview_html=preview_fragment,
        download_url=f"/api/jobs/{job_id}/deck.pptx",
        html_url=f"/api/jobs/{job_id}/slides.html",
    )
    yield make_event(
        "done",
        job_id=job_id,
        download_url=f"/api/jobs/{job_id}/deck.pptx",
        html_url=f"/api/jobs/{job_id}/slides.html",
    )


def iter_pipeline_with_persist(
    prompt: str,
    explicit_slide_count: int | None,
    settings: Settings,
) -> Iterator[dict[str, Any]]:
    """Wrap iter_pipeline. Writes events.jsonl line-by-line once job_start fires."""
    fh = None
    try:
        for event in iter_pipeline(prompt, explicit_slide_count, settings):
            if fh is None and event.get("type") == "job_start" and event.get("job_id"):
                job_dir = settings.output_dir / event["job_id"]
                job_dir.mkdir(parents=True, exist_ok=True)
                fh = (job_dir / "events.jsonl").open("w", encoding="utf-8")
            if fh is not None:
                fh.write(json.dumps(event, ensure_ascii=False, default=str))
                fh.write("\n")
                fh.flush()
            yield event
    finally:
        if fh is not None:
            fh.close()


def run_pipeline_and_persist(
    prompt: str,
    explicit_slide_count: int | None,
    settings: Settings,
) -> dict[str, Any]:
    """Drain iter_pipeline_with_persist, return summary for /api/generate."""
    summary: dict[str, Any] | None = None
    logs: list[str] = []

    for event in iter_pipeline_with_persist(prompt, explicit_slide_count, settings):
        etype = event.get("type")
        if etype == "log":
            logs.append(event.get("text", ""))
        elif etype == "deck_ready":
            summary = event
        elif etype == "error":
            raise RuntimeError(event.get("message", "pipeline error"))

    if summary is None:
        raise RuntimeError("Pipeline ended without a deck_ready event.")

    return {
        "job_id": summary["job_id"],
        "title": summary["title"],
        "slide_count": summary["slide_count"],
        "slides": summary["slides"],
        "sources": summary.get("sources", []),
        "logs": logs,
        "structure": summary["structure"],
        "slide_content": summary["slide_content"],
        "preview_html": summary["preview_html"],
        "download_url": summary["download_url"],
        "html_url": summary["html_url"],
    }


def _sources_markdown(deck: dict[str, Any], research: dict[str, Any]) -> str:
    sources = research.get("sources") or []
    if not sources:
        return f"# Sources\n\nNo external sources were used for **{deck.get('title', 'this deck')}**.\n"

    cited_by: dict[str, list[int]] = {}
    for slide in deck.get("slides", []):
        for sid in slide.get("citations") or []:
            cited_by.setdefault(str(sid), []).append(slide["number"])

    lines = [f"# Sources for {deck.get('title', 'Deck')}", ""]
    for source in sources:
        sid = str(source.get("source_id", ""))
        title = source.get("title", "Untitled")
        url = source.get("url", "")
        trust = source.get("trust") or domain_of(url) or "unknown"
        engines = source.get("engines") or ([source.get("engine")] if source.get("engine") else [])
        snippet = source.get("excerpt") or source.get("snippet", "")
        slides_using = cited_by.get(sid, [])
        slide_ref = (
            f"Cited by slides: {', '.join(str(n) for n in sorted(set(slides_using)))}"
            if slides_using
            else "Not cited by any slide."
        )

        header = f"## {sid}. {title}" if sid else f"## {title}"
        lines.extend(
            [
                header,
                f"- URL: {url}",
                f"- Trust tier: `{trust}`",
                f"- Engines: {', '.join(e for e in engines if e) or '—'}",
                f"- {slide_ref}",
            ]
        )
        if snippet:
            compact = " ".join(str(snippet).split())
            if len(compact) > 400:
                compact = compact[:399].rstrip() + "…"
            lines.append("")
            lines.append(f"> {compact}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
