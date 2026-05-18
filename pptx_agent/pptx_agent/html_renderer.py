from __future__ import annotations

from typing import Any

from .blocks import slide_to_blocks
from .charts import render_chart_svg
from .themes import all_theme_css, get_theme
from .utils import escape_html


def render_preview_fragment(deck: dict) -> str:
    slides = "\n".join(_render_slide(slide) for slide in deck["slides"])
    return f'<section class="deck-stage" aria-label="Slide preview">{slides}</section>'


def render_full_html(deck: dict) -> str:
    theme = get_theme(deck.get("theme"))
    return f"""<!doctype html>
<html lang="en" data-theme="{escape_html(theme.name)}" data-theme-mode="{escape_html(theme.mode)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(deck["title"])}</title>
  <style>{_standalone_css()}</style>
</head>
<body>
  <main>
    <header class="print-header">
      <p>{escape_html(deck.get("topic", ""))}</p>
      <h1>{escape_html(deck["title"])}</h1>
    </header>
    {render_preview_fragment(deck)}
  </main>
</body>
</html>
"""


def _render_slide(slide: dict[str, Any]) -> str:
    blocks = slide.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        blocks = slide_to_blocks(slide)

    layout = escape_html(slide.get("layout", "solution"))
    variant = int(slide.get("accent_variant") or ((int(slide.get("number") or 1) - 1) % 4))
    body = "\n".join(_render_block(block) for block in blocks)
    return f"""<article class="slide slide-{layout} slide-accent-{variant}" data-slide="{slide["number"]}" data-slide-id="{escape_html(slide.get("id", ""))}" data-accent-variant="{variant}">
  <div class="slide-topline">
    <span>{slide["number"]:02d}</span>
    <span>{escape_html(slide.get("eyebrow", ""))}</span>
  </div>
  <div class="slide-body">
    {body}
  </div>
</article>"""


def _render_block(block: dict[str, Any]) -> str:
    type_ = str(block.get("type") or "")
    props = block.get("props") or {}
    block_id = escape_html(str(block.get("id") or ""))
    renderer = _BLOCK_RENDERERS.get(type_, _render_unknown)
    inner = renderer(props)
    return f'<div class="block block-{escape_html(type_)}" data-block-id="{block_id}">{inner}</div>'


def _render_eyebrow(props: dict[str, Any]) -> str:
    text = escape_html(str(props.get("text") or ""))
    return f'<p class="eyebrow">{text}</p>'


def _render_heading(props: dict[str, Any]) -> str:
    text = escape_html(str(props.get("text") or ""))
    level = int(props.get("level") or 1)
    tag = "h2" if level <= 1 else "h3"
    return f"<{tag}>{text}</{tag}>"


def _render_subheading(props: dict[str, Any]) -> str:
    text = escape_html(str(props.get("text") or ""))
    return f'<p class="subtitle">{text}</p>'


def _render_paragraph(props: dict[str, Any]) -> str:
    text = escape_html(str(props.get("text") or ""))
    return f"<p>{text}</p>"


def _render_bullets(props: dict[str, Any]) -> str:
    items = props.get("items") or []
    rendered = "".join(f"<li>{escape_html(str(item))}</li>" for item in items)
    return f"<ul>{rendered}</ul>"


def _render_metric_row(props: dict[str, Any]) -> str:
    metrics = props.get("metrics") or []
    cards = "".join(
        f"""<div class="metric">
          <strong>{escape_html(str(m.get("value", "")))}</strong>
          <span>{escape_html(str(m.get("label", "")))}</span>
        </div>"""
        for m in metrics
    )
    return f'<div class="metric-row">{cards}</div>'


def _render_quote(props: dict[str, Any]) -> str:
    text = escape_html(str(props.get("text") or ""))
    attribution = escape_html(str(props.get("attribution") or ""))
    cite = f'<cite>— {attribution}</cite>' if attribution else ""
    return f'<blockquote>{text}{cite}</blockquote>'


def _render_callout(props: dict[str, Any]) -> str:
    tone = escape_html(str(props.get("tone") or "info"))
    text = escape_html(str(props.get("text") or ""))
    return f'<aside class="callout callout-{tone}">{text}</aside>'


