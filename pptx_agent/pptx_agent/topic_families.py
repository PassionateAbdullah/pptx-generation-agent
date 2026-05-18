"""Topic family registry.

A **topic family** is a recognisable deck shape (pitch deck, research
briefing, market analysis, case study, product overview). Each family has
a checklist of **slide roles** rather than fixed titles. The dynamic
outline builder walks the checklist, picks the role's theme keywords,
mines the research for claims matching those keywords, and synthesizes
the slide title + body from real findings.

This lets two prompts in the same family produce decks with the same
*structure* but topic-specific *content*. And two prompts in different
families produce structurally different decks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlideRole:
    """One slide slot in a family's checklist.

    - ``role``: short id (``cover``, ``problem``, ``solution``, …).
    - ``layout``: layout key consumed by html_renderer + pptx_writer.
    - ``title_template``: template w/ optional ``{topic}`` / ``{primary_keyword}``
      placeholders. Used only when the claim miner cannot produce a more
      specific title from research.
    - ``theme_keywords``: lowercase tokens that gate which claims feed this
      slide. Empty list = "any claim is welcome".
    - ``eyebrow``: short label above the title.
    - ``min_claims``/``max_claims``: how many bullets to emit.
    - ``prefer_chart``: when True the outliner tries to attach a chart block
      built from the slide's numeric claims.
    - ``required``: skip the slide if no claim matches AND not required.
    """
    role: str
    layout: str
    title_template: str
    theme_keywords: list[str]
    eyebrow: str = ""
    min_claims: int = 2
    max_claims: int = 4
    prefer_chart: bool = False
    required: bool = True


@dataclass
class TopicFamily:
    name: str
    label: str
    triggers: list[str]
    checklist: list[SlideRole]
    description: str = ""
    closing_blurb: str = ""


_PITCH_DECK = TopicFamily(
    name="pitch_deck",
    label="Investor / Pitch Deck",
    triggers=[
        "pitch", "investor", "fundraise", "fundraising", "seed", "series a",
        "series b", "series c", "raise", "round", "vc", "venture",
    ],
    description="Structured around problem → solution → market → traction → ask.",
    closing_blurb="Next step: schedule a follow-up to walk through pilots.",
    checklist=[
        SlideRole("cover", "cover", "{topic}",
                  theme_keywords=[], eyebrow="Investor Pitch", min_claims=0, max_claims=2),
        SlideRole("problem", "problem", "The {primary_keyword} problem",
                  theme_keywords=["problem", "gap", "challenge", "pain", "issue", "lack", "shortage", "broken", "manual", "fragmented", "slow"],
                  eyebrow="Problem"),
        SlideRole("solution", "solution", "How {topic} solves it",
                  theme_keywords=["solution", "platform", "product", "automates", "delivers", "enables", "powered", "ai", "ml", "saas"],
                  eyebrow="Solution"),
        SlideRole("technology", "architecture", "Built on {primary_keyword}",
                  theme_keywords=["architecture", "stack", "engine", "model", "infrastructure", "rag", "vector", "llm", "pipeline", "tech"],
                  eyebrow="Technology", required=False),
        SlideRole("market", "market", "Market opportunity",
                  theme_keywords=["market", "tam", "sam", "som", "growth", "cagr", "segment", "demand", "spend", "industry", "billion", "trillion"],
                  eyebrow="Market", prefer_chart=True),
        SlideRole("competition", "comparison", "Competitive edge",
                  theme_keywords=["competitor", "compared", "vs", "edge", "advantage", "moat", "faster", "cheaper", "outperform", "differentiator"],
                  eyebrow="Competition"),
        SlideRole("business_model", "metrics", "Business model",
                  theme_keywords=["pricing", "subscription", "saas", "tier", "revenue", "model", "license", "fee", "contract", "arr", "mrr"],
                  eyebrow="Model"),
        SlideRole("traction", "metrics", "Traction so far",
                  theme_keywords=["arr", "mrr", "pilot", "customer", "user", "growth", "retention", "deployed", "deal", "logos", "fortune"],
                  eyebrow="Traction", prefer_chart=True),
        SlideRole("team", "team", "The team",
                  theme_keywords=["founder", "ceo", "cto", "former", "previously", "led", "phd", "alumni", "advisor"],
                  eyebrow="Team", required=False),
        SlideRole("ask", "ask", "The ask",
                  theme_keywords=["raise", "seed", "round", "seeking", "funding", "use", "allocate", "runway"],
                  eyebrow="Ask"),
        SlideRole("closing", "closing", "Building the next chapter",
                  theme_keywords=[], eyebrow="Close", min_claims=0, max_claims=2, required=False),
    ],
)


_RESEARCH_BRIEFING = TopicFamily(
    name="research_briefing",
    label="Research Briefing",
    triggers=[
        "research", "briefing", "report", "analysis", "deep dive", "study",
        "overview of", "primer", "explainer",
    ],
    description="Structured around landscape → key findings → stakeholders → opportunity → risks.",
    closing_blurb="Recommended next step: deeper investigation on highest-uncertainty findings.",
    checklist=[
        SlideRole("cover", "cover", "{topic}",
                  theme_keywords=[], eyebrow="Research Briefing", min_claims=0, max_claims=2),
        SlideRole("context", "market", "{topic} today",
                  theme_keywords=["overview", "current", "state", "today", "context", "history", "background", "system", "structure"],
                  eyebrow="Context"),
        SlideRole("findings", "metrics", "Key findings",
                  theme_keywords=["finding", "data", "statistic", "shows", "indicates", "found", "rate", "level", "share"],
                  eyebrow="Findings", prefer_chart=True),
        SlideRole("stakeholders", "team", "Stakeholder map",
                  theme_keywords=["stakeholder", "government", "ministry", "agency", "ngo", "public", "private", "user", "buyer", "regulator"],
                  eyebrow="Stakeholders", required=False),
        SlideRole("drivers", "solution", "What drives change",
                  theme_keywords=["driver", "policy", "regulation", "technology", "investment", "funding", "shift", "trend", "reform"],
                  eyebrow="Drivers"),
        SlideRole("opportunity", "solution", "Where the opportunity sits",
                  theme_keywords=["opportunity", "potential", "addressable", "gap", "untapped", "underserved", "expansion"],
                  eyebrow="Opportunity"),
        SlideRole("evidence", "market", "What the data says",
                  theme_keywords=["data", "evidence", "study", "research", "found", "showed", "according"],
                  eyebrow="Evidence", prefer_chart=True, required=False),
        SlideRole("risks", "comparison", "Risks and constraints",
                  theme_keywords=["risk", "constraint", "challenge", "concern", "limit", "regulation", "compliance", "blocker"],
                  eyebrow="Risks"),
        SlideRole("recommendations", "ask", "Recommendations",
                  theme_keywords=["recommend", "should", "next step", "action", "priority", "plan", "roadmap"],
                  eyebrow="Recommendations"),
        SlideRole("closing", "closing", "Bottom line",
                  theme_keywords=[], eyebrow="Close", min_claims=0, max_claims=2, required=False),
    ],
)


_MARKET_ANALYSIS = TopicFamily(
    name="market_analysis",
    label="Market Analysis",
    triggers=["market", "industry", "sector", "size", "tam", "growth", "competitive landscape"],
    description="Structured around sizing → segments → players → trends → outlook.",
    closing_blurb="Bottom line: act on the segment with the highest growth and lowest competitive density.",
    checklist=[
        SlideRole("cover", "cover", "{topic} — Market Analysis",
                  theme_keywords=[], eyebrow="Market Analysis", min_claims=0, max_claims=2),
        SlideRole("sizing", "market", "Market size",
                  theme_keywords=["tam", "sam", "som", "size", "value", "billion", "trillion", "spend", "addressable"],
                  eyebrow="Sizing", prefer_chart=True),
        SlideRole("growth", "metrics", "Growth dynamics",
                  theme_keywords=["growth", "cagr", "compound", "expanding", "trend", "rising", "accelerating"],
                  eyebrow="Growth", prefer_chart=True),
        SlideRole("segments", "comparison", "Segments",
                  theme_keywords=["segment", "vertical", "category", "tier", "niche", "consumer", "enterprise"],
                  eyebrow="Segments"),
        SlideRole("players", "team", "Players",
                  theme_keywords=["company", "competitor", "incumbent", "challenger", "leader", "startup", "vendor"],
                  eyebrow="Players"),
        SlideRole("drivers", "solution", "Drivers",
                  theme_keywords=["driver", "tailwind", "headwind", "policy", "technology", "behavior"],
                  eyebrow="Drivers"),
        SlideRole("opportunity", "solution", "Opportunity",
                  theme_keywords=["opportunity", "untapped", "underserved", "gap", "whitespace"],
                  eyebrow="Opportunity"),
        SlideRole("risks", "comparison", "Risks",
                  theme_keywords=["risk", "regulation", "consolidation", "saturation", "barrier"],
                  eyebrow="Risks"),
        SlideRole("outlook", "roadmap", "Outlook",
                  theme_keywords=["outlook", "forecast", "projection", "year", "horizon"],
                  eyebrow="Outlook"),
        SlideRole("closing", "closing", "Recommendations",
                  theme_keywords=[], eyebrow="Close", min_claims=0, max_claims=2, required=False),
    ],
)


_CASE_STUDY = TopicFamily(
    name="case_study",
    label="Case Study",
    triggers=["case study", "success story", "customer story", "deployment story"],
    description="Structured around customer → challenge → approach → results → lessons.",
    closing_blurb="Lessons learned applied to future deployments.",
    checklist=[
        SlideRole("cover", "cover", "{topic}",
                  theme_keywords=[], eyebrow="Case Study", min_claims=0, max_claims=2),
        SlideRole("customer", "team", "Customer snapshot",
                  theme_keywords=["customer", "client", "company", "industry", "size", "deployed"],
                  eyebrow="Customer"),
        SlideRole("challenge", "problem", "The challenge",
                  theme_keywords=["challenge", "problem", "issue", "pain", "bottleneck", "manual"],
                  eyebrow="Challenge"),
        SlideRole("approach", "solution", "Our approach",
                  theme_keywords=["approach", "solution", "implementation", "rollout", "deployed", "integrated"],
                  eyebrow="Approach"),
        SlideRole("architecture", "architecture", "Architecture",
                  theme_keywords=["architecture", "stack", "integration", "system", "pipeline"],
                  eyebrow="Architecture", required=False),
        SlideRole("results", "metrics", "Results",
                  theme_keywords=["result", "outcome", "savings", "lift", "growth", "reduced", "improved", "%"],
                  eyebrow="Results", prefer_chart=True),
        SlideRole("comparison", "comparison", "Before vs After",
                  theme_keywords=["before", "after", "improved", "vs", "compared", "previously"],
                  eyebrow="Comparison"),
        SlideRole("lessons", "solution", "Lessons learned",
                  theme_keywords=["lesson", "learning", "insight", "takeaway", "would do"],
                  eyebrow="Lessons"),
        SlideRole("next", "ask", "Next steps",
                  theme_keywords=["next", "expand", "scale", "roadmap", "follow"],
                  eyebrow="Next"),
        SlideRole("closing", "closing", "Customer voice",
                  theme_keywords=[], eyebrow="Close", min_claims=0, max_claims=2, required=False),
    ],
)


_PRODUCT_OVERVIEW = TopicFamily(
    name="product_overview",
    label="Product Overview",
    triggers=["product overview", "launch", "what we built", "introducing", "release notes"],
    description="Structured around problem → product → features → use cases → roadmap.",
    closing_blurb="Get started: trial / contact info.",
    checklist=[
        SlideRole("cover", "cover", "{topic}",
                  theme_keywords=[], eyebrow="Product", min_claims=0, max_claims=2),
        SlideRole("problem", "problem", "Problem we solve",
                  theme_keywords=["problem", "pain", "challenge", "manual", "slow", "broken"],
                  eyebrow="Problem"),
        SlideRole("product", "solution", "Meet {topic}",
                  theme_keywords=["product", "platform", "delivers", "powered", "feature"],
                  eyebrow="Product"),
        SlideRole("features", "architecture", "What it does",
                  theme_keywords=["feature", "supports", "includes", "capability", "integration", "api"],
                  eyebrow="Features"),
        SlideRole("differentiation", "comparison", "Why it matters",
                  theme_keywords=["unlike", "compared", "advantage", "edge", "fast", "secure", "open"],
                  eyebrow="Differentiation", required=False),
        SlideRole("use_cases", "metrics", "Use cases",
                  theme_keywords=["use case", "workflow", "scenario", "for teams", "for users"],
                  eyebrow="Use cases"),
        SlideRole("traction", "metrics", "Adoption",
                  theme_keywords=["customer", "deployed", "users", "downloads", "stars", "active"],
                  eyebrow="Traction", required=False, prefer_chart=True),
        SlideRole("roadmap", "roadmap", "What's next",
                  theme_keywords=["roadmap", "next", "coming", "planned", "phase", "release"],
                  eyebrow="Roadmap"),
        SlideRole("get_started", "ask", "Get started",
                  theme_keywords=["start", "try", "signup", "trial", "contact", "demo"],
                  eyebrow="CTA"),
        SlideRole("closing", "closing", "Thank you",
                  theme_keywords=[], eyebrow="Close", min_claims=0, max_claims=2, required=False),
    ],
)


_FAMILIES: list[TopicFamily] = [
    _PITCH_DECK,
    _CASE_STUDY,
    _PRODUCT_OVERVIEW,
    _MARKET_ANALYSIS,
    _RESEARCH_BRIEFING,
]


def detect_family(prompt: str) -> TopicFamily:
    """Pick a topic family by prompt keyword overlap.

    Priority: case_study and product_overview (more specific) before
    pitch_deck (default for "pitch"/"investor" wording). Falls back to
    research_briefing for general informational decks.
    """
    lower = (prompt or "").lower()
    scores: list[tuple[int, TopicFamily]] = []
    for family in _FAMILIES:
        score = sum(1 for trigger in family.triggers if trigger in lower)
        if score > 0:
            scores.append((score, family))
    if scores:
        scores.sort(key=lambda x: x[0], reverse=True)
        return scores[0][1]
    return _RESEARCH_BRIEFING


def list_families() -> list[TopicFamily]:
    return list(_FAMILIES)


def family_by_name(name: str) -> TopicFamily | None:
    for f in _FAMILIES:
        if f.name == name:
            return f
    return None


# ---------------------------------------------------------------------------
# Helpers used by dynamic_outline
# ---------------------------------------------------------------------------

_PRIMARY_KW_STOPWORDS = {
    "create", "build", "make", "write", "generate", "produce", "design",
    "slide", "slides", "deck", "presentation", "pitch", "for", "about",
    "our", "the", "an", "a", "of", "on", "in", "to", "with", "and", "or",
}


def primary_keyword(topic: str, prompt: str = "") -> str:
    """Best-effort: pick the most informative noun phrase from the topic.

    Falls back to the prompt when topic is empty. Returns a token like
    "healthcare in Bangladesh" or "AI platform" suitable for slugging into
    a slide title template.
    """
    source = topic.strip() if topic else prompt
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", " ", source).strip()
    if not cleaned:
        return "this topic"
    words = [w for w in cleaned.split() if w.lower() not in _PRIMARY_KW_STOPWORDS]
    if not words:
        return cleaned[:48].strip()
    return " ".join(words[:6]).strip()


def fill_title_template(template: str, topic: str, prompt: str = "") -> str:
    """Substitute ``{topic}`` and ``{primary_keyword}`` placeholders."""
    pk = primary_keyword(topic, prompt)
    title = template.format(topic=topic or pk, primary_keyword=pk)
    return title.strip()
