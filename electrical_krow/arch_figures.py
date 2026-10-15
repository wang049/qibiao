"""PDF 里的图表（坐标图、曲线、框图、示意图）：找出来整块截图，嵌进 Excel 供人看。

文字层只能读出图里散落的标签，线条、坐标、走势都丢了，所以这类内容不拆条、不取数，截图最准。
矢量画的图按绘图指令聚块，有曲线或斜线、文字又不密的块才算图（纯横竖线加满格文字的是表格或文字框）；
位图类（没识读成表格的图片）直接按图片位置截。已按格线读成表格的区域和页眉页脚不算图。
依赖 pymupdf，缺失或出错都返回空，不影响文字层出表。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

Box = tuple[float, float, float, float]

_RENDER_DPI = 200
_MARGIN = 6.0  # 截图四周留的边（PDF 点）
_GAP = 14.0  # 绘图块之间相距不超过这个距离的并成一张图
_MIN_AREA_RATIO = 0.02  # 太小的（下划线、项目符号框）不算图
_MAX_SIDE_RATIO = 0.9  # 宽高都接近整页的是页面边框，不算图
_MIN_CURVED = 10  # 至少这么多笔曲线或斜线才像图；只有横竖线的是表格、文字框
_MAX_TEXT_RATIO = 0.3  # 文字占块面积超过这个比例的是文字框，不是图
_HEADER_BAND = 0.15  # 页顶这一段里的框是页眉表
_LABEL_REACH = 16.0  # 紧贴图边（坐标轴名、刻度）的字算图里的标签，离这么近以内
_FOOTER_BAND = 0.07  # 页底这一段里的线是页脚


@dataclass(frozen=True)
class Figure:
    page: int
    box: Box
    labels: str  # 图里的文字（原文，按阅读顺序），便于检索
    png: bytes
    kind: str  # 矢量图 / 位图


def _overlap(a: Box, b: Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, width) * max(0.0, height)


def _near(a: Box, b: Box, gap: float) -> bool:
    return a[0] <= b[2] + gap and b[0] <= a[2] + gap and a[1] <= b[3] + gap and b[1] <= a[3] + gap


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def cluster_boxes(boxes: list[Box], gap: float = _GAP) -> list[tuple[Box, list[int]]]:
    """相距不超过 gap 的框并成一块。返回 (块的外框, 块里各框的下标)。"""
    clusters: list[tuple[Box, list[int]]] = []
    for index, box in enumerate(boxes):
        merged: tuple[Box, list[int]] = (box, [index])
        rest: list[tuple[Box, list[int]]] = []
        for kept, members in clusters:
            if _near(merged[0], kept, gap):
                merged = (_union(merged[0], kept), merged[1] + members)
            else:
                rest.append((kept, members))
        rest.append(merged)
        clusters = rest
    return clusters


def curved_strokes(drawing: dict) -> int:
    """一笔绘图里曲线和斜线的段数。表格、文字框只有横竖线，这个数为 0。"""
    count = 0
    for item in drawing.get("items", []):
        if item[0] == "c":
            count += 1
        elif item[0] == "l":
            start, end = item[1], item[2]
            if abs(start.x - end.x) > 1 and abs(start.y - end.y) > 1:
                count += 1
    return count


def _is_frame(box: Box, page_w: float, page_h: float, excluded: list[Box]) -> bool:
    """聚块前先剔掉的笔画：整页边框、页眉页脚带里的线、已读成表格的格线。不然它们会把整页连成一块。"""
    width, height = box[2] - box[0], box[3] - box[1]
    if width >= 0.85 * page_w and height >= 0.85 * page_h:
        return True
    if box[3] <= _HEADER_BAND * page_h or box[1] >= (1 - _FOOTER_BAND) * page_h:
        return True
    area = max(width, 0.1) * max(height, 0.1)
    return any(_overlap(box, other) >= 0.8 * area for other in excluded)


def _big_enough(box: Box, page_w: float, page_h: float, excluded: list[Box]) -> bool:
    width, height = box[2] - box[0], box[3] - box[1]
    area = _area(box)
    if area < _MIN_AREA_RATIO * page_w * page_h:
        return False
    if width >= _MAX_SIDE_RATIO * page_w and height >= _MAX_SIDE_RATIO * page_h:
        return False
    if box[3] <= _HEADER_BAND * page_h:
        return False
    return not any(_overlap(box, other) >= 0.5 * area for other in excluded)


def _words_in(words, box: Box):
    return [w for w in words if _overlap((w[0], w[1], w[2], w[3]), box) > 0]


def _text_ratio(words, box: Box) -> float:
    return sum((w[2] - w[0]) * (w[3] - w[1]) for w in _words_in(words, box)) / max(_area(box), 1.0)


_LABEL_WORDS = 4  # 一行不超过这么多词才算标签；整句是正文，不往图里拉


def _label_words(words):
    """只在短行里的词：坐标轴名、刻度、图例。标题、段落不算。"""
    per_line: dict[tuple[int, int], int] = {}
    for w in words:
        key = (w[5], w[6])
        per_line[key] = per_line.get(key, 0) + 1
    return [w for w in words if per_line[(w[5], w[6])] <= _LABEL_WORDS and re.search(r"[0-9A-Za-z\u4e00-\u9fff]", w[4])]


def _with_labels(words, box: Box) -> tuple[Box, str]:
    """把压在块边上和紧贴块边的标签（坐标轴名「Po (kW)」、左侧的「Derating」）纳进来，并按阅读顺序拼出图里的文字。
    只拉短行，免得把图上方的标题、段落一并圈进来。"""
    labels = _label_words(words)
    for _ in range(3):  # 纳进一圈标签后边界外扩，可能再够到下一圈
        reach = (box[0] - _LABEL_REACH, box[1] - _LABEL_REACH, box[2] + _LABEL_REACH, box[3] + _LABEL_REACH)
        grown = box
        for w in _words_in(labels, reach):
            grown = _union(grown, (w[0], w[1], w[2], w[3]))
        if grown == box:
            break
        box = grown
    # 图里的文字只记短行（标签、刻度、图例）；框进图里的整句正文已在条目里，不重复，也不能被当成标签从正文里去掉
    inside = _words_in(labels, box)
    inside.sort(key=lambda w: (round(w[1] / 4), w[0]))
    return box, re.sub(r"\s+", " ", " ".join(w[4] for w in inside)).strip()


def _merge_candidates(candidates: list[tuple[Box, str]]) -> list[tuple[Box, str]]:
    merged: list[tuple[Box, str]] = []
    for box, kind in candidates:
        current = (box, kind)
        rest: list[tuple[Box, str]] = []
        for kept_box, kept_kind in merged:
            if _overlap(current[0], kept_box) > 0:
                current = (_union(current[0], kept_box), "矢量图" if "矢量图" in (current[1], kept_kind) else kept_kind)
            else:
                rest.append((kept_box, kept_kind))
        rest.append(current)
        merged = rest
    return merged


def _render(page, box: Box) -> bytes:
    import pymupdf

    clip = pymupdf.Rect(box[0] - _MARGIN, box[1] - _MARGIN, box[2] + _MARGIN, box[3] + _MARGIN) & page.rect
    return page.get_pixmap(clip=clip, dpi=_RENDER_DPI, alpha=False).tobytes("png")


def find_figures(path: Path, table_boxes: dict[int, list[Box]] | None = None, image_table_pages: set[int] | None = None) -> dict[int, list[Figure]]:
    """每页的图表截图。table_boxes 是已按格线读出的表格位置（不截）；image_table_pages 是图片已识读成表格的页（该页图片不再当图）。"""
    import pymupdf

    table_boxes = table_boxes or {}
    image_table_pages = image_table_pages or set()
    found: dict[int, list[Figure]] = {}
    with pymupdf.open(str(path)) as doc:
        for index, page in enumerate(doc, start=1):
            page_w, page_h = page.rect.width, page.rect.height
            excluded = list(table_boxes.get(index, []))
            words = page.get_text("words")
            candidates: list[tuple[Box, str]] = []
            # 位图：没识读成表格的大图直接截
            if index not in image_table_pages:
                for info in page.get_image_info():
                    box = tuple(float(v) for v in info["bbox"])
                    if _big_enough(box, page_w, page_h, excluded):
                        candidates.append((box, "位图"))
            # 矢量图：绘图指令聚块，有曲线或斜线、文字不密的块才是图
            try:
                drawings = [d for d in page.get_drawings() if d.get("rect") is not None]
            except Exception:  # noqa: BLE001
                drawings = []
            boxes = [tuple(float(v) for v in d["rect"]) for d in drawings]
            keep = [i for i, box in enumerate(boxes) if not _is_frame(box, page_w, page_h, excluded)]
            for box, members in cluster_boxes([boxes[i] for i in keep]):
                if not _big_enough(box, page_w, page_h, excluded):
                    continue
                curved = sum(curved_strokes(drawings[keep[m]]) for m in members)
                if curved < _MIN_CURVED or _text_ratio(words, box) > _MAX_TEXT_RATIO:
                    continue
                candidates.append((box, "矢量图"))
            # 位图和矢量线叠在一起的（坐标图里的阴影块）是同一张图
            figures: list[Figure] = []
            for box, kind in _merge_candidates(candidates):
                box, labels = _with_labels(words, box)
                figures.append(Figure(index, box, labels, _render(page, box), kind))
            if figures:
                figures.sort(key=lambda f: (f.box[1], f.box[0]))
                found[index] = figures
    return found