def _render_image(props: dict[str, Any]) -> str:
    src = escape_html(str(props.get("src") or ""))
    alt = escape_html(str(props.get("alt") or ""))
    fit = escape_html(str(props.get("fit") or "cover"))
    caption = escape_html(str(props.get("caption") or ""))
    if not src:
        placeholder = f'<div class="image-placeholder">image: {alt or "missing"}</div>'
        cap = f'<figcaption>{caption}</figcaption>' if caption else ""
        return f"<figure>{placeholder}{cap}</figure>"
    img = f'<img src="{src}" alt="{alt}" loading="lazy" style="object-fit:{fit}">'
    cap = f'<figcaption>{caption}</figcaption>' if caption else ""
    return f"<figure>{img}{cap}</figure>"


def _render_chart(props: dict[str, Any]) -> str:
    kind = str(props.get("kind") or "bar")
    title = str(props.get("title") or "")
    series = props.get("series") or []
    labels = props.get("labels") or []
    svg = render_chart_svg(kind, list(series) if isinstance(series, list) else [], list(labels) if isinstance(labels, list) else [], title)
    legend = _chart_legend(series)
    return (
        f'<div class="chart chart-{escape_html(kind)}" data-chart-kind="{escape_html(kind)}">'
        f"{svg}{legend}</div>"
    )


def _chart_legend(series: Any) -> str:
    if not isinstance(series, list):
        return ""
    items: list[str] = []
    for i, s in enumerate(series):
        if not isinstance(s, dict):
            continue
        label = str(s.get("label") or "").strip()
        if not label:
            continue
        cls = "chart-legend-a" if i % 2 == 0 else "chart-legend-b"
        items.append(f'<li><i class="{cls}"></i>{escape_html(label)}</li>')
    if not items:
        return ""
    return f'<ul class="chart-legend">{"".join(items)}</ul>'


def _render_diagram(props: dict[str, Any]) -> str:
    kind = str(props.get("kind") or "flow").lower()
    nodes = props.get("nodes") or []
    labels = [str(n.get("label") or "").strip() for n in nodes if isinstance(n, dict)]
    labels = [l for l in labels if l]
    if kind == "orbit":
        pieces = "".join(f'<span title="{escape_html(l)}"></span>' for l in labels[:5] or [""] * 5)
        return f'<div class="visual-orbit">{pieces}</div>'
    if kind == "matrix":
        cells = "".join(f"<span>{escape_html(l)}</span>" for l in labels[:6])
        return f'<div class="matrix">{cells}</div>'
    if not labels:
        labels = ["Step 1", "Step 2", "Step 3"]
    parts: list[str] = []
    for i, label in enumerate(labels):
        if i:
            parts.append('<i></i>')
        parts.append(f"<b>{escape_html(label)}</b>")
    return f'<div class="flow">{"".join(parts)}</div>'


def _render_hero_stat(props: dict[str, Any]) -> str:
    value = escape_html(str(props.get("value") or ""))
    label = escape_html(str(props.get("label") or ""))
    trend = escape_html(str(props.get("trend") or ""))
    source_id = escape_html(str(props.get("source_id") or ""))
    trend_html = f'<span class="hero-trend">{trend}</span>' if trend else ""
    source_html = f'<span class="hero-source">[{source_id}]</span>' if source_id else ""
    return (
        f'<div class="hero-stat">'
        f'<div class="hero-value">{value}{trend_html}</div>'
        f'<div class="hero-label">{label}{source_html}</div>'
        f'</div>'
    )


def _render_highlight(props: dict[str, Any]) -> str:
    tone = escape_html(str(props.get("tone") or "accent"))
    title = escape_html(str(props.get("title") or ""))
    text = escape_html(str(props.get("text") or ""))
    title_html = f'<strong class="highlight-title">{title}</strong>' if title else ""
    return (
        f'<aside class="highlight highlight-{tone}">'
        f'{title_html}<span class="highlight-text">{text}</span>'
        f'</aside>'
    )


def _render_spacer(props: dict[str, Any]) -> str:
    size = escape_html(str(props.get("size") or "md"))
    return f'<div class="spacer spacer-{size}" aria-hidden="true"></div>'


def _render_unknown(props: dict[str, Any]) -> str:
    return ""


