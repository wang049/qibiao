"""死区页按原图重画，时间数写在单元格里，图和文字要求随单元格变。"""

from __future__ import annotations

import posixpath
import re
import zipfile
from pathlib import Path

from lxml import etree
from openpyxl.utils import get_column_letter, range_boundaries

SHEET_NAME = "7_Dead Time"
_DEAD_CELL = "J7"
_PULSE_CELL = "J8"
_DEAD_LINK = "$AA$7"

_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_DRAWING_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_DRAWING_CT = "application/vnd.openxmlformats-officedocument.drawing+xml"

_DEAD_SENTENCE = re.compile(
    r"Dead time of PWM-H and PWM-L shall be set\s*([0-9]+(?:\.[0-9]+)?)\s*(?:μ|µ|u)?s",
    re.IGNORECASE,
)
_PULSE_SENTENCE = re.compile(
    r"Add Short Pulse Inhibition Time:\s*([0-9]+(?:\.[0-9]+)?)\s*(?:μ|µ|u)?s",
    re.IGNORECASE,
)


def apply_dead_time_sheet(path: Path) -> bool:
    """给 7_Dead Time 补上可改的死区时间，并换成矢量时序图。没有这张表则不动文件。"""
    path = Path(path)
    with zipfile.ZipFile(path) as book:
        sheet_path = _sheet_path(book)
        if sheet_path is None:
            return False
        shared = _shared_strings(book)
        root = etree.fromstring(book.read(sheet_path))
        dead, pulse = _read_times(root, shared)
        if dead is None and pulse is None:
            return False
        _write_inputs(root, dead, pulse)
        drawing_name, rels_name, sheet_rels_name, rels_root, drawing_id = _ensure_drawing(book, sheet_path, root)
        files = {
            sheet_path: _xml_bytes(root),
            drawing_name: _drawing_xml(dead if dead is not None else pulse).encode("utf-8"),
            rels_name: _empty_rels(),
        }
        if sheet_rels_name is not None and rels_root is not None:
            files[sheet_rels_name] = _xml_bytes(rels_root)
        content_types = _content_types(book, drawing_name)
        if content_types is not None:
            files["[Content_Types].xml"] = content_types
    _rewrite(path, files)
    return True


def _figure() -> dict[str, int]:
    """原图的几何：上框 PWM_H，中线向两侧伸出，下沿两侧各留一段死区。单位 EMU。"""
    return {
        "cx": 5200000,
        "cy": 2280000,
        "x0": 200000,
        "x1": 900000,
        "x2": 1680000,
        "x3": 3520000,
        "x4": 4300000,
        "x5": 5000000,
        "y0": 180000,
        "y1": 900000,
        "y2": 1460000,
        "y3": 2080000,
    }


def _resolve(base_file: str, target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return posixpath.normpath(target)
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_file), target))


def _sheet_path(book: zipfile.ZipFile) -> str | None:
    workbook = etree.fromstring(book.read("xl/workbook.xml"))
    rid = ""
    for sheet in workbook.findall(f".//{{{_SS}}}sheet"):
        if (sheet.get("name") or "").strip() == SHEET_NAME:
            rid = sheet.get(f"{{{_REL}}}id") or ""
            break
    if not rid:
        return None
    rels = etree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.get("Id") == rid:
            return _resolve("xl/workbook.xml", rel.get("Target") or "")
    return None


def _shared_strings(book: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = etree.fromstring(book.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(f"{{{_SS}}}si"):
        parts: list[str] = []
        for node in item.iter(f"{{{_SS}}}t"):
            parent = node.getparent()
            if parent is not None and parent.tag == f"{{{_SS}}}rPh":
                continue
            parts.append(node.text or "")
        values.append("".join(parts))
    return values


def _cell_text(cell: etree._Element, shared: list[str]) -> str:
    kind = cell.get("t") or ""
    if kind == "s":
        value = cell.findtext(f"{{{_SS}}}v") or ""
        if value.isdigit() and int(value) < len(shared):
            return shared[int(value)]
        return ""
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_SS}}}t"))
    return cell.findtext(f"{{{_SS}}}v") or ""


