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


def _owned_column(x: float, columns: list[tuple[float, str]]) -> str:
    """字落在哪一列表头的半宽里，才算这一列。隔列的标注不就近并进来。"""
    ordered = sorted(columns)
    for index, (origin, name) in enumerate(ordered):
        left = (ordered[index - 1][0] + origin) / 2 if index else origin - 36
        right = (origin + ordered[index + 1][0]) / 2 if index + 1 < len(ordered) else origin + 36
        if left <= x <= right:
            if name == "材料标记":
                return "材料"
            if name == "零件名称":
                return "零件名"
            return name
    return ""


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
            column = _owned_column(word[0], columns)
            if not column:
                continue
            text = _text(word[4])
            if re.search(r"±|技术要求|未注公差|未注|MAX", text, re.I):
                continue
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


def _scanned_view_clip(page):
    """没有文字层时，截标题栏以外的全部视图。右下角标题栏不占画面。"""
    import pymupdf

    rect = page.rect
    title = pymupdf.Rect(
        rect.x0 + rect.width * 0.58,
        rect.y0 + rect.height * 0.72,
        rect.x1,
        rect.y1,
    )
    # 0.06 倍时密封圈这种细线会消失，只剩清洁度表那种深色网格。
    scale = 0.28
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY, clip=rect, alpha=False)
    width, height = pix.width, pix.height
    samples = memoryview(pix.samples)
    min_x, min_y, max_x, max_y = width, height, 0, 0
    found = False
    for y in range(height):
        row = y * width
        for x in range(width):
            if samples[row + x] >= 242:
                continue
            px = rect.x0 + x / scale
            py = rect.y0 + y / scale
            if title.x0 <= px <= title.x1 and title.y0 <= py <= title.y1:
                continue
            found = True
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
    if not found:
        return rect
    box = pymupdf.Rect(
        rect.x0 + min_x / scale - 10,
        rect.y0 + min_y / scale - 10,
        rect.x0 + (max_x + 1) / scale + 10,
        rect.y0 + (max_y + 1) / scale + 10,
    )
    return box & rect


