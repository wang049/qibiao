"""PDF 里以图片形式贴进去的表格：找出图片、按格线切格、OCR 识读每格文字，还原成行×列的表。

只处理有格线的表格图片；流程图、示意图、照片识不出格线就跳过。识读结果是 OCR 字符，
出表时单独标注「图片表格·OCR」，由确认人对照原图核对，不当原文字层用。
依赖 pymupdf（渲染）、opencv（找格线）、rapidocr（识字），任一缺失或出错都返回空，不影响文字层出表。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

Grid = list[list[str]]

_MIN_AREA_RATIO = 0.03  # 图片占页面面积不到 3% 的（logo、小图标）不看
_RENDER_DPI = 200
_LINE_RATIO = 0.3  # 一条格线至少横贯图片宽（高）的 30%，不然是文字笔画或框图的边
_MERGE_PX = 8  # 相距 8 像素以内的格线算同一条
_OCR: Any = None


def _ocr_engine():
    global _OCR
    if _OCR is None:
        from rapidocr import RapidOCR

        _OCR = RapidOCR(params={"Global.log_level": "warning"})
    return _OCR


def _union(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def merge_boxes(boxes: list[tuple[float, float, float, float]], gap: float = 6.0) -> list[tuple[float, float, float, float]]:
    """上下紧挨、左右基本对齐的几张图合成一张：一张长表常被切成几张图贴进 PDF。"""
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    merged: list[tuple[float, float, float, float]] = []
    for box in boxes:
        for index, kept in enumerate(merged):
            x_overlap = min(box[2], kept[2]) - max(box[0], kept[0])
            width = max(box[2] - box[0], kept[2] - kept[0])
            touching = box[1] <= kept[3] + gap and box[3] >= kept[1] - gap
            if width > 0 and x_overlap >= 0.8 * width and touching:
                merged[index] = _union(kept, box)
                break
        else:
            merged.append(box)
    return merged


def image_regions(path: Path) -> dict[int, list[tuple[float, float, float, float]]]:
    """每页上足够大的图片的位置（PDF 坐标，已合并上下相接的）。"""
    import pymupdf

    found: dict[int, list[tuple[float, float, float, float]]] = {}
    with pymupdf.open(str(path)) as doc:
        for index, page in enumerate(doc, start=1):
            area = page.rect.width * page.rect.height
            boxes = []
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                if (x1 - x0) * (y1 - y0) >= _MIN_AREA_RATIO * area:
                    boxes.append((x0, y0, x1, y1))
            if boxes:
                found[index] = merge_boxes(boxes)
    return found


def render_region(path: Path, page_no: int, box: tuple[float, float, float, float]):
    import numpy as np
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        page = doc[page_no - 1]
        pix = page.get_pixmap(clip=pymupdf.Rect(*box), dpi=_RENDER_DPI, colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _cluster(positions: list[int], tolerance: int) -> list[int]:
    out: list[int] = []
    for pos in sorted(positions):
        if out and pos - out[-1] <= tolerance:
            continue
        out.append(pos)
    return out


def grid_lines(gray) -> tuple[list[int], list[int]]:
    """找横竖格线的位置。返回 (横线 y 列表, 竖线 x 列表)，都带上图片边缘，格线不足以成表时返回空。"""
    ys, xs, _, _ = _lines(gray)
    return ys, xs


def _lines(gray):
    import cv2
    import numpy as np

    height, width = gray.shape
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, width // 15), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, height // 15))))
    rows = [y for y in range(height) if np.count_nonzero(horizontal[y]) >= _LINE_RATIO * width]
    cols = [x for x in range(width) if np.count_nonzero(vertical[:, x]) >= _LINE_RATIO * height]
    ys = _cluster([0, *rows, height - 1], _MERGE_PX)
    xs = _cluster([0, *cols, width - 1], _MERGE_PX)
    if len(ys) < 3 or len(xs) < 3:
        return [], [], None, None
    return ys, xs, horizontal, vertical


def _has_segment(mask, fixed: int, span: tuple[int, int], *, vertical_line: bool) -> bool:
    """格线在 fixed 处、span 范围内是否真的画了（合并格之间没有线）。"""
    import numpy as np

    lo, hi = span
    if hi - lo <= 0:
        return True
    half = _MERGE_PX
    if vertical_line:
        band = mask[lo:hi, max(0, fixed - half) : fixed + half + 1]
        drawn = np.count_nonzero(band.any(axis=1))
    else:
        band = mask[max(0, fixed - half) : fixed + half + 1, lo:hi]
        drawn = np.count_nonzero(band.any(axis=0))
    return drawn >= 0.5 * (hi - lo)


def grid_from_image(gray) -> Grid | None:
    """有格线的表格图片 → 行×列的文字。认不出格线、或格里几乎没字的返回 None。"""
    ys, xs, horizontal, vertical = _lines(gray)
    if not ys:
        return None
    import cv2

    result = _ocr_engine()(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    if not result or result.boxes is None or len(result.boxes) == 0:
        return None
    cells: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
    for box, text in zip(result.boxes, result.txts):
        text = _clean(text)
        if not text:
            continue
        cx = sum(p[0] for p in box) / 4
        cy = sum(p[1] for p in box) / 4
        row = max(0, sum(1 for y in ys[1:-1] if cy > y))
        col = max(0, sum(1 for x in xs[1:-1] if cx > x))
        # 合并格：左边、上边没有画线的，归到合并区域左上那一格（和文字层表格的读法一致）
        while col > 0 and not _has_segment(vertical, xs[col], (ys[row], ys[row + 1]), vertical_line=True):
            col -= 1
        while row > 0 and not _has_segment(horizontal, ys[row], (xs[col], xs[col + 1]), vertical_line=False):
            row -= 1
        cells.setdefault((row, col), []).append((cy, cx, text))
    n_rows, n_cols = len(ys) - 1, len(xs) - 1
    grid: Grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for (row, col), pieces in cells.items():
        pieces.sort()
        grid[row][col] = " ".join(piece[2] for piece in pieces)
    # 没有任何字的整行、整列是边框和格线之间的空隙，去掉
    grid = [row for row in grid if any(row)]
    if not grid:
        return None
    keep = [c for c in range(len(grid[0])) if any(row[c] for row in grid)]
    grid = [[row[c] for c in keep] for row in grid]
    filled = sum(1 for row in grid for cell in row if cell)
    if len(grid) < 2 or len(grid[0]) < 2 or filled < 4:
        return None
    return grid


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def read_image_tables(path: Path, progress=None) -> dict[int, list[Grid]]:
    """每页图片里识读出的表格。依赖缺失或任何一步出错都按没有图片表处理。"""
    try:
        regions = image_regions(path)
    except Exception as exc:  # noqa: BLE001
        log.info("找不到图片区域，跳过图片表格：%s", exc)
        return {}
    found: dict[int, list[Grid]] = {}
    ordered = list(regions.items())
    total_pages = len(ordered) or 1
    for at, (page_no, boxes) in enumerate(ordered, start=1):
        if progress:
            progress(at, total_pages)
        grids: list[Grid] = []
        for box in boxes:
            try:
                grid = grid_from_image(render_region(path, page_no, box))
            except Exception as exc:  # noqa: BLE001
                log.info("第 %s 页图片识读失败，跳过：%s", page_no, exc)
                continue
            if grid:
                grids.append(grid)
        if grids:
            found[page_no] = grids
    return found
