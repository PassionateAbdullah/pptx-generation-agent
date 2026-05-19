"""Block-based slide content model.

A slide is a sequence of typed blocks. Each block carries an opaque id
(stable across regenerations), a type tag, and a typed ``props`` dict.

Block schema (type -> props):

    eyebrow      {text: str}
    heading      {text: str, level: 1|2}
    subheading   {text: str}
    paragraph    {text: str}
    bullets      {items: [str]}
    metric_row   {metrics: [{label: str, value: str}]}
    quote        {text: str, attribution: str}
    callout      {tone: "info"|"warn"|"success", text: str}
    image        {src: str, alt: str, fit: "cover"|"contain", caption: str}
    chart        {kind: "bar"|"line"|"pie"|"area",
                  series: [{label, values: [number]}],
                  labels: [str], title: str}
    diagram      {kind: "flow"|"matrix"|"orbit", nodes: [{label, role?}]}
    spacer       {size: "sm"|"md"|"lg"}

The PPTX writer and HTML renderer dispatch on ``type``. Unknown types are
rendered as paragraphs by the HTML renderer and skipped by the PPTX writer.
"""

from __future__ import annotations

from typing import Any, Iterable

BLOCK_TYPES = {
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

_DIAGRAM_BY_LAYOUT = {
    "cover": "orbit",
    "architecture": "flow",
    "solution": "flow",
    "comparison": "matrix",
    "team": "matrix",
}


def make_block(slide_number: int, index: int, type_: str, **props: Any) -> dict[str, Any]:
    return {
        "id": f"s{slide_number}-b{index}-{type_}",
        "type": type_,
        "props": {k: v for k, v in props.items() if v is not None},
    }


def normalize_block(slide_number: int, index: int, raw: Any) -> dict[str, Any] | None:
    """Coerce loosely-shaped block dicts (e.g. from LLM output) into the schema."""
    if not isinstance(raw, dict):
        return None
    type_ = str(raw.get("type") or "").strip().lower()
    if type_ not in BLOCK_TYPES:
        return None
    props = raw.get("props") if isinstance(raw.get("props"), dict) else {}
    props = dict(props)

    if type_ == "bullets":
        items = props.get("items") or raw.get("items") or []
        if isinstance(items, str):
            items = [items]
        props["items"] = [str(i) for i in items if i]
    elif type_ == "metric_row":
        metrics = props.get("metrics") or raw.get("metrics") or []
        props["metrics"] = [_coerce_metric(m) for m in metrics if isinstance(m, dict)]
    elif type_ == "chart":
        kind = str(props.get("kind") or "bar").lower()
        if kind not in {"bar", "line", "area", "pie"}:
            kind = "bar"
        raw_series = props.get("series") or []
        clean_series: list[dict[str, Any]] = []
        for s in raw_series:
            if not isinstance(s, dict):
                continue
            values_raw = s.get("values") or []
            values: list[float] = []
            for v in values_raw:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    continue
            clean_series.append({"label": str(s.get("label") or ""), "values": values})
        raw_labels = props.get("labels") or []
        if not isinstance(raw_labels, (list, tuple)):
            raw_labels = []
        props["kind"] = kind
        props["series"] = clean_series
        props["labels"] = [str(l) for l in raw_labels]
        props["title"] = str(props.get("title") or "")
    elif type_ == "diagram":
        props.setdefault("kind", "flow")
        nodes = props.get("nodes") or []
        props["nodes"] = [n for n in nodes if isinstance(n, dict)]
    elif type_ == "image":
        props.setdefault("fit", "cover")
        props.setdefault("alt", "")
        props.setdefault("caption", "")
    elif type_ == "callout":
        props.setdefault("tone", "info")
    elif type_ == "hero_stat":
        props.setdefault("value", "")
        props.setdefault("label", "")
        props.setdefault("trend", "")  # e.g. "▲ +12%"
        props.setdefault("source_id", "")
    elif type_ == "highlight":
        props.setdefault("tone", "accent")  # accent | warn | success | danger
        props.setdefault("title", "")
        props.setdefault("text", "")
    elif type_ == "table":
        # Shape: { headers: [str], rows: [[str]], caption: str }
        headers = props.get("headers") or []
        rows = props.get("rows") or []
        if not isinstance(headers, (list, tuple)):
            headers = []
        clean_rows: list[list[str]] = []
        if isinstance(rows, (list, tuple)):
            for r in rows:
                if isinstance(r, (list, tuple)):
                    clean_rows.append([str(c) for c in r])
        props["headers"] = [str(h) for h in headers]
        props["rows"] = clean_rows
        props["caption"] = str(props.get("caption") or "")

    return {
        "id": str(raw.get("id") or f"s{slide_number}-b{index}-{type_}"),
        "type": type_,
        "props": props,
    }


def normalize_blocks(slide_number: int, raw: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw, start=1):
        normalized = normalize_block(slide_number, i, item)
        if normalized is not None:
            out.append(normalized)
    return out


def slide_to_blocks(slide: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapter: derive a blocks list from a legacy slide dict.

    Used as a fallback when planner or LLM does not provide explicit blocks.
    Order follows: eyebrow -> heading -> subheading -> bullets -> metric_row
    -> diagram (for visual layouts).
    """
    number = int(slide.get("number") or 0)
    blocks: list[dict[str, Any]] = []
    idx = 1

    eyebrow = str(slide.get("eyebrow") or "").strip()
    if eyebrow:
        blocks.append(make_block(number, idx, "eyebrow", text=eyebrow))
        idx += 1

    title = str(slide.get("title") or "").strip()
    if title:
        blocks.append(make_block(number, idx, "heading", text=title, level=1))
        idx += 1

    subtitle = str(slide.get("subtitle") or "").strip()
    if subtitle:
        blocks.append(make_block(number, idx, "subheading", text=subtitle))
        idx += 1

    bullets = [str(b) for b in (slide.get("bullets") or []) if str(b).strip()]
    if bullets:
        blocks.append(make_block(number, idx, "bullets", items=bullets))
        idx += 1

    metrics = [_coerce_metric(m) for m in (slide.get("metrics") or []) if isinstance(m, dict)]
    metrics = [m for m in metrics if m["label"] or m["value"]]
    if metrics:
        blocks.append(make_block(number, idx, "metric_row", metrics=metrics))
        idx += 1

    layout = str(slide.get("layout") or "").lower()
    diagram_kind = _DIAGRAM_BY_LAYOUT.get(layout)
    if diagram_kind:
        nodes = _diagram_nodes(layout, slide)
        if nodes:
            blocks.append(make_block(number, idx, "diagram", kind=diagram_kind, nodes=nodes))
            idx += 1

    return blocks


def _coerce_metric(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"label": "", "value": ""}
    return {
        "label": str(raw.get("label") or "").strip(),
        "value": str(raw.get("value") or "").strip(),
    }


def _diagram_nodes(layout: str, slide: dict[str, Any]) -> list[dict[str, str]]:
    if layout == "cover":
        return [{"label": label} for label in ["Plan", "Research", "Draft", "Render", "Export"]]
    if layout in {"architecture", "solution"}:
        return [
            {"label": "Research"},
            {"label": "Plan"},
            {"label": "HTML"},
            {"label": "PPTX"},
        ]
    if layout in {"comparison", "team"}:
        return [
            {"label": "Context"},
            {"label": "Quality"},
            {"label": "Governance"},
            {"label": "Scale"},
        ]
    return []