def _view_png(page) -> bytes:
    """有文字层时截外形尺寸旁边的主视图。扫描图截标题栏以外的全部视图，并保留足够像素。"""
    import pymupdf
    from io import BytesIO

    from PIL import Image as PilImage

    words = [(word[0], word[1], word[2], word[3], word[4]) for word in page.get_text("words")]
    clips = _main_view_clips(page, words)
    if not clips and words:
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
    elif not clips:
        clips = [_scanned_view_clip(page)]
    images = []
    zoom = 1.8
    for clip in clips:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
        images.append(PilImage.open(BytesIO(pix.tobytes("png"))).convert("RGB"))
    width = max(image.width for image in images)
    gap = 12
    canvas = PilImage.new("RGB", (width, sum(image.height for image in images) + gap * (len(images) - 1)), "white")
    top = 0
    for image in images:
        canvas.paste(image, ((width - image.width) // 2, top))
        top += image.height + gap
    if max(canvas.size) > 1800:
        canvas.thumbnail((1800, 1800), PilImage.Resampling.LANCZOS)
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _center(word: tuple[float, float, float, float, str]) -> tuple[float, float]:
    return ((word[0] + word[2]) / 2, (word[1] + word[3]) / 2)


def _nearest(origin: tuple[float, float], words: list[tuple[float, float, float, float, str]]):
    best = None
    best_distance = 0.0
    for word in words:
        cx, cy = _center(word)
        distance = (cx - origin[0]) ** 2 + (cy - origin[1]) ** 2
        if best is None or distance < best_distance:
            best = word
            best_distance = distance
    return best


def _ocr_title_words(page) -> list[tuple[float, float, float, float, str]]:
    """没有文字层的图纸，只认标题栏这一块。"""
    import os
    import tempfile

    import pymupdf

    try:
        from electrical_krow.arch_ocr import _ocr_engine
    except Exception:
        return []
    clip = pymupdf.Rect(page.rect.width * 0.55, page.rect.height * 0.58, page.rect.width, page.rect.height)
    zoom = 2.6
    fd, image_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False).save(image_path)
        result = _ocr_engine()(image_path)
    except Exception:
        return []
    finally:
        try:
            os.unlink(image_path)
        except OSError:
            pass
    txts = getattr(result, "txts", None) or ()
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    words: list[tuple[float, float, float, float, str]] = []
    for text, box in zip(txts, boxes):
        shown = _text(str(text))
        if not shown:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        words.append(
            (
                clip.x0 + min(xs) / zoom,
                clip.y0 + min(ys) / zoom,
                clip.x0 + max(xs) / zoom,
                clip.y0 + max(ys) / zoom,
                shown,
            )
        )
    return words


_NAME_SKIP = ("极光湾", "科技", "有限公司", "质量", "比例", "日期", "签字", "设计", "审核", "批准", "校对", "会签", "标准", "数量", "材料", "版本", "项目", "特性")


def _ocr_name(text: str) -> bool:
    shown = _chinese_title(text)
    if len(re.findall(r"[\u4e00-\u9fff]", shown)) < 2:
        return False
    return not any(token in shown for token in _NAME_SKIP)


def _title_from_ocr(
    words: list[tuple[float, float, float, float, str]],
    source: str,
) -> StructureRow | None:
    """扫描件标题栏没有「图样名称」这四个字时，用零件名、图号和质量。"""
    names = [word for word in words if _ocr_name(word[4])]
    pool = [word for word in names if re.search(r"\[\d+\]", word[4])]
    labels = [
        word
        for word in words
        if re.search(r"图样名称|图科名称|drawing\s*title|dr[ae][ws]ing\s*[tjil]", word[4], re.I)
    ]
    name_word = _nearest(_center(labels[0]), pool) if labels and pool else (max(pool, key=lambda word: word[0]) if pool else None)
    title = _chinese_title(name_word[4]) if name_word else ""
    numbers = []
    for word in words:
        compact = re.sub(r"\s+", "", word[4])
        if _PART_NO.fullmatch(compact):
            numbers.append((word[0], word[1], word[2], word[3], compact))
            continue
        found = _PART_NO.search(compact)
        if found and found.group(0) != compact:
            numbers.append((word[0], word[1], word[2], word[3], found.group(0)))
    part_no = ""
    if numbers:
        counts: dict[str, int] = {}
        for word in numbers:
            counts[word[4]] = counts.get(word[4], 0) + 1
        part_no = max(counts, key=counts.get)
    parent = ""
    others = [word for word in numbers if word[4] != part_no]
    parent_labels = [word for word in words if re.search(r"总成|上级|Assembly|Ass", word[4], re.I)]
    if others and parent_labels:
        parent = _nearest(_center(parent_labels[0]), others)[4]
    elif len({word[4] for word in others}) == 1 and others:
        parent = others[0][4]
    weight = ""
    weights = [word for word in words if re.fullmatch(r"\d+(?:\.\d+)?g", word[4].replace(" ", ""), re.I)]
    mass_labels = [word for word in words if word[4] == "质量" or word[4].startswith("质量")]
    if weights and mass_labels:
        weight = _nearest(_center(mass_labels[0]), weights)[4].replace(" ", "")
    elif len(weights) == 1:
        weight = weights[0][4].replace(" ", "")
    if weight and not _WEIGHT.match(weight):
        weight = ""
    material = ""
    material_labels = [word for word in words if re.search(r"材料|Material|Moterial|Materiol|Moleriol", word[4], re.I)]

    def _material_text(text: str) -> str:
        token = re.sub(r"^A[1lI](?=\d{3,4})", "Al", text.replace(" ", ""))
        if re.fullmatch(r"EPDM|NBR|FKM|VMQ", token, re.I):
            return token.upper()
        if re.search(r"^(Al|ADC|PPS|PA|T2)\d", token, re.I) or re.search(r"碳钢|铝合金|铜", token):
            return token
        return ""

    if material_labels:
        hit = _nearest(
            _center(material_labels[0]),
            [word for word in words if _material_text(word[4])],
        )
        if hit:
            material = _material_text(hit[4])
    if not material:
        tokens = []
        for word in words:
            token = _material_text(word[4])
            if token and token not in tokens:
                tokens.append(token)
        if len(tokens) == 1:
            material = tokens[0]
    if not title and not part_no:
        return None
    return StructureRow(title, part_no, "", "", weight, material, parent, source, "")


def _fill_title(located: StructureRow | None, guessed: StructureRow | None) -> StructureRow | None:
    if located is None:
        return guessed
    if guessed is None:
        return located
    return StructureRow(
        located.name or guessed.name,
        located.part_no or guessed.part_no,
        located.quantity or guessed.quantity,
        located.thickness or guessed.thickness,
        located.weight or guessed.weight,
        located.material or guessed.material,
        located.parent or guessed.parent,
        located.source or guessed.source,
        located.note or guessed.note,
        located.size_x or guessed.size_x,
        located.size_y or guessed.size_y,
        located.size_z or guessed.size_z,
        located.picture or guessed.picture,
    )


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
            if any(word[4] == "图样名称" for word in words):
                title = _title_row(words, path.name)
            else:
                words = _ocr_title_words(page)
                located = _title_row(words, path.name) if words else None
                guessed = _title_from_ocr(words, path.name) if words else None
                title = _fill_title(located, guessed)
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
