"""从结构二维图的标题栏和明细栏抽出 CE BOM 能对上的字段。

产品尺寸不从散落的标注里挑。质量没有单位时不写入净重。级别不按图号编造。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PART_NO = re.compile(r"\d{10}")
_WEIGHT = re.compile(r"^\d+(?:\.\d+)?\s*g$", re.I)
_THICKNESS = re.compile(r"板料厚度\s*([0-9]+(?:\.[0-9]+)?(?:±[0-9]+(?:\.[0-9]+)?)?)\s*mm")
_SKIP_VALUE = frozenset({"Material", "Mark", "Weight", "Amount", "Drawing", "Title:", "Part", "NO", "NO."})
_NOT_MATERIAL = frozenset({
    "日期", "签字", "设计", "校对", "审核", "批准", "图样名称", "图样标记", "图样代号",
    "数量", "质量", "比例", "版本号", "项目编号", "Date", "Signature", "Version",
})


@dataclass(frozen=True)
class StructureRow:
    name: str
    part_no: str
    quantity: str
    thickness: str
    weight: str
    material: str
    parent: str
    source: str
    note: str


def _text(value: str) -> str:
    return value.replace("\xa0", " ").strip()


def _chinese_title(text: str) -> str:
    return re.sub(r"\[\d+\]$", "", _text(text)).strip()


def _below(
    words: list[tuple[float, float, float, float, str]],
    label: str,
    *,
    dy: tuple[float, float] = (6, 45),
    dx: float = 140,
    accept=None,
) -> str:
    anchors = [word for word in words if word[4] == label]
    if not anchors:
        return ""
    anchor = anchors[0]
    found: list[tuple[float, str]] = []
    for word in words:
        text = _text(word[4])
        if not text or text in _SKIP_VALUE or text == label:
            continue
        if accept is not None and not accept(text):
            continue
        shift_y = word[1] - anchor[1]
        shift_x = abs(word[0] - anchor[0])
        if dy[0] <= shift_y <= dy[1] and shift_x <= dx:
            found.append((shift_y, shift_x, text))
    if not found:
        return ""
    found.sort()
    return found[0][2]


def _title_row(words: list[tuple[float, float, float, float, str]], source: str) -> StructureRow | None:
    title = _chinese_title(_below(words, "图样名称", accept=lambda text: bool(re.search(r"[\u4e00-\u9fff]", text))))
    if not title:
        return None
    part_no = _below(words, "图样代号", accept=lambda text: bool(_PART_NO.fullmatch(text)))
    parent = _below(words, "上级总成", accept=lambda text: bool(_PART_NO.fullmatch(text)))
    material = _below(
        words,
        "材料标记",
        accept=lambda text: bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text)) and text not in _NOT_MATERIAL,
    )
    weight = _below(words, "质量", accept=lambda text: bool(re.fullmatch(r"\d+(?:\.\d+)?g?", text.replace(" ", ""), re.I)))
    note = ""
    if weight and not _WEIGHT.match(weight.replace(" ", "")):
        note = f"图样质量栏为 {weight}，未标单位，不写入净重"
        weight = ""
    thickness = ""
    if "盖板" in title:
        blob = " ".join(word[4] for word in words)
        matched = _THICKNESS.search(blob.replace(" ", ""))
        if matched is None:
            matched = _THICKNESS.search(" ".join(word[4] for word in words))
        if matched:
            thickness = matched.group(1) + "mm"
    return StructureRow(title, part_no, "", thickness, weight, material, parent, source, note)


def _bom_rows(words: list[tuple[float, float, float, float, str]], source: str, parent: str) -> list[StructureRow]:
    header = [word for word in words if word[4] == "序号"]
    if not header:
        return []
    head = min(header, key=lambda word: word[0])
    band = [word for word in words if abs(word[1] - head[1]) <= 4 and word[0] >= head[0] - 5]
    columns: list[tuple[float, str]] = []
    for word in band:
        if word[4] in {"序号", "零件名", "零件名称", "材料", "材料标记", "数量", "零件号"}:
            columns.append((word[0], word[4]))
    if not any(name in {"零件名", "零件名称"} for _x, name in columns):
        return []
    columns.sort()
    below = [word for word in words if head[1] + 8 <= word[1] <= head[1] + 160 and word[0] >= head[0] - 8]
    above = [word for word in words if head[1] - 160 <= word[1] <= head[1] - 8 and word[0] >= head[0] - 8]

    def _row_numbers(group: list[tuple[float, float, float, float, str]]) -> int:
        count = 0
        for word in group:
            if abs(word[0] - head[0]) <= 30 and word[4].isdigit() and int(word[4]) <= 30:
                count += 1
        return count

    body = below if _row_numbers(below) >= _row_numbers(above) else above
    anchors = [
        word
        for word in body
        if abs(word[0] - head[0]) <= 40 and word[4].isdigit() and int(word[4]) <= 30
    ]
    rows: list[StructureRow] = []
    for anchor in sorted(anchors, key=lambda word: int(word[4])):
        cells: dict[str, list[str]] = {}
        for word in body:
            if abs(word[1] - anchor[1]) > 12:
                continue
            column = min(columns, key=lambda item: abs(item[0] - word[0]))[1]
            if column == "材料标记":
                column = "材料"
            if column == "零件名称":
                column = "零件名"
            text = _text(word[4])
            if text in {"/", "序号"} or text.startswith(("CAD", "DWG")) or re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", text):
                continue
            cells.setdefault(column, []).append(text)
        name = "".join(cells.get("零件名", []))
        if not name or name in {"零件名", "零件名称", "/"}:
            continue
        quantity = "".join(item for item in cells.get("数量", []) if item.isdigit())
        material = "".join(item for item in cells.get("材料", []) if item != "/")
        part_no = "".join(cells.get("零件号", []))
        if not _PART_NO.fullmatch(part_no):
            part_no = ""
        rows.append(StructureRow(name, part_no, quantity, "", "", material, parent, source, ""))
    return rows


def read_structure_drawing(path: Path) -> list[StructureRow]:
    """读一张结构二维图。不是这种图则返回空。"""
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return []
    import pymupdf

    doc = pymupdf.open(path)
    try:
        found: list[StructureRow] = []
        seen_titles: set[str] = set()
        for page in doc:
            words = [(word[0], word[1], word[2], word[3], word[4]) for word in page.get_text("words")]
            if not any(word[4] == "图样名称" for word in words):
                continue
            title = _title_row(words, path.name)
            if title is None:
                continue
            details = _bom_rows(words, path.name, title.part_no)
            key = title.part_no or title.name
            if key not in seen_titles:
                seen_titles.add(key)
                covered = any(row.name == title.name or (title.part_no and row.part_no == title.part_no) for row in details)
                if covered:
                    for row in details:
                        if row.name == title.name or (title.part_no and row.part_no == title.part_no):
                            found.append(
                                StructureRow(
                                    row.name or title.name,
                                    row.part_no or title.part_no,
                                    row.quantity,
                                    row.thickness or title.thickness,
                                    row.weight or title.weight,
                                    row.material or title.material,
                                    title.parent,
                                    path.name,
                                    title.note,
                                )
                            )
                        else:
                            found.append(row)
                else:
                    found.append(title)
                    found.extend(details)
            elif details:
                found.extend(row for row in details if row.name != title.name)
        return found
    finally:
        doc.close()
