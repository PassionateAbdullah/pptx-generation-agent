"""PPTX writer that dispatches by block type and applies deck theme tokens.

A slide is laid out top-to-bottom from its ``blocks`` list (falling back to
the legacy adapter ``slide_to_blocks`` when no blocks are present). Each
block type renders to one or more OOXML shapes positioned with computed
heights. Colors come from the deck's theme tokens so the PPTX export
matches the HTML preview.
"""

from __future__ import annotations

import html
import logging
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blocks import slide_to_blocks
from .images import guess_mime, resolve_local_image
from .themes import DEFAULT_THEME, get_theme

log = logging.getLogger("pptx_agent.pptx_writer")

SLIDE_W = 12192000
SLIDE_H = 6858000
MARGIN_X = 533400
CONTENT_X = MARGIN_X
CONTENT_W = SLIDE_W - 2 * MARGIN_X
CONTENT_Y_START = 720000
CONTENT_Y_END = SLIDE_H - 400000
BLOCK_GAP = 120000


class PptxWriter:
    def __init__(self) -> None:
        self.shape_id = 1
        self._job_dir: Path | None = None
        # Per-pptx image registry: media_filename -> (target_path_in_zip, mime).
        # Deduped across slides so a reused image only ships one media part.
        self._media_index: dict[str, tuple[str, str]] = {}
        # Per-slide rels for image refs. slide_idx -> list[(rId, target_path_relative_to_slide)].
        self._slide_image_rels: dict[int, list[tuple[str, str]]] = {}
        self._current_slide_number: int | None = None

    def write(self, deck: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        theme_name = str(deck.get("theme") or DEFAULT_THEME)
        theme = get_theme(theme_name)
        self._media_index = {}
        self._slide_image_rels = {}
        self._job_dir = self._job_dir or path.parent
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for slide in deck["slides"]:
                    self._slide_image_rels.setdefault(slide["number"], [])
                slide_xmls: dict[int, str] = {}
                for slide in deck["slides"]:
                    self.shape_id = 1
                    idx = slide["number"]
                    slide_xmls[idx] = self._slide_xml(slide, theme)
                self._write_static_parts(zf, deck, theme)
                for slide in deck["slides"]:
                    idx = slide["number"]
                    zf.writestr(f"ppt/slides/slide{idx}.xml", slide_xmls[idx])
                    zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", self._slide_rels(idx))
                for media_name, (source_path, _) in self._media_index.items():
                    zf.write(source_path, f"ppt/media/{media_name}")
        finally:
            self._job_dir = None
            self._current_slide_number = None

    def set_job_dir(self, job_dir: Path | None) -> None:
        """Explicitly set the job dir so image blocks pointing at /api/jobs/<id>/media/<f>
        can be resolved to real bytes on disk. Server calls this before write()."""
        self._job_dir = job_dir

    # ------------------------------------------------------------------
    # Slide composition (block dispatcher)
    # ------------------------------------------------------------------

    def _slide_xml(self, slide: dict, theme) -> str:
        self._current_slide_number = int(slide.get("number") or 0)
        tokens = theme.tokens
        bg = _hex(tokens["bg"])
        accent = _hex(tokens["accent"])
        warn = _hex(tokens["warn"])
        danger = _hex(tokens["danger"])
        muted = _hex(tokens["muted"])

        shapes: list[str] = []
        # Decorative header gradient strip — three accent stripes.
        third = SLIDE_W // 3
        shapes.append(self._rect(0, 0, third, 95250, accent))
        shapes.append(self._rect(third, 0, third, 95250, warn))
        shapes.append(self._rect(2 * third, 0, SLIDE_W - 2 * third, 95250, danger))

        # Topline (slide number + eyebrow uppercase)
        topline_text = f"{slide.get('number', 0):02d}  {(slide.get('eyebrow') or '').upper()}"
        shapes.append(
            self._text(
                MARGIN_X,
                250000,
                SLIDE_W - 2 * MARGIN_X,
                250000,
                topline_text,
                size=950,
                color=muted,
                bold=True,
                name="Topline",
            )
        )

        # Block area: stack blocks vertically.
        blocks = slide.get("blocks") or []
        if not isinstance(blocks, list) or not blocks:
            blocks = slide_to_blocks(slide)

        cursor_y = CONTENT_Y_START
        dropped = 0
        for block in blocks:
            if cursor_y >= CONTENT_Y_END:
                dropped += 1
                continue
            available = CONTENT_Y_END - cursor_y
            block_shapes, used = self._render_block(block, CONTENT_X, cursor_y, CONTENT_W, available, theme)
            shapes.extend(block_shapes)
            cursor_y += used + BLOCK_GAP
        if dropped:
            log.warning(
                "slide %s overflowed: %d block(s) dropped (total %d, layout=%s). "
                "Consider splitting the slide or reducing block content.",
                slide.get("number"), dropped, len(blocks), slide.get("layout"),
            )

        shapes_xml = "\n".join(shapes)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld>'
            f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
            '<p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            f'{shapes_xml}'
            '</p:spTree>'
            '</p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
            '</p:sld>'
        )

    def _render_block(
        self,
        block: dict[str, Any],
        x: int,
        y: int,
        w: int,
        max_h: int,
        theme,
    ) -> tuple[list[str], int]:
        type_ = str(block.get("type") or "")
        props = block.get("props") or {}
        tokens = theme.tokens
        if type_ == "eyebrow":
            return self._render_eyebrow(props, x, y, w, tokens)
        if type_ == "heading":
            return self._render_heading(props, x, y, w, tokens)
        if type_ == "subheading":
            return self._render_subheading(props, x, y, w, tokens)
        if type_ == "paragraph":
            return self._render_paragraph(props, x, y, w, tokens)
        if type_ == "bullets":
            return self._render_bullets(props, x, y, w, tokens)
        if type_ == "metric_row":
            return self._render_metric_row(props, x, y, w, tokens)
        if type_ == "quote":
            return self._render_quote(props, x, y, w, tokens)
        if type_ == "callout":
            return self._render_callout(props, x, y, w, tokens)
        if type_ == "image":
            return self._render_image_placeholder(props, x, y, w, tokens)
        if type_ == "chart":
            return self._render_chart(props, x, y, w, max_h, tokens)
        if type_ == "diagram":
            return self._render_diagram(props, x, y, w, tokens)
        if type_ == "spacer":
            size = str(props.get("size", "md"))
            heights = {"sm": 120000, "md": 240000, "lg": 480000}
            return [], heights.get(size, 240000)
        if type_ == "hero_stat":
            return self._render_hero_stat(props, x, y, w, tokens)
        if type_ == "highlight":
            return self._render_highlight(props, x, y, w, tokens)
        if type_ == "table":
            return self._render_table(props, x, y, w, max_h, tokens)
        return [], 0

    def _render_table(self, props, x, y, w, max_h, tokens) -> tuple[list[str], int]:
        headers = [str(h) for h in (props.get("headers") or [])]
        rows = [r for r in (props.get("rows") or []) if isinstance(r, list)]
        caption = str(props.get("caption") or "")
        if not headers and not rows:
            return [], 0
        # Layout: caption (optional) + native PPTX table.
        shapes: list[str] = []
        cur_y = y
        if caption:
            shapes.append(
                self._text(x, cur_y, w, 240000, caption.upper(),
                           size=900, color=_hex(tokens["muted"]), bold=True, name="TableCaption")
            )
            cur_y += 280000
        col_count = max(len(headers), max((len(r) for r in rows), default=0))
        if col_count == 0:
            return shapes, cur_y - y
        col_w = w // col_count
        row_h = 360000
        header_h = 360000 if headers else 0
        body_h = row_h * len(rows)
        table_h = header_h + body_h
        if cur_y + table_h > y + max_h:
            # Clip rows to fit.
            available_rows = max(0, (y + max_h - cur_y - header_h) // row_h)
            rows = rows[:available_rows]
            body_h = row_h * len(rows)
            table_h = header_h + body_h
        shapes.append(
            self._table_shape(
                x, cur_y, w, table_h,
                col_w=col_w, col_count=col_count,
                headers=headers, rows=rows,
                row_h=row_h, header_h=header_h,
                accent=_hex(tokens["accent"]),
                accent_soft=_hex(tokens["accent_soft"]),
                ink=_hex(tokens["ink"]),
                line=_hex(tokens["line"]),
                muted=_hex(tokens["muted"]),
            )
        )
        return shapes, (cur_y - y) + table_h

    def _table_shape(
        self, x: int, y: int, w: int, h: int, *,
        col_w: int, col_count: int,
        headers: list[str], rows: list[list[str]],
        row_h: int, header_h: int,
        accent: str, accent_soft: str, ink: str, line: str, muted: str,
    ) -> str:
        sid = self._next_id()
        # Build <a:tbl> grid.
        grid_cols = "".join(f'<a:gridCol w="{col_w}"/>' for _ in range(col_count))
        tr_lines: list[str] = []
        if headers:
            tr_lines.append(self._tr(headers, height=header_h, col_count=col_count,
                                     fill=accent_soft, color=accent, bold=True, size=950, line=line))
        for r in rows:
            padded = list(r) + [""] * (col_count - len(r))
            tr_lines.append(self._tr(padded[:col_count], height=row_h, col_count=col_count,
                                     fill="", color=ink, bold=False, size=950, line=line))
        return (
            f'<p:graphicFrame><p:nvGraphicFramePr>'
            f'<p:cNvPr id="{sid}" name="Table {sid}"/><p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/>'
            f'</p:nvGraphicFramePr>'
            f'<p:xfrm><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{int(w)}" cy="{int(h)}"/></p:xfrm>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
            f'<a:tbl><a:tblPr firstRow="1"><a:tableStyleId>{{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}}</a:tableStyleId></a:tblPr>'
            f'<a:tblGrid>{grid_cols}</a:tblGrid>'
            f'{"".join(tr_lines)}'
            f'</a:tbl></a:graphicData></a:graphic></p:graphicFrame>'
        )

    def _tr(self, cells: list[str], *, height: int, col_count: int, fill: str,
            color: str, bold: bool, size: int, line: str) -> str:
        bold_attr = ' b="1"' if bold else ""
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else '<a:noFill/>'
        border = f'<a:lnB w="6350"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:lnB>'
        tc_xml: list[str] = []
        for cell in cells[:col_count]:
            safe = html.escape(str(cell), quote=False)
            tc_xml.append(
                f'<a:tc><a:txBody><a:bodyPr wrap="square" anchor="ctr"/><a:lstStyle/>'
                f'<a:p><a:r><a:rPr lang="en-US" sz="{size}"{bold_attr}>'
                f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
                f'<a:latin typeface="Aptos"/></a:rPr><a:t>{safe}</a:t></a:r></a:p>'
                f'</a:txBody><a:tcPr>{border}{fill_xml}</a:tcPr></a:tc>'
            )
        return f'<a:tr h="{height}">{"".join(tc_xml)}</a:tr>'

    def _render_hero_stat(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        value = str(props.get("value") or "")
        label = str(props.get("label") or "")
        trend = str(props.get("trend") or "")
        height = 1500000
        # Giant centered number — fills the slide.
        shapes = [
            self._text(x, y, w, 900000, value, size=7200, color=_hex(tokens["accent"]), bold=True, name="HeroValue"),
        ]
        sub_y = y + 900000
        if trend:
            shapes.append(
                self._text(x, sub_y, w, 280000, trend, size=1600, color=_hex(tokens["warn"]), bold=True, name="HeroTrend")
            )
            sub_y += 320000
        if label:
            shapes.append(
                self._text(x, sub_y, w, 320000, label.upper(), size=1100, color=_hex(tokens["muted"]), bold=True, name="HeroLabel")
            )
        return shapes, height

    def _render_highlight(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        tone = str(props.get("tone") or "accent")
        title = str(props.get("title") or "")
        text = str(props.get("text") or "")
        height = 700000 if len(text) < 160 else 1000000
        tone_map = {
            "warn": ("warn", "panel_alt"),
            "danger": ("danger", "panel_alt"),
            "success": ("accent", "accent_soft"),
            "accent": ("accent", "accent_soft"),
        }
        bar_token, fill_token = tone_map.get(tone, ("accent", "accent_soft"))
        shapes = [
            self._rect(x, y, 100000, height, _hex(tokens[bar_token])),
            self._round_rect(x + 100000, y, w - 100000, height, _hex(tokens[fill_token]), line=_hex(tokens["line"])),
        ]
        inner_x = x + 280000
        if title:
            shapes.append(
                self._text(inner_x, y + 80000, w - 360000, 240000, title.upper(),
                           size=950, color=_hex(tokens["accent"]), bold=True, name="HighlightTitle")
            )
        shapes.append(
            self._text(inner_x, y + (320000 if title else 100000), w - 360000, height - 160000,
                       text, size=1500, color=_hex(tokens["ink"]), bold=True, name="HighlightText")
        )
        return shapes, height

    # ---- Per-block renderers --------------------------------------------------

    def _render_eyebrow(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        if not text:
            return [], 0
        return [
            self._text(x, y, w, 280000, text.upper(), size=1050, color=_hex(tokens["accent"]), bold=True, name="Eyebrow")
        ], 280000

    def _render_heading(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        level = int(props.get("level") or 1)
        if not text:
            return [], 0
        if level <= 1:
            size = 3200 if len(text) < 36 else 2600 if len(text) < 60 else 2200
            height = 900000 if len(text) < 36 else 1150000
        else:
            size = 2200
            height = 700000
        return [
            self._text(x, y, w, height, text, size=size, color=_hex(tokens["ink"]), bold=True, name="Heading")
        ], height

    def _render_subheading(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        if not text:
            return [], 0
        height = 500000 if len(text) < 110 else 800000
        return [
            self._text(x, y, w, height, text, size=1400, color=_hex(tokens["muted"]), name="Subheading")
        ], height

    def _render_paragraph(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        if not text:
            return [], 0
        # Approximate height: 1 line per ~75 chars at width=CONTENT_W.
        lines = max(1, (len(text) // 75) + 1)
        height = min(2200000, 280000 * lines)
        return [
            self._text(x, y, w, height, text, size=1100, color=_hex(tokens["ink"]), name="Paragraph")
        ], height

    def _render_bullets(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        items = [str(i) for i in (props.get("items") or []) if str(i).strip()][:6]
        if not items:
            return [], 0
        height = min(2800000, 350000 * len(items))
        return [self._bullets(x, y, w, height, items, color_hex=_hex(tokens["ink"]), accent_hex=_hex(tokens["accent"]))], height

    def _render_metric_row(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        metrics = [m for m in (props.get("metrics") or []) if isinstance(m, dict)][:4]
        if not metrics:
            return [], 0
        gap = 100000
        card_w = (w - gap * (len(metrics) - 1)) // len(metrics)
        card_h = 750000
        shapes: list[str] = []
        for i, m in enumerate(metrics):
            cx = x + i * (card_w + gap)
            shapes.append(self._round_rect(cx, y, card_w, card_h, _hex(tokens["panel_alt"]), line=_hex(tokens["line"])))
            shapes.append(
                self._text(cx + 152400, y + 70000, card_w - 305000, 350000,
                           str(m.get("value", "")), size=1800, color=_hex(tokens["accent"]), bold=True, name="MetricValue")
            )
            shapes.append(
                self._text(cx + 152400, y + 430000, card_w - 305000, 280000,
                           str(m.get("label", "")).upper(), size=850, color=_hex(tokens["muted"]), bold=True, name="MetricLabel")
            )
        return shapes, card_h

    def _render_quote(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        attribution = str(props.get("attribution") or "")
        if not text:
            return [], 0
        height = 700000 if len(text) < 200 else 1000000
        shapes = [
            self._rect(x, y, 80000, height, _hex(tokens["accent"])),
            self._round_rect(x + 80000, y, w - 80000, height, _hex(tokens["panel_alt"]), line=_hex(tokens["line"])),
            self._text(x + 220000, y + 80000, w - 400000, height - 200000,
                       text, size=1300, color=_hex(tokens["ink"]), italic=True, name="Quote"),
        ]
        if attribution:
            shapes.append(
                self._text(x + 220000, y + height - 280000, w - 400000, 240000,
                           f"— {attribution}", size=900, color=_hex(tokens["muted"]), name="Attribution")
            )
        return shapes, height

    def _render_callout(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        text = str(props.get("text") or "")
        tone = str(props.get("tone") or "info")
        if not text:
            return [], 0
        fill_token = "accent_soft" if tone in {"info", "success"} else "panel_alt"
        border_token = "accent" if tone in {"info", "success"} else "warn"
        height = 480000 if len(text) < 150 else 800000
        return [
            self._round_rect(x, y, w, height, _hex(tokens[fill_token]), line=_hex(tokens[border_token])),
            self._text(x + 220000, y + 80000, w - 440000, height - 160000,
                       text, size=1150, color=_hex(tokens["ink"]), name="Callout"),
        ], height

    def _render_image_placeholder(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        # Note: caller passes the current slide_number via self._current_slide_number
        # for image rel registration.
        src = str(props.get("src") or "")
        alt = str(props.get("alt") or "image")
        caption = str(props.get("caption") or "")
        height = 1700000

        local_path = resolve_local_image(self._job_dir, src) if self._job_dir else None
        if local_path is not None and self._current_slide_number is not None:
            r_id, media_name = self._register_image(local_path, self._current_slide_number)
            shapes = [self._picture(x, y, w, height, r_id, media_name, alt)]
            if caption:
                shapes.append(
                    self._text(x + 80000, y + height + 40000, w - 160000, 240000,
                               caption, size=850, color=_hex(tokens["muted"]), name="Caption")
                )
                height += 280000
            return shapes, height

        # Fallback: placeholder rect with alt text and (if external URL) source hint.
        label = f"[image: {alt}]" if not src else f"[image: {alt} — external URL not embedded]"
        shapes = [
            self._round_rect(x, y, w, height, _hex(tokens["panel_alt"]), line=_hex(tokens["line"])),
            self._text(x + 220000, y + height // 2 - 120000, w - 440000, 280000,
                       label, size=1050, color=_hex(tokens["muted"]), name="ImagePlaceholder"),
        ]
        if caption:
            shapes.append(
                self._text(x + 220000, y + height + 40000, w - 440000, 240000,
                           caption, size=850, color=_hex(tokens["muted"]), name="Caption")
            )
            height += 280000
        return shapes, height

    def _register_image(self, local_path: Path, slide_number: int) -> tuple[str, str]:
        """Register an image file in the global media index and the slide's rels.
        Returns ``(rId, media_filename)``."""
        media_name = local_path.name
        if media_name not in self._media_index:
            self._media_index[media_name] = (str(local_path), guess_mime(local_path))
        rels = self._slide_image_rels.setdefault(slide_number, [])
        existing = next(
            ((rid, target) for rid, target in rels if target.endswith(f"/{media_name}")),
            None,
        )
        if existing:
            return existing[0], media_name
        r_id = f"rIdImg{len(rels) + 1}"
        target = f"../media/{media_name}"
        rels.append((r_id, target))
        return r_id, media_name

    def _picture(self, x: int, y: int, w: int, h: int, r_id: str, name: str, alt: str) -> str:
        sid = self._next_id()
        safe_alt = html.escape(alt or "image", quote=True)
        safe_name = html.escape(name, quote=True)
        return (
            f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{safe_name}" descr="{safe_alt}"/>'
            f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{r_id}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
        )

    def _render_chart(self, props, x, y, w, max_h, tokens) -> tuple[list[str], int]:
        kind = str(props.get("kind") or "bar").lower()
        title = str(props.get("title") or "")
        series = props.get("series") or []
        labels = [str(l) for l in (props.get("labels") or [])]

        height = min(max_h, 2100000)
        shapes: list[str] = []

        # Title row (if set)
        title_h = 0
        if title:
            title_h = 260000
            shapes.append(
                self._text(x, y, w, title_h, title.upper(), size=900, color=_hex(tokens["muted"]), bold=True, name="ChartTitle")
            )

        chart_y = y + title_h
        chart_h = height - title_h

        # Flatten numeric values
        clean_series: list[tuple[str, list[float]]] = []
        for s in series:
            if not isinstance(s, dict):
                continue
            values: list[float] = []
            for v in s.get("values") or []:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    continue
            clean_series.append((str(s.get("label") or ""), values))

        if not clean_series or all(not vals for _, vals in clean_series):
            shapes.append(
                self._round_rect(x, chart_y, w, chart_h, _hex(tokens["panel_alt"]), line=_hex(tokens["line"]))
            )
            shapes.append(
                self._text(x + 220000, chart_y + chart_h // 2 - 120000, w - 440000, 280000,
                           "[chart — no data]", size=1050, color=_hex(tokens["muted"]), name="ChartEmpty")
            )
            return shapes, height

        if kind == "bar":
            shapes.extend(self._bar_chart_shapes(clean_series, labels, x, chart_y, w, chart_h, tokens))
        else:
            # Data table fallback for line/area/pie until those get native PPTX rendering.
            shapes.extend(self._data_table_shapes(clean_series, labels, x, chart_y, w, chart_h, tokens, kind))

        return shapes, height

    def _bar_chart_shapes(
        self,
        series: list[tuple[str, list[float]]],
        labels: list[str],
        x: int,
        y: int,
        w: int,
        h: int,
        tokens,
    ) -> list[str]:
        accent = _hex(tokens["accent"])
        warn = _hex(tokens["warn"])
        muted = _hex(tokens["muted"])
        line_color = _hex(tokens["line"])
        points = max((len(vals) for _, vals in series), default=0)
        if not points:
            return []
        peak = max((max((abs(v) for v in vals), default=0) for _, vals in series), default=1.0) or 1.0
        plot_h = h - 280000  # leave room for axis labels
        plot_y = y
        axis_y = plot_y + plot_h
        group_w = w / points
        band_w = group_w * 0.78
        bar_w = int(band_w / max(1, len(series)))
        shapes: list[str] = [
            # baseline
            self._rect(x, axis_y, w, 8000, line_color),
        ]
        for i in range(points):
            x_center = int(x + group_w * (i + 0.5))
            for s_idx, (_, vals) in enumerate(series):
                if i >= len(vals):
                    continue
                v = vals[i]
                bar_h = max(40000, int((abs(v) / peak) * (plot_h - 80000)))
                bx = int(x_center - band_w / 2 + s_idx * bar_w)
                by = axis_y - bar_h
                fill = accent if s_idx % 2 == 0 else warn
                shapes.append(self._round_rect(bx, by, max(40000, bar_w - 40000), bar_h, fill))
            if i < len(labels) and labels[i]:
                shapes.append(
                    self._text(int(x + group_w * i), axis_y + 60000, int(group_w), 200000,
                               labels[i], size=700, color=muted, name="ChartAxis")
                )
        return shapes

    def _data_table_shapes(
        self,
        series: list[tuple[str, list[float]]],
        labels: list[str],
        x: int,
        y: int,
        w: int,
        h: int,
        tokens,
        kind: str,
    ) -> list[str]:
        muted = _hex(tokens["muted"])
        ink = _hex(tokens["ink"])
        accent = _hex(tokens["accent"])
        panel_alt = _hex(tokens["panel_alt"])
        line_color = _hex(tokens["line"])
        shapes: list[str] = [self._round_rect(x, y, w, h, panel_alt, line=line_color)]
        header_h = 240000
        shapes.append(
            self._text(x + 200000, y + 80000, w - 400000, header_h,
                       f"[{kind} chart — data shown as table]", size=900, color=muted, bold=True, name="ChartTableLabel")
        )
        rows = list(enumerate(labels)) if labels else list(enumerate(["#" + str(i + 1) for i in range(len(series[0][1]))]))
        row_h = max(180000, (h - header_h - 100000) // max(1, len(rows) + 1))
        col_w_label = int((w - 400000) * 0.25)
        col_w_values = w - 400000 - col_w_label
        # Header row
        header_y = y + header_h + 80000
        shapes.append(self._text(x + 200000, header_y, col_w_label, row_h, "Label", size=850, color=muted, bold=True, name="Th"))
        shapes.append(self._text(x + 200000 + col_w_label, header_y, col_w_values, row_h,
                                 "  ".join(name or f"S{i+1}" for i, (name, _) in enumerate(series)),
                                 size=850, color=muted, bold=True, name="ThSeries"))
        for i, (_, label) in enumerate(rows):
            ry = header_y + (i + 1) * row_h
            if ry > y + h - row_h:
                break
            shapes.append(self._text(x + 200000, ry, col_w_label, row_h, str(label), size=900, color=ink, name="TdLabel"))
            cells: list[str] = []
            for _, vals in series:
                cells.append(f"{vals[i]:.2f}" if i < len(vals) else "—")
            shapes.append(self._text(x + 200000 + col_w_label, ry, col_w_values, row_h,
                                     "   ".join(cells), size=900, color=accent, bold=True, name="TdVals"))
        return shapes

    def _render_diagram(self, props, x, y, w, tokens) -> tuple[list[str], int]:
        kind = str(props.get("kind") or "flow").lower()
        nodes = [n for n in (props.get("nodes") or []) if isinstance(n, dict)]
        labels = [str(n.get("label") or "").strip() for n in nodes]
        labels = [l for l in labels if l] or ["Step 1", "Step 2", "Step 3"]
        if kind == "matrix":
            return self._diagram_matrix(labels, x, y, w, tokens)
        if kind == "orbit":
            return self._diagram_orbit(labels, x, y, w, tokens)
        return self._diagram_flow(labels, x, y, w, tokens)

    def _diagram_flow(self, labels, x, y, w, tokens) -> tuple[list[str], int]:
        h = 600000
        count = len(labels)
        gap = 80000
        box_w = (w - gap * (count - 1)) // max(1, count)
        shapes: list[str] = []
        for i, label in enumerate(labels):
            cx = x + i * (box_w + gap)
            shapes.append(self._round_rect(cx, y, box_w, h, _hex(tokens["accent_soft"]), line=_hex(tokens["line"])))
            shapes.append(
                self._text(cx + 80000, y + h // 3, box_w - 160000, h // 2, label,
                           size=1150, color=_hex(tokens["accent"]), bold=True, name="FlowBox")
            )
            if i < count - 1:
                arrow_x = cx + box_w + (gap - 60000) // 2
                shapes.append(self._rect(arrow_x, y + h // 2 - 12000, 60000, 24000, _hex(tokens["warn"])))
        return shapes, h

    def _diagram_matrix(self, labels, x, y, w, tokens) -> tuple[list[str], int]:
        cells = labels[:6]
        cols = 2
        rows = (len(cells) + cols - 1) // cols
        h = 240000 + rows * 480000
        cell_w = (w - 100000) // cols
        cell_h = 460000
        shapes: list[str] = []
        for i, label in enumerate(cells):
            r = i // cols
            c = i % cols
            cx = x + c * (cell_w + 100000)
            cy = y + r * (cell_h + 60000)
            shapes.append(self._round_rect(cx, cy, cell_w, cell_h, _hex(tokens["panel_alt"]), line=_hex(tokens["line"])))
            shapes.append(self._text(cx + 200000, cy + cell_h // 3, cell_w - 400000, cell_h // 2,
                                     label, size=1100, color=_hex(tokens["ink"]), bold=True, name="MatrixCell"))
        return shapes, h

    def _diagram_orbit(self, labels, x, y, w, tokens) -> tuple[list[str], int]:
        h = 1400000
        center_x = x + w // 2
        center_y = y + h // 2
        radius = min(w, h) // 3
        shapes: list[str] = [
            self._ellipse(center_x - radius, center_y - radius, radius * 2, radius * 2,
                          _hex(tokens["accent_soft"]), line=_hex(tokens["line"]))
        ]
        count = min(len(labels), 6)
        from math import cos, sin, pi
        for i in range(count):
            ang = -pi / 2 + 2 * pi * i / count
            cx = int(center_x + radius * cos(ang)) - 200000
            cy = int(center_y + radius * sin(ang)) - 90000
            shapes.append(self._round_rect(cx, cy, 400000, 180000, _hex(tokens["accent"])))
            shapes.append(self._text(cx, cy + 240000, 400000, 200000, labels[i],
                                     size=800, color=_hex(tokens["ink"]), bold=True, name="OrbitLabel"))
        return shapes, h

    # ------------------------------------------------------------------
    # Primitive shape helpers
    # ------------------------------------------------------------------

    def _rect(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("rect", x, y, w, h, fill, line=line)

    def _round_rect(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("roundRect", x, y, w, h, fill, line=line)

    def _ellipse(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("ellipse", x, y, w, h, fill, line=line)

    def _shape(self, prst: str, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        sid = self._next_id()
        line_xml = f'<a:ln><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else '<a:ln><a:noFill/></a:ln>'
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Shape {sid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom>'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{line_xml}</p:spPr></p:sp>'
        )

    def _text(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        text: str,
        *,
        size: int,
        color: str,
        bold: bool = False,
        italic: bool = False,
        name: str = "Text",
    ) -> str:
        sid = self._next_id()
        safe = html.escape(str(text), quote=False)
        bold_attr = ' b="1"' if bold else ""
        italic_attr = ' i="1"' if italic else ""
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name} {sid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" anchor="t"/><a:lstStyle/>'
            f'<a:p><a:pPr/><a:r><a:rPr lang="en-US" sz="{size}"{bold_attr}{italic_attr}>'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Aptos"/></a:rPr>'
            f'<a:t>{safe}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size}"/></a:p></p:txBody></p:sp>'
        )

    def _bullets(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        bullets: list[str],
        *,
        color_hex: str,
        accent_hex: str,
    ) -> str:
        sid = self._next_id()
        paragraphs = []
        for bullet in bullets[:6]:
            safe = html.escape(str(bullet), quote=False)
            paragraphs.append(
                f'<a:p><a:pPr marL="285750" indent="-171450"><a:buClr><a:srgbClr val="{accent_hex}"/></a:buClr>'
                f'<a:buChar char="&#8226;"/></a:pPr>'
                f'<a:r><a:rPr lang="en-US" sz="1150">'
                f'<a:solidFill><a:srgbClr val="{color_hex}"/></a:solidFill>'
                f'<a:latin typeface="Aptos"/></a:rPr><a:t>{safe}</a:t></a:r>'
                f'<a:endParaRPr lang="en-US" sz="1150"/></a:p>'
            )
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Bullets {sid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" anchor="t"/><a:lstStyle/>{"".join(paragraphs)}</p:txBody></p:sp>'
        )

    def _next_id(self) -> int:
        self.shape_id += 1
        return self.shape_id

    # ------------------------------------------------------------------
    # Static OOXML parts (theme-aware)
    # ------------------------------------------------------------------

    def _write_static_parts(self, zf: zipfile.ZipFile, deck: dict, theme) -> None:
        slide_count = deck["slide_count"]
        zf.writestr("[Content_Types].xml", self._content_types(slide_count))
        zf.writestr("_rels/.rels", self._root_rels())
        zf.writestr("docProps/app.xml", self._app_props(slide_count))
        zf.writestr("docProps/core.xml", self._core_props(deck))
        zf.writestr("ppt/presentation.xml", self._presentation_xml(slide_count))
        zf.writestr("ppt/_rels/presentation.xml.rels", self._presentation_rels(slide_count))
        zf.writestr("ppt/slideMasters/slideMaster1.xml", self._slide_master(theme))
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._slide_master_rels())
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", self._slide_layout())
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", self._slide_layout_rels())
        zf.writestr("ppt/theme/theme1.xml", self._theme(theme))
        zf.writestr("ppt/presProps.xml", '<p:presentationPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
        zf.writestr("ppt/viewProps.xml", '<p:viewPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
        zf.writestr("ppt/tableStyles.xml", '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>')

    def _content_types(self, slide_count: int) -> str:
        slide_overrides = "\n".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, slide_count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Default Extension="gif" ContentType="image/gif"/>'
            '<Default Extension="webp" ContentType="image/webp"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
            '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
            '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
            f'{slide_overrides}'
            '</Types>'
        )

    def _root_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>'
        )

    def _app_props(self, slide_count: int) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<Application>Manus-Style PPTX Agent</Application>'
            '<PresentationFormat>On-screen Show (16:9)</PresentationFormat>'
            f'<Slides>{slide_count}</Slides><Notes>0</Notes><HiddenSlides>0</HiddenSlides>'
            '<MMClips>0</MMClips><ScaleCrop>false</ScaleCrop>'
            '<HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Theme</vt:lpstr></vt:variant>'
            '<vt:variant><vt:i4>1</vt:i4></vt:variant></vt:vector></HeadingPairs>'
            '<TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>Office Theme</vt:lpstr></vt:vector></TitlesOfParts>'
            '<Company></Company><LinksUpToDate>false</LinksUpToDate><SharedDoc>false</SharedDoc>'
            '<HyperlinksChanged>false</HyperlinksChanged><AppVersion>16.0000</AppVersion>'
            '</Properties>'
        )

    def _core_props(self, deck: dict) -> str:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        title = html.escape(deck.get("title", "Pitch Deck"), quote=False)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{title}</dc:title><dc:creator>Manus-Style PPTX Agent</dc:creator>'
            f'<cp:lastModifiedBy>Manus-Style PPTX Agent</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
            '</cp:coreProperties>'
        )

    def _presentation_xml(self, slide_count: int) -> str:
        slide_ids = "\n".join(
            f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, slide_count + 1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f'<p:sldIdLst>{slide_ids}</p:sldIdLst>'
            f'<p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>'
            '<p:notesSz cx="6858000" cy="9144000"/>'
            '<p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle>'
            '</p:presentation>'
        )

    def _presentation_rels(self, slide_count: int) -> str:
        rels = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        ]
        for i in range(1, slide_count + 1):
            rels.append(
                f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
            )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{" ".join(rels)}'
            '</Relationships>'
        )

    def _slide_rels(self, slide_number: int) -> str:
        image_rels = "".join(
            f'<Relationship Id="{html.escape(r_id, quote=True)}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            f'Target="{html.escape(target, quote=True)}"/>'
            for r_id, target in self._slide_image_rels.get(slide_number, [])
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            f'{image_rels}'
            '</Relationships>'
        )

    def _slide_master(self, theme) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            '<p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '</p:spTree></p:cSld>'
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
            'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            '<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>'
            '</p:sldMaster>'
        )

    def _slide_master_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
            '</Relationships>'
        )

    def _slide_layout(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
            '<p:cSld name="Blank"><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
        )

    def _slide_layout_rels(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            '</Relationships>'
        )

    def _theme(self, theme) -> str:
        t = theme.tokens
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="{theme.label}">'
            '<a:themeElements>'
            f'<a:clrScheme name="{theme.name}">'
            f'<a:dk1><a:srgbClr val="{_hex(t["ink"])}"/></a:dk1>'
            f'<a:lt1><a:srgbClr val="{_hex(t["panel"])}"/></a:lt1>'
            f'<a:dk2><a:srgbClr val="{_hex(t["muted"])}"/></a:dk2>'
            f'<a:lt2><a:srgbClr val="{_hex(t["bg"])}"/></a:lt2>'
            f'<a:accent1><a:srgbClr val="{_hex(t["accent"])}"/></a:accent1>'
            f'<a:accent2><a:srgbClr val="{_hex(t["warn"])}"/></a:accent2>'
            f'<a:accent3><a:srgbClr val="{_hex(t["danger"])}"/></a:accent3>'
            f'<a:accent4><a:srgbClr val="{_hex(t["accent_strong"])}"/></a:accent4>'
            f'<a:accent5><a:srgbClr val="{_hex(t["muted"])}"/></a:accent5>'
            f'<a:accent6><a:srgbClr val="{_hex(t["accent_soft"])}"/></a:accent6>'
            f'<a:hlink><a:srgbClr val="{_hex(t["accent"])}"/></a:hlink>'
            f'<a:folHlink><a:srgbClr val="{_hex(t["muted"])}"/></a:folHlink>'
            '</a:clrScheme>'
            '<a:fontScheme name="Aptos"><a:majorFont><a:latin typeface="Aptos Display"/></a:majorFont>'
            '<a:minorFont><a:latin typeface="Aptos"/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="Default"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>'
            '</a:themeElements>'
            '</a:theme>'
        )


def _hex(token_value: str) -> str:
    """Convert a CSS color (#RRGGBB / #RGB / rgba(...)) to bare RRGGBB hex for OOXML."""
    if not token_value:
        return "FFFFFF"
    v = token_value.strip()
    if v.startswith("#"):
        v = v[1:]
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return v.upper()[:6].ljust(6, "0")
    if v.lower().startswith("rgb"):
        # Crude fallback: parse digits inside parens.
        inside = v[v.find("(") + 1 : v.rfind(")")]
        parts = [p.strip() for p in inside.split(",")[:3]]
        try:
            r, g, b = (int(float(p)) for p in parts)
            return f"{r:02X}{g:02X}{b:02X}"
        except (ValueError, TypeError):
            return "FFFFFF"
    return "FFFFFF"