def _formula(cell: etree._Element | None) -> str:
    if cell is None:
        return ""
    return cell.findtext(f"{{{_SS}}}f") or ""


def _find_cell(root: etree._Element, ref: str) -> etree._Element | None:
    for cell in root.findall(f".//{{{_SS}}}c"):
        if cell.get("r") == ref:
            return cell
    return None


def _read_times(root: etree._Element, shared: list[str]) -> tuple[float | None, float | None]:
    dead = _number_cell(root, _DEAD_CELL)
    pulse = _number_cell(root, _PULSE_CELL)
    c4 = _find_cell(root, "C4")
    c5 = _find_cell(root, "C5")
    if dead is None and "TEXT(J7" not in _formula(c4):
        match = _DEAD_SENTENCE.search(_cell_text(c4, shared) if c4 is not None else "")
        if match:
            dead = float(match.group(1))
    if pulse is None and "TEXT(J8" not in _formula(c5):
        match = _PULSE_SENTENCE.search(_cell_text(c5, shared) if c5 is not None else "")
        if match:
            pulse = float(match.group(1))
    if dead is None and "TEXT(J7" in _formula(c4):
        dead = _number_cell(root, _DEAD_CELL)
    return dead, pulse


def _number_cell(root: etree._Element, ref: str) -> float | None:
    cell = _find_cell(root, ref)
    if cell is None or cell.get("t") in {"s", "inlineStr"}:
        return None
    raw = cell.findtext(f"{{{_SS}}}v")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _write_inputs(root: etree._Element, dead: float | None, pulse: float | None) -> None:
    style = ""
    sample = _find_cell(root, "C4")
    if sample is not None:
        style = sample.get("s") or ""
    sheet_data = root.find(f"{{{_SS}}}sheetData")
    if sheet_data is None:
        return
    if dead is not None:
        _upsert_number(sheet_data, _DEAD_CELL, dead, style)
        _upsert_text(sheet_data, "I7", "死区时间")
        _upsert_text(sheet_data, "K7", "μs")
        _upsert_formula(sheet_data, "AA7", 'TEXT(J7,"0.0")&"μs"', _label(dead))
        _replace_sentence(
            root,
            "C4",
            '"Dead time of PWM-H and PWM-L shall be set "&TEXT(J7,"0.0")&"μs；"',
            f"Dead time of PWM-H and PWM-L shall be set {_label(dead)}；",
        )
    if pulse is not None:
        _upsert_number(sheet_data, _PULSE_CELL, pulse, style)
        _upsert_text(sheet_data, "I8", "窄脉冲抑制")
        _upsert_text(sheet_data, "K8", "μs")
        _upsert_formula(sheet_data, "AA8", 'TEXT(J8,"0.0")&"μs"', _label(pulse))
        _replace_sentence(
            root,
            "C5",
            '"Add Short Pulse Inhibition Time: "&TEXT(J8,"0.0")&"μs；"',
            f"Add Short Pulse Inhibition Time: {_label(pulse)}；",
        )
    _hide_column(root, 27)
    _set_column_width(root, 9, 14)
    _set_column_width(root, 11, 8)
    _expand_dimension(root)


def _label(value: float) -> str:
    return f"{value:.1f}μs"


def _number_text(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _row(sheet_data: etree._Element, number: int) -> etree._Element:
    for row in sheet_data.findall(f"{{{_SS}}}row"):
        if int(row.get("r") or "0") == number:
            return row
    row = etree.Element(f"{{{_SS}}}row")
    row.set("r", str(number))
    placed = False
    for existing in sheet_data.findall(f"{{{_SS}}}row"):
        if int(existing.get("r") or "0") > number:
            existing.addprevious(row)
            placed = True
            break
    if not placed:
        sheet_data.append(row)
    return row


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch.upper()) - 64
    return index


