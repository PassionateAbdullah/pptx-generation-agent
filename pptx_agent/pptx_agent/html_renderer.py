from __future__ import annotations

from .utils import escape_html


def render_preview_fragment(deck: dict) -> str:
    slides = "\n".join(_render_slide(slide) for slide in deck["slides"])
    return f'<section class="deck-stage" aria-label="Slide preview">{slides}</section>'


def render_full_html(deck: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
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


def _render_slide(slide: dict) -> str:
    bullets = "".join(f"<li>{escape_html(item)}</li>" for item in slide.get("bullets", []))
    metrics = "".join(
        f"""<div class="metric">
          <strong>{escape_html(item.get("value", ""))}</strong>
          <span>{escape_html(item.get("label", ""))}</span>
        </div>"""
        for item in slide.get("metrics", [])
    )
    layout = escape_html(slide.get("layout", "solution"))
    return f"""<article class="slide slide-{layout}" data-slide="{slide["number"]}">
  <div class="slide-topline">
    <span>{slide["number"]:02d}</span>
    <span>{escape_html(slide.get("eyebrow", ""))}</span>
  </div>
  <div class="slide-grid">
    <section class="slide-copy">
      <p class="eyebrow">{escape_html(slide.get("eyebrow", ""))}</p>
      <h2>{escape_html(slide.get("title", ""))}</h2>
      <p class="subtitle">{escape_html(slide.get("subtitle", ""))}</p>
      <ul>{bullets}</ul>
    </section>
    <aside class="slide-visual" aria-hidden="true">
      {_visual_markup(slide)}
    </aside>
  </div>
  <div class="metric-row">{metrics}</div>
</article>"""


def _visual_markup(slide: dict) -> str:
    layout = slide.get("layout", "solution")
    metrics = slide.get("metrics", [])
    if layout == "cover":
        return """<div class="visual-orbit">
          <span></span><span></span><span></span><span></span><span></span>
        </div>"""
    if layout in {"architecture", "solution"}:
        return """<div class="flow">
          <b>Research</b><i></i><b>Plan</b><i></i><b>HTML</b><i></i><b>PPTX</b>
        </div>"""
    if layout in {"market", "metrics", "ask"}:
        bars = []
        values = [86, 64, 42, 72]
        for index, value in enumerate(values, start=1):
            label = metrics[index - 1]["label"] if index - 1 < len(metrics) else f"Signal {index}"
            bars.append(
                f'<div class="bar"><span style="height:{value}%"></span><em>{escape_html(label)}</em></div>'
            )
        return f'<div class="bars">{"".join(bars)}</div>'
    if layout in {"comparison", "team"}:
        return """<div class="matrix">
          <span>Context</span><span>Quality</span><span>Governance</span><span>Scale</span>
        </div>"""
    return """<div class="signal-card">
      <b>Verified narrative</b>
      <span>Source-aware plan</span>
      <span>Slide-by-slide preview</span>
      <span>Export-ready format</span>
    </div>"""


def _standalone_css() -> str:
    return """
:root {
  color-scheme: light;
  --ink: #17202a;
  --muted: #53606d;
  --line: #d9e0e6;
  --panel: #ffffff;
  --bg: #f3f6f8;
  --teal: #087c7c;
  --amber: #d98f1f;
  --coral: #c95746;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { width: min(1180px, calc(100% - 32px)); margin: 28px auto; }
.print-header { margin: 0 0 18px; }
.print-header p { margin: 0 0 4px; color: var(--teal); font-weight: 700; text-transform: uppercase; font-size: 12px; }
.print-header h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
.deck-stage { display: grid; gap: 22px; }
.slide { position: relative; overflow: hidden; aspect-ratio: 16 / 9; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 34px; box-shadow: 0 18px 42px rgba(23,32,42,.08); }
.slide::before { content: ""; position: absolute; inset: 0 0 auto; height: 8px; background: linear-gradient(90deg, var(--teal), var(--amber), var(--coral)); }
.slide-topline { display: flex; justify-content: space-between; gap: 18px; color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; }
.slide-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(260px, .9fr); gap: 26px; align-items: center; height: calc(100% - 90px); }
.eyebrow { color: var(--teal); font-size: 13px; text-transform: uppercase; font-weight: 850; margin: 0 0 10px; }
h2 { margin: 0; font-size: 38px; line-height: 1.04; letter-spacing: 0; max-width: 13ch; }
.subtitle { color: var(--muted); font-size: 17px; line-height: 1.45; max-width: 58ch; }
ul { margin: 20px 0 0; padding-left: 20px; color: #2f3b46; font-size: 16px; line-height: 1.42; }
li + li { margin-top: 8px; }
.slide-visual { min-height: 260px; border-left: 1px solid var(--line); padding-left: 26px; display: grid; place-items: center; }
.metric-row { position: absolute; left: 34px; right: 34px; bottom: 26px; display: flex; gap: 12px; flex-wrap: wrap; }
.metric { min-width: 130px; border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fbfcfd; }
.metric strong { display: block; font-size: 22px; color: var(--teal); }
.metric span { display: block; color: var(--muted); font-size: 11px; text-transform: uppercase; font-weight: 800; }
.visual-orbit { width: 270px; height: 270px; border: 1px solid var(--line); border-radius: 50%; position: relative; background: radial-gradient(circle, rgba(8,124,124,.2), rgba(255,255,255,0) 58%); }
.visual-orbit span { position: absolute; width: 54px; height: 54px; border-radius: 16px; background: var(--teal); box-shadow: 0 12px 22px rgba(8,124,124,.18); }
.visual-orbit span:nth-child(1) { left: 108px; top: 108px; background: var(--ink); }
.visual-orbit span:nth-child(2) { left: 20px; top: 62px; background: var(--amber); }
.visual-orbit span:nth-child(3) { right: 22px; top: 52px; }
.visual-orbit span:nth-child(4) { left: 50px; bottom: 28px; background: var(--coral); }
.visual-orbit span:nth-child(5) { right: 42px; bottom: 44px; background: #6f7b85; }
.flow { width: 100%; display: grid; grid-template-columns: 1fr 20px 1fr; gap: 12px; align-items: center; }
.flow b { min-height: 74px; display: grid; place-items: center; border-radius: 8px; background: #eef6f5; color: var(--teal); border: 1px solid #c8ddda; }
.flow i { height: 2px; background: var(--amber); }
.bars { height: 250px; width: 100%; display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; align-items: end; }
.bar { height: 100%; display: grid; grid-template-rows: 1fr auto; gap: 8px; color: var(--muted); font-size: 11px; font-weight: 800; text-transform: uppercase; }
.bar span { align-self: end; border-radius: 8px 8px 2px 2px; background: linear-gradient(180deg, var(--teal), var(--amber)); }
.matrix { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.matrix span, .signal-card span, .signal-card b { border: 1px solid var(--line); border-radius: 8px; padding: 18px; background: #fbfcfd; color: var(--ink); font-weight: 800; }
.signal-card { display: grid; width: 100%; gap: 12px; }
.signal-card b { background: var(--ink); color: white; }
@media (max-width: 760px) {
  main { width: min(100% - 16px, 680px); }
  .slide { aspect-ratio: auto; min-height: 720px; padding: 24px; }
  .slide-grid { grid-template-columns: 1fr; height: auto; }
  .slide-visual { min-height: 180px; border-left: 0; border-top: 1px solid var(--line); padding: 20px 0 0; }
  h2 { font-size: 30px; max-width: none; }
  .metric-row { position: static; margin-top: 20px; }
}
"""

