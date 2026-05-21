from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .config import Settings
from .events import PHASE_CONTENT, PHASE_EXPORT, PHASE_RENDER, PHASE_RESEARCH, domain_of, make_event
from .deck_audit import audit_deck, render_audit_html
from .html_renderer import render_full_html, render_preview_fragment, render_single_slide_html
from .layout_audit import audit_deck_layout, audit_report_markdown
from .planner import (
    deck_structure_text,
    extract_slide_count,
    extract_topic,
    iter_build_deck,
    slide_content_markdown,
)
from .research import Researcher
from .slide_md import emit_slide_md
from .utils import timestamp_id, write_json


def write_deck_artifacts(
    deck: dict[str, Any],
    job_dir: Path,
    research: dict[str, Any] | None = None,
    only_slides: list[int] | None = None,
) -> dict[str, str]:
    """Render and persist every artifact derived from a deck.

    Used by the initial pipeline run and by post-generation edits so that
    deck.json, slides.html, sources.md, structure, and slide-content markdown
    stay in lockstep with the in-memory deck.

    ``only_slides`` (optional) limits per-slide ``slide-NN.html`` rewrites to
    the listed slide numbers. Deck-level files (deck.json, slides.html,
    audit.json, etc.) are always rewritten because they embed every slide.
    """
    research = research if research is not None else deck.get("research") or {}
    structure = deck_structure_text(deck)
    markdown = slide_content_markdown(deck)
    # Run deck_audit BEFORE render so the HTML can embed the audit panel.
    audit = audit_deck(deck)
    html = render_full_html(deck, audit=audit)
    preview_fragment = render_preview_fragment(deck)
    sources_md = _sources_markdown(deck, research)
    slide_md = emit_slide_md(deck)
    layout_report = audit_deck_layout(deck)
    layout_report_md = audit_report_markdown(layout_report)

    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(job_dir / "deck.json", deck)
    (job_dir / "pitch_deck_structure.txt").write_text(structure, encoding="utf-8")
    (job_dir / "slide_content.md").write_text(markdown, encoding="utf-8")
    (job_dir / "slides.html").write_text(html, encoding="utf-8")
    (job_dir / "sources.md").write_text(sources_md, encoding="utf-8")
    (job_dir / "slide.md").write_text(slide_md, encoding="utf-8")
    write_json(job_dir / "layout_report.json", layout_report)
    (job_dir / "layout_report.md").write_text(layout_report_md, encoding="utf-8")
    write_json(job_dir / "audit.json", audit)
    if isinstance(deck.get("quality"), dict):
        write_json(job_dir / "quality.json", deck["quality"])

    # Per-slide standalone HTML — viewable directly via
    # /api/jobs/<id>/slide-NN.html. Files live at the top of job_dir so they
    # pass the existing 4-part path dispatcher.
    only_set = {int(n) for n in only_slides} if only_slides else None
    for slide in deck.get("slides", []):
        number = int(slide.get("number") or 0)
        if number <= 0:
            continue
        if only_set is not None and number not in only_set:
            continue
        slide_html = render_single_slide_html(deck, slide)
        (job_dir / f"slide-{number:02d}.html").write_text(slide_html, encoding="utf-8")

    return {
        "structure": structure,
        "slide_content": markdown,
        "preview_html": preview_fragment,
        "html": html,
        "sources_md": sources_md,
        "slide_md": slide_md,
        "layout_report": layout_report,
        "layout_report_md": layout_report_md,
        "audit": audit,
    }


