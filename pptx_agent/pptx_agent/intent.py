"""Intent classification for chat messages.

Decides whether a follow-up message should:
  - ``new``     start a fresh deck (default when no active job)
  - ``edit``    patch the existing deck (default when active job + edit verbs)
  - ``clarify`` request UI clarification (e.g. "change the chart" with no
                slide currently open in the drawer)

Heuristic first (cheap, no LLM). LLM fallback only when the heuristic is
ambiguous AND a job is active AND ``LLMClient.enabled`` is true.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .llm import LLMClient

# Verbs / phrases that imply editing an existing artifact.
_EDIT_VERBS_RE = re.compile(
    r"\b("
    r"change|edit|update|modify|tweak|adjust|fix|replace|swap|"
    r"rewrite|reword|rephrase|shorten|lengthen|expand|shrink|"
    r"add to|remove|drop|delete|"
    r"make (it|this|that|them|the)|use (this|that|a) (instead|color)|"
    r"color|colour|font|size|smaller|larger|bigger|brighter|darker|"
    r"this slide|that slide|the slide|on slide|the chart|the table|"
    r"the heading|the title|the bullets"
    r")\b",
    re.IGNORECASE,
)

# Strong new-deck markers (override edit signal even with a job).
_NEW_DECK_RE = re.compile(
    r"\b("
    r"new deck|new presentation|new pitch|new slide deck|"
    r"create (a |another |new )?(deck|pitch|presentation|slides)|"
    r"start (over|fresh|new)|"
    r"now make|now create|now build|"
    r"another deck|different topic|switch to"
    r")\b",
    re.IGNORECASE,
)

# Words that imply the request needs fresh data (drives targeted research).
_NEEDS_RESEARCH_RE = re.compile(
    r"\b("
    r"add|new|latest|recent|missing|"
    r"\d{4}|q[1-4]\s*\d{4}|"
    r"more.{0,12}data|more.{0,12}numbers|more.{0,12}stats|"
    r"statistic|figure|number|percentage|"
    r"source|cite|citation"
    r")\b",
    re.IGNORECASE,
)

# "Slide N" / "the third slide" — try to lift a target number out of the
# message before falling back to the drawer's active slide.
_SLIDE_NUM_RE = re.compile(r"\bslide\s*#?\s*(\d{1,2})\b", re.IGNORECASE)
_ORDINAL_NUM = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "last": -1,
}


@dataclass
class IntentResult:
    intent: str                   # "new" | "edit" | "clarify"
    target_slide: int | None = None
    needs_research: bool = False
    reason: str = ""
    clarify_question: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "target_slide": self.target_slide,
            "needs_research": self.needs_research,
            "reason": self.reason,
            "clarify_question": self.clarify_question,
        }


def classify_intent(
    message: str,
    has_active_job: bool,
    active_slide_number: int | None = None,
    deck_summary: dict[str, Any] | None = None,
    llm: LLMClient | None = None,
) -> IntentResult:
    """Decide what the user wants. See module docstring."""
    text = (message or "").strip()
    if not text:
        return IntentResult(intent="new", reason="empty message")

    # No active job → only choice is "new". Nothing to edit.
    if not has_active_job:
        return IntentResult(intent="new", reason="no active job")

    new_match = _NEW_DECK_RE.search(text)
    edit_match = _EDIT_VERBS_RE.search(text)
    needs_research = bool(_NEEDS_RESEARCH_RE.search(text))

    # Strong new-deck signal beats edit verbs ("now make a deck about X" — the
    # explicit "new deck" phrase wins over the generic "make" edit verb).
    if new_match:
        return IntentResult(intent="new", reason=f"matched '{new_match.group(0)}'")

    # Edit signal — figure out target.
    if edit_match:
        target = _extract_slide_number(text, deck_summary)
        if target is None:
            target = active_slide_number
        if target is None:
            return IntentResult(
                intent="clarify",
                needs_research=needs_research,
                reason="edit-verb hit but no slide target",
                clarify_question="Which slide should I edit?",
            )
        return IntentResult(
            intent="edit",
            target_slide=target,
            needs_research=needs_research,
            reason=f"matched '{edit_match.group(0)}'",
        )

    # Ambiguous — ask the LLM if available, otherwise default to new.
    if llm is not None and llm.enabled and deck_summary:
        try:
            llm_call = _llm_classify(text, deck_summary, active_slide_number, llm)
            if llm_call:
                return llm_call
        except Exception:  # noqa: BLE001 — never let intent block the pipeline
            pass

    # Default: treat as new prompt. Safer than mis-editing.
    return IntentResult(intent="new", reason="no edit signal, no LLM tie-break")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_slide_number(text: str, deck_summary: dict[str, Any] | None) -> int | None:
    m = _SLIDE_NUM_RE.search(text)
    if m:
        try:
            n = int(m.group(1))
            if 1 <= n <= 99:
                return n
        except ValueError:
            pass
    lower = text.lower()
    for word, n in _ORDINAL_NUM.items():
        if re.search(rf"\bthe\s+{word}\b", lower):
            if n == -1 and deck_summary and deck_summary.get("slide_count"):
                return int(deck_summary["slide_count"])
            if n > 0:
                return n
    return None


def _llm_classify(
    message: str,
    deck_summary: dict[str, Any],
    active_slide_number: int | None,
    llm: LLMClient,
) -> IntentResult | None:
    system = (
        "You are a request router. Classify the user's chat message as one of: "
        "'new' (they want a fresh deck on a different topic), 'edit' (they want "
        "to change the existing deck), or 'clarify' (target is ambiguous). "
        "Output strict JSON: "
        '{"intent":"new|edit|clarify","target_slide":int|null,'
        '"needs_research":bool,"reason":"short","clarify_question":"optional"}.'
    )
    user = json.dumps(
        {
            "message": message,
            "active_slide_number": active_slide_number,
            "deck": {
                "title": deck_summary.get("title", ""),
                "topic": deck_summary.get("topic", ""),
                "slides": [
                    {"number": s.get("number"), "title": s.get("title")}
                    for s in (deck_summary.get("slides") or [])
                ][:25],
            },
        },
        ensure_ascii=False,
    )
    raw = llm.complete_json(system, user, max_tokens=220)
    if not isinstance(raw, dict):
        return None
    intent = str(raw.get("intent") or "").strip().lower()
    if intent not in {"new", "edit", "clarify"}:
        return None
    target = raw.get("target_slide")
    try:
        target_int = int(target) if target is not None else None
    except (TypeError, ValueError):
        target_int = None
    return IntentResult(
        intent=intent,
        target_slide=target_int,
        needs_research=bool(raw.get("needs_research")),
        reason=str(raw.get("reason") or "llm classifier"),
        clarify_question=str(raw.get("clarify_question") or ""),
    )


__all__ = ["IntentResult", "classify_intent"]
