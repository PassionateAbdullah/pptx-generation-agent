"""Dynamic outline builder.

Phase 8.5: produces a deck shaped by the prompt's **topic family**, with
each slide's title + body filled from **claims mined from research**.

Pipeline:

  1. Detect topic family from prompt (``topic_families.detect_family``).
  2. Mine claims from research (``claim_miner.mine_claims``).
  3. Walk the family's checklist of slide roles.
  4. For each role, route claims by theme keywords; emit a slide dict with
     research-anchored title, subtitle, bullets, optional chart block,
     and inline ``[S#]`` citations.
  5. Filter every text through ``hedge_filter`` so no meta-instruction
     copy ships.

Output shape is the same dict shape the legacy fallback produced
(``{number, layout, eyebrow, title, subtitle, bullets, metrics,
speaker_notes, citations, blocks}``) so it slots into
``planner.normalize_deck`` without any other code changes.
"""

from __future__ import annotations

import re
from typing import Any

from .claim_miner import Claim, mine_claims, take_top_claims_for_theme
from .dynamic_blocks import (
    _bullets_block,
    _callout,
    _chart,
    _diagram,
    _eyebrow,
    _heading,
    _id,
    _image_placeholder,
    _metric_row,
    _paragraph,
    _quote,
    _subheading,
    chart_block_from_research,
)
from .hedge_filter import assertive, scrub_bullets, scrub_paragraph
from .topic_families import (
    SlideRole,
    TopicFamily,
    detect_family,
    fill_title_template,
    primary_keyword,
)


_TITLE_FROM_CLAIM_KIND_PRIORITY = ("head_to_head", "percent", "currency", "time", "number", "entity")


def _hero_stat_block(slide_number: int, metric: dict[str, str], source_id: str = "") -> dict[str, Any]:
    return {
        "id": f"s{slide_number}-bHero-hero_stat",
        "type": "hero_stat",
        "props": {
            "value": metric.get("value", ""),
            "label": metric.get("label", ""),
            "trend": "",
            "source_id": source_id,
        },
    }


def _highlight_from_claim(slide_number: int, claim: Claim, tone: str = "accent") -> dict[str, Any]:
    return {
        "id": f"s{slide_number}-bHi-highlight",
        "type": "highlight",
        "props": {
            "tone": tone,
            "title": "Key insight",
            "text": claim.text,
        },
    }


def _is_hero_worthy(metric: dict[str, str]) -> bool:
    value = (metric.get("value") or "").strip()
    if not value:
        return False
    # Pithy stat: short enough to display giant.
    return len(value) <= 12


# Topic-anchored fallback bullets per role. Used only when the claim miner
# returns nothing for a role's theme — keeps the slide from shipping blank.
# Format strings have ``{topic}``/``{primary}`` placeholders.
_ROLE_FALLBACK_BULLETS: dict[str, list[str]] = {
    "competition": [
        "{primary} compares favorably against incumbents on speed, cost, and integration.",
        "Switching cost stays low because data and workflows remain owned by the customer.",
        "Moat strengthens with usage: every customer improves shared retrieval and benchmarks.",
    ],
    "differentiation": [
        "{primary} differs from incumbents on accuracy, latency, and total cost of ownership.",
        "Open integration surface vs proprietary lock-in keeps options open.",
        "Stronger feedback loops compound model quality faster than category averages.",
    ],
    "business_model": [
        "Tiered subscription: starter, team, and enterprise pricing for {primary}.",
        "Usage-based add-ons for high-volume workloads.",
        "Professional services accelerate onboarding without becoming the revenue engine.",
    ],
    "model": [
        "Tiered subscription priced per seat or per workflow on {primary}.",
        "Usage-based components scale revenue with adoption.",
        "Enterprise contracts unlock procurement and security review.",
    ],
    "ask": [
        "Raise targeted at expanding engineering and go-to-market for {primary}.",
        "12-18 months of runway covers product, pilots, and security work.",
        "Investor partners with sector expertise are preferred.",
    ],
    "team": [
        "Founding team combines AI research and enterprise deployment for {primary}.",
        "Advisors include practitioners from buyer-side institutions.",
        "Distributed hiring strategy targets specialists in target segments.",
    ],
    "stakeholders": [
        "Primary buyer, operational owner, and end users are mapped for {primary}.",
        "Regulators and standards bodies shape adoption timelines.",
        "Partnership channels (NGO, public, private) accelerate first-customer reach.",
    ],
    "traction": [
        "{primary} pilots in progress with named-account anchor customers.",
        "Retention and usage metrics improve quarter over quarter.",
        "Pipeline concentrated in segments with measurable pain and clear budget.",
    ],
    "results": [
        "{primary} reduced cycle time and unit cost in pilot deployments.",
        "Quality scores beat baseline benchmarks on representative workloads.",
        "Customers expanded usage within 90 days of go-live.",
    ],
    "closing": [
        "{primary}: research-backed, focused, and execution-ready.",
        "Next step is a pilot conversation with a named account.",
    ],
    "drivers": [
        "Policy and funding shifts are pulling {primary} forward.",
        "Buyer expectations have moved from experimentation to operational readiness.",
        "Technology stack is mature enough for production deployment.",
    ],
    "opportunity": [
        "{primary} has a narrow beachhead with clear pain, budget, and ability to adopt.",
        "Expansion from beachhead to adjacent segments compounds with usage.",
        "Public, private, and partnership channels reinforce the wedge.",
    ],
    "risks": [
        "Adoption risk is mitigated by anchor pilots and reference customers in {primary}.",
        "Execution risk is bounded by clear owner, timeline, and partner dependency.",
        "Policy or trust risk is addressed by compliance and stakeholder alignment.",
    ],
    "recommendations": [
        "Run a 90-day pilot in the highest-pain segment of {primary}.",
        "Validate willingness-to-pay with one anchor customer before scaling.",
        "Build the measurement loop into the deployment from day one.",
    ],
    "lessons": [
        "Highest-value learnings from {primary} pilots map to product roadmap.",
        "Operational integration matters more than model selection.",
        "Customer success motion is the moat compounder.",
    ],
}


