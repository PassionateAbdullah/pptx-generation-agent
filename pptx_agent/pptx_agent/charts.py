"""SVG chart renderer for chart blocks.

Pure-Python SVG generation so the standalone ``slides.html`` export carries
real charts without a JS runtime. The frontend mirrors the same data shape
and math in ``frontend/src/components/ChartView.tsx`` so the editor preview
matches the exported HTML exactly.

Supported kinds: ``bar``, ``line``, ``area``, ``pie``.

Data contract:

    series = [
        {"label": "Revenue", "values": [1.2, 3.4, 5.1, 4.0]},
        {"label": "Cost",    "values": [0.8, 2.1, 3.2, 3.0]},
    ]
    labels = ["Q1", "Q2", "Q3", "Q4"]

For ``pie`` charts only the first series is used; values become slice sizes.
"""

from __future__ import annotations

import math
from typing import Any

from .utils import escape_html

VIEW_W = 480
VIEW_H = 220
PAD_L = 36
PAD_R = 12
PAD_T = 10
PAD_B = 28
CHART_W = VIEW_W - PAD_L - PAD_R
CHART_H = VIEW_H - PAD_T - PAD_B


def render_chart_svg(
    kind: str,
    series: list[dict[str, Any]],
    labels: list[str],
    title: str = "",
) -> str:
    """Return an SVG string for the given chart spec. Inherits color tokens
    from the ambient ``var(--accent)`` / ``var(--accent-soft)`` so charts
    re-theme with the rest of the deck."""

    kind = (kind or "bar").lower()
    cleaned_series = _clean_series(series)
    labels = [str(l) for l in (labels or [])]

    if not cleaned_series or all(not s["values"] for s in cleaned_series):
        return _empty_svg(title)

    if kind == "pie":
        return _wrap_svg(title, _render_pie(cleaned_series[0]))
    if kind == "line":
        return _wrap_svg(title, _render_line(cleaned_series, labels, fill=False))
    if kind == "area":
        return _wrap_svg(title, _render_line(cleaned_series, labels, fill=True))
    return _wrap_svg(title, _render_bar(cleaned_series, labels))


