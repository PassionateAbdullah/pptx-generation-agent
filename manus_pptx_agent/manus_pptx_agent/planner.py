from __future__ import annotations

import json
import re
from typing import Any

from .config import Settings
from .llm import LLMClient
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


def build_deck(prompt: str, slide_count: int, research: dict[str, Any], settings: Settings) -> tuple[dict[str, Any], list[str]]:
    logs: list[str] = []
    topic = extract_topic(prompt)
    llm = LLMClient(settings)
    if llm.enabled:
        logs.append(f"LLM planner enabled with model: {settings.llm_model}.")
        try:
            deck = _build_with_llm(llm, prompt, topic, slide_count, research)
            normalized = normalize_deck(deck, prompt, topic, slide_count, research)
            logs.append("LLM returned a valid slide plan.")
            return normalized, logs
        except Exception as exc:  # noqa: BLE001
            logs.append(f"LLM planning failed; using deterministic planner. Reason: {exc}")
    else:
        logs.append("LLM planner not configured. Using deterministic planner.")

    deck = _fallback_deck(prompt, topic, slide_count, research)
    return normalize_deck(deck, prompt, topic, slide_count, research), logs


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
                    }
                ],
            },
            "rules": [
                "Return exactly slide_count slides.",
                "No markdown fences.",
                "Use concrete but clearly assumptive metrics if the prompt lacks company data.",
                "Use source-aware language without fake citations.",
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
    insights = research.get("insights", [])
    market_hint = "Enterprise AI adoption is accelerating, but buyers need security, measurable ROI, and workflow fit."
    if insights:
        market_hint = insights[min(2, len(insights) - 1)]

    templates = [
        {
            "layout": "cover",
            "eyebrow": "Investor Pitch",
            "title": title,
            "subtitle": subtitle,
            "bullets": ["Research-backed pitch narrative", "HTML preview first", "PPTX export on demand"],
            "metrics": [{"label": "Deck", "value": f"{slide_count} slides"}],
        },
        {
            "layout": "problem",
            "eyebrow": "Problem",
            "title": "Enterprise Decisions Are Slowed By Fragmented Data",
            "subtitle": "Teams have more information than ever, but less confidence in what to do next.",
            "bullets": [
                "Critical knowledge is split across documents, apps, tickets, calls, and dashboards.",
                "Manual analysis creates slow cycles, inconsistent answers, and expensive handoffs.",
                "Generic AI tools lack business context, controls, and repeatable workflow ownership.",
            ],
            "metrics": [{"label": "Utilized data", "value": "<20%"}, {"label": "Manual effort", "value": "High"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Why Now",
            "title": "The Timing Has Shifted From AI Experiments To AI Operations",
            "subtitle": market_hint,
            "bullets": [
                "LLMs are strong enough for knowledge work, but enterprise adoption needs orchestration.",
                "Companies are moving from isolated copilots to governed, auditable AI workflows.",
                "Infrastructure cost pressure makes routing, caching, and retrieval quality strategic.",
            ],
            "metrics": [{"label": "Buyer priority", "value": "ROI"}, {"label": "Blocker", "value": "Trust"}],
        },
        {
            "layout": "solution",
            "eyebrow": "Solution",
            "title": f"{title} Turns Company Knowledge Into Action",
            "subtitle": "A secure AI platform that connects data, reasons over context, and delivers workflow-ready outputs.",
            "bullets": [
                "Connects to existing data sources and normalizes them into a governed knowledge layer.",
                "Routes tasks across retrieval, agents, tools, and models based on risk and complexity.",
                "Produces cited answers, automations, dashboards, and presentation-ready deliverables.",
            ],
            "metrics": [{"label": "Setup", "value": "Days"}, {"label": "Outputs", "value": "Multi-format"}],
        },
        {
            "layout": "architecture",
            "eyebrow": "Product",
            "title": "A Modular Platform Built For Enterprise Workflows",
            "subtitle": "Each layer can improve independently while keeping governance centralized.",
            "bullets": [
                "Data connectors ingest documents, apps, databases, and collaboration history.",
                "Retrieval and memory services keep answers grounded in approved company context.",
                "Agent orchestration executes multi-step tasks with human review where needed.",
                "Analytics show cost, quality, usage, risk, and business impact.",
            ],
            "metrics": [{"label": "Layers", "value": "4"}, {"label": "Control", "value": "Central"}],
        },
        {
            "layout": "architecture",
            "eyebrow": "How It Works",
            "title": "From Prompt To Verified Output",
            "subtitle": "The workflow mirrors the Manus-style process: research, plan, render, then export.",
            "bullets": [
                "Research: collect market, customer, and competitive context.",
                "Plan: turn findings into a slide-by-slide narrative.",
                "Generate: produce HTML slides for fast visual review.",
                "Export: convert the approved structure into a PowerPoint file.",
            ],
            "metrics": [{"label": "Workflow", "value": "4 steps"}],
        },
        {
            "layout": "market",
            "eyebrow": "Market",
            "title": "Large Market, Clear Beachhead",
            "subtitle": "Start with high-value enterprise knowledge workflows, then expand across functions.",
            "bullets": [
                "TAM: broad enterprise AI software and automation spend.",
                "SAM: mid-market and enterprise teams with complex knowledge operations.",
                "SOM: regulated teams where security, auditability, and accuracy drive willingness to pay.",
            ],
            "metrics": [{"label": "TAM", "value": "$150B+"}, {"label": "Beachhead", "value": "Ops + Analytics"}],
        },
        {
            "layout": "solution",
            "eyebrow": "Use Cases",
            "title": "High-Frequency Workflows Create Expansion",
            "subtitle": "The platform starts with urgent jobs and grows into the operating layer for decisions.",
            "bullets": [
                "Executive briefings and board materials generated from live company context.",
                "Sales and support copilots that answer with policy-aware knowledge.",
                "Research, diligence, and market monitoring workflows for strategy teams.",
                "Compliance review and evidence packaging for regulated operations.",
            ],
            "metrics": [{"label": "Initial wedges", "value": "4"}],
        },
        {
            "layout": "comparison",
            "eyebrow": "Differentiation",
            "title": "More Than A Generic LLM Wrapper",
            "subtitle": "The moat is workflow ownership, proprietary context, quality feedback, and governance.",
            "bullets": [
                "Context graph maps business entities, permissions, workflows, and decision history.",
                "Model routing balances quality, latency, privacy, and cost per task.",
                "Evaluation loops turn usage and human review into compounding quality improvements.",
            ],
            "metrics": [{"label": "Accuracy lift", "value": "+20%"}, {"label": "TCO reduction", "value": "30-40%"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Business Model",
            "title": "Subscription Revenue With Usage Expansion",
            "subtitle": "Pricing aligns with seats, workflows, data volume, and premium automation.",
            "bullets": [
                "Team tier for departmental pilots and proof-of-value work.",
                "Enterprise tier for security controls, integrations, admin, and analytics.",
                "Usage-based add-ons for high-volume agents, retrieval, and generation.",
                "Services accelerate onboarding without becoming the core revenue engine.",
            ],
            "metrics": [{"label": "Gross margin target", "value": "75%+"}, {"label": "Expansion", "value": "Usage"}],
        },
        {
            "layout": "metrics",
            "eyebrow": "Traction",
            "title": "Early Signals Show Pull From Enterprise Teams",
            "subtitle": "Use real company data here when available; these placeholders show the target evidence type.",
            "bullets": [
                "Pilot customers use the platform weekly for research, reporting, and decision support.",
                "Time-to-output improves as reusable workflows and knowledge bases compound.",
                "Pipeline is concentrated in teams with measurable pain and budget ownership.",
            ],
            "metrics": [{"label": "Pilot target", "value": "15"}, {"label": "ARR target", "value": "$500K"}],
        },
        {
            "layout": "roadmap",
            "eyebrow": "Roadmap",
            "title": "Focused Roadmap To Scale Quality And Distribution",
            "subtitle": "The next phase deepens integrations, governance, and repeatable vertical workflows.",
            "bullets": [
                "Quarter 1: self-serve workspace setup, core connectors, and evaluation dashboards.",
                "Quarter 2: workflow templates for finance, healthcare, legal, and operations teams.",
                "Quarter 3: admin controls, marketplace connectors, and partner implementation kits.",
            ],
            "metrics": [{"label": "Horizon", "value": "12 months"}],
        },
        {
            "layout": "team",
            "eyebrow": "Team",
            "title": "Built By AI, Infrastructure, And Enterprise Operators",
            "subtitle": "The right team combines model expertise with the patience to solve enterprise deployment.",
            "bullets": [
                "CEO: AI product leader with enterprise workflow experience.",
                "CTO: retrieval, platform, and distributed systems background.",
                "GTM Lead: sold data and automation platforms into regulated teams.",
                "Advisors: security, vertical workflow, and AI evaluation experts.",
            ],
            "metrics": [{"label": "Core functions", "value": "AI + GTM"}],
        },
        {
            "layout": "ask",
            "eyebrow": "The Ask",
            "title": "Seeking Seed Capital To Turn Pull Into Repeatable Growth",
            "subtitle": "Funding accelerates product maturity, enterprise readiness, and go-to-market learning.",
            "bullets": [
                "40% product and engineering: workflow builder, evaluation, integrations.",
                "35% sales and marketing: founder-led sales, vertical playbooks, partner channel.",
                "25% infrastructure and security: scale, observability, compliance readiness.",
            ],
            "metrics": [{"label": "Raise", "value": "$5M"}, {"label": "Runway", "value": "18 months"}],
        },
        {
            "layout": "closing",
            "eyebrow": "Close",
            "title": "The Operating Layer For AI-Driven Enterprises",
            "subtitle": "Join us in turning scattered company knowledge into secure, measurable execution.",
            "bullets": [
                "Next step: pilot the highest-value workflow with one enterprise team.",
                "Contact: founders@example.com",
                "Website: nextgen-ai.example",
            ],
            "metrics": [{"label": "Next step", "value": "Pilot"}],
        },
    ]

    slides = templates[:slide_count]
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
        "audience": "Investors and enterprise buyers",
        "topic": topic,
        "prompt": prompt,
        "slides": slides,
    }


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
        slides.append(
            {
                "number": index,
                "id": f"slide-{index}",
                "layout": str(raw.get("layout") or _layout_for_index(index, slide_count)),
                "eyebrow": str(raw.get("eyebrow") or f"Slide {index}"),
                "title": str(raw.get("title") or f"Slide {index}"),
                "subtitle": str(raw.get("subtitle") or ""),
                "bullets": [str(item) for item in bullets[:5]],
                "metrics": [_normalize_metric(item) for item in metrics[:4]],
                "speaker_notes": str(raw.get("speaker_notes") or raw.get("notes") or ""),
            }
        )

    if len(slides) < slide_count:
        fallback = _fallback_deck(prompt, topic, slide_count, research)
        for raw in fallback["slides"][len(slides) : slide_count]:
            index = len(slides) + 1
            slides.append(
                {
                    "number": index,
                    "id": f"slide-{index}",
                    "layout": raw["layout"],
                    "eyebrow": raw["eyebrow"],
                    "title": raw["title"],
                    "subtitle": raw["subtitle"],
                    "bullets": raw["bullets"],
                    "metrics": raw["metrics"],
                    "speaker_notes": "",
                }
            )

    return {
        "title": title,
        "subtitle": subtitle,
        "topic": topic,
        "slug": slugify(title),
        "audience": str(deck.get("audience") or "Investors"),
        "prompt": prompt,
        "slide_count": slide_count,
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
        return "NextGen AI Platform"
    if "ai" in words.lower() and "platform" in words.lower():
        return "NextGen AI Platform"
    return "NextGen " + words.title()


def _subtitle_for_topic(topic: str) -> str:
    if "ai" in topic.lower():
        return "Revolutionizing enterprise decision-making with scalable intelligence"
    return "Turning market insight into an investor-ready growth story"