def _fallback_bullets_for_role(role: SlideRole, topic: str, primary: str, count: int) -> list[str]:
    raw = _ROLE_FALLBACK_BULLETS.get(role.role) or []
    out: list[str] = []
    for line in raw[:count]:
        filled = line.format(topic=topic, primary=primary or topic)
        out.append(filled)
    return out


def _title_from_claim(claim: Claim, role: SlideRole, topic: str, prompt: str) -> str:
    """Turn a strong claim into a slide title.

    Strategy:
      - Drop trailing punctuation, source-id markers.
      - Cap to 70 chars (Manus titles run ~50-70).
      - If the claim is a clean noun-phrase fragment, use as-is.
      - Otherwise prepend the role's eyebrow as scaffold + ": " + claim.
    """
    text = claim.text.strip().rstrip(".:;")
    text = re.sub(r"\s*\[S\d+\]\s*$", "", text)
    if len(text) > 70:
        text = text[:67].rstrip(" ,;:") + "…"
    eyebrow = role.eyebrow or role.role.replace("_", " ").title()
    if len(text) < 18:
        # Fall back to template — claim too short to stand alone.
        return fill_title_template(role.title_template, topic, prompt)
    # Prefer concise quoted-style titles when the claim already reads well.
    if re.search(r"^\d", text):
        return f"{eyebrow}: {text}"
    return text


def _build_subtitle(claims: list[Claim], topic: str, fallback: str) -> str:
    """Pick the highest-scoring concrete claim as the slide lede."""
    for c in claims:
        candidate = assertive(c.text)
        if not candidate:
            continue
        if 24 <= len(candidate) <= 180:
            return candidate
    return assertive(fallback) or f"What we know about {topic}."


def _claims_to_bullets(claims: list[Claim], min_n: int, max_n: int, fallbacks: list[str]) -> list[str]:
    """Convert claims to slide bullets, padding with fallback text when needed."""
    bullets: list[str] = []
    for c in claims[:max_n]:
        text = assertive(c.text)
        if not text:
            continue
        if c.source_id:
            text = f"{text.rstrip('.')} [{c.source_id}]"
        bullets.append(text)
        if len(bullets) >= max_n:
            break
    if len(bullets) < min_n:
        for fb in fallbacks:
            tight = assertive(fb)
            if tight and tight not in bullets:
                bullets.append(tight)
            if len(bullets) >= min_n:
                break
    return scrub_bullets(bullets)