_BLOCK_RENDERERS = {
    "eyebrow": _render_eyebrow,
    "heading": _render_heading,
    "subheading": _render_subheading,
    "paragraph": _render_paragraph,
    "bullets": _render_bullets,
    "metric_row": _render_metric_row,
    "quote": _render_quote,
    "callout": _render_callout,
    "image": _render_image,
    "chart": _render_chart,
    "diagram": _render_diagram,
    "spacer": _render_spacer,
    "hero_stat": _render_hero_stat,
    "highlight": _render_highlight,
}


def _standalone_css() -> str:
    return f"""
{all_theme_css()}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font-body); }}
main {{ width: min(1180px, calc(100% - 32px)); margin: 28px auto; }}
.print-header {{ margin: 0 0 18px; }}
.print-header p {{ margin: 0 0 4px; color: var(--accent); font-weight: 700; text-transform: uppercase; font-size: 12px; letter-spacing: .04em; }}
.print-header h1 {{ margin: 0; font-size: 28px; font-family: var(--font-display); }}
.deck-stage {{ display: grid; gap: 22px; }}
.slide {{ position: relative; overflow: hidden; aspect-ratio: 16 / 9; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 34px; box-shadow: 0 18px 42px var(--shadow); display: flex; flex-direction: column; gap: 14px; color: var(--ink); }}
.slide::before {{ content: ""; position: absolute; inset: 0 0 auto; height: 6px; background: linear-gradient(90deg, var(--accent), var(--warn), var(--danger)); }}
.slide-topline {{ display: flex; justify-content: space-between; gap: 18px; color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; }}
.slide-body {{ flex: 1; display: flex; flex-direction: column; gap: 12px; min-height: 0; }}
.block {{ min-width: 0; }}
.block-eyebrow .eyebrow {{ color: var(--accent); font-size: 13px; text-transform: uppercase; font-weight: 850; margin: 0; letter-spacing: .08em; }}
.block-heading h2 {{ margin: 0; font-size: 38px; line-height: 1.04; max-width: 24ch; font-family: var(--font-display); }}
.block-heading h3 {{ margin: 0; font-size: 26px; line-height: 1.1; font-family: var(--font-display); }}
.block-subheading .subtitle {{ color: var(--muted); font-size: 17px; line-height: 1.45; max-width: 70ch; margin: 0; }}
.block-paragraph p {{ margin: 0; color: var(--ink); opacity: .88; font-size: 15px; line-height: 1.5; max-width: 70ch; }}
.block-bullets ul {{ margin: 0; padding-left: 20px; color: var(--ink); font-size: 16px; line-height: 1.42; }}
.block-bullets li + li {{ margin-top: 8px; }}
.block-bullets li::marker {{ color: var(--accent); }}
.block-metric_row .metric-row {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.metric {{ min-width: 130px; border: 1px solid var(--line); border-radius: calc(var(--radius) * .8); padding: 10px 12px; background: var(--panel-alt); }}
.metric strong {{ display: block; font-size: 22px; color: var(--accent); font-family: var(--font-display); }}
.metric span {{ display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; font-weight: 800; }}
.block-quote blockquote {{ margin: 0; padding: 16px 18px; border-left: 4px solid var(--accent); background: var(--panel-alt); color: var(--ink); font-style: italic; }}
.block-quote cite {{ display: block; margin-top: 8px; color: var(--muted); font-style: normal; font-size: 13px; }}
.callout {{ padding: 12px 14px; border-radius: calc(var(--radius) * .8); border: 1px solid var(--line); background: var(--panel-alt); color: var(--ink); }}
.callout-info {{ border-color: var(--accent); background: var(--accent-soft); }}
.callout-warn {{ border-color: var(--warn); background: var(--panel-alt); }}
.callout-success {{ border-color: var(--accent); background: var(--accent-soft); }}
.block-image figure {{ margin: 0; }}
.block-image img {{ width: 100%; max-height: 320px; border-radius: calc(var(--radius) * .8); display: block; }}
.block-image figcaption {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
.image-placeholder {{ display: grid; place-items: center; height: 180px; border: 1px dashed var(--line); border-radius: calc(var(--radius) * .8); color: var(--muted); font-size: 12px; background: var(--panel-alt); }}
.chart {{ display: grid; gap: 6px; }}
.chart-svg {{ width: 100%; height: auto; max-height: 240px; display: block; }}
.chart-svg-empty {{ width: 100%; height: 80px; }}
.chart-legend {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 12px; color: var(--muted); font-size: 12px; }}
.chart-legend li {{ display: inline-flex; align-items: center; gap: 6px; }}
.chart-legend i {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
.chart-legend-a {{ background: var(--accent); }}
.chart-legend-b {{ background: var(--warn); }}
.matrix {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.matrix span {{ border: 1px solid var(--line); border-radius: calc(var(--radius) * .8); padding: 14px; background: var(--panel-alt); color: var(--ink); font-weight: 800; }}
.flow {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
.flow b {{ padding: 12px 14px; border-radius: calc(var(--radius) * .8); background: var(--accent-soft); color: var(--accent); border: 1px solid var(--line); }}
.flow i {{ width: 20px; height: 2px; background: var(--warn); }}
.visual-orbit {{ width: 220px; height: 220px; border: 1px solid var(--line); border-radius: 50%; position: relative; background: radial-gradient(circle, var(--accent-soft), transparent 58%); align-self: center; }}
.visual-orbit span {{ position: absolute; width: 44px; height: 44px; border-radius: 14px; background: var(--accent); box-shadow: 0 12px 22px var(--shadow); }}
.visual-orbit span:nth-child(1) {{ left: 88px; top: 88px; background: var(--ink); }}
.visual-orbit span:nth-child(2) {{ left: 14px; top: 50px; background: var(--warn); }}
.visual-orbit span:nth-child(3) {{ right: 16px; top: 42px; }}
.visual-orbit span:nth-child(4) {{ left: 40px; bottom: 22px; background: var(--danger); }}
.visual-orbit span:nth-child(5) {{ right: 34px; bottom: 36px; background: var(--muted); }}
.spacer-sm {{ height: 8px; }}
.spacer-md {{ height: 16px; }}
.spacer-lg {{ height: 32px; }}
/* Per-slide accent rotation — keeps theme but cycles the headline color across slides. */
.slide-accent-0 {{ /* primary accent — default */ }}
.slide-accent-1 {{ --accent: var(--warn); --accent-soft: color-mix(in srgb, var(--warn) 18%, transparent); }}
.slide-accent-2 {{ --accent: var(--danger); --accent-soft: color-mix(in srgb, var(--danger) 18%, transparent); }}
.slide-accent-3 {{ --accent: var(--accent-strong); --accent-soft: color-mix(in srgb, var(--accent-strong) 18%, transparent); }}
.hero-stat {{ display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: 12px 0; }}
.hero-value {{ font-size: 96px; line-height: 1; font-weight: 900; color: var(--accent); font-family: var(--font-display); letter-spacing: -0.02em; display: flex; align-items: baseline; gap: 12px; }}
.hero-value .hero-trend {{ font-size: 22px; color: var(--warn); font-weight: 700; }}
.hero-label {{ font-size: 16px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; }}
.hero-label .hero-source {{ margin-left: 8px; color: var(--accent); font-size: 12px; }}
.highlight {{ display: flex; flex-direction: column; gap: 6px; padding: 16px 18px; border-radius: calc(var(--radius) * .8); border-left: 6px solid var(--accent); background: linear-gradient(135deg, var(--accent-soft), transparent 80%); }}
.highlight-accent {{ border-left-color: var(--accent); }}
.highlight-warn {{ border-left-color: var(--warn); background: linear-gradient(135deg, color-mix(in srgb, var(--warn) 16%, transparent), transparent 80%); }}
.highlight-success {{ border-left-color: var(--accent); }}
.highlight-danger {{ border-left-color: var(--danger); background: linear-gradient(135deg, color-mix(in srgb, var(--danger) 16%, transparent), transparent 80%); }}
.highlight-title {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); font-weight: 800; }}
.highlight-text {{ font-size: 18px; line-height: 1.35; color: var(--ink); font-weight: 500; }}
@media (max-width: 760px) {{
  main {{ width: min(100% - 16px, 680px); }}
  .slide {{ aspect-ratio: auto; min-height: 640px; padding: 24px; }}
  .block-heading h2 {{ font-size: 30px; max-width: none; }}
  .chart .bars {{ height: 140px; }}
}}
"""
