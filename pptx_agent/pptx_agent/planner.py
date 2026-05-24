from __future__ import annotations

import re
from typing import Any, Iterator

from .citations import cite_slide
from .config import Settings
from .dynamic_outline import build_outline as build_dynamic_outline
from .events import PHASE_CONTENT, PHASE_OUTLINE, make_event
from .hedge_filter import scrub_paragraph
from .llm import LLMClient
from .slide_author import (
    build_outline_llm,
    iter_analyst_authoring_events,
    iter_authoring_events,
)
from .themes import DEFAULT_THEME, choose_theme_name, resolve_theme_name
from .utils import clamp, slugify


def extract_slide_count(prompt: str, explicit_count: int | None = None) -> int:
    """Resolve slide count from explicit arg or "<N>-slide"/"<N>-page" mention."""
    if explicit_count:
        return clamp(explicit_count, 1, 25)
    match = re.search(
        r"\b(\d{1,2})\s*[- ]?\s*(?:slides?|pages?)\b", prompt, flags=re.IGNORECASE
    )
    if match:
        return clamp(int(match.group(1)), 1, 25)
    return 12


_COMMAND_VERBS = (
    r"create|build|make|generate|write|draft|produce|design|prepare|"
    r"craft|put together|give me|i need|i want|help me (?:create|build|make)"
)
_DECK_NOUNS = (
    r"pitch deck|investor deck|sales deck|deck|presentation|slide deck|"
    r"slides?|briefing|brief|report|overview|analysis|study|memo|writeup|"
    r"document|pptx|powerpoint|google slides"
)
_PHRASE_PREFIXES = (
    r"for our|for an?|for the|for|about|on|regarding|covering|"
    r"focused on|focusing on|titled|named|called"
)


def extract_topic(prompt: str) -> str:
    """Pull the subject of the deck out of a free-text prompt.

    Strips command verbs ("create", "build"...), slide count ("10-slide"),
    deck nouns ("pitch deck", "presentation", "briefing"...), and leading
    framing phrases ("for our", "about", "on"...). What survives is the
    topic. No fallback to "AI platform" — that swallowed every non-AI
    prompt and made every research query generic.
    """
    cleaned = re.sub(r"\s+", " ", prompt).strip(" .")

    # 1. Phrase-prefix lift: "Create a 10-slide pitch deck on healthcare in
    #    Bangladesh" → after "on" → "healthcare in Bangladesh".
    prefix_pattern = rf"\b(?:{_PHRASE_PREFIXES})\s+([^.,;:?]+)"
    match = re.search(prefix_pattern, cleaned, flags=re.IGNORECASE)
    if match:
        topic = _clean_topic(match.group(1))
        if topic:
            return topic

    # 2. Strip command verb at sentence start.
    stripped = re.sub(
        rf"^(?:{_COMMAND_VERBS})\s+", "", cleaned, count=1, flags=re.IGNORECASE
    )
    topic = _clean_topic(stripped)
    if topic:
        return topic

    # 3. Last resort: original cleaned prompt minus deck nouns + counts.
    return _clean_topic(cleaned) or "the requested topic"


