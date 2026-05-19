"""Closed agent loop — render, inspect, repair, repeat.

Public surface:

- ``repair_slide(slide, audit_findings, visual_findings, research, deck_meta, llm)``
  Single LLM call that rewrites the specific blocks called out by the
  validators. The result is re-grounded with the same numeric-grounding
  pass the original author used so hallucinations can't slip back in.

- ``quality_score(audit, visual_by_slide)``
  Weighted aggregate of audit + visual findings. Lower is better, 0 means
  the deck passes all checks.

- ``run_loop(deck, research, settings, llm, max_passes=2)``
  Iteration controller. Renders → inspects → repairs → re-renders until
  the score reaches 0, no improvement happens, ``max_passes`` is hit, or
  the per-slide repair cap (2) is exhausted.

Closes user's "inspect output / fix layout / repeat" boxes. No browser —
inspection is HTML/DOM rule-based (see ``visual_inspect``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterator

from .blocks import normalize_blocks
from .deck_audit import audit_deck
from .html_renderer import render_single_slide_html
from .llm import LLMClient
from .prompts import load as load_prompt
from .slide_author import _extract_signals, _ground_blocks, _pick_sources
from .visual_inspect import inspect_slide_html

log = logging.getLogger("pptx_agent.agent_loop")

# Weights for quality_score. Lower aggregate = better deck.
_SEVERITY_WEIGHTS = {"error": 10.0, "warn": 2.0, "info": 0.5}
_MAX_REPAIRS_PER_SLIDE = 2


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------


def quality_score(
    audit: dict[str, Any],
    visual_by_slide: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Aggregate audit + visual findings into one weighted score.

    Returns ``{score, by_slide, by_severity}``. ``by_slide`` maps
    slide_number -> per-slide score so the controller can target the worst
    slides for repair first.
    """
    visual_by_slide = visual_by_slide or {}
    by_slide: dict[int, float] = {}
    by_severity = {"error": 0, "warn": 0, "info": 0}
    deck_score = 0.0

    for f in (audit or {}).get("findings", []):
        sev = str(f.get("severity") or "info")
        w = _SEVERITY_WEIGHTS.get(sev, 1.0)
        by_severity[sev] = by_severity.get(sev, 0) + 1
        deck_score += w
        slide_no = f.get("slide")
        if slide_no:
            by_slide[int(slide_no)] = by_slide.get(int(slide_no), 0.0) + w

    for slide_no, items in visual_by_slide.items():
        for f in items or []:
            sev = str(f.get("severity") or "info")
            w = _SEVERITY_WEIGHTS.get(sev, 1.0)
            by_severity[sev] = by_severity.get(sev, 0) + 1
            deck_score += w
            by_slide[int(slide_no)] = by_slide.get(int(slide_no), 0.0) + w

    return {
        "score": round(deck_score, 2),
        "by_slide": {int(k): round(v, 2) for k, v in by_slide.items()},
        "by_severity": by_severity,
    }


# ---------------------------------------------------------------------------
# Repair LLM call
# ---------------------------------------------------------------------------


def repair_slide(
    slide: dict[str, Any],
    audit_findings: list[dict[str, Any]],
    visual_findings: list[dict[str, Any]],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
) -> dict[str, Any] | None:
    """Ask the LLM to fix the blocks the validators flagged.

    Returns a repaired slide dict (same shape as ``author_slide`` output)
    or ``None`` if the LLM returned nothing usable.
    """
    if not (audit_findings or visual_findings):
        return None

    number = int(slide.get("number") or 0)
    layout = str(slide.get("layout") or "solution")
    assigned_ids = slide.get("assigned_source_ids") or [
        str(c) for c in (slide.get("citations") or [])
    ]
    sources = _pick_sources(research, assigned_ids)
    signals = _extract_signals(sources)

    system = load_prompt("slide")
    user = json.dumps(
        {
            "deck": {
                "task": deck_meta.get("prompt", ""),
                "topic": deck_meta.get("topic", ""),
                "title": deck_meta.get("title", ""),
                "audience": deck_meta.get("audience", ""),
                "family": deck_meta.get("family", ""),
            },
            "slide": {
                "number": number,
                "role": str(slide.get("role") or layout),
                "layout": layout,
                "eyebrow": slide.get("eyebrow", ""),
                "working_title": slide.get("title", ""),
                "working_subtitle": slide.get("subtitle", ""),
                "focus_keywords": slide.get("focus_keywords", []),
            },
            "sources": sources,
            "signals": signals,
            "previous_blocks": slide.get("blocks") or [],
            "feedback": {
                "audit_findings": [
                    {"code": f.get("code"), "message": f.get("message")}
                    for f in audit_findings
                ],
                "visual_findings": [
                    {"code": f.get("code"), "message": f.get("message"),
                     "suggested_fix": f.get("suggested_fix")}
                    for f in visual_findings
                ],
                "instruction": (
                    "Your previous attempt produced the slide in `previous_blocks` "
                    "but the validators flagged the issues above. Re-author the slide. "
                    "Use ONLY values that appear in `signals[].text` or "
                    "`sources[].excerpt` — do not invent numbers. Fix only the "
                    "flagged blocks; leave correctly-grounded blocks alone."
                ),
            },
        },
        ensure_ascii=False,
    )

    raw = llm.complete_json(system, user, max_tokens=1800)
    if not raw:
        return None

    raw_blocks = raw.get("blocks") or []
    blocks = normalize_blocks(number, raw_blocks)
    if not blocks:
        return None
    blocks = _ground_blocks(blocks, sources)
    if not blocks:
        return None

    repaired = dict(slide)
    repaired["blocks"] = blocks
    if raw.get("title"):
        repaired["title"] = str(raw["title"])
    if raw.get("subtitle"):
        repaired["subtitle"] = str(raw["subtitle"])
    if raw.get("speaker_notes"):
        repaired["speaker_notes"] = str(raw["speaker_notes"])
    if raw.get("citations"):
        repaired["citations"] = [str(c) for c in raw["citations"] if c]
    return repaired