def _metrics_from_claims(claims: list[Claim], max_n: int = 3) -> list[dict[str, str]]:
    """Pull (label, value) cards from currency/percent claims."""
    metrics: list[dict[str, str]] = []
    pct_re = re.compile(r"(\d{1,3}(?:\.\d+)?\s*%)")
    cur_re = re.compile(r"(\$\s?\d{1,3}(?:[,\d]*\.?\d*)\s*[BMK]?)", re.IGNORECASE)
    num_re = re.compile(r"\b(\d{1,3}(?:[,\d]*\.?\d*)\s*(?:million|billion|thousand|users|customers|deals|pilots|patients|hospitals))", re.IGNORECASE)
    seen_values: set[str] = set()
    for c in claims:
        for pattern in (cur_re, pct_re, num_re):
            m = pattern.search(c.text)
            if not m:
                continue
            value = m.group(1).strip()
            if value in seen_values:
                continue
            seen_values.add(value)
            # Use the claim's leading 3-4 capitalised words as label, or its keywords.
            label_match = re.match(r"([A-Z][\w\s-]{2,28}?)[:\s]", c.text)
            label = label_match.group(1).strip(" :,-") if label_match else (
                " ".join(k.title() for k in c.keywords[:2]) or "Signal"
            )
            metrics.append({"label": label[:24], "value": value})
            if len(metrics) >= max_n:
                return metrics
    return metrics


def _blocks_for_role(
    role: SlideRole,
    number: int,
    title: str,
    subtitle: str,
    bullets: list[str],
    metrics: list[dict[str, str]],
    research: dict[str, Any],
    citations: list[str],
) -> list[dict[str, Any]]:
    """Compose a blocks list tailored to the role.

    The shape varies by role to give the deck visual variety (works with
    phase 8's variety scorer). Charts only attach when the role asks for
    one AND the research has enough numeric points to fill it.
    """
    blocks: list[dict[str, Any]] = []
    blocks.append(_eyebrow(number, 1, role.eyebrow or role.role.replace("_", " ").title()))
    blocks.append(_heading(number, 2, title))

    if subtitle:
        blocks.append(_subheading(number, 3, subtitle))

    chart_block = None
    if role.prefer_chart:
        chart_block = chart_block_from_research(number, research, kind="bar")

    if role.role == "cover":
        # Cover always gets a giant hero stat if any metric is pithy, else big paragraph.
        if metrics and _is_hero_worthy(metrics[0]):
            sid = citations[0] if citations else ""
            blocks.append(_hero_stat_block(number, metrics[0], source_id=sid))
            if len(metrics) > 1:
                blocks.append(_metric_row(number, len(blocks) + 1, metrics[1:]))
        elif metrics:
            blocks.append(_metric_row(number, len(blocks) + 1, metrics))
        else:
            blocks.append(_paragraph(number, len(blocks) + 1, subtitle or title))
    elif role.role in {"problem", "challenge"}:
        if bullets:
            blocks.append(_callout(number, len(blocks) + 1, bullets[0], tone="warn"))
            if len(bullets) > 1:
                blocks.append(_bullets_block(number, len(blocks) + 1, bullets[1:]))
        else:
            blocks.append(_callout(number, len(blocks) + 1, subtitle, tone="warn"))
    elif role.role in {"solution", "approach", "product"}:
        if chart_block is None:
            blocks.append(_diagram(number, len(blocks) + 1, "flow", bullets[:4] or ["Plan", "Build", "Ship"]))
        blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"technology", "architecture", "features"}:
        blocks.append(_diagram(number, len(blocks) + 1, "matrix", bullets[:6] or ["Pillar 1", "Pillar 2", "Pillar 3", "Pillar 4"]))
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"market", "sizing", "growth", "evidence", "findings"}:
        # Hero stat for first metric, regular metric row for rest.
        if metrics and _is_hero_worthy(metrics[0]):
            sid = citations[0] if citations else ""
            blocks.append(_hero_stat_block(number, metrics[0], source_id=sid))
            if len(metrics) > 1:
                blocks.append(_metric_row(number, len(blocks) + 1, metrics[1:]))
        elif metrics:
            blocks.append(_metric_row(number, len(blocks) + 1, metrics))
        if chart_block:
            blocks.append(chart_block)
            chart_block = None
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"competition", "differentiation", "comparison", "segments", "risks"}:
        # Promote any head-to-head bullet to a colored highlight at the top.
        h2h_idx = next((i for i, b in enumerate(bullets) if " vs " in b.lower() or " vs. " in b.lower()), -1)
        if h2h_idx >= 0:
            blocks.append({
                "id": f"s{number}-bHi-highlight",
                "type": "highlight",
                "props": {"tone": "warn", "title": "Head-to-head", "text": bullets[h2h_idx]},
            })
            bullets = [b for i, b in enumerate(bullets) if i != h2h_idx]
        blocks.append(_diagram(number, len(blocks) + 1, "matrix", bullets[:6] or ["Alt 1", "Alt 2"]))
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"business_model", "model"}:
        if metrics:
            blocks.append(_metric_row(number, len(blocks) + 1, metrics))
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"traction", "results", "adoption"}:
        if metrics and _is_hero_worthy(metrics[0]):
            sid = citations[0] if citations else ""
            blocks.append(_hero_stat_block(number, metrics[0], source_id=sid))
            if len(metrics) > 1:
                blocks.append(_metric_row(number, len(blocks) + 1, metrics[1:]))
        elif metrics:
            blocks.append(_metric_row(number, len(blocks) + 1, metrics))
        if chart_block:
            blocks.append(chart_block)
            chart_block = None
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"team", "stakeholders", "players", "customer"}:
        blocks.append(_image_placeholder(number, len(blocks) + 1, title))
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
    elif role.role in {"roadmap", "outlook"}:
        blocks.append(_diagram(number, len(blocks) + 1, "flow", bullets[:4] or ["Now", "Next", "Later"]))
        if len(bullets) > 4:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets[4:]))
    elif role.role in {"ask", "recommendations", "get_started", "next"}:
        if metrics:
            blocks.append(_metric_row(number, len(blocks) + 1, metrics))
        blocks.append(_callout(number, len(blocks) + 1, bullets[0] if bullets else subtitle, tone="success"))
        if len(bullets) > 1:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets[1:]))
    elif role.role == "closing":
        blocks.append(_quote(number, len(blocks) + 1, subtitle or title, attribution=""))
    elif role.role in {"drivers", "opportunity", "lessons"}:
        if bullets:
            blocks.append(_callout(number, len(blocks) + 1, bullets[0], tone="info"))
            if len(bullets) > 1:
                blocks.append(_bullets_block(number, len(blocks) + 1, bullets[1:]))
        else:
            blocks.append(_paragraph(number, len(blocks) + 1, subtitle))
    else:
        if bullets:
            blocks.append(_bullets_block(number, len(blocks) + 1, bullets))
        else:
            blocks.append(_paragraph(number, len(blocks) + 1, subtitle))

    if chart_block:
        blocks.append(chart_block)

    if citations:
        # Carry citations as a paragraph footnote-style note so the source
        # mapping is also visible inside the slide body, not only via the
        # pill row underneath.
        cite_line = "Sources: " + " ".join(f"[{c}]" for c in citations[:5])
        blocks.append(_paragraph(number, len(blocks) + 1, cite_line))
    return blocks


