from __future__ import annotations

import json
import re
from typing import Any, Iterator

from .blocks import normalize_blocks, slide_to_blocks
from .citations import cite_slide
from .config import Settings
from .dynamic_blocks import compose_slide_blocks, optimize_deck_variety, variety_score
from .dynamic_outline import build_outline
from .hedge_filter import scrub_bullets, scrub_paragraph
from .topic_families import detect_family
from .events import PHASE_CONTENT, PHASE_OUTLINE, make_event
from .llm import LLMClient
from .themes import DEFAULT_THEME, get_theme
from .utils import clamp, slugify


def extract_slide_count(prompt: str, explicit_count: int | None = None) -> int:
    if explicit_count:
        return clamp(explicit_count, 5, 25)
    match = re.search(r"\b(\d{1,2})\s*[- ]?\s*slides?\b", prompt, flags=re.IGNORECASE)
    if match:
        return clamp(int(match.group(1)), 5, 25)
    return 12


def extract_topic(prompt: str) -> str:
    cleaned = re.sub(r"\s+", " ", prompt).strip(" .")
    patterns = [
        r"for our ([^.]+)",
        r"for an? ([^.]+)",
        r"about ([^.]+)",
        r"on ([^.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            topic = match.group(1).strip(" .")
            topic = re.sub(r"\b(pitch deck|presentation|slides?)\b", "", topic, flags=re.IGNORECASE)
            topic = re.sub(r"\s+", " ", topic).strip(" .")
            if topic:
                return topic
    if "ai" in cleaned.lower():
        return "AI platform"
    return "startup platform"


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
        topic = extract_topic(prompt)
        deck = normalize_deck(
            build_outline(prompt, topic, slide_count, research),
            prompt, topic, slide_count, research,
        )
        deck["theme"] = get_theme(theme).name
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
    deck: dict[str, Any] | None = None
    resolved_theme = get_theme(theme).name

    if llm.enabled:
        yield make_event("log", phase=PHASE_OUTLINE, text=f"LLM planner enabled with model: {settings.llm_model}.")
        try:
            raw = _build_with_llm(llm, prompt, topic, slide_count, research)
            deck = normalize_deck(raw, prompt, topic, slide_count, research)
            yield make_event("log", phase=PHASE_OUTLINE, text="LLM returned a valid slide plan.")
        except Exception as exc:  # noqa: BLE001
            yield make_event(
                "log",
                phase=PHASE_OUTLINE,
                text=f"LLM planning failed; using deterministic planner. Reason: {exc}",
            )
    else:
        yield make_event("log", phase=PHASE_OUTLINE, text="LLM planner not configured. Using deterministic planner.")

    if deck is None:
        family = detect_family(prompt)
        yield make_event(
            "log",
            phase=PHASE_OUTLINE,
            text=f"Topic family detected: {family.name} ({family.label}).",
        )
        outline_deck = build_outline(prompt, topic, slide_count, research)
        yield make_event(
            "log",
            phase=PHASE_OUTLINE,
            text=f"Outline built from research: {len(outline_deck['slides'])} slide(s).",
        )
        deck = normalize_deck(outline_deck, prompt, topic, slide_count, research)

    deck["theme"] = resolved_theme

    sources = research.get("sources") or []
    for slide in deck["slides"]:
        existing = slide.get("citations")
        if isinstance(existing, list) and existing:
            slide["citations"] = [str(item) for item in existing if item]
        else:
            slide["citations"] = cite_slide(slide, sources)

    # Phase 8 optimize pass: critique variety, rotate recipes if too uniform.
    score_before = variety_score([s.get("blocks") or [] for s in deck["slides"]])
    changed, score_after = optimize_deck_variety(deck, research, topic_seed=topic)
    yield make_event(
        "log",
        phase=PHASE_OUTLINE,
        text=(
            f"Variety score: {score_before:.2f}"
            + (f" → {score_after:.2f} after optimize" if changed else " (no optimize needed)")
        ),
    )

    yield make_event(
        "deck_meta",
        phase=PHASE_OUTLINE,
        title=deck["title"],
        subtitle=deck.get("subtitle", ""),
        slide_count=deck["slide_count"],
        topic=deck.get("topic", topic),
        theme=resolved_theme,
    )
    for slide in deck["slides"]:
        yield make_event(
            "slide_outline",
            phase=PHASE_OUTLINE,
            number=slide["number"],
            title=slide["title"],
            subtitle=slide.get("subtitle", ""),
            eyebrow=slide.get("eyebrow", ""),
            layout=slide.get("layout", "solution"),
        )
    yield make_event("phase_end", id=PHASE_OUTLINE)

    yield make_event("phase_start", id=PHASE_CONTENT, label="Write slide content")
    for slide in deck["slides"]:
        yield make_event("slide_detail", phase=PHASE_CONTENT, number=slide["number"], slide=slide)
        if slide.get("citations"):
            yield make_event(
                "slide_citation",
                phase=PHASE_CONTENT,
                number=slide["number"],
                source_ids=list(slide["citations"]),
            )
    yield make_event("phase_end", id=PHASE_CONTENT, result=deck)


def _build_with_llm(
    llm: LLMClient,
    prompt: str,
    topic: str,
    slide_count: int,
    research: dict[str, Any],
) -> dict[str, Any]:
    system = (
        "You are a senior presentation strategist. Return only JSON. "
        "Create investor-grade slide plans that can be rendered as HTML and PPTX."
    )
    user = json.dumps(
        {
            "task": prompt,
            "topic": topic,
            "slide_count": slide_count,
            "research": {
                "sources": research.get("sources", []),
                "insights": research.get("insights", []),
            },
            "required_schema": {
                "title": "string",
                "subtitle": "string",
                "audience": "string",
                "slides": [
                    {
                        "title": "string",
                        "subtitle": "string",
                        "layout": "cover|problem|solution|metrics|market|architecture|comparison|roadmap|team|ask|closing",
                        "eyebrow": "string",
                        "bullets": ["3 to 5 concise bullets"],
                        "metrics": [{"label": "string", "value": "string"}],
                        "speaker_notes": "string",
                        "citations": ["S1", "S2"],
                    }
                ],
            },
            "rules": [
                "Return exactly slide_count slides.",
                "No markdown fences.",
                "Use concrete but clearly assumptive metrics if the prompt lacks company data.",
                "Use source-aware language without fake citations.",
                "For each slide, include a citations array listing source_id values (e.g. \"S1\", \"S3\") whose snippet/excerpt actually supports the slide's claims. Empty array if no source applies.",
            ],
        },
        ensure_ascii=False,
    )
    result = llm.complete_json(system, user)
    if not result:
        raise RuntimeError("empty LLM result")
    return result


def _fallback_deck(prompt: str, topic: str, slide_count: int, research: dict[str, Any]) -> dict[str, Any]:
    title = _title_for_topic(topic)
    subtitle = _subtitle_for_topic(topic)
    points = _research_points(research)
    primary_point = _point(
        points,
        0,
        f"Use the user prompt and live research to explain {topic} with concrete evidence.",
    )
    problem_point = _point(
        points,
        1,
        "The strongest narrative separates current-state context, stakeholder pain, and the opportunity to improve outcomes.",
    )
    timing_point = _point(
        points,
        2,
        "Policy shifts, buyer expectations, technology readiness, and service gaps should be connected to a clear why-now argument.",
    )

    templates = [
        {
            "layout": "cover",
            "eyebrow": "Research Deck",
            "title": title,
            "subtitle": subtitle,
            "bullets": [
                primary_point,
                "Built from live SearXNG research and source snippets.",
                "Organized for an investor or decision-maker discussion.",
            ],
            "metrics": [{"label": "Deck", "value": f"{slide_count} slides"}],
        },
        {
            "layout": "market",
            "eyebrow": "Landscape",
            "title": f"Current State Of {title}",
            "subtitle": primary_point,
            "bullets": [
                _point(points, 1, "Identify the main delivery channels, buyers, users, and service constraints."),
                _point(points, 2, "Separate national context from the first beachhead or target segment."),
                "Use source-backed facts before making market or product claims.",
            ],
            "metrics": [{"label": "Focus", "value": "Current state"}, {"label": "Evidence", "value": "Live sources"}],
        },
        {
            "layout": "problem",
            "eyebrow": "Problem",
            "title": "The Gap Is Specific, Not Generic",
            "subtitle": problem_point,
            "bullets": [
                _point(points, 3, "Call out the highest-friction problem for users or institutions."),
                "Show who feels the pain, how often it happens, and what it costs.",
                "Avoid broad sector descriptions unless they connect to an urgent decision.",
            ],
            "metrics": [{"label": "Pain", "value": "Defined"}, {"label": "Impact", "value": "Measurable"}],
        },
        {
            "layout": "solution",
            "eyebrow": "Stakeholders",
            "title": "The Stakeholder Map Shapes The Opportunity",
            "subtitle": "A strong deck names the people, institutions, and budgets involved in the decision.",
            "bullets": [
                "Clarify the primary user, economic buyer, implementation owner, and regulator.",
                _point(points, 4, "Use research to distinguish public, private, and partnership roles."),
                "Translate stakeholder incentives into adoption requirements.",
            ],
            "metrics": [{"label": "Users", "value": "Named"}, {"label": "Buyer", "value": "Defined"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Why Now",
            "title": "The Timing Needs A Clear Trigger",
            "subtitle": timing_point,
            "bullets": [
                "Connect current data points to a change in urgency or willingness to adopt.",
                "Explain why the opportunity is better now than it was one or two years ago.",
                _point(points, 5, "Use source evidence for policy, market, funding, or technology shifts."),
            ],
            "metrics": [{"label": "Timing", "value": "Now"}, {"label": "Trigger", "value": "Evidence"}],
        },
        {
            "layout": "solution",
            "eyebrow": "Opportunity",
            "title": "A Focused Opportunity Beats A Broad Sector Claim",
            "subtitle": "Start with the segment where the pain, budget, and ability to implement overlap.",
            "bullets": [
                "Define the beachhead use case and the measurable outcome it improves.",
                "Explain why this target segment can adopt faster than the whole market.",
                "Use the broader landscape as expansion logic, not as the whole thesis.",
            ],
            "metrics": [{"label": "Beachhead", "value": "Focused"}, {"label": "Expansion", "value": "Planned"}],
        },
        {
            "layout": "market",
            "eyebrow": "Evidence",
            "title": "What The Research Says",
            "subtitle": _point(points, 6, "The source list should drive the claims, not decorate a finished deck."),
            "bullets": [
                _point(points, 0, "Use the strongest source finding as the first proof point."),
                _point(points, 1, "Use the second source finding to validate the problem or market."),
                _point(points, 2, "Use the third source finding to shape positioning or timing."),
            ],
            "metrics": [{"label": "Sources", "value": str(len(research.get("sources", [])))}, {"label": "Claims", "value": "Grounded"}],
        },
        {
            "layout": "solution",
            "eyebrow": "Market",
            "title": "Market Logic And Adoption Path",
            "subtitle": "The deck should show how the first use case can become a larger platform or service business.",
            "bullets": [
                "Describe TAM, SAM, and the initial reachable segment separately.",
                "Show the adoption path by customer type, geography, channel, or workflow.",
                "Tie growth to repeat usage, partnerships, distribution, or regulatory readiness.",
            ],
            "metrics": [{"label": "Segment", "value": "Specific"}, {"label": "Path", "value": "Sequenced"}],
        },
        {
            "layout": "comparison",
            "eyebrow": "Differentiation",
            "title": "Positioning Must Be Defensible",
            "subtitle": "Differentiation should compare against the real alternatives visible in the market.",
            "bullets": [
                "Name direct competitors, substitutes, and the status quo.",
                "Explain what is meaningfully better: access, quality, cost, speed, trust, or integration.",
                "Show why the advantage can compound over time.",
            ],
            "metrics": [{"label": "Alternatives", "value": "Compared"}, {"label": "Advantage", "value": "Clear"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Model",
            "title": "Business Model And Unit Economics",
            "subtitle": "The revenue logic should match how the buyer already pays for outcomes or services.",
            "bullets": [
                "Define who pays, when they pay, and what value metric pricing follows.",
                "Separate recurring revenue, implementation fees, services, and partnership revenue.",
                "List the assumptions that need validation in pilots.",
            ],
            "metrics": [{"label": "Buyer", "value": "Known"}, {"label": "Pricing", "value": "Testable"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Proof",
            "title": "Traction And Validation Plan",
            "subtitle": "Use real company evidence when available; otherwise show the exact validation plan.",
            "bullets": [
                "Summarize pilots, LOIs, partnerships, usage, revenue, or expert validation.",
                "Define the next three proof points needed to reduce investor risk.",
                "Connect traction metrics directly to the problem and buyer budget.",
            ],
            "metrics": [{"label": "Proof", "value": "Needed"}, {"label": "Risk", "value": "Reducing"}],
        },
        {
            "layout": "roadmap",
            "eyebrow": "Execution",
            "title": "Roadmap From Insight To Adoption",
            "subtitle": "The roadmap should move from research-backed wedge to repeatable execution.",
            "bullets": [
                "Phase 1: validate the highest-risk assumptions with the first target users.",
                "Phase 2: build repeatable delivery, partnerships, and measurement.",
                "Phase 3: expand across adjacent segments once the wedge is proven.",
            ],
            "metrics": [{"label": "Horizon", "value": "12 months"}],
        },
        {
            "layout": "comparison",
            "eyebrow": "Risks",
            "title": "Risks And Mitigations",
            "subtitle": "Credible decks name adoption blockers before investors do.",
            "bullets": [
                "Adoption risk: prove workflow fit with a narrow initial segment.",
                "Execution risk: define owner, timeline, partner dependency, and success metric.",
                "Policy or trust risk: show compliance, governance, and stakeholder buy-in plan.",
            ],
            "metrics": [{"label": "Risks", "value": "Named"}, {"label": "Plan", "value": "Mitigated"}],
        },
        {
            "layout": "ask",
            "eyebrow": "The Ask",
            "title": "The Ask Should Match The Next Milestone",
            "subtitle": "Close with the capital, partnership, or decision needed to prove the opportunity.",
            "bullets": [
                "Specify the funding amount or decision requested.",
                "Tie use of funds to product, operations, distribution, and validation milestones.",
                "Define what success looks like at the next financing or decision point.",
            ],
            "metrics": [{"label": "Ask", "value": "Specific"}, {"label": "Milestone", "value": "Next"}],
        },
        {
            "layout": "closing",
            "eyebrow": "Close",
            "title": f"{title}: From Research To Action",
            "subtitle": "The opportunity is strongest when evidence, focus, and execution plan reinforce each other.",
            "bullets": [
                "Lead with the clearest evidence from the research.",
                "Focus the next step on one measurable decision or pilot.",
                "Use updated source data before presenting externally.",
            ],
            "metrics": [{"label": "Next step", "value": "Decision"}],
        },
    ]

    slides = templates[:slide_count]
    if slide_count < len(templates) and slides:
        slides[-1] = templates[-1]
    while len(slides) < slide_count:
        index = len(slides) + 1
        slides.append(
            {
                "layout": "solution",
                "eyebrow": f"Appendix {index - len(templates)}",
                "title": f"Additional Proof Point {index}",
                "subtitle": "Use this slide for customer evidence, financial detail, or a product screenshot.",
                "bullets": [
                    "Add the strongest supporting evidence for the investor conversation.",
                    "Keep the slide focused on one decision-driving message.",
                    "Use metrics, screenshots, or customer language where possible.",
                ],
                "metrics": [{"label": "Proof", "value": str(index)}],
            }
        )

    return {
        "title": f"{title} Pitch Deck",
        "subtitle": subtitle,
        "audience": "Investors, operators, and decision-makers",
        "topic": topic,
        "prompt": prompt,
        "slides": slides,
    }


def _research_points(research: dict[str, Any]) -> list[str]:
    points: list[str] = []
    for insight in research.get("insights", []):
        _append_point(points, insight)
    for source in research.get("sources", []):
        if not isinstance(source, dict):
            continue
        for key in ("excerpt", "snippet"):
            _append_point(points, source.get(key, ""))
            if len(points) >= 10:
                return points
    return points


def _append_point(points: list[str], value: Any) -> None:
    text = _compact_text(str(value or ""))
    if not text:
        return
    if text not in points:
        points.append(text)


def _point(points: list[str], index: int, fallback: str) -> str:
    if index < len(points):
        return points[index]
    return fallback


def _compact_text(value: str, limit: int = 190) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"\bMissing:.*$", "", text).strip()
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip(" ,;:-") + "."


def normalize_deck(
    deck: dict[str, Any],
    prompt: str,
    topic: str,
    slide_count: int,
    research: dict[str, Any],
) -> dict[str, Any]:
    title = str(deck.get("title") or f"{_title_for_topic(topic)} Pitch Deck")
    subtitle = str(deck.get("subtitle") or _subtitle_for_topic(topic))
    raw_slides = deck.get("slides") or []
    slides: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_slides[:slide_count], start=1):
        if not isinstance(raw, dict):
            continue
        bullets = raw.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        metrics = raw.get("metrics") or []
        if not isinstance(metrics, list):
            metrics = []
        raw_citations = raw.get("citations") or raw.get("source_refs") or []
        if isinstance(raw_citations, (list, tuple)):
            citations = [str(item) for item in raw_citations if item]
        else:
            citations = []
        cleaned_bullets = scrub_bullets([str(item) for item in bullets[:8]])[:5]
        slide_dict = {
            "number": index,
            "id": f"slide-{index}",
            "layout": str(raw.get("layout") or _layout_for_index(index, slide_count)),
            "eyebrow": str(raw.get("eyebrow") or f"Slide {index}"),
            "title": scrub_paragraph(str(raw.get("title") or f"Slide {index}")),
            "subtitle": scrub_paragraph(str(raw.get("subtitle") or "")),
            "bullets": cleaned_bullets,
            "metrics": [_normalize_metric(item) for item in metrics[:4]],
            "speaker_notes": str(raw.get("speaker_notes") or raw.get("notes") or ""),
            "citations": citations,
            "accent_variant": int(raw.get("accent_variant") if raw.get("accent_variant") is not None else (index - 1) % 4),
        }
        raw_blocks = raw.get("blocks")
        if isinstance(raw_blocks, list) and raw_blocks:
            slide_dict["blocks"] = normalize_blocks(index, raw_blocks)
        else:
            # Phase 8: dynamic composition for slide variety.
            slide_dict["blocks"] = compose_slide_blocks(
                slide_dict,
                position=index - 1,
                total=slide_count,
                research=research,
                topic_seed=topic,
            )
        slides.append(slide_dict)

    if len(slides) < slide_count:
        fallback = build_outline(prompt, topic, slide_count, research)
        for raw in fallback["slides"][len(slides) : slide_count]:
            index = len(slides) + 1
            slide_dict = {
                "number": index,
                "id": f"slide-{index}",
                "layout": raw["layout"],
                "eyebrow": raw["eyebrow"],
                "title": raw["title"],
                "subtitle": raw["subtitle"],
                "bullets": raw["bullets"],
                "metrics": raw["metrics"],
                "speaker_notes": "",
                "citations": [],
                "accent_variant": (index - 1) % 4,
            }
            slide_dict["blocks"] = compose_slide_blocks(
                slide_dict,
                position=index - 1,
                total=slide_count,
                research=research,
                topic_seed=topic,
            )
            slides.append(slide_dict)

    theme_name = get_theme(str(deck.get("theme") or DEFAULT_THEME)).name
    return {
        "title": title,
        "subtitle": subtitle,
        "topic": topic,
        "slug": slugify(title),
        "audience": str(deck.get("audience") or "Investors"),
        "prompt": prompt,
        "slide_count": slide_count,
        "theme": theme_name,
        "family": str(deck.get("family") or ""),
        "research": research,
        "slides": slides,
    }


def deck_structure_text(deck: dict[str, Any]) -> str:
    lines = [f"{deck['title']} Structure ({deck['slide_count']} Slides):"]
    for slide in deck["slides"]:
        label = slide.get("eyebrow") or slide.get("layout", "Slide").title()
        description = (slide["subtitle"] or label).rstrip(".")
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
                lines.append(f"- {metric['label']}: {metric['value']}")
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


def _normalize_metric(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        return {
            "label": str(item.get("label") or item.get("name") or "Metric"),
            "value": str(item.get("value") or item.get("amount") or ""),
        }
    return {"label": "Metric", "value": str(item)}


def _layout_for_index(index: int, slide_count: int) -> str:
    if index == 1:
        return "cover"
    if index == slide_count:
        return "closing"
    return "solution"


def _title_for_topic(topic: str) -> str:
    words = topic.strip()
    if not words:
        return "Research Opportunity"
    if "ai" in words.lower() and "platform" in words.lower():
        return "NextGen AI Platform"
    return words.title()


def _subtitle_for_topic(topic: str) -> str:
    if "ai" in topic.lower():
        return "Revolutionizing enterprise decision-making with scalable intelligence"
    return "Turning live research into an investor-ready growth story"
