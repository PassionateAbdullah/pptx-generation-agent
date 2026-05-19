"""DOM-rule visual inspector.

Parses the rendered ``slide-NN.html`` and reports issues the audit can't
see from the deck dict alone: empty chart svg, table with no body rows,
broken image references, text density overflow proxy, block-count
mismatches, citation tokens missing from the slide's declared citations.

stdlib only (uses ``html.parser``). No Playwright, no headless browser.

Public surface:

- ``VisualFinding`` dataclass.
- ``inspect_slide_html(html_text, slide_dict) -> list[VisualFinding]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

_CITATION_RE = re.compile(r"\[S\d+\]")
_DENSITY_OVERFLOW_THRESHOLD = 1500  # chars of visible text per slide
_DATA_TAGS = {"rect", "polyline", "path", "line", "circle"}


@dataclass
class VisualFinding:
    code: str
    severity: str  # "error" | "warn" | "info"
    message: str
    suggested_fix: str = ""


def inspect_slide_html(html_text: str, slide_dict: dict[str, Any]) -> list[VisualFinding]:
    parser = _SlideHTMLParser()
    parser.feed(html_text)
    findings: list[VisualFinding] = []

    blocks = slide_dict.get("blocks") or []
    declared_block_types = [str(b.get("type") or "") for b in blocks]

    # --- Chart svg emptiness ---
    for chart in parser.charts:
        data_tags = sum(chart.tag_counts.get(t, 0) for t in _DATA_TAGS)
        if data_tags == 0:
            findings.append(VisualFinding(
                code="chart-empty-render",
                severity="error",
                message="chart svg rendered without any data shapes",
                suggested_fix="re-author chart block using verbatim values from signals",
            ))

    # --- Table emptiness ---
    for tbl in parser.tables:
        if tbl.body_rows < 2:
            findings.append(VisualFinding(
                code="table-empty-render",
                severity="error",
                message=f"table rendered with {tbl.body_rows} body row(s)",
                suggested_fix="re-author table with ≥3 grounded rows or switch block type to diagram",
            ))

    # --- Image src placeholder ---
    for src in parser.image_srcs:
        if not src or src.lower().startswith("data:") and len(src) < 32:
            findings.append(VisualFinding(
                code="image-broken",
                severity="error",
                message="image block rendered without a valid src",
                suggested_fix="drop the image block or attach a real local media file",
            ))

    # --- Text density (overflow proxy without a real browser) ---
    visible_chars = len(parser.visible_text.strip())
    if visible_chars > _DENSITY_OVERFLOW_THRESHOLD:
        findings.append(VisualFinding(
            code="density-too-high",
            severity="warn",
            message=f"slide has {visible_chars} visible chars (>{_DENSITY_OVERFLOW_THRESHOLD}); likely overflow",
            suggested_fix="shorten paragraph/bullets blocks or split the slide",
        ))

    # --- Block-render count mismatch ---
    if declared_block_types:
        if parser.rendered_block_types:
            # Compare counts only — order/normalisation differences are fine.
            from collections import Counter
            want = Counter(declared_block_types)
            got = Counter(parser.rendered_block_types)
            if want != got:
                findings.append(VisualFinding(
                    code="block-render-mismatch",
                    severity="warn",
                    message=f"declared blocks {dict(want)} vs rendered {dict(got)}",
                    suggested_fix="check html_renderer for unsupported block types",
                ))

    # --- Citation token mismatch ---
    rendered_cites = set(_CITATION_RE.findall(parser.visible_text))
    declared_cites = {f"[{c}]" for c in (slide_dict.get("citations") or [])}
    stray = rendered_cites - declared_cites
    if stray and declared_cites:
        findings.append(VisualFinding(
            code="citation-render-mismatch",
            severity="warn",
            message=f"inline citations {sorted(stray)} not in slide.citations",
            suggested_fix="add missing source_ids to slide.citations or strip the inline tokens",
        ))

    return findings


# ---------------------------------------------------------------------------
# Internal HTML parser
# ---------------------------------------------------------------------------


class _ChartProbe:
    __slots__ = ("tag_counts",)

    def __init__(self) -> None:
        self.tag_counts: dict[str, int] = {}


class _TableProbe:
    __slots__ = ("body_rows",)

    def __init__(self) -> None:
        self.body_rows: int = 0


class _SlideHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.charts: list[_ChartProbe] = []
        self.tables: list[_TableProbe] = []
        self.image_srcs: list[str] = []
        self.rendered_block_types: list[str] = []
        self._stack: list[str] = []
        self._in_chart_svg: int = 0
        self._in_tbody: int = 0
        self._text_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        self._stack.append(tag)
        cls = (a.get("class") or "").split()
        if tag == "div" and any(c.startswith("block-") for c in cls):
            for c in cls:
                if c.startswith("block-"):
                    self.rendered_block_types.append(c[len("block-"):])
                    break
        if tag == "svg" and any(c == "chart-svg" or "chart" in c for c in cls):
            self.charts.append(_ChartProbe())
            self._in_chart_svg += 1
        elif tag in _DATA_TAGS and self._in_chart_svg > 0 and self.charts:
            self.charts[-1].tag_counts[tag] = self.charts[-1].tag_counts.get(tag, 0) + 1
        if tag == "tbody":
            self._in_tbody += 1
            self.tables.append(_TableProbe())
        elif tag == "tr" and self._in_tbody > 0 and self.tables:
            self.tables[-1].body_rows += 1
        elif tag == "img":
            self.image_srcs.append(a.get("src") or "")

    def handle_endtag(self, tag: str) -> None:
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if tag == "svg" and self._in_chart_svg > 0:
            self._in_chart_svg -= 1
        if tag == "tbody" and self._in_tbody > 0:
            self._in_tbody -= 1

    def handle_data(self, data: str) -> None:
        # Skip text inside <script>/<style>.
        if any(t in {"script", "style"} for t in self._stack):
            return
        s = data.strip()
        if s:
            self._text_chunks.append(s)

    @property
    def visible_text(self) -> str:
        return " ".join(self._text_chunks)


__all__ = ["VisualFinding", "inspect_slide_html"]