def _topic_from_prompt(prompt: str, topic: str) -> str:
    pk = primary_keyword(topic, prompt)
    if topic and len(topic.strip()) > 1:
        return topic.strip()
    return pk


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_outline(
    prompt: str,
    topic: str,
    slide_count: int,
    research: dict[str, Any],
) -> dict[str, Any]:
    """Return a full deck dict shaped by the detected topic family.

    The output is structurally identical to what
    ``planner._fallback_deck`` used to return (title, subtitle, audience,
    slides=[...]) so it slots into ``normalize_deck`` unchanged.
    """
    family = detect_family(prompt)
    pk = primary_keyword(topic, prompt)
    topic_label = _topic_from_prompt(prompt, topic)

    claims = mine_claims(research)

    # Walk checklist, build slides until we hit slide_count.
    slides: list[dict[str, Any]] = []
    checklist = list(family.checklist)
    used_claim_texts: set[str] = set()

    for role in checklist:
        if len(slides) >= slide_count:
            break

        themed = take_top_claims_for_theme(
            claims,
            role.theme_keywords,
            max_count=role.max_claims + 1,
            require_match=False,
            used=used_claim_texts,
        )
        # Skip a role only when it (a) has theme keywords (so its absence is
        # signal not scaffolding), (b) found no themed claims, and (c) is not
        # marked required. Scaffolding roles (cover / closing) have empty
        # theme_keywords and should always emit.
        if not themed and role.theme_keywords and not role.required:
            continue

        number = len(slides) + 1
        title = (
            _title_from_claim(themed[0], role, topic_label, prompt)
            if themed
            else fill_title_template(role.title_template, topic_label, prompt)
        )
        subtitle = _build_subtitle(themed, topic_label, fallback="")
        if role.role == "cover":
            subtitle = subtitle or _deck_subtitle(topic_label, family)
        fallbacks = _fallback_bullets_for_role(role, topic_label, pk, count=role.max_claims)
        bullets = _claims_to_bullets(
            themed,
            min_n=role.min_claims,
            max_n=role.max_claims,
            fallbacks=fallbacks,
        )
        metrics = _metrics_from_claims(themed)
        citations = sorted({c.source_id for c in themed if c.source_id})
        if role.role == "cover":
            citations = []

        slide_dict: dict[str, Any] = {
            "number": number,
            "id": f"slide-{number}",
            "layout": role.layout,
            "eyebrow": role.eyebrow or role.role.replace("_", " ").title(),
            "title": title,
            "subtitle": subtitle,
            "bullets": bullets,
            "metrics": metrics,
            "speaker_notes": "",
            "citations": citations,
            "accent_variant": (number - 1) % 4,
        }
        slide_dict["blocks"] = _blocks_for_role(
            role,
            number=number,
            title=title,
            subtitle=subtitle,
            bullets=bullets,
            metrics=metrics,
            research=research,
            citations=citations,
        )
        slides.append(slide_dict)

    # Pad with appendix-style slides if we haven't reached slide_count.
    # Use the family's optional roles a second time if any were skipped, then
    # fall back to thematic appendix content.
    appendix_titles = [
        ("Appendix: Why now", "info"),
        ("Appendix: Risks and assumptions", "warn"),
        ("Appendix: Roadmap detail", "info"),
        ("Appendix: Team & advisors", "info"),
        ("Appendix: Methodology", "info"),
    ]
    pad_idx = 0
    while len(slides) < slide_count:
        number = len(slides) + 1
        if pad_idx < len(appendix_titles):
            title, tone = appendix_titles[pad_idx]
            pad_idx += 1
        else:
            title, tone = (f"Appendix {number}", "info")
        # Try to surface any remaining unused claims here.
        remaining = [c for c in claims if c.text.lower() not in used_claim_texts]
        remaining.sort(key=lambda c: c.score, reverse=True)
        leftover = remaining[:3]
        for c in leftover:
            used_claim_texts.add(c.text.lower())
        bullets = scrub_bullets([assertive(c.text) + (f" [{c.source_id}]" if c.source_id else "") for c in leftover])
        if not bullets:
            bullets = _fallback_bullets_for_role(
                SlideRole(role="closing", layout="closing", title_template="", theme_keywords=[], eyebrow="Close"),
                topic_label, pk, count=2,
            )
        subtitle = family.closing_blurb if pad_idx == 1 else ""
        slides.append({
            "number": number,
            "id": f"slide-{number}",
            "layout": "closing",
            "eyebrow": "Appendix",
            "title": title,
            "subtitle": subtitle,
            "bullets": bullets,
            "metrics": [],
            "speaker_notes": "",
            "citations": sorted({c.source_id for c in leftover if c.source_id}),
            "blocks": [
                _eyebrow(number, 1, "Appendix"),
                _heading(number, 2, title),
                _callout(number, 3, bullets[0] if bullets else family.closing_blurb, tone=tone),
                _bullets_block(number, 4, bullets[1:] if len(bullets) > 1 else []),
            ],
        })

    deck = {
        "title": _deck_title(topic_label, family),
        "subtitle": _deck_subtitle(topic_label, family),
        "audience": _deck_audience(family),
        "topic": topic_label,
        "family": family.name,
        "prompt": prompt,
        "slides": slides,
    }
    return deck


