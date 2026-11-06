"""PDF 里的图表（坐标图、曲线、框图、示意图）：找出来整块截图，嵌进 Excel 供人看。

文字层只能读出图里散落的标签，线条、坐标、走势都丢了，所以这类内容不拆条、不取数，截图最准。
矢量画的图按绘图指令聚块，有曲线或斜线、文字又不密的块才算图（纯横竖线加满格文字的是表格或文字框）；
位图类（没识读成表格的图片）直接按图片位置截。页眉页脚不算图。
曲线图和同一高度旁边的数据表合成一张截图：表已经按格线读出时，截图仍要盖住整张表，不从半格切开。
纯数字数据表只留在截图里，不写成摘录、也不翻译。图框上方的页眉标题、编号条款、曲线标题和说明按行摘录并翻译。带 Table、Load、Speed rate 的规格表仍按表格摘录。
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
_CHART_TABLE_REACH = 40.0  # 曲线图旁边的数据表并进截图，避免表被裁掉
_TABLE_BESIDE = 72.0  # 笔画没连上、但和曲线同一高度的数据表，仍整张收进截图
_FOOTER_BAND = 0.07  # 页底这一段里的线是页脚


@dataclass(frozen=True)
class Figure:
    page: int
    box: Box
    labels: str  # 图里的短标签（坐标名、刻度），便于检索
    png: bytes
    kind: str  # 矢量图 / 位图
    transcript: str = ""  # 图框里全部文字，按行、按列摘出；只有刻度时为空串以外的短标签也可放这里
    grid: tuple[tuple[str, ...], ...] = ()  # 截图里按格线认出的表；文字层没有字时用它来画表


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
            dx = abs(start.x - end.x)
            dy = abs(start.y - end.y)
            # 略斜的表格边不当成曲线。明显的斜线才算坐标图。
            if dx > 3 and dy > 3 and min(dx, dy) / max(dx, dy) > 0.3:
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


def _prose_from_png(png: bytes) -> str:
    """整图再识一遍正文，用来补上分块时漏掉的编号。"""
    import io

    import numpy as np
    from PIL import Image

    from electrical_krow.arch_ocr import figure_ocr

    gray = np.asarray(Image.open(io.BytesIO(png)).convert("L"))
    _grid, extra = figure_ocr(gray)
    return extra or ""


def _collapse_overlapping(page, figures: list[Figure], tables: list[Box] | None = None) -> list[Figure]:
    """同一块内容被收成几张重叠的图时，合成一张。正文和表取更全的那份，截图用合成后的范围。"""
    groups: list[list[Figure]] = []
    for fig in figures:
        hit = [group for group in groups if any(_overlap(fig.box, other.box) > 0 for other in group)]
        if not hit:
            groups.append([fig])
            continue
        merged = [fig]
        for group in hit:
            groups.remove(group)
            merged.extend(group)
        groups.append(merged)
    out: list[Figure] = []
    page_w, page_h = page.rect.width, page.rect.height
    for group in groups:
        if len(group) == 1:
            fig = group[0]
            box = _cover_tables(fig.box, tables or [], page_w, page_h)
            text = "" if _chart_label_noise(fig.transcript) else fig.transcript
            if box != fig.box or text != fig.transcript:
                png = _render(page, box) if box != fig.box else fig.png
                fig = Figure(fig.page, box, fig.labels, png, fig.kind, text, fig.grid)
            out.append(fig)
            continue
        box = group[0].box
        for fig in group[1:]:
            box = _union(box, fig.box)
        box = _cover_tables(box, tables or [], page_w, page_h)
        from electrical_krow.arch_ocr import insert_missing_lines

        grid = max(group, key=lambda fig: _filled(fig.grid))
        ordered = sorted(group, key=lambda item: (len(re.findall(r"[①②③④⑤⑥⑦⑧⑨⑩]", item.transcript)), _letters(item.transcript)))
        text = ordered[-1].transcript
        for fig in ordered[:-1]:
            text = insert_missing_lines(text, fig.transcript)
        png = _render(page, box)
        # 合成后的图比单块更全，再识一次，把某一块里漏掉的编号插回去。
        # 拼起来仍只是转速–分贝曲线时，坐标上的字不写成原文摘录。
        text = prose_beside(insert_missing_lines(text, _prose_from_png(png)), grid.grid)
        if _chart_label_noise(text):
            text, kept_grid = "", ()
        else:
            text = order_clauses(text)
            kept_grid = grid.grid
        out.append(Figure(group[0].page, box, group[0].labels, png, group[0].kind, text, kept_grid))
    return out


def _merge_candidates(candidates: list[tuple[Box, str, int]]) -> list[tuple[Box, str, int]]:
    merged: list[tuple[Box, str, int]] = []
    for box, kind, curved in candidates:
        current = (box, kind, curved)
        rest: list[tuple[Box, str, int]] = []
        for kept_box, kept_kind, kept_curved in merged:
            if _overlap(current[0], kept_box) > 0:
                current = (
                    _union(current[0], kept_box),
                    "矢量图" if "矢量图" in (current[1], kept_kind) else kept_kind,
                    current[2] + kept_curved,
                )
            else:
                rest.append((kept_box, kept_kind, kept_curved))
        rest.append(current)
        merged = rest
    return merged


_SPEC_TABLE = re.compile(
    r"\bTable\s*\d|\bLoad\s*\(|\bSpeed rate\b|\bInput-Dyno\b|\bMotor Tq\b|\bParallel Mode\b",
    re.I,
)


def _spec_table_text(text: str) -> bool:
    """规格表要按表格摘录。曲线图坐标旁的 rpm、dBA 数据表不是这种表。"""
    return _SPEC_TABLE.search(text or "") is not None


def _axis_scale_grid(grid: tuple[tuple[str, ...], ...] | tuple) -> bool:
    """曲线图横轴刻度被识成表：一行是 0、5000、10000、15000 这种整数，格子里没有表头。"""
    if not grid:
        return False
    if any(re.search(r"[A-Za-z]{3,}", str(cell)) for row in grid for cell in row):
        return False
    for row in grid:
        nums = []
        for cell in row:
            token = str(cell).strip().replace(",", "")
            if re.fullmatch(r"\d+", token):
                nums.append(int(token))
        if len(nums) >= 3 and nums == sorted(nums) and nums[-1] - nums[0] >= 1000 and all(num % 500 == 0 for num in nums):
            return True
    return False


def _axis_chart(text: str) -> bool:
    """转速–分贝这张曲线和它旁边的数据表，只留截图。"""
    low = text or ""
    return bool(re.search(r"\brpm\b", low, re.I) and re.search(r"\b(?:dBA|dB|noise)\b", low, re.I)) and not _spec_table_text(low)


def _chart_label_noise(text: str) -> bool:
    """坐标、图名、分贝刻度，不是编号条款，也不另写原文摘录。"""
    if not (text or "").strip():
        return False
    if re.search(r"(?:^|\s)\d{1,2}[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩]", text or ""):
        return False
    if _spec_table_text(text):
        return False
    return _axis_chart(text) or transcript_kind(text) == "chart"


def _curve_chart_only(text: str, curved: int) -> bool:
    """只有坐标曲线图不摘录。句子、规格表、普通表格都要摘录。"""
    if curved < _MIN_CURVED:
        return False
    if _spec_table_text(text):
        return False
    if _axis_chart(text):
        return True
    if transcript_kind(text) in {"prose", "table"}:
        return False
    return True


def _contains(outer: Box, inner: Box, slop: float = 1.0) -> bool:
    return (
        outer[0] <= inner[0] + slop
        and outer[1] <= inner[1] + slop
        and outer[2] >= inner[2] - slop
        and outer[3] >= inner[3] - slop
    )


def _detected_tables(page) -> list[Box]:
    """页面上按格线认出的表。截图切到表中间时，用这些外框把整张表补上。"""
    try:
        found = page.find_tables()
    except Exception:  # noqa: BLE001
        return []
    page_w, page_h = page.rect.width, page.rect.height
    boxes: list[Box] = []
    for table in getattr(found, "tables", None) or []:
        raw = getattr(table, "bbox", None)
        if not raw:
            continue
        box = tuple(float(v) for v in raw)
        width, height = box[2] - box[0], box[3] - box[1]
        if _area(box) < 200 or (width >= 0.92 * page_w and height >= 0.92 * page_h):
            continue
        boxes.append(box)
    return boxes


def _cover_tables(box: Box, tables: list[Box], page_w: float, page_h: float) -> Box:
    """截图已经压进表格，或曲线同一高度旁边还有数据表时，收进整张表，不从半格切开。"""
    grown = box
    limit = 0.85 * page_w * page_h
    for _ in range(5):
        nxt = grown
        for table in tables:
            if _area(table) < 200 or _contains(nxt, table):
                continue
            overlap = _overlap(nxt, table)
            vertical = min(nxt[3], table[3]) - max(nxt[1], table[1])
            alongside = overlap <= 0 and vertical > 12 and _near(nxt, table, _TABLE_BESIDE)
            if overlap <= 0 and not alongside:
                continue
            wider = _union(nxt, table)
            if _area(wider) <= limit:
                nxt = wider
        if nxt == grown:
            break
        grown = nxt
    return grown


def _grow_chart_box(box: Box, straight: list[Box], page_w: float, page_h: float) -> Box:
    """曲线图旁边紧挨着的横竖线（数据表）并进截图范围。不再把这张表写成原文摘录。"""
    grown = box
    limit = 0.45 * page_w * page_h
    for _ in range(4):
        nxt = grown
        for other in straight:
            if not _near(nxt, other, _CHART_TABLE_REACH):
                continue
            wider = _union(nxt, other)
            if _area(wider) <= limit:
                nxt = wider
        if nxt == grown:
            break
        grown = nxt
    return grown


def transcript_of(words, box: Box) -> str:
    """图框里的文字按阅读顺序摘出。同一行里隔得开的字分成不同的格。"""
    inside = [w for w in _words_in(words, box) if re.search(r"[0-9A-Za-z\u4e00-\u9fff]", w[4])]
    if not inside:
        return ""
    inside.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[tuple[float, list]] = []
    for word in inside:
        cy = (word[1] + word[3]) / 2
        if rows and abs(cy - rows[-1][0]) <= 3.5:
            rows[-1][1].append(word)
        else:
            rows.append((cy, [word]))
    lines: list[str] = []
    for _, group in rows:
        group.sort(key=lambda w: w[0])
        parts = [group[0][4]]
        for prev, word in zip(group, group[1:]):
            parts.append(" | " if word[0] - prev[2] > 14 else " ")
            parts.append(word[4])
        lines.append("".join(parts))
    return "\n".join(lines)


def text_layer_broken(text: str) -> bool:
    """文字层缺字时会剩下一串一两个字母的碎片，例如「u nd n rm」。这种不能当正文。"""
    words = re.findall(r"[A-Za-z]+", text or "")
    if len(words) < 6:
        return False
    short = sum(1 for word in words if len(word) <= 2)
    return short * 5 >= len(words) * 2


def _letters(text: str) -> int:
    return len(re.findall(r"[A-Za-z\u4e00-\u9fff]", text or ""))


def _filled(grid: tuple[tuple[str, ...], ...] | tuple) -> int:
    return sum(1 for row in grid for cell in row if str(cell).strip())


def _pipe_table(text: str) -> tuple[tuple[str, ...], ...]:
    """文字层里用「 | 」分开的行，还原成表。不成表就返回空。"""
    parsed: list[tuple[str, ...]] = []
    for line in (text or "").splitlines():
        if " | " not in line:
            continue
        cells = tuple(cell.strip() for cell in line.split("|"))
        if sum(bool(cell) for cell in cells) >= 2:
            parsed.append(cells)
    if len(parsed) < 2:
        return ()
    width = max(len(row) for row in parsed)
    return tuple(row + ("",) * (width - len(row)) for row in parsed)


def pull_orphan_column(grid: tuple[tuple[str, ...], ...] | tuple) -> tuple[tuple[str, ...], ...]:
    """最右一列没有表头，数值却落在这里，左边有表头的格子是空的。把数值挪回去，再删掉空列。"""
    rows = [list(row) for row in grid]
    if not rows or len(rows[0]) < 3:
        return tuple(tuple(row) for row in rows)
    changed = True
    while changed and rows and len(rows[0]) >= 3:
        changed = False
        col = len(rows[0]) - 1
        band = rows[:2]
        if any(str(row[col]).strip() for row in band):
            break
        if not any(str(row[col - 1]).strip() for row in band):
            break
        values = [index for index, row in enumerate(rows) if str(row[col]).strip()]
        if not values or any(str(rows[index][col - 1]).strip() for index in values):
            break
        for index in values:
            rows[index][col - 1] = rows[index][col]
            rows[index][col] = ""
        for row in rows:
            row.pop()
        changed = True
    return _close_empty_columns(rows)


def _close_empty_columns(rows: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    """同一张表里夹着的空列删掉，转速回到表头下面。下一张表的空格（100Nm 往下）不动。"""
    if not rows:
        return ()
    width = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (width - len(row)))
    starts = [0]
    for index, row in enumerate(rows):
        if index == 0:
            continue
        filled = [col for col, cell in enumerate(row) if str(cell).strip()]
        if len(filled) == 1 and filled[0] == 0:
            starts.append(index)
    bounds = list(zip(starts, starts[1:] + [len(rows)]))
    for start, end in bounds:
        changed = True
        while changed:
            changed = False
            for col in range(1, width):
                if not any(str(rows[row][col]).strip() for row in range(start, end)):
                    continue
                if any(str(rows[row][col - 1]).strip() for row in range(start, end)):
                    continue
                for row in range(start, end):
                    if str(rows[row][col]).strip():
                        rows[row][col - 1] = rows[row][col]
                        rows[row][col] = ""
                changed = True
    keep = [col for col in range(width) if any(str(row[col]).strip() for row in rows)]
    if not keep:
        return ()
    return tuple(tuple(_ocr_over(str(row[col])) for col in keep) for row in rows)


def _ocr_over(cell: str) -> str:
    return re.sub(r"^0ver\b", "Over", cell)


def _norm_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("|", " ")).strip()


def prose_beside(text: str, grid: tuple[tuple[str, ...], ...] | tuple) -> str:
    """表已经按格摘出时，正文只留下不在表里的那些行。缺字碎片行也不留。"""
    covered = set()
    for row in grid:
        bits = [str(cell).strip() for cell in row if str(cell).strip()]
        if bits:
            covered.add(_norm_line(" ".join(bits)))
    kept: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or _norm_line(stripped) in covered:
            continue
        words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", stripped)
        short = sum(1 for word in words if len(word) <= 2)
        if words and len(words) >= 4 and short * 2 >= len(words):
            continue
        bare = _norm_line(stripped)
        if not re.search(r"\d[.)]|[①②③④⑤⑥⑦⑧⑨⑩]", bare):
            cells = [_norm_line(str(cell)) for row in grid for cell in row if str(cell).strip()]
            if any(
                bare == cell
                or (len(cell) > 12 and (cell in bare or (len(bare) > 12 and bare in cell)))
                for cell in cells
            ):
                continue
        for row_text in sorted(covered, key=len, reverse=True):
            if len(row_text) < 6:
                continue
            if _norm_line(stripped).endswith(row_text) and len(_norm_line(stripped)) > len(row_text) + 3:
                stripped = _norm_line(stripped)[: -len(row_text)].strip(" .:")
                break
        if stripped:
            kept.append(stripped)
    if _filled(grid) >= 4:
        kept = _bullet_blocks(kept)
    return "\n".join(_drop_longer_copies(kept))


def _bullet_blocks(lines: list[str]) -> list[str]:
    """表旁边的正文只留编号、项目符号和紧跟着的句子。表里漏出来的半句去掉。"""
    kept: list[str] = []
    taking = False
    seen_clause = False
    for line in lines:
        if re.match(r"(?i)^attachment\b", line) or (
            not seen_clause
            and not _TABLE_FRAGMENT.match(line)
            and len(re.findall(r"[A-Za-z]{4,}", line)) >= 3
        ):
            kept.append(line)
            continue
        if re.match(r"^(?:[•·▪■◦●○✓✔√☑※*]|\d{1,2}[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩])", line):
            seen_clause = True
            taking = len(line) >= 18
            if taking:
                kept.append(line)
            continue
        words = re.findall(r"[A-Za-z\u4e00-\u9fff]+", line)
        if taking and len(words) >= 3:
            kept.append(line)
        elif taking and len(words) == 1 and len(line) <= 16 and kept and not re.match(r"[A-Z√✓•]", line):
            kept.append(line)
        else:
            taking = False
    return kept


_PARENT_LINE = re.compile(r"^\d{1,2}[.)]\s+\S")
_CIRCLED_LINE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩])")
_CLAUSE_TAIL = re.compile(
    r"\s+(?:Input-Dyno\b|\(\s*±|P3 Motor Tq\b|\(\s*Engine\s*\)\s*Tq\b|Table\s*\d\b\S*(?:\s+\S+)*\s(?:Load|Speed)\b).*$",
    re.I,
)
_JUNK_TAIL = re.compile(r"(?:Input-Dyno\b|\(\s*±|P3 Motor Tq\b|Table\s*\d\b)", re.I)
_MEASURE_ONLY = re.compile(r"^[\s()±\d.%/~Nm\-–—,]+$")
_TABLE_FRAGMENT = re.compile(
    r"^(?:Table\s*\d\b|Load\s*\(|Speed rate\b|Step\s*:|\(?\s*±)",
    re.I,
)


def axis_tick_dump(text: str) -> bool:
    """一串坐标刻度。这种不写进「本页图表」后面的原文摘录。"""
    return len(re.findall(r"-?\d{2,}", text or "")) >= 4


def chart_hint(labels: str) -> str:
    """刻度很多时只留刻度前面的短名称。名称本身就是刻度或图名时不写。"""
    text = (labels or "").strip()
    if not text:
        return ""
    if axis_tick_dump(text):
        kept = []
        for word in text.split():
            if re.search(r"\d", word):
                break
            kept.append(word)
        text = " ".join(kept).strip(" :")
        if len(text.split()) <= 1:
            return ""
    return f"：{text}"


def _truncated_same(a: str, b: str) -> bool:
    """两句是同一条的截断和全文。短句已经写完、长句又多了一段条件时，不是同一条。"""
    na, nb = _norm_line(a), _norm_line(b)
    if na == nb:
        return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) <= 24 or not long.startswith(short):
        return False
    rest = long[len(short) :]
    if rest[:1].isalpha() and short[-1:].isalpha():
        return True
    if rest[:1].isdigit() and short[-1:].isdigit():
        return True
    return rest.startswith(" ") and len(rest.strip()) <= 24


def _strip_repeated_title(line: str, previous: str) -> str:
    """标题末尾重复了上一条标题的后半句时去掉。"""
    title = re.sub(r"^\d{1,2}[.)]\s*", "", previous).strip()
    words = title.split()
    norm = _norm_line(line)
    for count in range(len(words), 2, -1):
        suffix = _norm_line(" ".join(words[-count:]))
        if len(suffix) >= 12 and norm.endswith(suffix) and len(norm) > len(suffix) + 8:
            return re.sub(re.escape(suffix) + r"$", "", norm, flags=re.I).strip()
    return line


def _richer_line(a: str, b: str) -> str:
    """同一句有截断和完整两种识读时留完整的。多出来的是表里的格子时留短的。"""
    na, nb = _norm_line(a), _norm_line(b)
    short, long = (a, b) if len(na) <= len(nb) else (b, a)
    extra = _norm_line(long)[len(_norm_line(short)) :].strip()
    if extra and _JUNK_TAIL.match(extra):
        return short
    return long


def order_clauses(text: str) -> str:
    """同一条标题下面的 ①②③④ 按编号排，重复的只留较短的一句，表里粘上来的格子去掉。"""
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = _CLAUSE_TAIL.sub("", raw).strip()
        line = re.sub(r"\s+0ver\b", "", line).strip()
        line = re.sub(r"^([①②③④⑤⑥⑦⑧⑨⑩])(?!\s)", r"\1 ", line)
        if not line or _MEASURE_ONLY.match(line) or _TABLE_FRAGMENT.match(line):
            continue
        if re.fullmatch(r"[A-Za-z]{1,3}", line):
            continue
        words = re.findall(r"[A-Za-z]+", line)
        short = sum(1 for word in words if len(word) <= 2)
        if (
            len(words) >= 3
            and short * 2 >= len(words)
            and not any(len(word) > 4 for word in words)
            and not _PARENT_LINE.match(line)
            and not _CIRCLED_LINE.match(line)
        ):
            continue
        lines.append(line)
    prepared: list[str] = []
    seen_circled: list[str] = []
    previous_parent = ""
    for at, line in enumerate(lines):
        if _PARENT_LINE.match(line):
            nxt = next((lines[j] for j in range(at + 1, len(lines)) if _CIRCLED_LINE.match(lines[j]) or _PARENT_LINE.match(lines[j])), "")
            nxt_core = _norm_line(re.split(r"\s+Table\s*\d", nxt, maxsplit=1, flags=re.I)[0])
            if _CIRCLED_LINE.match(nxt) and any(
                _norm_line(re.split(r"\s+Table\s*\d", old, maxsplit=1, flags=re.I)[0]) == nxt_core for old in seen_circled
            ):
                continue
            if previous_parent:
                line = _strip_repeated_title(line, previous_parent)
            line = re.sub(r"\s+\d+\s*Nm$", "", line).strip()
            previous_parent = line
        if _CIRCLED_LINE.match(line):
            seen_circled.append(line)
        if line:
            prepared.append(line)
    lines = prepared
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _PARENT_LINE.match(line):
            out.append(line)
            index += 1
            continue
        out.append(line)
        index += 1
        subs: list[str] = []
        notes: list[str] = []
        while index < len(lines) and not _PARENT_LINE.match(lines[index]):
            if _CIRCLED_LINE.match(lines[index]):
                subs.append(lines[index])
            else:
                notes.append(lines[index])
            index += 1
        kept: list[str] = []
        for sub in subs:
            mark = sub[0]
            norm = _norm_line(sub)
            replaced = False
            nxt: list[str] = []
            for old in kept:
                if old[0] != mark:
                    nxt.append(old)
                    continue
                if not _truncated_same(sub, old):
                    nxt.append(old)
                    continue
                if not replaced:
                    nxt.append(_richer_line(sub, old))
                    replaced = True
            if not replaced:
                nxt.append(sub)
            kept = nxt
        kept.sort(key=lambda item: _CIRCLED_LINE.match(item).group(1))
        out.extend(kept)
        out.extend(notes)
    return "\n".join(_drop_longer_copies(out))


def _drop_longer_copies(lines: list[str]) -> list[str]:
    """同一条 ② 被识读了两遍时，只留较短的那句，并留在先出现的位置。"""
    kept: list[str] = []
    for line in lines:
        norm = _norm_line(line)
        placed = False
        nxt: list[str] = []
        for old in kept:
            if _truncated_same(line, old):
                if not placed:
                    nxt.append(_richer_line(line, old))
                    placed = True
                continue
            nxt.append(old)
        if not placed:
            nxt.append(line)
        kept = nxt
    return kept


def _data_table(grid: tuple[tuple[str, ...], ...]) -> bool:
    """短格为主的才是数据表。整段要求被识进格子里的，不拿来画表。"""
    cells = [cell.strip() for row in grid for cell in row if cell.strip()]
    if len(cells) < 4 or len(grid) < 2:
        return False
    long = sum(1 for cell in cells if len(cell) > 40 or re.search(r"(?:^|\s)(?:\d{1,2}[.)]\s|[①②③④⑤])", cell))
    return long * 2 < len(cells)


def transcript_kind(text: str) -> str:
    """成列表格、成句正文，或只有刻度标签。刻度不当成表格，避免把坐标图读成数。"""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    columnar = 0
    for line in lines:
        if " | " not in line:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        words = sum(1 for cell in cells if re.search(r"[A-Za-z\u4e00-\u9fff]{2,}", cell))
        if words >= 2 and len(line) >= 8:
            columnar += 1
    if columnar >= 2:
        return "table"
    if any(len(line.split()) >= 6 or len(re.findall(r"[A-Za-z\u4e00-\u9fff]", line)) >= 40 for line in lines):
        return "prose"
    return "chart"


def _ocr_figure(png: bytes) -> tuple[tuple[tuple[str, ...], ...], str]:
    """文字层没有表时，按截图里的格线认表。失败就当没有。"""
    try:
        import io

        import numpy as np
        from PIL import Image

        from electrical_krow.arch_ocr import figure_ocr

        gray = np.asarray(Image.open(io.BytesIO(png)).convert("L"))
        grid, prose = figure_ocr(gray)
    except Exception:  # noqa: BLE001
        return (), ""
    if not grid:
        return (), prose or ""
    return tuple(tuple(cell for cell in row) for row in grid), prose or ""


def _chart_data_table(grid: list[list[str]]) -> bool:
    """曲线旁边的小数据表。不看文件名，也不限转速、噪声这两个词。规格表不是。"""
    if len(grid) < 2 or not grid[0] or len(grid[0]) < 2:
        return False
    cells = [cell for row in grid for cell in row if cell]
    if len(cells) < 4:
        return False
    blob = " ".join(cells)
    if _spec_table_text(blob):
        return False
    if re.search(r"(?:^|\s)(?:\d{1,2}[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩])", blob):
        return False
    if any(len(cell) > 40 for cell in cells):
        return False
    if len(blob.split()) > 24:
        return False
    body = [cell for row in grid[1:] for cell in row if cell]
    numbered = sum(1 for cell in body if re.search(r"\d", cell))
    return numbered >= 2 and numbered * 2 >= len(body)


def _drop_axis_rows(grid: list[tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    kept: list[tuple[str, ...]] = []
    for row in grid:
        nums = []
        for cell in row:
            token = cell.replace(",", "").strip()
            if re.fullmatch(r"\d+", token):
                nums.append(int(token))
        if len(nums) >= 3 and nums == sorted(nums) and nums[-1] - nums[0] >= 1000 and all(num % 500 == 0 for num in nums):
            continue
        kept.append(row)
    return tuple(kept)


def _chart_tables(page) -> list[tuple[Box, tuple[tuple[str, ...], ...]]]:
    """一页上每张曲线数据表的外框和格子。不足两张时不拆图标。"""
    try:
        found = page.find_tables()
    except Exception:  # noqa: BLE001
        return []
    tables: list[tuple[Box, tuple[tuple[str, ...], ...]]] = []
    for table in getattr(found, "tables", None) or []:
        raw = getattr(table, "bbox", None)
        if not raw:
            continue
        grid = [[(cell or "").strip() for cell in row] for row in (table.extract() or [])]
        if not _chart_data_table(grid):
            continue
        rows = _drop_axis_rows([tuple(row) for row in grid if any(row)])
        if len(rows) < 2:
            continue
        tables.append((tuple(float(v) for v in raw), rows))
    return tables


def _plot_boxes(page) -> list[Box]:
    page_w, page_h = page.rect.width, page.rect.height
    boxes: list[Box] = []
    try:
        drawings = [d for d in page.get_drawings() if d.get("rect") is not None]
    except Exception:  # noqa: BLE001
        return []
    for drawing in drawings:
        rect = drawing["rect"]
        box = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
        if box[2] - box[0] >= 0.85 * page_w or box[3] - box[1] >= 0.85 * page_h:
            continue
        if max(box[2] - box[0], box[3] - box[1]) < 8:
            continue
        boxes.append(box)
    return boxes


def _icon_box(page, table: Box, others: list[Box], plots: list[Box]) -> Box:
    """数据表加上它右侧、同一高度的那条曲线。左侧另一张表的曲线不进来。"""
    grown = table
    for plot in plots:
        cx = (plot[0] + plot[2]) / 2
        cy = (plot[1] + plot[3]) / 2
        if cy < table[1] - 6 or cy > table[3] + 52:
            continue
        if plot[2] < table[0] + 6:
            continue
        distance = 0.0 if table[0] <= cx <= table[2] else cx - table[2]
        if distance > 340:
            continue
        nearer = False
        for other in others:
            if cy < other[1] - 6 or cy > other[3] + 52:
                continue
            if cx + 8 < other[0]:
                continue
            other_distance = 0.0 if other[0] <= cx <= other[2] else cx - other[2]
            if other_distance + 8 < distance:
                nearer = True
                break
        if nearer:
            continue
        grown = _union(grown, plot)
    words = page.get_text("words")
    for word in words:
        token = word[4].strip()
        if not token or len(token) > 18:
            continue
        box = (float(word[0]), float(word[1]), float(word[2]), float(word[3]))
        if box[2] < table[0] - 2:
            continue
        center_y = (box[1] + box[3]) / 2
        center_x = (box[0] + box[2]) / 2
        if center_y < table[1] - 16:
            continue
        if center_y < table[1] and center_x < table[0] + 12:
            continue
        if any(_contains(other, box) for other in others):
            continue
        if _near(box, grown, 12):
            grown = _union(grown, box)
    for other in others:
        tables_share_rows = min(table[3], other[3]) - max(table[1], other[1]) > 12
        if tables_share_rows and other[0] >= table[2] - 2:
            grown = (grown[0], grown[1], min(grown[2], other[0]), grown[3])
        if min(table[2], other[2]) - max(table[0], other[0]) > 20 and other[1] >= table[3] - 2:
            grown = (grown[0], grown[1], grown[2], min(grown[3], other[1] - 8))
        if min(table[2], other[2]) - max(table[0], other[0]) > 20 and other[3] <= table[1] + 2:
            grown = (grown[0], max(grown[1], table[1] - 12), grown[2], grown[3])
    for info in page.get_image_info():
        raw = info.get("bbox")
        if not raw:
            continue
        image = tuple(float(v) for v in raw)
        if _area(image) < 0.02 * page.rect.width * page.rect.height:
            continue
        if image[1] >= table[3] - 4 and grown[3] > image[1] + 8:
            grown = (grown[0], grown[1], grown[2], min(grown[3], image[1] + 8))
    if grown[0] < table[0]:
        grown = (table[0], grown[1], grown[2], grown[3])
    return (
        max(0.0, grown[0]),
        max(0.0, grown[1]),
        min(page.rect.width, grown[2]),
        min(page.rect.height, grown[3]),
    )


def outlined_titles(page) -> str:
    """文字层上方的页眉。轮廓字读不到，按第一行正文上面的窄带识出来。"""
    tops = [float(word[1]) for word in page.get_text("words") if float(word[1]) > 12 and str(word[4]).strip()]
    first = min(tops) if tops else 120.0
    if first < 56:
        return ""
    bottom = min(first - 3.0, 100.0)
    if bottom < 36:
        return ""
    png = _render(page, (16.0, 10.0, page.rect.width - 16.0, bottom), margin=0)
    kept: list[str] = []
    for raw in _prose_from_png(png).splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" .-")
        if len(re.findall(r"[A-Za-z]", line)) < 8 or re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", line):
            continue
        if line not in kept:
            kept.append(line)
    return "\n".join(kept)


def _title_key(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").lower()


def apply_outlined_titles(path: Path, pages: tuple[tuple[int, str], ...], figures: dict) -> tuple[tuple[int, str], ...]:
    """页眉不在文字层里时补到该页正文最前。图里已经有的不重复。"""
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return pages
    found: dict[int, str] = {}
    try:
        with pymupdf.open(str(path)) as doc:
            for index, _text in pages:
                if index < 1 or index > doc.page_count:
                    continue
                title = outlined_titles(doc[index - 1])
                if title:
                    found[index] = title
    except Exception:  # noqa: BLE001
        return pages
    if not found:
        return pages
    out: list[tuple[int, str]] = []
    for index, text in pages:
        lines = []
        known = _title_key(text) + "".join(
            _title_key(getattr(figure, "transcript", "") or "") for figure in figures.get(index, [])
        )
        for line in found.get(index, "").splitlines():
            key = _title_key(line)
            if key and key not in known:
                lines.append(line)
                known += key
        if lines:
            text = "\n".join(lines + ([text] if text else []))
        out.append((index, text))
    return tuple(out)


def _titles_above(page, box: Box) -> str:
    """图框上方单独的标题。轮廓字不在文字层里，要单独识出来。"""
    band_top = 22.0
    if box[1] - band_top < 18 or box[1] - band_top > 110:
        return ""
    png = _render(page, (18.0, band_top, page.rect.width - 18.0, box[1]), margin=0)
    kept: list[str] = []
    for raw in _prose_from_png(png).splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" .-")
        if len(re.findall(r"[A-Za-z]", line)) < 8 or re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", line):
            continue
        if line not in kept:
            kept.append(line)
    return "\n".join(kept)


def _icon_caption(page, box: Box, table: Box) -> str:
    """图里除了数据表和坐标刻度以外的字：标题、说明。这些要摘录并翻译。"""
    grouped: list[tuple[float, list]] = []
    for word in page.get_text("words"):
        token = str(word[4]).strip()
        if not token or re.fullmatch(r"[-+]?\d+(?:\.\d+)?", token):
            continue
        if token.lower() in {"rpm", "dba", "db"}:
            continue
        rect = (float(word[0]), float(word[1]), float(word[2]), float(word[3]))
        center_x = (rect[0] + rect[2]) / 2
        center_y = (rect[1] + rect[3]) / 2
        if table[0] - 1 <= center_x <= table[2] + 1 and table[1] - 1 <= center_y <= table[3] + 1:
            continue
        if rect[0] < box[0] - 1 or rect[2] > box[2] + 1 or rect[1] < box[1] - 1 or rect[3] > box[3] + 1:
            continue
        if grouped and abs(center_y - grouped[-1][0]) <= 4:
            grouped[-1][1].append((rect[0], token))
        else:
            grouped.append((center_y, [(rect[0], token)]))
    lines = []
    for _, words in grouped:
        words.sort()
        lines.append(" ".join(token for _, token in words))
    return "\n".join(lines)


def _split_chart_icons(page, figures: list[Figure]) -> list[Figure]:
    """任何文件都一样：同一页有多张曲线时，每张连同它自己的数据表各成一张图。"""
    tables = _chart_tables(page)
    if len(tables) < 2:
        return figures
    out: list[Figure] = []
    consumed: set[int] = set()
    for index, figure in enumerate(figures):
        inside = [item for item in tables if _overlap(figure.box, item[0]) >= 0.5 * _area(item[0])]
        if len(inside) < 2:
            if len(inside) == 1 and not (figure.transcript or "").strip() and not figure.grid:
                table_box, grid = inside[0]
                others = [other[0] for other in tables if other[0] != table_box]
                box = _icon_box(page, table_box, others, _plot_boxes(page))
                out.append(Figure(
                    figure.page, box, "", _render(page, box), figure.kind or "矢量图",
                    _icon_caption(page, box, table_box), (),
                ))
            else:
                out.append(figure)
            continue
        consumed.add(index)
        made: list[Figure] = []
        plots = _plot_boxes(page)
        for table_box, grid in inside:
            others = [other[0] for other in inside if other[0] != table_box]
            box = _icon_box(page, table_box, others, plots)
            caption = _icon_caption(page, box, table_box)
            # 纯数字表只留在截图里，不把格子再写成摘录。
            made.append(Figure(figure.page, box, "", _render(page, box, margin=1), figure.kind or "矢量图", caption, ()))
        below = max(item.box[3] for item in made)
        for info in page.get_image_info():
            raw = info.get("bbox")
            if not raw:
                continue
            box = tuple(float(v) for v in raw)
            if _area(box) < 0.02 * page.rect.width * page.rect.height:
                continue
            if box[1] < below - 30:
                continue
            if any(_overlap(box, item.box) >= 0.5 * _area(box) for item in made):
                continue
            made.append(Figure(figure.page, box, "", _render(page, box, margin=0), "位图", "", ()))
        out.extend(made)
    return out


def _render(page, box: Box, margin: float = _MARGIN) -> bytes:
    import pymupdf

    clip = pymupdf.Rect(box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin) & page.rect
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
            tables = excluded + _detected_tables(page)
            words = page.get_text("words")
            candidates: list[tuple[Box, str, int]] = []
            # 位图：没识读成表格的大图直接截
            if index not in image_table_pages:
                for info in page.get_image_info():
                    box = tuple(float(v) for v in info["bbox"])
                    if _big_enough(box, page_w, page_h, excluded):
                        candidates.append((box, "位图", 0))
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
                candidates.append((box, "矢量图", curved))
            straight = [
                tuple(float(v) for v in d["rect"])
                for d in drawings
                if d.get("rect") is not None and curved_strokes(d) == 0 and not _is_frame(tuple(float(v) for v in d["rect"]), page_w, page_h, excluded)
            ]
            # 位图和矢量线叠在一起的（坐标图里的阴影块）是同一张图
            figures: list[Figure] = []
            for box, kind, curved in _merge_candidates(candidates):
                box, labels = _with_labels(words, box)
                if curved >= _MIN_CURVED:
                    box = _grow_chart_box(box, straight, page_w, page_h)
                box = _cover_tables(box, tables, page_w, page_h)
                transcript = transcript_of(words, box)
                png = _render(page, box)
                grid: tuple[tuple[str, ...], ...] = ()
                kind_now = transcript_kind(transcript)
                found_grid: tuple[tuple[str, ...], ...] = ()
                extra = ""
                clean_lines = [
                    line for line in transcript.splitlines()
                    if " | " in line and not text_layer_broken(line)
                ]
                prose_layer = "\n".join(
                    line for line in transcript.splitlines()
                    if line not in clean_lines
                )
                broken = text_layer_broken(prose_layer)
                if broken or (kind_now != "table" and (kind_now == "prose" or len(transcript.strip()) < 12 or curved >= _MIN_CURVED)):
                    found_grid, extra = _ocr_figure(png)
                blob = " ".join(
                    part
                    for part in (
                        transcript,
                        labels,
                        extra,
                        " ".join(" ".join(row) for row in found_grid),
                    )
                    if part
                )
                if _curve_chart_only(blob, curved) or _axis_scale_grid(found_grid):
                    # 曲线图只留整图。横轴刻度 0、5000、10000、15000 不写成表。
                    figures.append(Figure(index, box, labels, png, kind, "", ()))
                    continue
                text_grid = _pipe_table("\n".join(clean_lines))
                if _filled(found_grid) > _filled(text_grid) and _data_table(found_grid):
                    grid = found_grid
                elif _data_table(text_grid):
                    grid = text_grid
                elif _data_table(found_grid):
                    grid = found_grid
                if grid:
                    grid = pull_orphan_column(grid)
                if _axis_scale_grid(grid):
                    figures.append(Figure(index, box, labels, png, kind, "", ()))
                    continue
                # 文字层只有脚注或碎片时，用截图按行识出的正文。完整文字层比识读更长时仍用文字层。
                if broken or _letters(prose_layer) * 2 < _letters(extra):
                    prose_source = extra or prose_layer
                else:
                    prose_source = prose_layer or extra
                transcript = order_clauses(prose_beside(prose_source, grid))
                if not transcript.strip() and not grid and extra:
                    transcript = extra
                above = _titles_above(page, box)
                if above:
                    transcript = order_clauses(above + "\n" + (transcript or ""))
                figures.append(Figure(index, box, labels, png, kind, transcript, grid))
            figures = _collapse_overlapping(page, figures, tables)
            if figures:
                figures.sort(key=lambda f: (f.box[1], f.box[0]))
                found[index] = figures
    return found
