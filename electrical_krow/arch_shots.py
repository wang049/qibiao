"""条款级截图：每条需求在 PDF 原文里那一小块（表格的一行、正文的一段）的位置和渲染。

甲方的偏差跟踪表每条附的是原文截图而不是文字，所以出表时按条截一张。
位置来自两处：表格行用 pdfplumber 给的行格坐标；正文条目用 pymupdf 的文字行坐标，
把条文里出现的行并起来。算不出位置的条目不截，不补。依赖缺失或出错都返回空，不影响文字出表。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

Box = tuple[float, float, float, float]

_RENDER_DPI = 216
_RENDER_DPI_TALL = 240  # 很长的段落进表格时要缩小，渲染得精细些，放大看仍清楚
_TALL_PT = 260.0
_MARGIN_X = 2.5
_MARGIN_Y = 1.0  # 纵向只留 1pt，紧贴本行上下格线，免得切进相邻行的字
_MIN_LINE_ALNUM = 3  # 太短的行（「-」「5」）不参与定位，免得误并到别处
_MAX_GAP = 28.0  # 正文条目里相邻两行相距超过这个距离就不是同一段，不并
_HEADER_RATIO = 0.105  # 多页文件的顶部页眉表区域，不参与正文定位
_FOOTER_RATIO = 0.94  # 多页文件的底部页脚页码区域，不参与正文定位


@dataclass(frozen=True)
class Shot:
    page: int
    box: Box | None  # None 时 png 已经渲染好（图表）
    png: bytes = b""


def _no_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u3130-\u318f\u4e00-\u9fff]", "", text or "")


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def read_lines(
    path: Path,
    table_boxes: dict[int, list[Box]] | None = None,
) -> dict[int, list[tuple[Box, str]]]:
    """每页文字行的位置和内容（按阅读顺序）。多页文件剔除页眉表和页脚；已认出格线的表格区域也不算进正文行。"""
    import pymupdf

    found: dict[int, list[tuple[Box, str]]] = {}
    with pymupdf.open(str(path)) as doc:
        multi = len(doc) > 1
        for index, page in enumerate(doc, start=1):
            height = float(page.rect.height)
            excluded = (table_boxes or {}).get(index, [])
            lines: list[tuple[Box, str]] = []
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", []))
                    if not text.strip():
                        continue
                    box = tuple(float(v) for v in line["bbox"])
                    if multi and (box[3] <= height * _HEADER_RATIO or box[1] >= height * _FOOTER_RATIO):
                        continue
                    xmid, ymid = 0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3])
                    if any(tb[0] - 2 <= xmid <= tb[2] + 2 and tb[1] - 2 <= ymid <= tb[3] + 2 for tb in excluded):
                        continue
                    lines.append((box, text))
            lines.sort(key=lambda item: (round(item[0][1] / 3), item[0][0]))
            found[index] = lines
    return found


def clause_box(lines: list[tuple[Box, str]], text: str) -> Box | None:
    """条文在页面上的范围：把内容出现在条文里的行并起来。行与行离得太远的取命中字数最多的那一簇。"""
    # 两个库对标点、全角符号的读法不一样，只比字母数字汉字
    key = _alnum(text).lower()
    if not key:
        return None
    hits: list[tuple[Box, int]] = []
    for box, line in lines:
        line_key = _alnum(line).lower()
        body_key = re.sub(r"^\d{1,2}", "", line_key)  # pypdf 有时把标题尾词插在「1)」和句首之间
        if len(line_key) >= _MIN_LINE_ALNUM and (
            line_key in key
            or (len(body_key) >= 8 and body_key in key)
            or (len(key) >= 12 and key in line_key)
        ):
            hits.append((box, min(len(line_key), len(key))))
    if not hits:
        return None
    hits.sort(key=lambda item: (item[0][1], item[0][0]))
    clusters: list[list[tuple[Box, int]]] = [[hits[0]]]
    for item in hits[1:]:
        if item[0][1] - clusters[-1][-1][0][3] > _MAX_GAP:
            clusters.append([item])
        else:
            clusters[-1].append(item)
    best = max(clusters, key=lambda c: (sum(w for _, w in c), len(c)))
    out = best[0][0]
    for box, _ in best[1:]:
        out = _union(out, box)
    return out


def row_box(cells: list[Box | None], table_box: Box) -> Box | None:
    """表格一行的范围：纵向取本行自己的格（纵向合并、跨好几行的大格不算），横向取整张表。"""
    own = [c for c in cells if c is not None]
    if not own:
        return None
    min_h = min(c[3] - c[1] for c in own)
    normal = [c for c in own if c[3] - c[1] <= 1.25 * min_h] or own
    top = min(c[1] for c in normal)
    bottom = max(c[3] for c in normal)
    return (table_box[0], top, table_box[2], bottom)


def render_shots(path: Path, shots: list[Shot]) -> list[bytes]:
    """按页批量渲染。已经带 png 的（图表）原样返回。"""
    import pymupdf

    out: list[bytes] = [shot.png for shot in shots]
    pending = [(i, shot) for i, shot in enumerate(shots) if shot.box is not None and not shot.png]
    if not pending:
        return out
    with pymupdf.open(str(path)) as doc:
        for i, shot in pending:
            page = doc[shot.page - 1]
            box = shot.box
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                continue  # 定位到的范围小得不像一条内容
            clip = pymupdf.Rect(box[0] - _MARGIN_X, box[1] - _MARGIN_Y, box[2] + _MARGIN_X, box[3] + _MARGIN_Y) & page.rect
            if clip.is_empty:
                continue
            try:
                dpi = _RENDER_DPI_TALL if clip.height > _TALL_PT else _RENDER_DPI
                out[i] = page.get_pixmap(clip=clip, dpi=dpi, alpha=False).tobytes("png")
            except Exception:  # noqa: BLE001
                continue
    return out