def iter_pipeline(
    prompt: str,
    explicit_slide_count: int | None,
    settings: Settings,
    theme: str | None = None,
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
        theme=theme or "",
    )

    research: dict[str, Any] | None = None
    for event in Researcher(settings).iter_run(prompt, topic):
        yield event
        if event.get("type") == "phase_end" and event.get("id") == PHASE_RESEARCH:
            research = event.get("result")
    if research is None:
        research = {"queries": [], "sources": [], "insights": [], "provider": "none"}

    # Progressive per-slide HTML: as each slide_detail event streams, write
    # that slide's standalone slide-NN.html and emit a file event so the
    # drawer's iframe can show real rendered HTML the moment authoring
    # finishes (instead of waiting for the whole deck to land).
    progressive_deck: dict[str, Any] = {
        "title": "",
        "theme": theme or "",
        "topic": topic,
        "slides": [],
    }
    seen_slide_numbers: set[int] = set()

    deck: dict[str, Any] | None = None
    for event in iter_build_deck(prompt, slide_count, research, settings, theme=theme):
        yield event
        etype = event.get("type")
        if etype == "deck_meta":
            progressive_deck["title"] = event.get("title", "")
            progressive_deck["theme"] = event.get("theme", progressive_deck["theme"])
        elif etype == "slide_detail" and event.get("slide"):
            slide = event["slide"]
            n = int(slide.get("number") or 0)
            if n <= 0:
                continue
            # Insert/replace this slide in the progressive deck so the
            # standalone HTML render carries fresh data.
            existing = next(
                (i for i, s in enumerate(progressive_deck["slides"]) if int(s.get("number") or 0) == n),
                None,
            )
            if existing is None:
                progressive_deck["slides"].append(slide)
            else:
                progressive_deck["slides"][existing] = slide
            try:
                slide_html = render_single_slide_html(progressive_deck, slide)
                (job_dir / f"slide-{n:02d}.html").write_text(slide_html, encoding="utf-8")
                first_time = n not in seen_slide_numbers
                seen_slide_numbers.add(n)
                yield make_event(
                    "slide_html_ready",
                    phase=PHASE_CONTENT,
                    number=n,
                    url=f"/api/jobs/{job_id}/slide-{n:02d}.html",
                    first=first_time,
                )
            except Exception as exc:  # noqa: BLE001
                yield make_event(
                    "log",
                    phase=PHASE_CONTENT,
                    text=f"Progressive slide-{n} HTML write failed: {exc}",
                )
        if etype == "phase_end" and event.get("id") == PHASE_CONTENT:
            deck = event.get("result")
    if deck is None:
        yield make_event("error", phase=PHASE_CONTENT, message="Planner returned no deck.")
        return

    yield make_event("phase_start", id=PHASE_RENDER, label="Render HTML")
    artifacts = write_deck_artifacts(deck, job_dir, research)
    structure = artifacts["structure"]
    markdown = artifacts["slide_content"]
    preview_fragment = artifacts["preview_html"]
    sources_md = artifacts["sources_md"]
    layout_report = artifacts["layout_report"]
    layout_report_md = artifacts["layout_report_md"]

    yield make_event("file", phase=PHASE_RENDER, path="pitch_deck_structure.txt", content=structure)
    yield make_event("file", phase=PHASE_RENDER, path="slide_content.md", content=markdown)
    yield make_event(
        "file",
        phase=PHASE_RENDER,
        path="slides.html",
        url=f"/api/jobs/{job_id}/slides.html",
    )
    yield make_event("file", phase=PHASE_RENDER, path="sources.md", content=sources_md)
    yield make_event("file", phase=PHASE_RENDER, path="slide.md", content=artifacts["slide_md"])
    yield make_event("file", phase=PHASE_RENDER, path="layout_report.md", content=layout_report_md)
    yield make_event("file", phase=PHASE_RENDER, path="layout_report.json", content=layout_report)
    yield make_event(
        "log",
        phase=PHASE_RENDER,
        text="Saved structure, slide notes, and HTML preview.",
    )
    if layout_report.get("summary", {}).get("critical_count", 0):
        yield make_event(
            "log",
            phase=PHASE_RENDER,
            text=(
                "Layout audit found critical alignment risks. "
                f"See /api/jobs/{job_id}/layout_report.md"
            ),
        )
    else:
        yield make_event(
            "log",
            phase=PHASE_RENDER,
            text=(
                "Layout audit passed static checks for overlap/clipping risk and "
                "HTML/PPTX block-type consistency."
            ),
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
        layout_audit=layout_report.get("summary", {}),
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
    theme: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Wrap iter_pipeline. Writes events.jsonl line-by-line once job_start fires."""
    fh = None
    try:
        for event in iter_pipeline(prompt, explicit_slide_count, settings, theme=theme):
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
    theme: str | None = None,
) -> dict[str, Any]:
    """Drain iter_pipeline_with_persist, return summary for /api/generate."""
    summary: dict[str, Any] | None = None
    logs: list[str] = []

    for event in iter_pipeline_with_persist(prompt, explicit_slide_count, settings, theme=theme):
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
        "layout_audit": summary.get("layout_audit", {}),
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