def _clean_series(series: list[Any]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for s in series or []:
        if not isinstance(s, dict):
            continue
        values: list[float] = []
        for v in s.get("values") or []:
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
        cleaned.append({"label": str(s.get("label") or ""), "values": values})
    return cleaned


def _wrap_svg(title: str, body: str) -> str:
    title_html = (
        f'<text x="{PAD_L}" y="{PAD_T + 2}" class="chart-svg-title">{escape_html(title)}</text>'
        if title
        else ""
    )
    return (
        f'<svg viewBox="0 0 {VIEW_W} {VIEW_H}" xmlns="http://www.w3.org/2000/svg" '
        f'class="chart-svg" role="img" aria-label="{escape_html(title or "chart")}">'
        f"<style>"
        f".chart-svg-axis {{ stroke: var(--line, #d9e0e6); stroke-width: 1; }}"
        f".chart-svg-tick {{ fill: var(--muted, #53606d); font-size: 9px; font-family: var(--font-body, sans-serif); }}"
        f".chart-svg-title {{ fill: var(--muted, #53606d); font-size: 10px; text-transform: uppercase; "
        f"letter-spacing: 0.06em; font-weight: 700; font-family: var(--font-body, sans-serif); }}"
        f".chart-svg-bar {{ fill: var(--accent, #087c7c); }}"
        f".chart-svg-bar-alt {{ fill: var(--warn, #d98f1f); }}"
        f".chart-svg-line {{ fill: none; stroke: var(--accent, #087c7c); stroke-width: 2; stroke-linejoin: round; }}"
        f".chart-svg-line-alt {{ fill: none; stroke: var(--warn, #d98f1f); stroke-width: 2; stroke-linejoin: round; }}"
        f".chart-svg-area {{ fill: var(--accent-soft, rgba(0,0,0,0.08)); }}"
        f".chart-svg-pie-a {{ fill: var(--accent, #087c7c); }}"
        f".chart-svg-pie-b {{ fill: var(--warn, #d98f1f); }}"
        f".chart-svg-pie-c {{ fill: var(--danger, #c95746); }}"
        f".chart-svg-pie-d {{ fill: var(--muted, #53606d); }}"
        f"</style>"
        f"{title_html}{body}</svg>"
    )


def _render_bar(series: list[dict[str, Any]], labels: list[str]) -> str:
    points = max((len(s["values"]) for s in series), default=0)
    if points == 0:
        return ""
    peak = max((max((abs(v) for v in s["values"]), default=0) for s in series), default=1.0) or 1.0
    group_w = CHART_W / points
    band_w = group_w * 0.78
    bar_w = band_w / max(1, len(series))
    fragments: list[str] = []
    axis_y = PAD_T + CHART_H
    fragments.append(
        f'<line class="chart-svg-axis" x1="{PAD_L}" y1="{axis_y}" x2="{PAD_L + CHART_W}" y2="{axis_y}"/>'
    )
    for i in range(points):
        x_center = PAD_L + group_w * (i + 0.5)
        for s_idx, s in enumerate(series):
            try:
                value = s["values"][i]
            except IndexError:
                continue
            height = max(2.0, abs(value) / peak * (CHART_H - 8))
            x = x_center - band_w / 2 + s_idx * bar_w
            y = axis_y - height
            cls = "chart-svg-bar" if s_idx % 2 == 0 else "chart-svg-bar-alt"
            fragments.append(
                f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{bar_w - 2:.1f}" height="{height:.1f}" rx="2"/>'
            )
        label = labels[i] if i < len(labels) else ""
        if label:
            fragments.append(
                f'<text class="chart-svg-tick" x="{x_center:.1f}" y="{axis_y + 14}" text-anchor="middle">{escape_html(label)}</text>'
            )
    return "".join(fragments)


def _render_line(series: list[dict[str, Any]], labels: list[str], fill: bool) -> str:
    points = max((len(s["values"]) for s in series), default=0)
    if points < 2:
        # A single point line is meaningless; fall back to bar so user still sees data.
        return _render_bar(series, labels)
    peak = max((max((abs(v) for v in s["values"]), default=0) for s in series), default=1.0) or 1.0
    step = CHART_W / (points - 1)
    axis_y = PAD_T + CHART_H
    fragments: list[str] = [
        f'<line class="chart-svg-axis" x1="{PAD_L}" y1="{axis_y}" x2="{PAD_L + CHART_W}" y2="{axis_y}"/>'
    ]
    for s_idx, s in enumerate(series):
        pts: list[str] = []
        for i, v in enumerate(s["values"]):
            x = PAD_L + step * i
            y = axis_y - max(2.0, abs(v) / peak * (CHART_H - 8))
            pts.append(f"{x:.1f},{y:.1f}")
        if not pts:
            continue
        if fill and s_idx == 0:
            area_pts = pts + [f"{PAD_L + step * (len(s['values']) - 1):.1f},{axis_y:.1f}", f"{PAD_L:.1f},{axis_y:.1f}"]
            fragments.append(f'<polygon class="chart-svg-area" points="{" ".join(area_pts)}"/>')
        cls = "chart-svg-line" if s_idx % 2 == 0 else "chart-svg-line-alt"
        fragments.append(f'<polyline class="{cls}" points="{" ".join(pts)}"/>')
    for i in range(points):
        x = PAD_L + step * i
        label = labels[i] if i < len(labels) else ""
        if label:
            fragments.append(
                f'<text class="chart-svg-tick" x="{x:.1f}" y="{axis_y + 14}" text-anchor="middle">{escape_html(label)}</text>'
            )
    return "".join(fragments)


def _render_pie(series_entry: dict[str, Any]) -> str:
    values = [abs(v) for v in series_entry["values"] if v != 0]
    if not values:
        return ""
    total = sum(values) or 1.0
    cx = PAD_L + CHART_W / 2
    cy = PAD_T + CHART_H / 2
    radius = min(CHART_W, CHART_H) / 2 - 6
    angle = -math.pi / 2  # start at 12 o'clock
    fragments: list[str] = []
    palette = ["chart-svg-pie-a", "chart-svg-pie-b", "chart-svg-pie-c", "chart-svg-pie-d"]
    for i, value in enumerate(values):
        slice_angle = (value / total) * 2 * math.pi
        end = angle + slice_angle
        large_arc = 1 if slice_angle > math.pi else 0
        x1 = cx + radius * math.cos(angle)
        y1 = cy + radius * math.sin(angle)
        x2 = cx + radius * math.cos(end)
        y2 = cy + radius * math.sin(end)
        cls = palette[i % len(palette)]
        path = (
            f"M{cx:.1f},{cy:.1f} "
            f"L{x1:.1f},{y1:.1f} "
            f"A{radius:.1f},{radius:.1f} 0 {large_arc} 1 {x2:.1f},{y2:.1f} Z"
        )
        fragments.append(f'<path class="{cls}" d="{path}"/>')
        angle = end
    return "".join(fragments)


def _empty_svg(title: str) -> str:
    label = escape_html(title or "chart")
    return (
        f'<svg viewBox="0 0 {VIEW_W} 80" xmlns="http://www.w3.org/2000/svg" '
        f'class="chart-svg chart-svg-empty" role="img" aria-label="{label}">'
        f'<rect x="0" y="0" width="{VIEW_W}" height="80" fill="none" stroke="var(--line, #d9e0e6)" '
        f'stroke-dasharray="4 4" rx="6"/>'
        f'<text x="{VIEW_W / 2}" y="44" text-anchor="middle" '
        f'style="font-family: sans-serif; font-size: 12px; fill: var(--muted, #53606d);">{label} — no data</text>'
        f"</svg>"
    )