def _place_cell(row: etree._Element, cell: etree._Element) -> None:
    ref = cell.get("r") or ""
    for existing in list(row.findall(f"{{{_SS}}}c")):
        if existing.get("r") == ref:
            existing.getparent().replace(existing, cell)
            return
    index = _column_index(ref)
    for existing in row.findall(f"{{{_SS}}}c"):
        if _column_index(existing.get("r") or "") > index:
            existing.addprevious(cell)
            return
    row.append(cell)
    row.set("spans", f"1:{max(_column_index(ref), 27)}")


def _upsert_number(sheet_data: etree._Element, ref: str, value: float, style: str) -> None:
    row = _row(sheet_data, int("".join(ch for ch in ref if ch.isdigit())))
    current = None
    for cell in row.findall(f"{{{_SS}}}c"):
        if cell.get("r") == ref:
            current = cell
            break
    if current is not None and current.get("t") not in {"s", "inlineStr"} and current.find(f"{{{_SS}}}f") is None:
        if current.findtext(f"{{{_SS}}}v") not in {None, ""}:
            return
    cell = etree.Element(f"{{{_SS}}}c")
    cell.set("r", ref)
    if style:
        cell.set("s", style)
    value_node = etree.SubElement(cell, f"{{{_SS}}}v")
    value_node.text = _number_text(value)
    _place_cell(row, cell)


def _upsert_text(sheet_data: etree._Element, ref: str, text: str) -> None:
    row = _row(sheet_data, int("".join(ch for ch in ref if ch.isdigit())))
    for cell in row.findall(f"{{{_SS}}}c"):
        if cell.get("r") == ref and "".join(node.text or "" for node in cell.iter(f"{{{_SS}}}t")) == text:
            return
    cell = etree.Element(f"{{{_SS}}}c")
    cell.set("r", ref)
    cell.set("t", "inlineStr")
    inline = etree.SubElement(cell, f"{{{_SS}}}is")
    node = etree.SubElement(inline, f"{{{_SS}}}t")
    node.text = text
    _place_cell(row, cell)


def _upsert_formula(sheet_data: etree._Element, ref: str, formula: str, cached: str) -> None:
    row = _row(sheet_data, int("".join(ch for ch in ref if ch.isdigit())))
    cell = etree.Element(f"{{{_SS}}}c")
    cell.set("r", ref)
    cell.set("t", "str")
    formula_node = etree.SubElement(cell, f"{{{_SS}}}f")
    formula_node.text = formula
    value_node = etree.SubElement(cell, f"{{{_SS}}}v")
    value_node.text = cached
    _place_cell(row, cell)


def _replace_sentence(root: etree._Element, ref: str, formula: str, cached: str) -> None:
    cell = _find_cell(root, ref)
    if cell is None:
        return
    current = _formula(cell)
    if current and "TEXT(J7" not in current and "TEXT(J8" not in current:
        return
    style = cell.get("s")
    for child in list(cell):
        cell.remove(child)
    if "t" in cell.attrib:
        del cell.attrib["t"]
    if style:
        cell.set("s", style)
    cell.set("t", "str")
    formula_node = etree.SubElement(cell, f"{{{_SS}}}f")
    formula_node.text = formula
    value_node = etree.SubElement(cell, f"{{{_SS}}}v")
    value_node.text = cached


def _set_column_width(root: etree._Element, index: int, width: float) -> None:
    cols = root.find(f"{{{_SS}}}cols")
    if cols is None:
        cols = etree.Element(f"{{{_SS}}}cols")
        anchor = root.find(f"{{{_SS}}}sheetData")
        if anchor is not None:
            anchor.addprevious(cols)
        else:
            root.append(cols)
    for col in cols.findall(f"{{{_SS}}}col"):
        start = int(col.get("min") or "0")
        end = int(col.get("max") or "0")
        if start == index and end == index:
            col.set("width", str(width))
            col.set("customWidth", "1")
            return
        if start <= index <= end:
            return
    col = etree.SubElement(cols, f"{{{_SS}}}col")
    col.set("min", str(index))
    col.set("max", str(index))
    col.set("width", str(width))
    col.set("customWidth", "1")