def _clean_topic(text: str) -> str:
    """Remove slide counts, deck nouns, and trailing fluff from a topic span."""
    if not text:
        return ""
    out = text
    # "10-slide", "10 slide", "10 slides"
    out = re.sub(r"\b\d{1,2}\s*[- ]?\s*slides?\b", "", out, flags=re.IGNORECASE)
    # "10 page", "10-pager", "10 page deck", "build 10 page" — users say
    # "page" interchangeably with "slide". Strip the count + page word
    # together so the topic doesn't trail off into "build 10 page".
    out = re.sub(
        r"\b(?:build|make|create|need|want|generate|draft|write)?\s*\d{1,2}\s*[- ]?\s*pages?(?:r)?\b",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(rf"\b(?:{_DECK_NOUNS})\b", "", out, flags=re.IGNORECASE)
    # "I need", "give me", "help me" etc. prefixes → drop.
    out = re.sub(
        r"^(?:i\s+(?:need|want)|give\s+me|help\s+me|please)\s+",
        "",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\b(?:a|an|the)\b\s+", " ", out, flags=re.IGNORECASE)
    out = re.sub(r"[\"'“”‘’]", "", out)
    out = re.sub(r"\s+", " ", out).strip(" .,-—:;|")
    # Drop dangling prepositions left over after stripping deck nouns
    # (e.g. "market of EV charging" → "EV charging" if "market" was a noun;
    # here we keep the topic core).
    out = re.sub(r"^(?:of|for|in|on|about|regarding)\s+", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+(?:of|for|in|on|about|regarding)$", "", out, flags=re.IGNORECASE)
    # Collapse repeated whitespace from internal strips.
    out = re.sub(r"\s{2,}", " ", out).strip(" .,-—:;|")
    return out


def build_deck(
    prompt: str,
    slide_count: int,
    research: dict[str, Any],
    settings: Settings,
    theme: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    deck: dict[str, Any] | None = None
    for event in iter_build_deck(prompt, slide_count, research, settings, theme=theme):
        etype = event.get("type")
        if etype == "log":
            logs.append(event.get("text", ""))
        elif etype == "phase_end" and event.get("id") == PHASE_CONTENT:
            deck = event.get("result")
    if deck is None:
        deck = _empty_deck(prompt, slide_count, research, theme)
    return deck, logs


def iter_build_deck(
    prompt: str,
    slide_count: int,
    research: dict[str, Any],
    settings: Settings,
    theme: str | None = None,
) -> Iterator[dict[str, Any]]:
    yield make_event("phase_start", id=PHASE_OUTLINE, label="Plan outline")
    topic = extract_topic(prompt)
    llm = LLMClient(settings)
    requested_theme = resolve_theme_name(theme)
    resolved_theme = requested_theme
    llm_ok = False

    # ---- Probe LLM up front. Bad keys / wrong model / wrong endpoint:
    # surface the error to the UI immediately instead of running N+1 doomed
    # calls and emitting a deck full of placeholder slides.
    if llm.enabled:
        yield make_event(
            "log", phase=PHASE_OUTLINE,
            text=f"Probing LLM: {settings.llm_model} @ {settings.llm_base_url}",
        )
        ok, msg = llm.probe()
        if ok:
            llm_ok = True
            yield make_event("log", phase=PHASE_OUTLINE, text="LLM probe ok.")
        else:
            yield make_event(
                "log", phase=PHASE_OUTLINE,
                text=(
                    "LLM probe failed; falling back to deterministic research-based planning. "
                    f"Reason: {msg[:220]}"
                ),
            )
    else:
        yield make_event(
            "log", phase=PHASE_OUTLINE,
            text="LLM not configured. Using deterministic research-based planning.",
        )

    # ---- Outline pass (single LLM call) ----
    outline: dict[str, Any]
    deterministic_deck: dict[str, Any] | None = None
    if llm_ok:
        try:
            outline = build_outline_llm(prompt, topic, slide_count, research, llm)
            yield make_event(
                "log", phase=PHASE_OUTLINE,
                text=f"Outline returned: {len(outline.get('slides') or [])} slide(s), family={outline.get('family') or '—'}.",
            )
        except Exception as exc:  # noqa: BLE001
            llm_ok = False
            yield make_event(
                "log", phase=PHASE_OUTLINE,
                text=f"LLM outline failed; using deterministic fallback. Reason: {str(exc)[:220]}",
            )
            deterministic_deck = _build_deterministic_deck(
                prompt=prompt,
                topic=topic,
                slide_count=slide_count,
                research=research,
                theme=resolved_theme,
            )
            outline = _outline_from_existing_deck(deterministic_deck)
    else:
        deterministic_deck = _build_deterministic_deck(
            prompt=prompt,
            topic=topic,
            slide_count=slide_count,
            research=research,
            theme=resolved_theme,
        )
        outline = _outline_from_existing_deck(deterministic_deck)

    # Story-arc validation + 1-shot LLM repair if required roles are missing.
    if llm_ok:
        from .intake import validate_story, story_gap_repair_prompt
        gaps = validate_story(outline, outline.get("family"))
        if gaps:
            for g in gaps:
                yield make_event(
                    "story_gap", phase=PHASE_OUTLINE,
                    role=g.role, severity=g.severity, suggestion=g.suggestion,
                )
            try:
                from .prompts import load as _load_prompt
                repaired = llm.complete_json(
                    _load_prompt("outline"),
                    story_gap_repair_prompt(outline, gaps, slide_count),
                    max_tokens=1600,
                )
                if repaired and repaired.get("slides"):
                    outline = repaired
                    yield make_event(
                        "log", phase=PHASE_OUTLINE,
                        text=f"Patched outline to cover {len(gaps)} missing role(s): "
                             f"{', '.join(g.role for g in gaps)}.",
                    )
            except Exception as exc:  # noqa: BLE001
                yield make_event(
                    "log", phase=PHASE_OUTLINE,
                    text=f"Story-gap repair failed; keeping original outline. Reason: {str(exc)[:160]}",
                )

    # Targeted research: spawn focused queries for any slide that asks for
    # data-heavy blocks but has weak or no source assignment.
    if research.get("sources"):
        from .intake import targeted_queries
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from .research import Researcher
        pending: list[tuple[dict[str, Any], list[str]]] = []
        for entry in outline.get("slides") or []:
            if not (entry.get("needs_chart") or entry.get("needs_table") or entry.get("needs_hero_stat")):
                continue
            if len(entry.get("assigned_source_ids") or []) >= 2:
                continue
            queries = targeted_queries(entry, topic)
            if queries:
                pending.append((entry, queries))
        if pending:
            researcher = Researcher(settings)
            new_sources: list[dict[str, Any]] = []
            existing_urls = {str(s.get("url", "")).lower() for s in research.get("sources") or []}
            with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
                futs = {}
                for entry, queries in pending:
                    for q in queries:
                        futs[pool.submit(researcher._search, researcher._resolve_provider(), q)] = (entry, q)
                for fut in as_completed(futs):
                    entry, q = futs[fut]
                    try:
                        hits = fut.result() or []
                    except Exception:  # noqa: BLE001
                        continue
                    yield make_event(
                        "targeted_query", phase=PHASE_OUTLINE,
                        slide=entry.get("number"), query=q, hits=len(hits),
                    )
                    for r in hits[:3]:
                        if not r.url or r.url.lower() in existing_urls:
                            continue
                        existing_urls.add(r.url.lower())
                        new_sources.append({
                            "title": r.title, "url": r.url, "snippet": r.snippet,
                            "excerpt": r.snippet, "query": q,
                        })
            if new_sources:
                start_idx = len(research.get("sources") or []) + 1
                for i, s in enumerate(new_sources, start=start_idx):
                    s["source_id"] = f"S{i}"
                research.setdefault("sources", []).extend(new_sources)
                yield make_event(
                    "log", phase=PHASE_OUTLINE,
                    text=f"Targeted research added {len(new_sources)} source(s) for data-heavy slides.",
                )

    # Pad or trim to exact slide_count.
    outline["slides"] = _normalize_outline_slides(outline.get("slides") or [], slide_count, topic)

    deck_title = scrub_paragraph(str(outline.get("title") or _title_for_topic(topic)))
    deck_subtitle = scrub_paragraph(str(outline.get("subtitle") or _subtitle_for_topic(topic)))
    audience = str(outline.get("audience") or "Stakeholders")
    family = str(outline.get("family") or "report")
    resolved_theme = choose_theme_name(prompt, topic, family, theme)
    if deterministic_deck is not None:
        deterministic_deck["theme"] = resolved_theme

    yield make_event(
        "deck_meta",
        phase=PHASE_OUTLINE,
        title=deck_title,
        subtitle=deck_subtitle,
        slide_count=slide_count,
        topic=topic,
        theme=resolved_theme,
    )
    for entry in outline["slides"]:
        yield make_event(
            "slide_outline",
            phase=PHASE_OUTLINE,
            number=entry["number"],
            title=entry.get("title", ""),
            subtitle=entry.get("subtitle", ""),
            eyebrow=entry.get("eyebrow", ""),
            layout=entry.get("layout") or entry.get("role") or "solution",
            role=entry.get("role") or entry.get("layout") or "solution",
            focus_keywords=entry.get("focus_keywords") or [],
            assigned_source_ids=entry.get("assigned_source_ids") or [],
            needs_chart=bool(entry.get("needs_chart")),
            needs_table=bool(entry.get("needs_table")),
            needs_diagram=bool(entry.get("needs_diagram")),
            needs_hero_stat=bool(entry.get("needs_hero_stat")),
            animation=entry.get("animation") or "",
        )
    yield make_event("phase_end", id=PHASE_OUTLINE)

    # ---- Content pass: per-slide LLM authoring in parallel ----
    yield make_event("phase_start", id=PHASE_CONTENT, label="Write slide content")

    deck_meta = {
        "prompt": prompt,
        "topic": topic,
        "title": deck_title,
        "audience": audience,
        "family": family,
    }

    authored: dict[int, dict[str, Any]] = {}
    # Analyst mode = slide-by-slide author → validate → data-hunt →
    # re-author → render → inspect → repair, then move to next slide.
    # Default ON; opt out by setting PPTX_AGENT_PARALLEL=1 in .env if the
    # user needs the older fast-but-shallow path.
    import os as _os
    analyst_mode = (_os.environ.get("PPTX_AGENT_PARALLEL", "").strip() != "1")
    if llm_ok and analyst_mode:
        yield make_event(
            "log", phase=PHASE_CONTENT,
            text="Analyst mode: writing slides one at a time with per-slide validate + repair.",
        )
        events_iter = iter_analyst_authoring_events(outline, research, deck_meta, llm, settings)
        for evt in events_iter:
            etype = evt.get("type")
            if etype in {"slide_authored", "slide_failed"}:
                slide = evt.get("slide")
                if slide:
                    authored[int(slide["number"])] = slide
                    yield make_event(
                        "slide_detail", phase=PHASE_CONTENT,
                        number=int(slide["number"]), slide=slide,
                    )
                    if etype == "slide_failed":
                        yield make_event(
                            "log", phase=PHASE_CONTENT,
                            text=f"Slide {slide['number']} fell back to scaffold: {str(evt.get('error'))[:200]}",
                        )
            elif etype in {
                "analyst_slide_start", "analyst_check", "analyst_repaired",
                "analyst_data_hunt", "analyst_data_added", "analyst_reauthored",
                "analyst_reauthor_failed", "analyst_repair_failed",
                "analyst_slide_done", "analyst_author_failed", "targeted_query",
            }:
                # Pass analyst progress events to the UI verbatim.
                yield evt
    elif llm_ok:
        max_workers = max(1, min(6, int(getattr(settings, "max_search_queries", 6) or 6)))
        for evt in iter_authoring_events(outline, research, deck_meta, llm, max_workers=max_workers):
            etype = evt.get("type")
            if etype in {"slide_authored", "slide_failed"}:
                slide = evt.get("slide")
                if slide:
                    authored[int(slide["number"])] = slide
                    yield make_event(
                        "slide_detail", phase=PHASE_CONTENT,
                        number=int(slide["number"]), slide=slide,
                    )
                    if etype == "slide_failed":
                        yield make_event(
                            "log", phase=PHASE_CONTENT,
                            text=f"Slide {slide['number']} fell back to scaffold: {str(evt.get('error'))[:200]}",
                        )
            elif etype == "slides_ready":
                # final list arrives ordered — already captured per-event.
                pass
    else:
        if deterministic_deck is None:
            deterministic_deck = _build_deterministic_deck(
                prompt=prompt,
                topic=topic,
                slide_count=slide_count,
                research=research,
                theme=resolved_theme,
            )
        for slide in deterministic_deck.get("slides") or []:
            authored[int(slide["number"])] = slide
            yield make_event(
                "slide_detail", phase=PHASE_CONTENT,
                number=int(slide["number"]), slide=slide,
            )

    # Assemble final deck in slide-number order.
    slides = [authored[n] for n in sorted(authored.keys())]
    _enforce_citations(slides, research.get("sources") or [])

    deck = {
        "title": deck_title,
        "subtitle": deck_subtitle,
        "topic": topic,
        "slug": slugify(deck_title),
        "audience": audience,
        "prompt": prompt,
        "slide_count": slide_count,
        "theme": resolved_theme,
        "family": family,
        "research": research,
        "slides": slides,
    }

    # ---- Self-repair loop (render → inspect → repair → repeat) ----
    # Skip the deck-wide loop when analyst mode already ran a per-slide
    # repair pass — running it again wastes LLM calls. Still produce a
    # final quality snapshot so the artifact ships either way.
    from .agent_loop import run_loop, quality_score
    from .deck_audit import audit_deck as _audit
    from .visual_inspect import inspect_slide_html as _inspect
    from .html_renderer import render_single_slide_html as _render

    if llm_ok and slides and not analyst_mode:
        pending_events: list[dict[str, Any]] = []

        def _on_loop_event(evt: dict[str, Any]) -> None:
            pending_events.append(evt)

        try:
            run_loop(deck, research, deck_meta, llm, max_passes=2, on_event=_on_loop_event)
        except Exception as exc:  # noqa: BLE001
            yield make_event(
                "log", phase=PHASE_CONTENT,
                text=f"Agent loop aborted: {str(exc)[:200]}",
            )

        for evt in pending_events:
            etype = evt.get("type")
            if etype == "slide_repaired" and evt.get("ok") and evt.get("slide"):
                yield make_event(
                    "slide_detail", phase=PHASE_CONTENT,
                    number=int(evt["slide"]["number"]), slide=evt["slide"],
                )
            yield make_event(etype or "log", phase=PHASE_CONTENT, **{
                k: v for k, v in evt.items() if k not in {"type", "slide"}
            })

    # Always emit a final quality snapshot for the artifact.
    if slides:
        final_audit = _audit(deck)
        final_visual: dict[int, list[dict[str, Any]]] = {}
        for sl in deck.get("slides") or []:
            n = int(sl.get("number") or 0)
            findings = _inspect(_render(deck, sl), sl)
            if findings:
                final_visual[n] = [
                    {"code": f.code, "severity": f.severity,
                     "message": f.message, "suggested_fix": f.suggested_fix}
                    for f in findings
                ]
        deck["quality"] = quality_score(final_audit, final_visual)
        yield make_event(
            "log", phase=PHASE_CONTENT,
            text=f"Final quality score: {deck['quality']['score']} "
                 f"({deck['quality']['by_severity']})",
        )

    for slide in deck["slides"]:
        if slide.get("citations"):
            yield make_event(
                "slide_citation",
                phase=PHASE_CONTENT,
                number=slide["number"],
                source_ids=list(slide["citations"]),
            )
    yield make_event("phase_end", id=PHASE_CONTENT, result=deck)


# ---------------------------------------------------------------------------
# Deck-level helpers
# ---------------------------------------------------------------------------


def _normalize_outline_slides(
    raw_slides: list[Any], slide_count: int, topic: str
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_slides[:slide_count], start=1):
        if not isinstance(raw, dict):
            continue
        cleaned.append(
            {
                "number": i,
                "role": str(raw.get("role") or raw.get("layout") or _default_role(i, slide_count)),
                "layout": str(raw.get("layout") or raw.get("role") or _default_role(i, slide_count)),
                "eyebrow": scrub_paragraph(str(raw.get("eyebrow") or "")),
                "title": scrub_paragraph(str(raw.get("title") or f"Slide {i}")),
                "subtitle": scrub_paragraph(str(raw.get("subtitle") or "")),
                "focus_keywords": [str(k) for k in (raw.get("focus_keywords") or [])][:6],
                "assigned_source_ids": [str(s) for s in (raw.get("assigned_source_ids") or [])],
                "needs_chart": bool(raw.get("needs_chart")),
                "needs_table": bool(raw.get("needs_table")),
                "needs_diagram": bool(raw.get("needs_diagram")),
                "needs_hero_stat": bool(raw.get("needs_hero_stat")),
            }
        )

    while len(cleaned) < slide_count:
        i = len(cleaned) + 1
        cleaned.append(
            {
                "number": i,
                "role": _default_role(i, slide_count),
                "layout": _default_role(i, slide_count),
                "eyebrow": "",
                "title": f"Slide {i}",
                "subtitle": "",
                "focus_keywords": [],
                "assigned_source_ids": [],
                "needs_chart": False,
                "needs_table": False,
                "needs_diagram": False,
                "needs_hero_stat": False,
            }
        )

    # Renumber to guarantee 1..N.
    for i, entry in enumerate(cleaned, start=1):
        entry["number"] = i
    return cleaned


def _default_role(i: int, total: int) -> str:
    if i == 1:
        return "cover"
    if i == total:
        return "closing"
    return "solution"


def _enforce_citations(slides: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    """Fill missing citations from text-overlap matching so every slide
    that talks about something in the research carries [S#] traceability."""
    for slide in slides:
        existing = slide.get("citations") or []
        if existing:
            slide["citations"] = [str(c) for c in existing if c]
            continue
        slide["citations"] = cite_slide(slide, sources)


def _empty_deck(
    prompt: str,
    slide_count: int,
    research: dict[str, Any],
    theme: str | None,
) -> dict[str, Any]:
    topic = extract_topic(prompt)
    resolved_theme = choose_theme_name(prompt, topic, "report", theme)
    deterministic = _build_deterministic_deck(
        prompt=prompt,
        topic=topic,
        slide_count=slide_count,
        research=research,
        theme=resolved_theme,
    )
    slides = deterministic.get("slides") or []
    return {
        "title": deterministic.get("title") or topic,
        "subtitle": deterministic.get("subtitle") or "",
        "topic": topic,
        "slug": deterministic.get("slug") or slugify(topic),
        "audience": deterministic.get("audience") or "Stakeholders",
        "prompt": prompt,
        "slide_count": slide_count,
        "theme": resolved_theme,
        "family": deterministic.get("family") or "report",
        "research": research,
        "slides": slides,
    }


def _build_deterministic_deck(
    prompt: str,
    topic: str,
    slide_count: int,
    research: dict[str, Any],
    theme: str,
) -> dict[str, Any]:
    deck = build_dynamic_outline(prompt, topic, slide_count, research)
    deck["prompt"] = prompt
    deck["topic"] = topic
    deck["slide_count"] = slide_count
    deck["theme"] = theme
    deck["research"] = research
    deck["slug"] = slugify(str(deck.get("title") or topic))
    for index, slide in enumerate(deck.get("slides") or [], start=1):
        slide["number"] = index
        slide["id"] = slide.get("id") or f"slide-{index}"
        slide["accent_variant"] = int(slide.get("accent_variant") or ((index - 1) % 4))
    return deck


def _outline_from_existing_deck(deck: dict[str, Any]) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    for slide in deck.get("slides") or []:
        slides.append(
            {
                "number": int(slide.get("number") or (len(slides) + 1)),
                "role": str(slide.get("layout") or "solution"),
                "layout": str(slide.get("layout") or "solution"),
                "eyebrow": str(slide.get("eyebrow") or ""),
                "title": str(slide.get("title") or f"Slide {len(slides) + 1}"),
                "subtitle": str(slide.get("subtitle") or ""),
                "focus_keywords": [str(k) for k in (slide.get("focus_keywords") or [])][:6],
                "assigned_source_ids": [
                    str(s) for s in (slide.get("assigned_source_ids") or slide.get("citations") or [])
                ],
                "needs_chart": bool(slide.get("needs_chart")),
                "needs_table": bool(slide.get("needs_table")),
                "needs_diagram": bool(slide.get("needs_diagram")),
                "needs_hero_stat": bool(slide.get("needs_hero_stat")),
                "animation": str(slide.get("animation") or ""),
            }
        )
    return {
        "title": str(deck.get("title") or ""),
        "subtitle": str(deck.get("subtitle") or ""),
        "audience": str(deck.get("audience") or "Stakeholders"),
        "family": str(deck.get("family") or "report"),
        "slides": slides,
    }


# ---------------------------------------------------------------------------
# Artifact emitters (deck structure text + slide-content markdown)
# ---------------------------------------------------------------------------


def deck_structure_text(deck: dict[str, Any]) -> str:
    lines = [f"{deck['title']} Structure ({deck['slide_count']} Slides):"]
    for slide in deck["slides"]:
        label = slide.get("eyebrow") or slide.get("layout", "Slide").title()
        description = (slide.get("subtitle") or label).rstrip(".")
        lines.append(
            f"{slide['number']}. {label}: {slide['title']} - {description}."
        )
    return "\n".join(lines) + "\n"


def slide_content_markdown(deck: dict[str, Any]) -> str:
    lines = [f"# {deck['title']}", "", deck.get("subtitle", ""), ""]
    research = deck.get("research", {})
    insights = research.get("insights", [])
    if insights:
        lines.extend(["## Research Notes", ""])
        for insight in insights:
            lines.append(f"- {insight}")
        lines.append("")

    for slide in deck["slides"]:
        heading = "Cover" if slide["number"] == 1 else f"Slide {slide['number']}"
        lines.extend([f"## {heading}", slide["title"]])
        if slide.get("subtitle"):
            lines.append(slide["subtitle"])
        for bullet in slide.get("bullets", []):
            lines.append(f"- {bullet}")
        metrics = slide.get("metrics", [])
        if metrics:
            lines.append("")
            lines.append("Metrics:")
            for metric in metrics:
                lines.append(f"- {metric.get('label')}: {metric.get('value')}")
        if slide.get("speaker_notes"):
            lines.append("")
            lines.append(f"Speaker note: {slide['speaker_notes']}")
        lines.append("")

    sources = research.get("sources", [])
    if sources:
        lines.extend(["## Sources", ""])
        for source in sources:
            lines.append(f"- {source.get('title', 'Source')}: {source.get('url', '')}")
    return "\n".join(lines).strip() + "\n"


def slide_plan_markdown(deck: dict[str, Any]) -> str:
    lines = [f"# {deck['title']} Slide Plan", ""]
    for slide in deck.get("slides") or []:
        lines.append(f"## Slide {slide['number']}: {slide.get('title', '')}")
        lines.append(f"- Layout: {slide.get('layout', '')}")
        if slide.get("eyebrow"):
            lines.append(f"- Eyebrow: {slide.get('eyebrow')}")
        if slide.get("subtitle"):
            lines.append(f"- Lede: {slide.get('subtitle')}")
        keywords = ", ".join(str(k) for k in (slide.get("focus_keywords") or [])[:6])
        if keywords:
            lines.append(f"- Focus keywords: {keywords}")
        source_ids = ", ".join(
            str(s) for s in (slide.get("assigned_source_ids") or slide.get("citations") or [])[:4]
        )
        if source_ids:
            lines.append(f"- Planned sources: {source_ids}")
        visuals = [
            label
            for label, enabled in (
                ("chart", bool(slide.get("needs_chart"))),
                ("table", bool(slide.get("needs_table"))),
                ("diagram", bool(slide.get("needs_diagram"))),
                ("hero_stat", bool(slide.get("needs_hero_stat"))),
            )
            if enabled
        ]
        if visuals:
            lines.append(f"- Planned visual: {', '.join(visuals)}")
        block_types = [
            str(block.get("type") or "")
            for block in (slide.get("blocks") or [])
            if block.get("type")
        ]
        if block_types:
            lines.append(f"- Actual blocks: {' -> '.join(block_types)}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _title_for_topic(topic: str) -> str:
    words = topic.strip()
    if not words:
        return "Research Opportunity"
    return words[0].upper() + words[1:]


def _subtitle_for_topic(topic: str) -> str:
    return f"What the research says about {topic}." if topic else "Research-backed deck."


__all__ = [
    "extract_slide_count",
    "extract_topic",
    "build_deck",
    "iter_build_deck",
    "deck_structure_text",
    "slide_content_markdown",
    "slide_plan_markdown",
    "DEFAULT_THEME",
]
