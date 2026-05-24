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
    table_block_from_research,
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
_TOPIC_STOPWORDS = {
    "a", "an", "and", "are", "for", "from", "in", "into", "of", "on", "our",
    "recent", "the", "their", "this", "that", "to", "with", "years",
}


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
    "context": [
        "{primary} sits in a broader system that shapes demand, delivery, and buyer behavior.",
        "Recent shifts around {topic} matter because they change who pays, who adopts, and who benefits.",
        "The right reading starts with structure before moving to the opportunity layer.",
    ],
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
    "sizing": [
        "The addressable pool for {primary} should be split by buyer type, use case, and geography.",
        "Spend concentration matters more than top-line sector size when prioritizing the first wedge.",
        "The best early segment combines visible demand, budget, and low deployment friction.",
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
    "players": [
        "The leading players span incumbents, specialists, and fast-moving challengers around {primary}.",
        "Positioning depends on who owns distribution, trust, and workflow depth in the category.",
        "Partnerships may matter as much as direct competition in how the space consolidates.",
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
    "segments": [
        "Segments around {primary} differ on willingness to pay, regulatory friction, and urgency.",
        "The first segment should be the one where pain, budget, and deployment fit overlap.",
        "Expansion logic should move from the best-fit segment into adjacent categories, not everywhere at once.",
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
    "outlook": [
        "The next horizon for {primary} depends on whether current growth drivers remain intact.",
        "Scenario planning should separate near-term execution from longer-term structural change.",
        "The strongest outlook pairs measurable milestones with clear trigger points for expansion.",
    ],
}


def _fallback_bullets_for_role(role: SlideRole, topic: str, primary: str, count: int) -> list[str]:
    raw = _ROLE_FALLBACK_BULLETS.get(role.role) or []
    out: list[str] = []
    for line in raw[:count]:
        filled = line.format(topic=topic, primary=primary or topic)
        out.append(filled)
    return out


_ROLE_FALLBACK_SUBTITLES: dict[str, str] = {
    "cover": "{topic} through the angles that matter for this deck.",
    "agenda": "The story moves from context to evidence to the next decision.",
    "problem": "{topic} still faces concrete gaps that create urgency for change.",
    "challenge": "{topic} still faces concrete gaps that create urgency for change.",
    "solution": "{topic} needs a credible response path, not a generic overview.",
    "approach": "{topic} needs a credible response path, not a generic overview.",
    "product": "{topic} needs a credible response path, not a generic overview.",
    "technology": "The system design matters because delivery depends on operational fit.",
    "architecture": "The system design matters because delivery depends on operational fit.",
    "market": "The numeric story should show where demand, spend, or growth is concentrated.",
    "sizing": "The numeric story should show where demand, spend, or growth is concentrated.",
    "growth": "The numeric story should show where demand, spend, or growth is concentrated.",
    "findings": "The strongest takeaways should surface as evidence, not generic summary.",
    "evidence": "The strongest takeaways should surface as evidence, not generic summary.",
    "competition": "The deck should make tradeoffs and positioning obvious at a glance.",
    "comparison": "The deck should make tradeoffs and positioning obvious at a glance.",
    "segments": "Different segments behave differently; they should not be collapsed together.",
    "risks": "Constraints and downside scenarios need to be explicit before committing resources.",
    "business_model": "Revenue mechanics and delivery economics need to stay grounded and concrete.",
    "model": "Revenue mechanics and delivery economics need to stay grounded and concrete.",
    "traction": "Execution proof matters more than broad claims once the story advances.",
    "results": "Execution proof matters more than broad claims once the story advances.",
    "adoption": "Execution proof matters more than broad claims once the story advances.",
    "team": "Capability, credibility, and execution ownership should be visible here.",
    "stakeholders": "Capability, credibility, and execution ownership should be visible here.",
    "players": "Capability, credibility, and execution ownership should be visible here.",
    "customer": "Capability, credibility, and execution ownership should be visible here.",
    "roadmap": "The next moves should show sequencing, not just ambition.",
    "outlook": "The next moves should show sequencing, not just ambition.",
    "ask": "Close with a specific decision, ask, or recommendation.",
    "recommendations": "Close with a specific decision, ask, or recommendation.",
    "get_started": "Close with a specific decision, ask, or recommendation.",
    "next": "Close with a specific decision, ask, or recommendation.",
    "closing": "End on the clearest next move for this topic.",
    "drivers": "The forces shaping momentum should be separated from the outcome itself.",
    "opportunity": "The opportunity should be framed as a concrete wedge, not a broad sector claim.",
    "lessons": "The learning should translate into action, not stay abstract.",
}


def _external_sources(research: dict[str, Any]) -> list[dict[str, Any]]:
    sources = []
    for source in (research.get("sources") or []):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        if url.startswith("local://"):
            continue
        sources.append(source)
    return sources


def _topic_keywords(topic: str, max_n: int = 3) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]+", topic.lower())
    out: list[str] = []
    for token in tokens:
        if token in _TOPIC_STOPWORDS or len(token) < 3:
            continue
        if token not in out:
            out.append(token)
        if len(out) >= max_n:
            break
    return out


def _focus_keywords_for_role(role: SlideRole, topic: str, primary: str) -> list[str]:
    out: list[str] = []
    for token in [*role.theme_keywords, primary.lower(), *_topic_keywords(topic)]:
        token = str(token).strip().lower()
        if not token or token in _TOPIC_STOPWORDS or token in out:
            continue
        out.append(token)
        if len(out) >= 6:
            break
    return out


def _assigned_source_ids(role: SlideRole, research: dict[str, Any], citations: list[str]) -> list[str]:
    if citations:
        return citations[:3]
    candidates = []
    theme_terms = set(role.theme_keywords or [])
    if not theme_terms:
        return []
    for source in _external_sources(research):
        sid = str(source.get("source_id") or "").strip()
        if not sid:
            continue
        blob = " ".join(
            str(source.get(key) or "") for key in ("title", "snippet", "excerpt")
        ).lower()
        score = sum(1 for term in theme_terms if term and term in blob)
        if score <= 0 and role.required:
            continue
        candidates.append((score, sid))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return [sid for _, sid in candidates[:3]]


def _visual_flags(role: SlideRole, metrics: list[dict[str, str]]) -> dict[str, bool]:
    data_role = role.role in {"market", "sizing", "growth", "evidence", "findings", "traction", "results", "adoption"}
    needs_hero = bool(metrics and _is_hero_worthy(metrics[0]) and data_role)
    needs_chart = bool(role.prefer_chart and (metrics or data_role))
    needs_table = role.role in {"competition", "comparison", "segments", "risks"}
    needs_diagram = role.role in {"solution", "approach", "product", "technology", "architecture", "roadmap", "outlook", "drivers", "opportunity", "lessons"}
    return {
        "needs_chart": needs_chart,
        "needs_table": needs_table,
        "needs_diagram": needs_diagram,
        "needs_hero_stat": needs_hero,
    }


def _default_animation(role: SlideRole) -> str:
    if role.role in {"market", "sizing", "growth", "evidence", "findings", "traction", "results"}:
        return "fade-up"
    if role.role in {"competition", "comparison", "segments", "risks"}:
        return "slide-in-right"
    if role.role in {"solution", "approach", "product", "technology", "architecture", "roadmap", "outlook"}:
        return "slide-in-left"
    if role.role in {"team", "stakeholders", "players", "customer"}:
        return "reveal"
    if role.role in {"ask", "recommendations", "get_started", "next", "closing"}:
        return "fade-in"
    return ""


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


def _build_subtitle(claims: list[Claim], role: SlideRole, topic: str, fallback: str) -> str:
    """Pick the highest-scoring concrete claim as the slide lede."""
    for c in claims:
        candidate = assertive(c.text)
        if not candidate:
            continue
        if 24 <= len(candidate) <= 180:
            return candidate
    subtitle = fallback or _ROLE_FALLBACK_SUBTITLES.get(role.role, "")
    if subtitle:
        return assertive(subtitle.format(topic=topic))
    return f"{role.eyebrow or role.role.replace('_', ' ').title()} for {topic}."


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
        # Cover is hero-agnostic: topic + tagline only. No bullets, no chart,
        # no paragraph. Optional small tagline via subheading if subtitle short.
        # The eyebrow + heading were already appended above; we strip the
        # subheading the standard block builder added so the cover stays
        # uncluttered.
        if subtitle and len(subtitle) > 80:
            # Drop the auto-appended subheading on covers when it grew long.
            blocks = [b for b in blocks if b.get("type") != "subheading"]
    elif role.role == "agenda":
        # Agenda placeholder. The outline builder fills `agenda_items` after
        # all subsequent slide titles are known (see build_outline pass-2).
        items = list(role.theme_keywords) or ["Section 1", "Section 2", "Section 3"]
        blocks.append(_bullets_block(number, len(blocks) + 1, items))
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
        else:
            t = table_block_from_research(number, research)
            if t:
                blocks.append(t)
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
        # Otherwise promote the strongest claim as an accent highlight so the
        # slide always has at least one bold visual element, not just a matrix.
        elif bullets:
            blocks.append({
                "id": f"s{number}-bHi-highlight",
                "type": "highlight",
                "props": {"tone": "accent", "title": role.eyebrow.upper() if role.eyebrow else "KEY POINT", "text": bullets[0]},
            })
            bullets = bullets[1:]
        table_block = table_block_from_research(number, research)
        if table_block:
            blocks.append(table_block)
        else:
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
        else:
            t = table_block_from_research(number, research)
            if t:
                blocks.append(t)
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
    elif role.role == "drivers":
        blocks.append(_diagram(number, len(blocks) + 1, "flow", bullets[:4] or ["Policy", "Demand", "Supply", "Execution"]))
        if bullets:
            blocks.append(_callout(number, len(blocks) + 1, bullets[0], tone="info"))
            if len(bullets) > 1:
                blocks.append(_bullets_block(number, len(blocks) + 1, bullets[1:]))
    elif role.role in {"opportunity", "lessons"}:
        if bullets:
            tone = "success" if role.role == "opportunity" else "accent"
            blocks.append({
                "id": f"s{number}-bHi-highlight",
                "type": "highlight",
                "props": {"tone": tone, "title": role.eyebrow.upper() if role.eyebrow else "KEY", "text": bullets[0]},
            })
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

    research_external = {**research, "sources": _external_sources(research)}
    claims = mine_claims(research_external)

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
        # Scaffold roles (cover, agenda, closing) keep their template title —
        # never let claim miner hijack the cover or agenda heading. Only
        # content-bearing roles use research claims as titles.
        if role.role in {"cover", "agenda", "closing"} or not themed:
            title = fill_title_template(role.title_template, topic_label, prompt)
        else:
            title = _title_from_claim(themed[0], role, topic_label, prompt)
        subtitle = _build_subtitle(themed, role, topic_label, fallback="")
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
        plan_flags = _visual_flags(role, metrics)
        assigned_ids = _assigned_source_ids(role, research_external, citations)

        slide_dict: dict[str, Any] = {
            "number": number,
            "id": f"slide-{number}",
            "role": role.role,
            "layout": role.layout,
            "eyebrow": role.eyebrow or role.role.replace("_", " ").title(),
            "title": title,
            "subtitle": subtitle,
            "bullets": bullets,
            "metrics": metrics,
            "speaker_notes": "",
            "citations": citations,
            "accent_variant": (number - 1) % 4,
            "focus_keywords": _focus_keywords_for_role(role, topic_label, pk),
            "assigned_source_ids": assigned_ids,
            "animation": _default_animation(role),
            **plan_flags,
        }
        slide_dict["blocks"] = _blocks_for_role(
            role,
            number=number,
            title=title,
            subtitle=subtitle,
            bullets=bullets,
            metrics=metrics,
            research=research_external,
            citations=citations,
        )
        slides.append(slide_dict)

    # Pass-2: fill agenda slide bullets with downstream slide titles.
    for i, s in enumerate(slides):
        if s.get("eyebrow", "").lower() != "agenda":
            continue
        following = [
            ss for ss in slides[i + 1:]
            if ss.get("eyebrow", "").lower() != "agenda"
            and ss.get("layout") != "closing"
        ][:6]
        agenda_items = [ss.get("eyebrow") or ss.get("title", "Section") for ss in following]
        if agenda_items:
            s["bullets"] = agenda_items
            # Rebuild this slide's blocks now that bullets are known.
            new_role = SlideRole(
                role="agenda",
                layout=s["layout"],
                title_template="",
                theme_keywords=agenda_items,
                eyebrow=s.get("eyebrow", "Agenda"),
                min_claims=0,
                max_claims=len(agenda_items),
                required=False,
            )
            s["blocks"] = _blocks_for_role(
                new_role,
                number=s["number"],
                title=s["title"],
                subtitle=s.get("subtitle", ""),
                bullets=agenda_items,
                metrics=[],
                research=research,
                citations=[],
            )

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
            "role": "closing",
            "layout": "closing",
            "eyebrow": "Appendix",
            "title": title,
            "subtitle": subtitle,
            "bullets": bullets,
            "metrics": [],
            "speaker_notes": "",
            "citations": sorted({c.source_id for c in leftover if c.source_id}),
            "focus_keywords": _focus_keywords_for_role(
                SlideRole(role="closing", layout="closing", title_template="", theme_keywords=["appendix"], eyebrow="Appendix"),
                topic_label,
                pk,
            ),
            "assigned_source_ids": sorted({c.source_id for c in leftover if c.source_id}),
            "needs_chart": False,
            "needs_table": False,
            "needs_diagram": False,
            "needs_hero_stat": False,
            "animation": "fade-in",
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


# ---------------------------------------------------------------------------
# Public composer surface — consumed by regen.py for single-slide rebuilds.
# Kept as explicit aliases so the leading-underscore helpers remain private
# implementation details while regen still has a stable import target.
# ---------------------------------------------------------------------------

build_subtitle = _build_subtitle
claims_to_bullets = _claims_to_bullets
blocks_for_role = _blocks_for_role
fallback_bullets_for_role = _fallback_bullets_for_role
metrics_from_claims = _metrics_from_claims
title_from_claim = _title_from_claim
ROLE_FALLBACK_BULLETS = _ROLE_FALLBACK_BULLETS

__all__ = [
    "build_outline",
    "build_subtitle",
    "claims_to_bullets",
    "blocks_for_role",
    "fallback_bullets_for_role",
    "metrics_from_claims",
    "title_from_claim",
    "ROLE_FALLBACK_BULLETS",
]