def _deck_title(topic: str, family: TopicFamily) -> str:
    # Capitalize only the first letter of the first word — keep proper-noun
    # casing intact (e.g. "Bangladesh" stays "Bangladesh", "in" stays "in").
    if topic:
        pretty = topic[0].upper() + topic[1:]
    else:
        pretty = ""
    if family.name == "pitch_deck":
        return f"{pretty} Pitch Deck"
    if family.name == "research_briefing":
        return f"{pretty}: Research Briefing"
    if family.name == "market_analysis":
        return f"{pretty} Market Analysis"
    if family.name == "case_study":
        return f"{pretty}: Case Study"
    if family.name == "product_overview":
        return f"{pretty} Product Overview"
    return pretty or "Deck"


def _deck_subtitle(topic: str, family: TopicFamily) -> str:
    return f"{family.label} on {topic}." if topic else family.description


def _deck_audience(family: TopicFamily) -> str:
    if family.name == "pitch_deck":
        return "Investors, operators, and decision-makers"
    if family.name == "research_briefing":
        return "Policy makers, analysts, and program leads"
    if family.name == "market_analysis":
        return "Investors and strategy teams"
    if family.name == "case_study":
        return "Prospective customers and partners"
    if family.name == "product_overview":
        return "Users, partners, and prospects"
    return "Stakeholders"
