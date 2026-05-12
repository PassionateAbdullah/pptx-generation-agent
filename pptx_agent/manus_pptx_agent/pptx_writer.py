from __future__ import annotations

import html
import zipfile
from datetime import datetime, timezone
from pathlib import Path


SLIDE_W = 12192000
SLIDE_H = 6858000


class PptxWriter:
    def __init__(self) -> None:
        self.shape_id = 1

    def write(self, deck: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            self._write_static_parts(zf, deck)
            for slide in deck["slides"]:
                self.shape_id = 1
                idx = slide["number"]
                zf.writestr(f"ppt/slides/slide{idx}.xml", self._slide_xml(slide))
                zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", self._slide_rels())

    def _write_static_parts(self, zf: zipfile.ZipFile, deck: dict) -> None:
        slide_count = deck["slide_count"]
        zf.writestr("[Content_Types].xml", self._content_types(slide_count))
        zf.writestr("_rels/.rels", self._root_rels())
        zf.writestr("docProps/app.xml", self._app_props(slide_count))
        zf.writestr("docProps/core.xml", self._core_props(deck))
        zf.writestr("ppt/presentation.xml", self._presentation_xml(slide_count))
        zf.writestr("ppt/_rels/presentation.xml.rels", self._presentation_rels(slide_count))
        zf.writestr("ppt/slideMasters/slideMaster1.xml", self._slide_master())
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", self._slide_master_rels())
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", self._slide_layout())
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", self._slide_layout_rels())
        zf.writestr("ppt/theme/theme1.xml", self._theme())
        zf.writestr("ppt/presProps.xml", '<p:presentationPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
        zf.writestr("ppt/viewProps.xml", '<p:viewPr xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
        zf.writestr("ppt/tableStyles.xml", '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>')

    def _slide_xml(self, slide: dict) -> str:
        bg = self._bg_for_layout(slide.get("layout", "solution"))
        shapes = [
            self._rect(0, 0, SLIDE_W, 95250, "087C7C"),
            self._rect(0, 95250, SLIDE_W, 47625, "D98F1F"),
            self._text(
                533400,
                350520,
                10668000,
                228600,
                f"{slide['number']:02d}  {slide.get('eyebrow', '').upper()}",
                size=950,
                color="53606D",
                bold=True,
                name="Topline",
            ),
            self._text(
                533400,
                876300,
                5791200,
                1516380,
                slide.get("title", ""),
                size=2700 if len(slide.get("title", "")) < 48 else 2250,
                color="17202A",
                bold=True,
                name="Title",
            ),
            self._text(
                533400,
                2489200,
                5791200,
                914400,
                slide.get("subtitle", ""),
                size=1250,
                color="53606D",
                name="Subtitle",
            ),
            self._bullets(
                685800,
                3535680,
                5486400,
                1625600,
                slide.get("bullets", []),
            ),
        ]

        shapes.extend(self._visual_shapes(slide))
        shapes.extend(self._metric_shapes(slide))
        shapes_xml = "\n".join(shapes)
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {shapes_xml}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>'''

    def _visual_shapes(self, slide: dict) -> list[str]:
        layout = slide.get("layout", "solution")
        shapes: list[str] = []
        if layout == "cover":
            cx, cy = 8839200, 3124200
            shapes.append(self._ellipse(cx - 1270000, cy - 1270000, 2540000, 2540000, "E9F4F3", line="C8DDDA"))
            nodes = [
                (cx - 254000, cy - 254000, 508000, "17202A"),
                (cx - 1574800, cy - 838200, 533400, "D98F1F"),
                (cx + 965200, cy - 939800, 533400, "087C7C"),
                (cx - 1092200, cy + 762000, 533400, "C95746"),
                (cx + 711200, cy + 711200, 533400, "6F7B85"),
            ]
            for x, y, size, color in nodes:
                shapes.append(self._round_rect(x, y, size, size, color))
            return shapes

        if layout in {"architecture", "solution"}:
            labels = ["Research", "Plan", "HTML", "PPTX"]
            x = 7023100
            y = 1905000
            for idx, label in enumerate(labels):
                shapes.append(self._round_rect(x, y + idx * 762000, 3302000, 457200, "EEF6F5", line="C8DDDA"))
                shapes.append(self._text(x + 177800, y + idx * 762000 + 101600, 2946400, 254000, label, size=1200, color="087C7C", bold=True, name="Flow"))
                if idx < len(labels) - 1:
                    shapes.append(self._rect(x + 1574800, y + idx * 762000 + 508000, 101600, 203200, "D98F1F"))
            return shapes

        if layout in {"market", "metrics", "ask"}:
            values = [86, 64, 42, 72]
            colors = ["087C7C", "D98F1F", "C95746", "6F7B85"]
            x0 = 7112000
            base_y = 4826000
            for idx, value in enumerate(values):
                h = int(2286000 * value / 100)
                x = x0 + idx * 762000
                shapes.append(self._round_rect(x, base_y - h, 457200, h, colors[idx]))
                label = "Signal"
                if idx < len(slide.get("metrics", [])):
                    label = slide["metrics"][idx].get("label", "Signal")
                shapes.append(self._text(x - 76200, base_y + 101600, 609600, 304800, label, size=760, color="53606D", bold=True, name="BarLabel"))
            return shapes

        if layout in {"comparison", "team"}:
            labels = ["Context", "Quality", "Governance", "Scale"]
            x0 = 6908800
            y0 = 1828800
            for idx, label in enumerate(labels):
                x = x0 + (idx % 2) * 1778000
                y = y0 + (idx // 2) * 1143000
                shapes.append(self._round_rect(x, y, 1625600, 914400, "FBFCFD", line="D9E0E6"))
                shapes.append(self._text(x + 152400, y + 304800, 1320800, 304800, label, size=1050, color="17202A", bold=True, name="Matrix"))
            return shapes

        shapes.append(self._round_rect(7048500, 1727200, 3505200, 2438400, "17202A"))
        shapes.append(self._text(7289800, 2006600, 3022600, 355600, "Verified narrative", size=1250, color="FFFFFF", bold=True, name="SignalTitle"))
        for idx, label in enumerate(["Source-aware plan", "Slide preview", "Export-ready PPTX"]):
            shapes.append(self._text(7289800, 2590800 + idx * 508000, 3022600, 304800, label, size=1050, color="E9F4F3", name="Signal"))
        return shapes

    def _metric_shapes(self, slide: dict) -> list[str]:
        shapes: list[str] = []
        metrics = slide.get("metrics", [])[:4]
        if not metrics:
            return shapes
        x = 533400
        y = 5781040
        for metric in metrics:
            shapes.append(self._round_rect(x, y, 1727200, 584200, "FBFCFD", line="D9E0E6"))
            shapes.append(self._text(x + 127000, y + 76200, 1473200, 254000, metric.get("value", ""), size=1350, color="087C7C", bold=True, name="MetricValue"))
            shapes.append(self._text(x + 127000, y + 330200, 1473200, 177800, metric.get("label", ""), size=650, color="53606D", bold=True, name="MetricLabel"))
            x += 1879600
        return shapes

    def _rect(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("rect", x, y, w, h, fill, line=line)

    def _round_rect(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("roundRect", x, y, w, h, fill, line=line)

    def _ellipse(self, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        return self._shape("ellipse", x, y, w, h, fill, line=line)

    def _shape(self, prst: str, x: int, y: int, w: int, h: int, fill: str, line: str | None = None) -> str:
        sid = self._next_id()
        line_xml = f'<a:ln><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>' if line else '<a:ln><a:noFill/></a:ln>'
        return f'''<p:sp>
  <p:nvSpPr><p:cNvPr id="{sid}" name="Shape {sid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{line_xml}</p:spPr>
</p:sp>'''

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
        name: str = "Text",
    ) -> str:
        sid = self._next_id()
        safe = html.escape(str(text), quote=False)
        bold_attr = ' b="1"' if bold else ""
        return f'''<p:sp>
  <p:nvSpPr><p:cNvPr id="{sid}" name="{name} {sid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
  <p:txBody><a:bodyPr wrap="square" anchor="t"/><a:lstStyle/><a:p><a:pPr/><a:r><a:rPr lang="en-US" sz="{size}"{bold_attr}><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="Aptos"/></a:rPr><a:t>{safe}</a:t></a:r><a:endParaRPr lang="en-US" sz="{size}"/></a:p></p:txBody>
</p:sp>'''

    def _bullets(self, x: int, y: int, w: int, h: int, bullets: list[str]) -> str:
        sid = self._next_id()
        paragraphs = []
        for bullet in bullets[:5]:
            safe = html.escape(str(bullet), quote=False)
            paragraphs.append(
                f'''<a:p><a:pPr marL="285750" indent="-171450"><a:buChar char="&#8226;"/></a:pPr><a:r><a:rPr lang="en-US" sz="1050"><a:solidFill><a:srgbClr val="2F3B46"/></a:solidFill><a:latin typeface="Aptos"/></a:rPr><a:t>{safe}</a:t></a:r><a:endParaRPr lang="en-US" sz="1050"/></a:p>'''
            )
        return f'''<p:sp>
  <p:nvSpPr><p:cNvPr id="{sid}" name="Bullets {sid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>
  <p:txBody><a:bodyPr wrap="square" anchor="t"/><a:lstStyle/>{''.join(paragraphs)}</p:txBody>
</p:sp>'''

    def _next_id(self) -> int:
        self.shape_id += 1
        return self.shape_id

    def _bg_for_layout(self, layout: str) -> str:
        if layout == "cover":
            return "F4F7F8"
        if layout in {"ask", "closing"}:
            return "F7F4EF"
        return "FFFFFF"

    def _content_types(self, slide_count: int) -> str:
        slide_overrides = "\n".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, slide_count + 1)
        )
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  {slide_overrides}
</Types>'''

    def _root_rels(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

    def _app_props(self, slide_count: int) -> str:
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Manus-Style PPTX Agent</Application>
  <PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides>
  <Notes>0</Notes>
  <HiddenSlides>0</HiddenSlides>
  <MMClips>0</MMClips>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Theme</vt:lpstr></vt:variant><vt:variant><vt:i4>1</vt:i4></vt:variant></vt:vector></HeadingPairs>
  <TitlesOfParts><vt:vector size="1" baseType="lpstr"><vt:lpstr>Office Theme</vt:lpstr></vt:vector></TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0000</AppVersion>
</Properties>'''

    def _core_props(self, deck: dict) -> str:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        title = html.escape(deck.get("title", "Pitch Deck"), quote=False)
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{title}</dc:title>
  <dc:creator>Manus-Style PPTX Agent</dc:creator>
  <cp:lastModifiedBy>Manus-Style PPTX Agent</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>'''

    def _presentation_xml(self, slide_count: int) -> str:
        slide_ids = "\n".join(
            f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, slide_count + 1)
        )
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle><a:defPPr><a:defRPr lang="en-US"/></a:defPPr></p:defaultTextStyle>
</p:presentation>'''

    def _presentation_rels(self, slide_count: int) -> str:
        rels = [
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        ]
        for i in range(1, slide_count + 1):
            rels.append(
                f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>'
            )
        return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {' '.join(rels)}
</Relationships>'''

    def _slide_rels(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>'''

    def _slide_master(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>'''

    def _slide_master_rels(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>'''

    def _slide_layout(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>'''

    def _slide_layout_rels(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>'''

    def _theme(self) -> str:
        return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Manus Agent Theme">
  <a:themeElements>
    <a:clrScheme name="Agent">
      <a:dk1><a:srgbClr val="17202A"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="2F3B46"/></a:dk2><a:lt2><a:srgbClr val="F3F6F8"/></a:lt2>
      <a:accent1><a:srgbClr val="087C7C"/></a:accent1><a:accent2><a:srgbClr val="D98F1F"/></a:accent2>
      <a:accent3><a:srgbClr val="C95746"/></a:accent3><a:accent4><a:srgbClr val="6F7B85"/></a:accent4>
      <a:accent5><a:srgbClr val="53606D"/></a:accent5><a:accent6><a:srgbClr val="E9F4F3"/></a:accent6>
      <a:hlink><a:srgbClr val="087C7C"/></a:hlink><a:folHlink><a:srgbClr val="6F7B85"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Aptos"><a:majorFont><a:latin typeface="Aptos Display"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="Default"><a:fillStyleLst/><a:lnStyleLst/><a:effectStyleLst/><a:bgFillStyleLst/></a:fmtScheme>
  </a:themeElements>
</a:theme>'''

