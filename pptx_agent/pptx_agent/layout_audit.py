from __future__ import annotations

from typing import Any

from .blocks import slide_to_blocks
from .pptx_writer import BLOCK_GAP, CONTENT_Y_END, CONTENT_Y_START

_SUPPORTED_HTML = {
    "eyebrow",
    "heading",
    "subheading",
    "paragraph",
    "bullets",
    "metric_row",
    "quote",
    "callout",
    "image",
    "chart",
    "diagram",
    "spacer",
    "hero_stat",
    "highlight",
    "table",
}

_SUPPORTED_PPTX = set(_SUPPORTED_HTML)


def audit_deck_layout(deck: dict[str, Any]) -> dict[str, Any]:
    available_height = CONTENT_Y_END - CONTENT_Y_START
    slides = deck.get("slides") or []
    per_slide: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    critical: list[dict[str, Any]] = []

    for slide in slides:
        number = int(slide.get("number") or 0)
        blocks = slide.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            blocks = slide_to_blocks(slide)
        used_height = 0
        local_warnings: list[str] = []
        local_critical: list[str] = []
        text_risk_count = 0

        for block in blocks:
            block_type = str(block.get("type") or "")
            props = block.get("props") or {}
            est = _estimate_block_height(block_type, props)
            if est > 0:
                used_height += est + BLOCK_GAP

            if block_type not in _SUPPORTED_HTML:
                local_critical.append(f"Unsupported HTML block type: {block_type}")
            if block_type not in _SUPPORTED_PPTX:
                local_critical.append(f"Unsupported PPTX block type: {block_type}")

            risk = _text_risk(block_type, props)
            if risk:
                text_risk_count += 1
                local_warnings.append(risk)

            if block_type == "image":
                src = str(props.get("src") or "").strip()
                if src.startswith(("http://", "https://")):
                    local_warnings.append("Remote image may render in HTML but fall back in PPTX export.")
            if block_type == "chart":
                series = props.get("series") or []
                values = []
                for item in series:
                    if isinstance(item, dict):
                        values.extend(item.get("values") or [])
                if not values:
                    local_warnings.append("Chart block has no numeric values.")

        # remove trailing gap
        if used_height > 0:
            used_height -= BLOCK_GAP
        overflow = max(0, used_height - available_height)
        if overflow > 0:
            local_critical.append(f"Estimated overflow: {overflow} emu above available area.")
        elif used_height > int(available_height * 0.95):
            local_warnings.append("Slide is close to vertical limit; future edits may clip.")

        for msg in local_critical:
            critical.append({"slide": number, "message": msg})
        for msg in local_warnings:
            warnings.append({"slide": number, "message": msg})

        per_slide.append(
            {
                "slide": number,
                "layout": str(slide.get("layout") or ""),
                "block_count": len(blocks),
                "estimated_used_emu": used_height,
                "available_emu": available_height,
                "overflow_emu": overflow,
                "text_risk_count": text_risk_count,
                "critical": local_critical,
                "warnings": local_warnings,
            }
        )

    summary = {
        "slides_checked": len(slides),
        "critical_count": len(critical),
        "warning_count": len(warnings),
        "status": "pass" if not critical else "fail",
    }
    return {
        "summary": summary,
        "critical": critical,
        "warnings": warnings,
        "slides": per_slide,
    }


def audit_report_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Layout Audit",
        "",
        f"- Status: `{summary.get('status', 'unknown')}`",
        f"- Slides checked: {summary.get('slides_checked', 0)}",
        f"- Critical issues: {summary.get('critical_count', 0)}",
        f"- Warnings: {summary.get('warning_count', 0)}",
        "",
    ]
    critical = report.get("critical") or []
    warnings = report.get("warnings") or []
    if critical:
        lines.append("## Critical")
        lines.append("")
        for item in critical:
            lines.append(f"- Slide {item.get('slide')}: {item.get('message')}")
        lines.append("")
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for item in warnings[:30]:
            lines.append(f"- Slide {item.get('slide')}: {item.get('message')}")
        if len(warnings) > 30:
            lines.append(f"- ... {len(warnings) - 30} more warning(s)")
        lines.append("")
    if not critical and not warnings:
        lines.append("No alignment or consistency risks detected by static audit.")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _estimate_block_height(block_type: str, props: dict[str, Any]) -> int:
    if block_type == "eyebrow":
        return 280000
    if block_type == "heading":
        text = str(props.get("text") or "")
        if len(text) < 36:
            return 900000
        if len(text) < 60:
            return 1150000
        return 1400000
    if block_type == "subheading":
        text = str(props.get("text") or "")
        return 500000 if len(text) < 110 else 800000
    if block_type == "paragraph":
        text = str(props.get("text") or "")
        lines = max(1, (len(text) // 75) + 1)
        return min(2200000, 280000 * lines)
    if block_type == "bullets":
        items = [str(i) for i in (props.get("items") or []) if str(i).strip()][:6]
        return min(2800000, 350000 * len(items))
    if block_type == "metric_row":
        return 750000
    if block_type == "quote":
        text = str(props.get("text") or "")
        return 700000 if len(text) < 200 else 1000000
    if block_type == "callout":
        text = str(props.get("text") or "")
        return 550000 if len(text) < 140 else 900000
    if block_type == "image":
        return 1800000
    if block_type == "chart":
        return 1800000
    if block_type == "diagram":
        return 1650000
    if block_type == "spacer":
        size = str(props.get("size") or "md")
        return {"sm": 120000, "md": 240000, "lg": 480000}.get(size, 240000)
    if block_type == "hero_stat":
        return 1500000
    if block_type == "highlight":
        text = str(props.get("text") or "")
        return 700000 if len(text) < 160 else 1000000
    if block_type == "table":
        headers = props.get("headers") or []
        rows = props.get("rows") or []
        header_h = 360000 if headers else 0
        return (280000 if props.get("caption") else 0) + header_h + (360000 * len(rows))
    return 0


def _text_risk(block_type: str, props: dict[str, Any]) -> str:
    if block_type == "heading":
        text = str(props.get("text") or "")
        if len(text) > 110:
            return "Heading is very long and may wrap aggressively."
    if block_type == "subheading":
        text = str(props.get("text") or "")
        if len(text) > 240:
            return "Subheading is long and may crowd body blocks."
    if block_type == "bullets":
        items = [str(i) for i in (props.get("items") or []) if str(i).strip()]
        long_items = [i for i in items if len(i) > 170]
        if long_items:
            return "One or more bullets are very long."
        if len(items) > 5:
            return "More than 5 bullets may reduce readability."
    if block_type == "paragraph":
        text = str(props.get("text") or "")
        if len(text) > 700:
            return "Paragraph is very long."
    if block_type == "table":
        rows = props.get("rows") or []
        if len(rows) > 8:
            return "Table has many rows and may clip in PPTX."
    return ""
