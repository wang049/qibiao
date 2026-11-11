"""从结构二维图的标题栏和明细栏抽出 CE BOM 能对上的字段。

产品尺寸先认「外形尺寸」后的长×宽×高。没有这一栏时，认图面上括号括起的三个外形尺寸。平面图横向是 X，同一视图的竖向是 Y，另一视图的高度是 Z。全周槽、最大值这类局部尺寸不写入。质量没有单位时不写入净重。级别不按图号编造。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PART_NO = re.compile(r"\d{10}")
_WEIGHT = re.compile(r"^\d+(?:\.\d+)?\s*g$", re.I)
_THICKNESS = re.compile(r"板料厚度\s*([0-9]+(?:\.[0-9]+)?(?:±[0-9]+(?:\.[0-9]+)?)?)\s*mm")
_OUTLINE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×X*]\s*(\d+(?:\.\d+)?)\s*[x×X*]\s*(\d+(?:\.\d+)?)"
)
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
    size_x: str = ""
    size_y: str = ""
    size_z: str = ""
    picture: bytes = b""


def _text(value: str) -> str:
    return value.replace("\xa0", " ").strip()


def _outline_sizes(words: list[tuple[float, float, float, float, str]]) -> tuple[str, str, str]:
    """先认外形尺寸栏。没有时，用图面括号里恰好三个的外形参考尺寸。"""
    outline = _below(
        words,
        "外形尺寸",
        accept=lambda text: _OUTLINE.search(text.replace(" ", "")) is not None,
    )
    if outline:
        found = _OUTLINE.search(outline.replace(" ", ""))
        if found:
            return found.group(1), found.group(2), found.group(3)
    boxed = _parenthetical_numbers(words)
    if len(boxed) != 3:
        return "", "", ""
    horizontal = [item for item in boxed if item[1] == "h"]
    vertical = [item for item in boxed if item[1] == "v"]
    if len(horizontal) != 1 or len(vertical) != 2:
        return "", "", ""
    length = horizontal[0]
    nearer, farther = sorted(vertical, key=lambda item: abs(item[2] - length[2]))
    return length[0], nearer[0], farther[0]


def _parenthetical_numbers(
    words: list[tuple[float, float, float, float, str]],
) -> list[tuple[str, str, float]]:
    """括号里单独一个数字。横向括号算平面图的长，竖向括号算宽或高。"""
    opens = [word for word in words if word[4] == "("]
    closes = [word for word in words if word[4] == ")"]
    found: list[tuple[str, str, float]] = []
    for word in words:
        text = word[4]
        if not re.fullmatch(r"\d+(?:\.\d+)?", text):
            continue
        x0, y0, x1, y1 = word[:4]
        left = any(abs(item[1] - y0) < 6 and 0 <= x0 - item[2] <= 12 for item in opens)
        right = any(abs(item[1] - y0) < 6 and 0 <= item[0] - x1 <= 12 for item in closes)
        if left and right:
            found.append((text, "h", (y0 + y1) / 2, (x0 + x1) / 2))
            continue
        above = any(abs(item[0] - x0) < 8 and 0 <= y0 - item[3] <= 12 for item in closes + opens)
        below = any(abs(item[0] - x0) < 8 and 0 <= item[1] - y1 <= 12 for item in opens + closes)
        if above and below:
            found.append((text, "v", (y0 + y1) / 2, (x0 + x1) / 2))
    return found


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
    size_x, size_y, size_z = _outline_sizes(words)
    return StructureRow(
        title, part_no, "", thickness, weight, material, parent, source, note,
        size_x, size_y, size_z,
    )


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


def _ink_runs(page, clip, *, axis: str) -> list[tuple[float, float]]:
    """深色像素连在一起的一段。用来把主视图和旁边的局部视图分开。"""
    import pymupdf

    scale = 0.05
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, clip=clip, alpha=False)
    width, height = pix.width, pix.height
    samples = memoryview(pix.samples)
    runs: list[tuple[float, float]] = []
    start = -1
    span = width if axis == "x" else height
    for index in range(span):
        if axis == "x":
            dark = sum(1 for y in range(height) if samples[y * width + index] < 210)
        else:
            dark = sum(1 for x in range(width) if samples[index * width + x] < 210)
        if dark > 6 and start < 0:
            start = index
        elif dark <= 6 and start >= 0:
            origin = clip.x0 if axis == "x" else clip.y0
            runs.append((origin + start / scale, origin + index / scale))
            start = -1
    if start >= 0:
        origin = clip.x0 if axis == "x" else clip.y0
        runs.append((origin + start / scale, origin + span / scale))
    return [run for run in runs if run[1] - run[0] >= 80]


def _main_view_clips(page, words: list[tuple[float, float, float, float, str]]):
    """外形尺寸旁边的两张主视图。不把左边另一张视图和右边的局部放大一起截进来。"""
    import pymupdf

    boxed = _parenthetical_numbers(words)
    horizontal = [item for item in boxed if item[1] == "h"]
    vertical = [item for item in boxed if item[1] == "v"]
    if len(horizontal) != 1 or len(vertical) != 2:
        return []
    length = horizontal[0]
    width_dim, height_dim = sorted(vertical, key=lambda item: abs(item[2] - length[2]))
    clips = []
    for dim, below in ((height_dim, False), (length, True)):
        cx, cy = dim[3], dim[2]
        if below:
            window = pymupdf.Rect(cx - 900, min(cy, width_dim[2]) - 80, width_dim[3] + 80, max(cy, width_dim[2]) + 280)
        else:
            window = pymupdf.Rect(cx - 900, cy - 180, cx + 80, cy + 180)
        window = window & page.rect
        runs = _ink_runs(page, window, axis="x")
        if not runs:
            continue
        anchor = width_dim[3] if below else cx
        left, right = min(runs, key=lambda run: abs(run[1] - anchor))
        if below:
            clips.append(pymupdf.Rect(left - 16, window.y0, min(right, width_dim[3]) + 36, window.y1))
        else:
            clips.append(pymupdf.Rect(left - 16, window.y0, cx + 36, window.y1))
    return clips


def _view_png(page) -> bytes:
    """截外形尺寸旁边的主视图。整页左上角、技术要求和标题栏不放进图片。"""
    import pymupdf
    from io import BytesIO

    from PIL import Image as PilImage

    words = [(word[0], word[1], word[2], word[3], word[4]) for word in page.get_text("words")]
    clips = _main_view_clips(page, words)
    if not clips:
        notes_x = page.rect.width
        for word in words:
            text = word[4]
            if word[0] > page.rect.width * 0.5 and len(text) >= 8 and text.startswith(("1.", "1、")):
                notes_x = min(notes_x, word[0])
        title_top = page.rect.height
        for word in words:
            if word[4] in {"图样名称", "图样代号"} and word[1] > page.rect.height * 0.5:
                title_top = min(title_top, word[1])
        right = notes_x - 16 if notes_x < page.rect.width else page.rect.width * 0.7
        bottom = title_top - 16 if title_top < page.rect.height else page.rect.height * 0.82
        clips = [pymupdf.Rect(24, 24, max(right, 80), max(bottom, 80)) & page.rect]
    images = []
    for clip in clips:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(0.55, 0.55), clip=clip, alpha=False)
        images.append(PilImage.open(BytesIO(pix.tobytes("png"))).convert("RGB"))
    width = max(image.width for image in images)
    gap = 12
    canvas = PilImage.new("RGB", (width, sum(image.height for image in images) + gap * (len(images) - 1)), "white")
    top = 0
    for image in images:
        canvas.paste(image, ((width - image.width) // 2, top))
        top += image.height + gap
    canvas.thumbnail((420, 360))
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


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
            picture = _view_png(page)
            if picture:
                title = StructureRow(
                    title.name, title.part_no, title.quantity, title.thickness, title.weight,
                    title.material, title.parent, title.source, title.note,
                    title.size_x, title.size_y, title.size_z, picture,
                )
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
                                    title.size_x,
                                    title.size_y,
                                    title.size_z,
                                    title.picture,
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