def _hide_column(root: etree._Element, index: int) -> None:
    cols = root.find(f"{{{_SS}}}cols")
    if cols is None:
        cols = etree.Element(f"{{{_SS}}}cols")
        anchor = root.find(f"{{{_SS}}}sheetData")
        if anchor is not None:
            anchor.addprevious(cols)
        else:
            root.append(cols)
    for col in cols.findall(f"{{{_SS}}}col"):
        start = int(col.get("min") or "0")
        end = int(col.get("max") or "0")
        if start <= index <= end:
            col.set("hidden", "1")
            return
    col = etree.SubElement(cols, f"{{{_SS}}}col")
    col.set("min", str(index))
    col.set("max", str(index))
    col.set("width", "3")
    col.set("hidden", "1")
    col.set("customWidth", "1")


def _expand_dimension(root: etree._Element) -> None:
    dimension = root.find(f"{{{_SS}}}dimension")
    if dimension is None or not dimension.get("ref"):
        return
    min_col, min_row, max_col, max_row = range_boundaries(dimension.get("ref"))
    min_col = min(min_col, 1)
    min_row = min(min_row, 2)
    max_col = max(max_col, 27)
    max_row = max(max_row, 8)
    dimension.set("ref", f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}")


def _ensure_drawing(
    book: zipfile.ZipFile,
    sheet_path: str,
    root: etree._Element,
) -> tuple[str, str, str | None, etree._Element | None, str]:
    rels_name = posixpath.join(posixpath.dirname(sheet_path), "_rels", posixpath.basename(sheet_path) + ".rels")
    rels_root = etree.fromstring(book.read(rels_name)) if rels_name in book.namelist() else etree.Element(
        f"{{{_PKG}}}Relationships", nsmap={None: _PKG}
    )
    drawing_id = ""
    drawing_name = ""
    for rel in rels_root:
        if rel.get("Type") == _DRAWING_REL:
            drawing_id = rel.get("Id") or ""
            drawing_name = _resolve(sheet_path, rel.get("Target") or "")
            break
    if not drawing_id:
        used = {rel.get("Id") or "" for rel in rels_root}
        number = 1
        while f"rId{number}" in used:
            number += 1
        drawing_id = f"rId{number}"
        drawing_name = "xl/drawings/drawing_dead_time.xml"
        rel = etree.SubElement(rels_root, f"{{{_PKG}}}Relationship")
        rel.set("Id", drawing_id)
        rel.set("Type", _DRAWING_REL)
        rel.set("Target", "../drawings/drawing_dead_time.xml")
    drawing = root.find(f"{{{_SS}}}drawing")
    if drawing is None:
        drawing = etree.Element(f"{{{_SS}}}drawing")
        picture = root.find(f"{{{_SS}}}picture")
        if picture is not None:
            picture.addprevious(drawing)
        else:
            root.append(drawing)
    drawing.set(f"{{{_REL}}}id", drawing_id)
    drawing_rels = posixpath.join(posixpath.dirname(drawing_name), "_rels", posixpath.basename(drawing_name) + ".rels")
    return drawing_name, drawing_rels, rels_name, rels_root, drawing_id


def _content_types(book: zipfile.ZipFile, drawing_name: str) -> bytes | None:
    if "[Content_Types].xml" not in book.namelist():
        return None
    root = etree.fromstring(book.read("[Content_Types].xml"))
    part = "/" + drawing_name
    for node in root:
        if node.get("PartName") == part:
            return None
    override = etree.SubElement(root, f"{{{_CT}}}Override")
    override.set("PartName", part)
    override.set("ContentType", _DRAWING_CT)
    return _xml_bytes(root)