# ---------------------------------------------------------------------------
# Iteration controller
# ---------------------------------------------------------------------------


def run_loop(
    deck: dict[str, Any],
    research: dict[str, Any],
    deck_meta: dict[str, Any],
    llm: LLMClient,
    max_passes: int = 2,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Render → inspect → repair → repeat until quality is acceptable.

    Returns the deck dict (mutated in place w/ repaired slides). Emits
    progress events via ``on_event`` for ``loop_pass_start``,
    ``slide_repaired``, ``loop_pass_end``.
    """
    def emit(evt: dict[str, Any]) -> None:
        if on_event:
            try:
                on_event(evt)
            except Exception:  # noqa: BLE001
                pass

    slides = deck.get("slides") or []
    if not slides:
        return deck

    repairs_used: dict[int, int] = {int(s.get("number") or 0): 0 for s in slides}
    prev_score: float | None = None

    for pass_idx in range(1, max_passes + 1):
        audit = audit_deck(deck)
        visual_by_slide: dict[int, list[dict[str, Any]]] = {}
        for slide in slides:
            number = int(slide.get("number") or 0)
            html = render_single_slide_html(deck, slide)
            findings = inspect_slide_html(html, slide)
            if findings:
                visual_by_slide[number] = [
                    {"code": f.code, "severity": f.severity,
                     "message": f.message, "suggested_fix": f.suggested_fix}
                    for f in findings
                ]
        score_info = quality_score(audit, visual_by_slide)
        emit({
            "type": "loop_pass_start",
            "pass": pass_idx,
            "max_passes": max_passes,
            "score": score_info["score"],
            "by_severity": score_info["by_severity"],
        })

        if score_info["score"] == 0:
            emit({"type": "loop_pass_end", "pass": pass_idx,
                  "score": 0, "changed": 0, "stopped": "clean"})
            return deck
        if prev_score is not None and score_info["score"] >= prev_score - 2:
            emit({"type": "loop_pass_end", "pass": pass_idx,
                  "score": score_info["score"], "changed": 0,
                  "stopped": "no-improvement"})
            return deck
        prev_score = score_info["score"]

        # Repair slides in worst-first order until budget exhausted.
        worst_first = sorted(
            score_info["by_slide"].items(), key=lambda kv: kv[1], reverse=True
        )
        changed = 0
        slide_by_number = {int(s.get("number") or 0): s for s in slides}
        for number, _w in worst_first:
            if repairs_used.get(number, 0) >= _MAX_REPAIRS_PER_SLIDE:
                continue
            slide = slide_by_number.get(number)
            if not slide:
                continue
            audit_for_slide = [
                f for f in audit.get("findings", [])
                if f.get("slide") == number and f.get("severity") in ("error", "warn")
            ]
            visual_for_slide = [
                f for f in visual_by_slide.get(number, [])
                if f.get("severity") in ("error", "warn")
            ]
            if not (audit_for_slide or visual_for_slide):
                continue
            try:
                repaired = repair_slide(
                    slide, audit_for_slide, visual_for_slide,
                    research, deck_meta, llm,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("repair_slide failed for %s: %s", number, exc)
                emit({"type": "slide_repaired", "number": number,
                      "ok": False, "error": str(exc)[:200]})
                continue
            if not repaired:
                continue
            # Replace in place.
            for i, s in enumerate(slides):
                if int(s.get("number") or 0) == number:
                    slides[i] = repaired
                    break
            repairs_used[number] = repairs_used.get(number, 0) + 1
            changed += 1
            codes_fixed = [f.get("code") for f in audit_for_slide + visual_for_slide]
            emit({"type": "slide_repaired", "number": number,
                  "ok": True, "codes_fixed": codes_fixed,
                  "repairs_used": repairs_used[number],
                  "slide": repaired})

        emit({"type": "loop_pass_end", "pass": pass_idx,
              "score": score_info["score"], "changed": changed,
              "stopped": "max-passes" if pass_idx == max_passes else None})
        if changed == 0:
            return deck

    return deck


__all__ = ["quality_score", "repair_slide", "run_loop"]