def _empty_rels() -> bytes:
    root = etree.Element(f"{{{_PKG}}}Relationships", nsmap={None: _PKG})
    return _xml_bytes(root)


def _xml_bytes(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _drawing_xml(dead: float | None) -> str:
    box = _figure()
    label = _label(dead if dead is not None else 1.6)
    shapes = [_panel(box)]
    next_id = 20
    for x, y, w, h in _segments(box):
        shapes.append(_bar(next_id, x, y, w, h))
        next_id += 1
    for origin in (box["x1"], box["x3"]):
        shapes.append(_arrow_shape(next_id, *_arrow_box(box, origin)))
        next_id += 1
    shapes.append(_text_box(
        2, "PWM_H", "PWM_H",
        box["x2"], box["y0"], box["x3"] - box["x2"], box["y1"] - box["y0"],
        1500, "",
    ))
    shapes.append(_text_box(
        3, "PWM_L", "PWM_L",
        box["x2"], box["y1"], box["x3"] - box["x2"], box["y3"] - box["y1"],
        1500, "",
    ))
    shapes.append(_text_box(
        6, "dead-left", label,
        box["x1"], box["y1"], box["x2"] - box["x1"], box["y2"] - box["y1"],
        1100, _DEAD_LINK,
    ))
    shapes.append(_text_box(
        7, "dead-right", label,
        box["x3"], box["y1"], box["x4"] - box["x3"], box["y2"] - box["y1"],
        1100, _DEAD_LINK,
    ))
    body = "\n".join(shapes)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <xdr:oneCellAnchor>
    <xdr:from><xdr:col>1</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>6</xdr:row><xdr:rowOff>40000</xdr:rowOff></xdr:from>
    <xdr:ext cx="{box["cx"]}" cy="{box["cy"]}"/>
    <xdr:grpSp>
      <xdr:nvGrpSpPr>
        <xdr:cNvPr id="1" name="Dead time"/>
        <xdr:cNvGrpSpPr/>
      </xdr:nvGrpSpPr>
      <xdr:grpSpPr>
        <a:xfrm>
          <a:off x="0" y="0"/>
          <a:ext cx="{box["cx"]}" cy="{box["cy"]}"/>
          <a:chOff x="0" y="0"/>
          <a:chExt cx="{box["cx"]}" cy="{box["cy"]}"/>
        </a:xfrm>
      </xdr:grpSpPr>
      {body}
    </xdr:grpSp>
    <xdr:clientData/>
  </xdr:oneCellAnchor>
</xdr:wsDr>
"""


def _panel(box: dict[str, int]) -> str:
    return f"""<xdr:sp>
      <xdr:nvSpPr><xdr:cNvPr id="8" name="panel"/><xdr:cNvSpPr/></xdr:nvSpPr>
      <xdr:spPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="{box["cx"]}" cy="{box["cy"]}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>
        <a:ln><a:noFill/></a:ln>
      </xdr:spPr>
      <xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></xdr:txBody>
    </xdr:sp>"""


def _segments(box: dict[str, int]) -> list[tuple[int, int, int, int]]:
    """用矩形拼折线。WPS 会截断 custGeom 里过大的坐标，右半边会断开。"""
    thick = 16000
    half = thick // 2
    pieces: list[tuple[int, int, int, int]] = []

    def horizontal(x1: int, x2: int, y: int) -> None:
        pieces.append((min(x1, x2), y - half, abs(x2 - x1), thick))

    def vertical(x: int, y1: int, y2: int) -> None:
        pieces.append((x - half, min(y1, y2), thick, abs(y2 - y1)))

    horizontal(box["x0"], box["x2"], box["y1"])
    vertical(box["x2"], box["y0"], box["y1"])
    horizontal(box["x2"], box["x3"], box["y0"])
    vertical(box["x3"], box["y0"], box["y1"])
    horizontal(box["x3"], box["x5"], box["y1"])
    horizontal(box["x0"], box["x1"], box["y2"])
    vertical(box["x1"], box["y2"], box["y3"])
    horizontal(box["x1"], box["x4"], box["y3"])
    vertical(box["x4"], box["y2"], box["y3"])
    horizontal(box["x4"], box["x5"], box["y2"])
    dash, gap = 70000, 52000
    for x in (box["x2"], box["x3"]):
        y = box["y1"] + 90000
        end = box["y3"] - 70000
        while y < end:
            stop = min(y + dash, end)
            vertical(x, y, stop)
            y = stop + gap
    return pieces


def _bar(shape_id: int, x: int, y: int, w: int, h: int) -> str:
    return f"""<xdr:sp>
      <xdr:nvSpPr><xdr:cNvPr id="{shape_id}" name="seg-{shape_id}"/><xdr:cNvSpPr/></xdr:nvSpPr>
      <xdr:spPr>
        <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{max(w, 1)}" cy="{max(h, 1)}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        <a:solidFill><a:srgbClr val="222222"/></a:solidFill>
        <a:ln><a:noFill/></a:ln>
      </xdr:spPr>
      <xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></xdr:txBody>
    </xdr:sp>"""


def _arrow_box(box: dict[str, int], origin: int) -> tuple[int, int, int, int]:
    gap = box["x2"] - box["x1"]
    inset = 130000
    width = gap - 2 * inset
    height = 120000
    notch = box["y3"] - box["y2"]
    return origin + inset, box["y2"] + (notch - height) // 2, width, height


def _arrow_shape(shape_id: int, x: int, y: int, w: int, h: int) -> str:
    return f"""<xdr:sp>
      <xdr:nvSpPr><xdr:cNvPr id="{shape_id}" name="arrow-{shape_id}"/><xdr:cNvSpPr/></xdr:nvSpPr>
      <xdr:spPr>
        <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
        <a:prstGeom prst="leftRightArrow">
          <a:avLst>
            <a:gd name="adj1" fmla="val 28000"/>
            <a:gd name="adj2" fmla="val 18000"/>
          </a:avLst>
        </a:prstGeom>
        <a:solidFill><a:srgbClr val="222222"/></a:solidFill>
        <a:ln><a:noFill/></a:ln>
      </xdr:spPr>
      <xdr:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/></a:p></xdr:txBody>
    </xdr:sp>"""


def _text_box(shape_id: int, name: str, text: str, x: int, y: int, w: int, h: int, size: int, link: str) -> str:
    link_attr = f' textlink="{link}"' if link else ""
    return f"""<xdr:sp{link_attr}>
      <xdr:nvSpPr><xdr:cNvPr id="{shape_id}" name="{name}"/><xdr:cNvSpPr txBox="1"/></xdr:nvSpPr>
      <xdr:spPr>
        <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
        <a:noFill/>
        <a:ln><a:noFill/></a:ln>
      </xdr:spPr>
      <xdr:txBody>
        <a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"/>
        <a:lstStyle/>
        <a:p>
          <a:pPr algn="ctr"/>
          <a:r>
            <a:rPr lang="en-US" sz="{size}" dirty="0">
              <a:solidFill><a:srgbClr val="222222"/></a:solidFill>
              <a:latin typeface="Calibri"/>
              <a:ea typeface="等线"/>
            </a:rPr>
            <a:t>{text}</a:t>
          </a:r>
        </a:p>
      </xdr:txBody>
    </xdr:sp>"""


def _rewrite(path: Path, files: dict[str, bytes]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
        written: set[str] = set()
        for info in source.infolist():
            written.add(info.filename)
            data = files.get(info.filename)
            if data is None:
                target.writestr(info, source.read(info.filename))
                continue
            replaced = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            replaced.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(replaced, data)
        for name, data in files.items():
            if name not in written:
                target.writestr(name, data)
    temporary.replace(path)
