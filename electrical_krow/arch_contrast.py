"""电驱需求拆解：把当份需求文件按条款拆成可回溯的材料对照稿。

每条要求一条：行首「1)」「•」「※」等标记起一条，没有标记的页整页一条。原文只来自该页可复制文字。
章节按行首的目录章节号认，本页没有标题时沿用上一页。数值与单位、括注条件从该条原文里机械挑出，不是认条，须对照原文；
每个数前带原文里紧挨着的几个字，便于对应。有格线的表按格读：认得出项目／要求表头的每行一条，项目格进「项目」，要求格进「数值与单位」。
状态一律待确认；责任人、客户反馈、能否满足留空。数值表整页保留，不拆成单条。
没有文字层或读不开的文件记入「未能读取」，不补写内容。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

SHEET_NOTE = "确认说明"
SHEET_ATTACH = "附件"  # 整表原文和图表截图合在一张
SHEET_TABLES = SHEET_ATTACH  # 旧名，条目索引文字里仍用

STATUS_PENDING = "待确认"
# Currently status 与偏差跟踪表同一套英文。To be confirmed 就是待确认，避免中英混在一个下拉里。
STATUS_CURRENT = "To be confirmed"
STATUS_CHOICES = (STATUS_CURRENT, "Requirement Met", "Require Customer Clarified", "Closed")
SECTION_COVER = "封面"
SECTION_TOC = "目录"

COLUMNS = (
    "序号",
    "对象",
    "文件",
    "PDF页码",
    "文内页码",
    "章节",
    "条款号",
    "项目（表格栏目）",
    "原文摘录",
    "数值与单位",
    "适用条件（原文括注）",
    "状态",
    "责任人",
    "客户反馈",
    "能否满足",
    "备注",
)
ATTACH_COLUMNS = ("序号", "对象", "文件", "PDF页码", "章节", "类型", "整表原文／图中文字", "图", "备注")
ATTACH_TABLE, ATTACH_OCR, ATTACH_PAGE, ATTACH_BLOCK = "表格", "图片表格·OCR", "数值页", "表格块"

_HEAD_LINE = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+(\S.*)$")
_PAGE_MARK = re.compile(r"(?:PAGE\s*)?(\d{1,3})\s*/\s*(\d{1,3})", re.I)
# 数值表里的格：纯数、带单位的数（150V、-186A、3min）、括号或方括号包着的数。
_NUMBER = re.compile(r"^[\[(]?[-+±~≥≤<>]?\d[\d,]*(?:\.\d+)?(?:[a-zA-Z%°Ω℃℉]{1,4})?[\])]?$")
_EXCERPT_CAP = 8000
_MIN_TEXT = 40

# 条款标记：行首「1)」「(1)」「1.」「①」起一条编号项；「•」「·」等起一条要点；「※」「*」起一条附注。
# 「-」「┖」不算标记：PPT 导出的 PDF 里连字符会单独成行，当标记会把一个词切成两条。
_ITEM_MARK = re.compile(r"^\(?(\d{1,2})[.)]\s*(?!\d)")
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_BULLET_MARK = re.compile(r"^[•·▪■◦●○✓✔√☑]\s*")
_NOTE_MARK = re.compile(r"^[※*]\s*")
_LEAD_CAP = 80
# 数值与单位：数（可带符号、千分位、小数、范围）后跟常见工程单位。单位表只用于识别，不用于取值。
_UNIT = (
    r"(?:k|m|M|µ|μ|u|G)?(?:V(?:dc|ac|DC|AC)?|A(?:h|C|DC)?|W(?:h)?|VA|Hz|Nm|N·m|N\.m|rpm/s|rpm|r/min|"
    r"°C|℃|K|%|hr?s?|hours?|years?|yrs?|days?|min(?:utes?)?|s(?:ec)?|ms|km(?:/h)?|mm|cm|µm|μm|m|kg|g|"
    r"bar|k?Pa|MPa|dB(?:A)?|L(?:PM)?|l/min|Ω|ohm|cycles?|times|lux|J|kJ|Nm/s|°|deg)"
)
# PDF 文字层常把千分位逗号、小数点两侧拆出空格：160, 000 / 300 , 000 / 99 . 85。原样认下，不改写。
# 小数点只认「两侧都有空格」或「两侧都没有」：「1. 26 kW」里的「1.」是条款标记，不是 1.26。
_NUM = r"\d+(?:\s?,\s?\d{3})*(?:(?:\.|\s\.\s)\d+)?"
_QUANTITY = re.compile(
    r"(?<![A-Za-z\d.,])([-+±≥≤<>≈~]?\s?" + _NUM + r"(?:\s?(?:~|-|–|to|/)\s?" + _NUM + r")?)\s?" + _UNIT + r"(?![A-Za-z])"
)
# 数前的引导词：从上一个数（或句读）之后到这个数之前的那几个字，右对齐截短。只为对应原文，不是认条。
_LEAD_WORDS = 5
_LEAD_CJK = 12
_LEAD_BREAK = re.compile(r"[。;；:：!?！？]|\.(?=\s+[A-Z0-9(（])")
_LEAD_ABBR = re.compile(r"(?:\b(?:etc|vs|approx|No|Fig|Ref)|\be\.g|\bi\.e)$", re.I)
_LEAD_STRIP = " ,，、;；:：/\\-–—)）•·▪■◦●○"
# 数后紧跟的限定（400W ↑、65℃ 以上、5 A max）是这个数的一部分，一起留住
_TRAIL = re.compile(
    r"\s?(?:↑|↓|以上|以下|以内|及以上|及以下|max\.?|min\.?|typ\.?|or more|or less|and above|and below|or higher|or lower)(?![A-Za-z])",
    re.I,
)
_PAREN = re.compile(r"[（(]([^()（）]{3,160})[)）]")
# 保密声明行：各页都有、不是需求。按关键词整行剔除，避免按行去重时只删掉一半留下碎片。
_NOTICE = re.compile(
    r"보호받습니다|정보자산|기아의|관련 법령|confidential|proprietary|all rights reserved|保密|机密|版权所有|不得外传|仅供内部|together we can",
    re.I,
)
# 斜盖在表格上的图章，不是正文。
_STAMP = re.compile(r"corresponding\s+to\s+the\s+.{0,80}?drawing", re.I)
_MARK_CELL = re.compile(r"^[○◯●•〇✓✔√]+$")
_SIDE_NAME = re.compile(r"\b(?:hmc|supplier|供应商)\b", re.I)
NOTE_MARK_COL = "圆圈所在列读不出，请对照原页"
# 一条内的表格块：词数够多，且数字占四成以上，或重复词太多（表头「Torque Nm Power kW」反复出现）。
_TABLE_MIN_TOKENS = 10
_TABLE_NUMERIC = 0.5
_TABLE_UNIQUE = 0.2

_HEADER_FILL = PatternFill("solid", fgColor="142B49")
_DIFF_FILL = PatternFill("solid", fgColor="FCE4E4")  # 取值不一致或待定的行，隔行底色不能盖住
_BAND_FILL = PatternFill("solid", fgColor="F3F6FA")
_HEADER_FONT = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="微软雅黑", size=10, color="263445")
_ID_FONT = Font(name="微软雅黑", size=10, bold=True, color="142B49")
_WRAP = Alignment(wrap_text=True, vertical="top")
_THIN = Border(
    left=Side(style="thin", color="DCE3EB"),
    right=Side(style="thin", color="DCE3EB"),
    top=Side(style="thin", color="DCE3EB"),
    bottom=Side(style="thin", color="DCE3EB"),
)


Grid = list[list[str]]


@dataclass(frozen=True)
class SourceDoc:
    """一份已读出文字的 PDF。pages 为 (PDF 页码, 原文)；tables 为 页码 → 该页按格线读出的表格（行×列的原文）。"""

    name: str
    pages: tuple[tuple[int, str], ...]
    tables: dict[int, list[Grid]] = field(default_factory=dict)
    image_tables: dict[int, list[Grid]] = field(default_factory=dict)  # 页码 → 图片里 OCR 识读出的表格
    figures: dict[int, list] = field(default_factory=dict)  # 页码 → 图表截图（arch_figures.Figure）
    path: str = ""  # 原文件路径，条款截图时再打开渲染；空则不截图
    lines: dict[int, list] = field(default_factory=dict)  # 页码 → 文字行 (bbox, text)，正文条目定位用
    table_rows: dict[int, list[list]] = field(default_factory=dict)  # 页码 → 每张表每行的范围，与 tables 对齐
    unread: tuple[Unreadable, ...] = field(default_factory=tuple)  # 这份里单独读失败的页


@dataclass(frozen=True)
class Unreadable:
    name: str
    pages: int
    reason: str
    page: int = 0  # 大于 0 时是这一页读失败；0 表示整份文件


@dataclass(frozen=True)
class ContrastResult:
    path: Path
    files: int
    rows: int
    tables: int
    unreadable: tuple[Unreadable, ...] = field(default_factory=tuple)
    params: int = 0
    conflicts: int = 0
    model_used: bool = False
    image_tables: int = 0  # 图片里 OCR 识读出的表格张数
    figures: int = 0  # 图表截图张数
    reqs: int = 0  # 需求清单条数
    shots: int = 0  # 需求清单里带原文截图的条数
    quality_summary: str = ""  # 文件内容质检结论摘要
    bilingual_conflicts: int = 0  # 同条中英数值/语义冲突处数
    logic_conflicts: int = 0  # 内部逻辑/算式冲突处数
    tbd_count: int = 0  # 含 TBD/TBC 待定项的条数
    quality_issues: tuple[str, ...] = field(default_factory=tuple)  # 质检明细行


def _text(value: object) -> str:
    return str(value or "").strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Wingdings 等符号字体的项目符号在文字层里是私用区码位（U+F0A7），Excel 里显示成方框；统一写成「•」
_PUA = re.compile(r"[\ue000-\uf8ff]")
NOTE_OCR = "图片表格·OCR 识读，字符须对照原图核对"
SHEET_FIGURES = SHEET_ATTACH  # 旧名
SHOT_SLOT = len(COLUMNS)  # 条目行末尾放截图位置的下标
SHEET_REQS = "需求清单"
REQ_COLUMNS = (
    "REQ-ID", "Priority\n优先级", "Base on SR\n章节", "SR content\n原文截图", "原文摘录", "数值与单位", "适用条件（原文括注）",
    "Category\n类别（建议）", "Comments\n意见", "From whom\n提出人", "Currently status\n状态", "HMC feedback\n客户反馈",
    "Remark\n备注", "PDF页码", "置信度", "人工修改",
)
# 类别建议：按章节名和条文里的关键词给一个值，供人改。只是建议，不是认条。
_CATEGORY_RULES = (
    ("Regulation", re.compile(r"regulat|law\b|legal|certif|homolog|\bemc\b|emission|immunity|法规|认证|电磁")),
    ("Technical document output", re.compile(r"document|submission|submit|drawing|report|dfmea|deliverable|文档|提交|图纸|报告")),
    ("Simulation", re.compile(r"simulat|\banalysis|仿真|分析")),
    ("Service", re.compile(r"service|repair|maintenance|diagnos|售后|维修|诊断")),
    ("Quality", re.compile(r"reliab|durab|quality|\btest|validation|verification|environment|vibration|shock|temperature|humidity|可靠|耐久|质量|试验|验证|环境|振动")),
    ("Performance", re.compile(r"performance|efficien|output|accuracy|ripple|response|power|voltage|current|性能|效率|精度|纹波|功率|电压|电流")),
)


def suggest_category(section: str, text: str) -> str:
    key = f"{section} {text}".lower()
    for name, pattern in _CATEGORY_RULES:
        if pattern.search(key):
            return name
    return "Function"


def _plain_glyphs(text: str) -> str:
    return _PUA.sub("•", text or "")


def read_pdf_pages(path: Path, progress=None) -> SourceDoc | Unreadable:
    """读 PDF 文字层。读不开或没有文字层时返回 Unreadable。"""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                return Unreadable(path.name, 0, "文件已加密，读不出正文。")
        pages: list[tuple[int, str]] = []
        failed_extract: set[int] = set()
        total_pages = len(reader.pages)
        for index, page in enumerate(reader.pages, start=1):
            if progress:
                progress("text", index, total_pages)
            try:
                pages.append((index, _plain_glyphs(page.extract_text() or "")))
            except Exception:  # noqa: BLE001
                failed_extract.add(index)
                pages.append((index, ""))
    except Exception:  # noqa: BLE001
        return Unreadable(path.name, 0, "文件打不开，不是可读的 PDF。")
    if not pages:
        return Unreadable(path.name, 0, "PDF 没有页面。")
    if sum(len(_compact(text)) for _, text in pages) < _MIN_TEXT:
        return Unreadable(path.name, len(pages), "没有文字层，未拆条，未补写内容。")
    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    row_boxes: dict[int, list[list]] = {}
    tables = read_pdf_tables(
        path, boxes, row_boxes,
        progress=(lambda page, total: progress("tables", page, total)) if progress else None,
    )
    image_tables = drop_duplicate_grids(
        tables,
        read_image_tables(path, progress=(lambda page, total: progress("ocr", page, total)) if progress else None),
    )
    if progress:
        progress("figures", 1, 1)
    figures = read_figures(path, boxes, set(image_tables))
    from electrical_krow.arch_figures import apply_outlined_titles

    pages = apply_outlined_titles(path, tuple(pages), figures)
    unread: list[Unreadable] = []
    for index, text in pages:
        if _compact(text) or tables.get(index) or image_tables.get(index) or figures.get(index):
            continue
        if index in failed_extract:
            reason = f"第 {index} 页读取失败，未拆条，未从其他页补写。"
        else:
            reason = f"第 {index} 页没有文字，未拆条，未从其他页补写。"
        unread.append(Unreadable(path.name, 1, reason, page=index))
    return SourceDoc(
        path.name, pages, tables, image_tables, figures,
        path=str(path), lines=read_text_lines(path, boxes), table_rows=row_boxes,
        unread=tuple(unread),
    )


def read_text_lines(path: Path, boxes: dict[int, list[tuple[float, float, float, float]]] | None = None) -> dict[int, list]:
    try:
        from electrical_krow.arch_shots import read_lines

        return read_lines(path, boxes)
    except Exception:  # noqa: BLE001
        return {}


def read_figures(path: Path, boxes: dict[int, list[tuple[float, float, float, float]]], image_table_pages: set[int]) -> dict[int, list]:
    """图表截图。渲染库不可用或出错就当没有。"""
    try:
        from electrical_krow.arch_figures import find_figures

        return find_figures(path, boxes, image_table_pages)
    except Exception:  # noqa: BLE001
        return {}


def _cell_set(grid: Grid) -> set[str]:
    return {_alnum(cell).lower() for row in grid for cell in row if _alnum(cell)}


def drop_duplicate_grids(tables: dict[int, list[Grid]], image_tables: dict[int, list[Grid]]) -> dict[int, list[Grid]]:
    """有的 PDF 同一张表既有文字层又贴了一张图。OCR 读出的表和本页文字层表格大半格子相同的，只留文字层那份。"""
    kept: dict[int, list[Grid]] = {}
    for page_no, grids in image_tables.items():
        known = [_cell_set(grid) for grid in tables.get(page_no, [])]
        fresh = []
        for grid in grids:
            cells = _cell_set(grid)
            if any(cells and len(cells & other) * 10 >= len(cells | other) * 6 for other in known):
                continue
            fresh.append(grid)
        if fresh:
            kept[page_no] = fresh
    return kept


def read_image_tables(path: Path, progress=None) -> dict[int, list[Grid]]:
    """图片形式贴进 PDF 的表格：按格线切格、OCR 识字。识读库不可用或出错就当没有。"""
    try:
        from electrical_krow.arch_ocr import read_image_tables as _read

        return _read(path, progress=progress)
    except Exception:  # noqa: BLE001
        return {}


def read_pdf_tables(
    path: Path,
    boxes: dict[int, list[tuple[float, float, float, float]]] | None = None,
    row_boxes: dict[int, list[list]] | None = None,
    progress=None,
) -> dict[int, list[Grid]]:
    """按格线读每页的表格。读不出（没格线、库不可用）就当没有表，退回按文字拆。
    传入 boxes 时顺便记下每张认下的表在页面上的位置（截图表时避开）；传入 row_boxes 时记下每行的范围（条款截图用）。"""
    try:
        import pdfplumber
    except Exception:  # noqa: BLE001
        return {}
    found: dict[int, list[Grid]] = {}
    try:
        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)
            for index, page in enumerate(pdf.pages, start=1):
                if progress:
                    progress(index, total_pages)
                grids: list[Grid] = []
                try:
                    found_tables = page.find_tables()
                except Exception:  # noqa: BLE001
                    continue
                for table in found_tables:
                    grid = [[_compact(_plain_glyphs(cell or "")) for cell in row] for row in table.extract()]
                    if is_grid(grid):
                        grids.append(grid)
                        table_box = tuple(float(v) for v in table.bbox)
                        if boxes is not None:
                            boxes.setdefault(index, []).append(table_box)
                        if row_boxes is not None:
                            from electrical_krow.arch_shots import row_box

                            row_boxes.setdefault(index, []).append([row_box(list(r.cells), table_box) for r in table.rows])
                if grids:
                    found[index] = grids
    except Exception:  # noqa: BLE001
        return {}
    return found


def is_grid(grid: Grid) -> bool:
    """算得上表的：至少两行两列，且一半以上的行有两格以上有字（或左列纵向合并、末列有成句内容）。单行的页眉表、格里套出来的碎块不算。"""
    if len(grid) < 2 or not grid[0] or len(grid[0]) < 2:
        return False
    multi = sum(1 for row in grid if sum(1 for cell in row if cell) >= 2)
    if multi * 2 >= len(grid):
        return True
    if multi >= 2 and len(grid) >= 4:
        filled = sum(1 for row in grid if sum(1 for cell in row if cell) >= 2 or len(row[-1] or "") >= 15)
        return filled * 2 >= len(grid)
    return False


def boilerplate_lines(pages: tuple[tuple[int, str], ...]) -> frozenset[str]:
    """在四成以上页面重复出现的短行是页眉页脚，不算原文。"""
    if len(pages) < 5:
        return frozenset()
    counts: dict[str, int] = {}
    for _, text in pages:
        seen: set[str] = set()
        for line in text.splitlines():
            key = _compact(line)
            # 只有符号的行（「-」「•」「※」）是连字符或条款标记，不是页眉页脚
            if not key or len(key) > 60 or key in seen or not re.search(r"[A-Za-z0-9\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]", key):
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
    limit = max(3, int(len(pages) * 0.4))
    return frozenset(key for key, count in counts.items() if count >= limit)


_HANGUL = re.compile(r"[\uac00-\ud7af\u3130-\u318f]")
_LETTER = re.compile(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af\u3130-\u318f]")
_HANGUL_NOTICE_WORDS = frozenset({
    "본", "문서는", "현대자동차", "기아의", "정보자산으로", "관련", "법령에", "의해", "보호받습니다",
    "사내한", "대외비", "보안해제", "영문화", "수정", "ESMS수정",
})


def hangul_is_minor(pages: tuple[tuple[int, str], ...]) -> bool:
    """整份文件里韩文字母不到两成：英文或中文 SR 里夹的韩文保密声明拆行词予以剔除。"""
    letters = sum(len(_LETTER.findall(text)) for _, text in pages)
    hangul = sum(len(_HANGUL.findall(text)) for _, text in pages)
    return letters > 0 and hangul / letters < 0.2


def _hangul_only(key: str) -> bool:
    letters = _LETTER.findall(key)
    if not letters or not all(_HANGUL.match(ch) for ch in letters):
        return False
    words = [w.strip(".,()/[]") for w in key.split() if w.strip(".,()/[]")]
    return bool(words) and all(w in _HANGUL_NOTICE_WORDS for w in words)


def page_body(text: str, boilerplate: frozenset[str], page_no: str = "", *, drop_hangul: bool = False) -> str:
    kept: list[str] = []
    for line in (text or "").splitlines():
        key = _compact(line)
        if not key or key in boilerplate:
            continue
        if _PAGE_MARK.fullmatch(key):
            continue
        # 「PAGE / 16 / /51」拆成三行时，中间那行只剩页码数字
        if page_no and key == page_no:
            continue
        if _NOTICE.search(key) or _STAMP.search(key):
            continue
        # 保密声明按词拆成多行时，关键词只在其中一行；韩文占比低的文件里纯韩文行整行剔除
        if drop_hangul and _hangul_only(key):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


_FILLER = re.compile(r"^[.…·\-–—/|]+$")


_AXIS_CHROME = re.compile(
    r"^(?:dBA|dB|rpm|order|harmonic|fundamental|sideband|fun|restricted|respectively|noise|oder|gear|motor|input|output|st|nd|rd|th|p1|p3)$",
    re.I,
)


def _axis_chrome_line(line: str) -> bool:
    """坐标刻度、图名、保密水印。这种行不写进上一条要求，也不单独成条。"""
    flat = _compact(line)
    if not flat or _mark_of(flat):
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", flat):
        return True
    tokens = re.findall(r"[A-Za-z]+\d*|\d+(?:st|nd|rd|th)", flat, re.I)
    words = [token for token in tokens if re.search(r"[A-Za-z]", token)]
    if not words or len(words) > 6:
        return False
    return all(_AXIS_CHROME.match(word) or re.fullmatch(r"\d+(?:st|nd|rd|th)", word, re.I) for word in words)


def drop_axis_chrome(body: str) -> str:
    """曲线图上的刻度和图名从正文里拿掉。编号条款和成句要求留下。"""
    return "\n".join(line for line in (body or "").splitlines() if line.strip() and not _axis_chrome_line(line))


def _inside_chart_shot(doc: SourceDoc, page: int, span: tuple[float, float, float, float] | None) -> bool:
    """这张表已经画在曲线图上。文字层再写一遍就是重复。"""
    if span is None:
        return False
    for figure in doc.figures.get(page, []):
        box = getattr(figure, "box", None)
        if not box:
            continue
        if not (span[0] >= box[0] - 8 and span[1] >= box[1] - 8 and span[2] <= box[2] + 8 and span[3] <= box[3] + 8):
            continue
        text = getattr(figure, "transcript", "") or ""
        clauses = len(re.findall(r"(?m)^(?:\d{1,2}[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩])", text))
        if getattr(figure, "grid", ()) or clauses < 3:
            return True
    return False


def is_table_block(text: str) -> bool:
    """一条里是不是表格块（坐标轴刻度、占位点、反复出现的表头）。是的话整块保留，不当需求条。"""
    tokens = _compact(text).split()
    if len(tokens) < _TABLE_MIN_TOKENS:
        return False
    numeric = sum(1 for token in tokens if _NUMBER.match(token) or _FILLER.match(token)) / len(tokens)
    unique = len(set(tokens)) / len(tokens)
    words = sum(1 for token in tokens if re.fullmatch(r"[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff'-]{3,}[.,;:]?", token))
    # 同一组表头反复出现（Torque Nm Power kW ×12）：先于句子判断
    if len(tokens) >= 2 * _TABLE_MIN_TOKENS and unique <= _TABLE_UNIQUE:
        return True
    # 一句话里带几个数不是表格：词够多、数字不到六成的按句子算
    if words >= 6 and numeric < 0.6:
        return False
    # 几乎没有整词、只有量名和数（Vo_max (15.1V) Io (A) 180A …）：数字占四成就是表
    if words <= 2 and numeric >= 0.4:
        return True
    return numeric >= _TABLE_NUMERIC


def inner_page(text: str, total: int) -> str:
    for found in _PAGE_MARK.finditer(text or ""):
        if int(found.group(2)) in {total, total - 1, total - 2}:
            return found.group(1)
    return ""


_BARE_NUMBER = re.compile(r"^\d+(?:\.\d+){0,3}\.?$")


_ORDINAL_BIT = re.compile(r"^(?:/?\d+(?:st|nd|rd|th)?|(?:st|nd|rd|th))$", re.I)


def stitch_broken_tokens(text: str) -> str:
    """文字层把一个词拆成几行时拼回去。单独的大写字母接后面的小写；8、th、/24 接回 8th/24th。"""
    lines = (text or "").splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        flat = _compact(lines[index])
        if re.fullmatch(r"[A-Z]", flat) and index + 1 < len(lines):
            nxt = _compact(lines[index + 1])
            if nxt[:1].islower():
                out.append(flat + nxt)
                index += 2
                continue
        # 「after T / - / car」是被拆开的 T-car；「and 1 / st」是 1st。先拼上，避免 st、car 被当成碎片丢掉。
        if re.search(r"[A-Z]$", flat) and index + 2 < len(lines) and _compact(lines[index + 1]) == "-":
            tail = _compact(lines[index + 2])
            if re.fullmatch(r"[a-z]{1,12}", tail):
                out.append(f"{flat}-{tail}")
                index += 3
                continue
        if (
            re.search(r"\d$", flat)
            and not _ORDINAL_BIT.match(flat)
            and index + 1 < len(lines)
            and re.fullmatch(r"(?:st|nd|rd|th)", _compact(lines[index + 1]), re.I)
        ):
            out.append(flat + _compact(lines[index + 1]))
            index += 2
            continue
        if flat and _ORDINAL_BIT.match(flat):
            bits = [flat]
            look = index + 1
            while look < len(lines) and _ORDINAL_BIT.match(_compact(lines[look])):
                bits.append(_compact(lines[look]))
                look += 1
            nxt = _compact(lines[look]) if look < len(lines) else ""
            ordinal = any(re.search(r"(?:st|nd|rd|th)$", bit, re.I) for bit in bits)
            if ordinal and len(bits) >= 2 and nxt and re.match(r"[A-Za-z]", nxt):
                out.append(f"{''.join(bits)} {nxt}")
                index = look + 1
                continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def rejoin_numbers(lines: list[str]) -> list[str]:
    """PDF 文字层常把章节号和标题拆成两三行（「2」「.」「System requirements」、「3.1」「Design requirement」）。

    单独成行的章节号，后面紧跟「.」或以字母/汉字开头的行时拼回一行。后面是数字开头的行（表格里的刻度）不拼。
    """
    out: list[str] = []
    index = 0
    while index < len(lines):
        flat = _compact(lines[index])
        if not flat:
            index += 1
            continue
        if _BARE_NUMBER.match(flat):
            look = index + 1
            number = flat
            if look < len(lines) and _compact(lines[look]) == ".":
                number = number.rstrip(".") + "."
                look += 1
            if look < len(lines):
                title = _compact(lines[look])
                if title and re.match(r"[A-Za-z\u4e00-\u9fff]", title):
                    out.append(f"{number} {title}")
                    index = look + 1
                    continue
        out.append(flat)
        index += 1
    return out


def toc_headings(pages: tuple[tuple[int, str], ...]) -> tuple[list[tuple[str, str]], set[int]]:
    """目录页上的章节号与标题。目录页本身标成目录，不再按正文拆章节。

    目录页的判据：带章节号的行不少于 6 行、号码互不重复、其中至少 3 个是多级号（2.1、2.5.3）。
    进度表里反复出现的「1. … 2. … 3. …」不算目录。
    """
    heads: list[tuple[str, str]] = []
    toc_pages: set[int] = set()
    seen: set[str] = set()
    for index, text in pages[:8]:
        found: list[tuple[str, str]] = []
        for line in rejoin_numbers(text.splitlines()):
            matched = _HEAD_LINE.match(line)
            if not matched:
                continue
            number, title = matched.group(1), matched.group(2).strip(" .")
            if len(title) < 3 or re.fullmatch(r"[\d\s./-]+", title) or any(p.startswith("0") for p in number.split(".")):
                continue  # 页眉里的「001 Date」「1.0 PAGE」（版本号）不是章节
            found.append((number, title))
        numbers = [number for number, _ in found]
        if len(found) >= 6 and len(set(numbers)) == len(numbers) and sum(1 for n in numbers if "." in n) >= 3:
            toc_pages.add(index)
            for number, title in found:
                if number not in seen:
                    seen.add(number)
                    heads.append((number, title))
    return heads, toc_pages




def match_heading(body: str, heads: list[tuple[str, str]]) -> str:
    """只认行首的完整章节号，且章节号后紧跟目录里的标题首词。「4.4」不算第 4 章，「1)」不算章节，
    规范清单里的「2 ES 05206 - 00 … System」不算第 2 章。多行时返回最后一个。"""
    found = ""
    for line in rejoin_numbers(body.splitlines()):
        flat = line.lower()
        leading = re.match(r"^(\d+(?:\.\d+)*)", flat)
        if not leading or flat[leading.end() :].startswith(")"):
            continue
        rest = _alnum(flat[leading.end() :])
        for number, title in heads:
            if leading.group(1) != number:
                continue
            first = _alnum(title.split()[0].lower()) if title.split() else ""
            if first and not rest.startswith(first):
                continue
            found = f"{number} {title}"
    return found


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u3130-\u318f\u4e00-\u9fff]", "", text.lower())


def page_headings(body: str, heads: list[tuple[str, str]]) -> list[str]:
    """一页里按出现顺序认出的章节标题（含目录没列到的下级标题）。"""
    out: list[str] = []
    for line in rejoin_numbers(body.splitlines()):
        head = _heading_of(line, heads)
        if head:
            out.append(head)
    return out


def is_table_page(body: str) -> bool:
    tokens = _compact(body).split()
    if len(tokens) < 40:
        return False
    numeric = sum(1 for token in tokens if _NUMBER.match(token))
    return numeric / len(tokens) >= 0.5


def object_of(doc: SourceDoc) -> str:
    head = _compact(" ".join(text for _, text in doc.pages[:2]) + " " + doc.name).lower()
    if "ldc" in head or "dcdc" in head or "dc-dc" in head:
        return "LDC"
    if "pe system" in head or "inverter" in head or "motor" in head or "gear" in head:
        return "电驱系统"
    return STATUS_PENDING


def _excerpt(body: str, *, keep_short: bool) -> tuple[str, str]:
    text = body.strip()
    if len(_compact(text)) < _MIN_TEXT and not keep_short:
        return "本页几乎没有可复制文字，可能是图或表。", "需对照原页，未补写图中内容"
    if len(text) > _EXCERPT_CAP:
        return text[:_EXCERPT_CAP] + "\n……（本页其余文字见原 PDF）", f"摘录在 {_EXCERPT_CAP} 字处截断"
    return text, ""


def join_lines(lines: list[str]) -> str:
    """把 PDF 里碎开的行拼回一段。单独一行的「-」夹在词中间是连字符；条目列举则另起一行。"""
    pieces = [_compact(raw) for raw in lines if _compact(raw)]
    out = ""
    index = 0
    while index < len(pieces):
        piece = pieces[index]
        nxt = pieces[index + 1] if index + 1 < len(pieces) else ""
        if piece == "-" and nxt:
            if nxt[0].islower() and out and out[-1].isalnum():
                out += "-" + nxt
                index += 2
                continue
            if out.rstrip().endswith(":") or "\n- " in out:
                out += "\n- " + nxt
            else:
                out += (" " if out else "") + "- " + nxt
            index += 2
            continue
        if not out:
            out = piece
        elif out.endswith("-") and piece[:1].islower():
            out += piece
        else:
            out += " " + piece
        index += 1
    return out.strip()


def _heading_of(line: str, heads: list[tuple[str, str]]) -> str:
    """目录里的标题直接认；目录没列到的下级标题（2.5.2），上级 2.5 在目录里、行短且以字母开头的标题词时也认。"""
    found = match_heading(line, heads)
    if found or len(line) > 70:
        return found
    matched = _HEAD_LINE.match(line)
    if not matched:
        return ""
    number, title = matched.group(1), matched.group(2).strip(" .")
    if number.count(".") < 2 or not re.match(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]", title) or len(title) < 3:
        return ""
    parent = number.rsplit(".", 1)[0]
    if not any(parent == head_no for head_no, _ in heads):
        return ""
    return f"{number} {title}"


def _is_label(line: str) -> bool:
    """像栏目标签的短行：不长、不以句末标点结尾、至少有一个字母或文字。"""
    flat = _compact(line)
    return 0 < len(flat) <= 40 and not flat.endswith((".", "。", ":", "：", ";", "；")) and bool(
        re.search(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]", flat)
    )


def _ends_sentence_then_label(lines: list[str], flat: str) -> bool:
    """上一条已以句号结束、本行又像栏目标签（Safety、Laws and Regulation）：这是表格里下一行的栏目名，留给下一条。"""
    if not lines or not lines[-1].rstrip().endswith((".", "。", ";", "；")):
        return False
    # 栏目名很短：不超过 3 个词、30 字，没有逗号。「However, if there is…」「Evaluation report must provide」是续句
    return (
        _is_label(flat)
        and len(flat) <= 30
        and len(flat.split()) <= 3
        and "," not in flat
        and bool(re.match(r"[A-Z\u4e00-\u9fff]", flat))
    )


def _mark_of(flat: str) -> tuple[str, str] | None:
    """行首的条款标记。返回 (条款号, 去掉标记后的文字)；不是标记行返回 None。"""
    if flat and flat[0] in _CIRCLED:
        return flat[0], flat[1:].strip()
    found = _ITEM_MARK.match(flat)
    if found:
        return found.group(0).strip(), flat[found.end() :].strip()
    found = _BULLET_MARK.match(flat)
    if found:
        return "•", flat[found.end() :].strip()
    found = _NOTE_MARK.match(flat)
    if found:
        return "※", flat[found.end() :].strip()
    return None


def split_clauses(body: str, heads: list[tuple[str, str]], section: str) -> list[tuple[str, str, str]]:
    """把一页正文按条款标记拆成 (章节, 条款号, 原文)。

    没有标记的行并入上一条；标记前的短引导句（如「Durability」「以下要求须满足」）并入紧随其后的那条。
    整页没有标记时返回一条。
    """
    body = break_before_marks(body)
    clauses: list[tuple[str, str, list[str]]] = []  # (section, mark, lines)
    pending_lead: list[str] = []
    current_section = section
    fresh = True  # 页首或标题之后：没有标记的行先攒成引导句
    held = False  # pending_lead 里是从上一条末尾扣下的栏目名（表格行名），等着并入下一条
    prev = ""
    for flat in rejoin_numbers(body.splitlines()):
        if not flat:
            continue
        before, prev = prev, flat
        head = _heading_of(flat, heads)
        if head:
            # 标题只进「章节」列；标题后的文字另起引导句
            if pending_lead and held:
                clauses[-1][2].extend(pending_lead)
            elif pending_lead:
                clauses.append((current_section, "", pending_lead))
            current_section = head
            pending_lead = []
            fresh = True
            held = False
            continue
        mark = _mark_of(flat)
        if mark and before.endswith("-") and _ITEM_MARK.match(flat):
            # 上一行以连字符结尾时，「10)」是被拆开的「ES96200-10)」，不是新条
            mark = None
        if mark:
            # 标记前的行：末尾像栏目标签的短行（Durability、FASTENING）并入这条；整句说明自成一条
            lead: list[str] = []
            while pending_lead and _is_label(pending_lead[-1]) and len(join_lines(lead)) < _LEAD_CAP:
                lead.insert(0, pending_lead.pop())
            if pending_lead:
                clauses.append((current_section, "", pending_lead))
            clauses.append((current_section, mark[0], lead + ([mark[1]] if mark[1] else [])))
            pending_lead = []
            fresh = False
            held = False
            continue
        if held:
            # 刚从上一条末尾扣下的栏目名：后面再来一个栏目名就一起留着；来的是别的（续句、按词拆开的「Such」「as」）就放回上一条
            if _scrap_line(flat):
                continue
            if _ends_sentence_then_label(clauses[-1][2], flat):
                pending_lead.append(flat)
                continue
            clauses[-1][2].extend(pending_lead)
            clauses[-1][2].append(flat)
            pending_lead = []
            held = False
            continue
        if clauses and not pending_lead and not fresh:
            if _scrap_line(flat):
                continue
            if _ends_sentence_then_label(clauses[-1][2], flat):
                pending_lead.append(flat)
                held = True
            else:
                clauses[-1][2].append(flat)
        else:
            pending_lead.append(flat)
    if pending_lead:
        if clauses and not fresh and (held or all(_is_label(line) for line in pending_lead)):
            # 页末只剩几个栏目标签、后面没有条了：并回上一条，不单独成条
            clauses[-1][2].extend(pending_lead)
        else:
            clauses.append((current_section, "", pending_lead))
    out: list[tuple[str, str, str]] = []
    for sec, mark, lines in clauses:
        text = join_lines(lines)
        if mark and text:
            text = f"{mark} {text}"
        elif mark:
            text = mark
        if len(_compact(text.replace(mark, "", 1))) < 2:
            continue
        out.append((sec, mark, text))
    return out


def _lead_in(segment: str) -> str:
    """数前原文里紧挨着的几个字：从最近一个句读之后起，右对齐截到几个词。原样截取，不改写。"""
    cut = 0
    for brk in _LEAD_BREAK.finditer(segment):
        if brk.group(0) == "." and _LEAD_ABBR.search(segment[: brk.start()]):
            continue
        cut = brk.end()
    lead = _compact(segment[cut:])
    # 括号在这段之前就开了的（「…sub-parts) within」），右括号连同前面的都不算引导词
    depth, drop = 0, 0
    for pos, ch in enumerate(lead):
        if ch in "(（":
            depth += 1
        elif ch in ")）":
            depth -= 1
            if depth < 0:
                depth, drop = 0, pos + 1
    lead = lead[drop:].lstrip(_LEAD_STRIP).lstrip(".").strip()
    lead = _ITEM_MARK.sub("", lead) if cut == 0 else lead
    if not re.search(r"[A-Za-z0-9\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff@=<>≤≥±]", lead):
        return ""  # 只剩标点（如孤零零一个「(」）不算引导词；「@」「=」这类关系符保留
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", lead):
        return lead[-_LEAD_CJK:] if len(lead) > _LEAD_CJK else lead
    words = lead.split()
    return " ".join(words[-_LEAD_WORDS:])


def quantities(text: str) -> str:
    """原文里带单位的数，按出现顺序以「；」连接，每个数前带原文里紧挨着的几个字以便对应。
    只认数字紧跟常见工程单位的写法，是机械挑出，不是认条。"""
    found: list[str] = []
    seen: set[str] = set()
    source = text or ""
    prev_end = 0
    last_single = False  # 上一个数刚列入、还不是范围，可以并入紧跟的「~ 下限」
    for match in _QUANTITY.finditer(source):
        if match.start() < prev_end:
            continue
        qty = _compact(match.group(0))
        end = match.end()
        trail = _TRAIL.match(source, end)
        if trail:
            qty = _compact(qty + " " + trail.group(0))
            end = trail.end()
        between = source[prev_end : match.start()]
        # 「150kHz ~ 108MHz」两头都带单位时正则会拆成两个数：紧跟上一个数、以 ~ 或 - 开头的，并回上一条当范围
        link = between.strip()
        # 只认 ~、–、to 当范围连接，「/」当成对的量（「15 years / 300,000 km」「-40 / 105 °C」）；
        # 「-」在条文里多是破折号或项目符号（「Io= 180A - 91% ↑」），不并
        if last_single and link in ("", "~", "–", "to", "/") and (link or re.match(r"[~–]", qty)):
            found[-1] = _compact(f"{found[-1]} {link} {qty}")
            seen.add(qty)
            prev_end = end
            last_single = link == "/" and not trail  # 「3min / 10min / 30min」整串一起
            continue
        last_single = False
        lead = _lead_in(between)
        # 括号没合上、数后紧跟右括号的，把右括号带上：「(400W ↑)」
        unclosed = lead.count("(") + lead.count("（") > lead.count(")") + lead.count("）")
        if unclosed or (not lead and between.rstrip().endswith(("(", "（"))):
            close = re.match(r"\s?[)）]", source[end:])
            if close:
                qty += close.group(0).strip()
                end += close.end()
                if not lead:
                    qty = between.rstrip()[-1] + qty
        item = f"{lead}{qty}" if lead.endswith(("(", "（")) else _compact(f"{lead} {qty}")
        prev_end = end
        # 同一个数再次出现而前面没新的字（「15 years / 300,000 km (15 years / 300,000 km)」）不重复列；带了不同引导词的照列
        if item in found or (qty in seen and not re.search(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]", lead)):
            continue
        found.append(item)
        seen.add(qty)
        last_single = not re.search(r"\d\s?(?:~|–|to)\s?\d", qty) and not trail
    # 并成范围后可能与后面重复出现的同一句相同，最后再去一次重
    return "；".join(dict.fromkeys(found))


def conditions(text: str) -> str:
    """原文括号里带数或带条件词的话，原样列出。不解释、不改写。"""
    found: list[str] = []
    for match in _PAREN.finditer(text or ""):
        inner = _compact(match.group(1))
        has_qty = bool(_QUANTITY.search(inner))
        if not has_qty and not re.search(
            r"\b(?:at|under|during|when|condition|conditions|temp|temperature|load|speed|mode|level|confidence|based on|e\.g\.)\b|[条件工况温度负载转速时下]",
            inner,
            re.I,
        ):
            continue
        # 括号里只有数和单位（如「15 years / 300,000 km」）是数值不是条件，已在数值列
        rest = _QUANTITY.sub("", inner)
        if has_qty and not re.search(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]{2,}", rest):
            continue
        if inner not in found:
            found.append(inner)
    return "；".join(found)


# 表头词 → 栏目角色。只按表头认栏，不认格里的内容（支持英、中、韩、日、德表头）。
_COL_KEY = re.compile(
    r"^(?:(?:major|sub)?classification|catego?ry|items?|parameters?|name|test(?:items?)?|analysis|regions?|"
    r"项目|分类|参数|名称|试验项目|分析项|区域|"
    r"구분|항목|분류|시험항목|점검항목|검증항목|파라미터|명칭|"
    r"項目|区分|分類|試験項目|"
    r"kategorie|parameter|prüfpunkt)$"
)
_COL_VALUE = re.compile(
    r"^(?:requirements?|(?:request)?specifications?|spec|targets?|values?|contents?|standard|criteria|(?:verification)?results?|status|details?|(?:warranty)?period|designchecklist|"
    r"要求|规格|目标|指标|标准|内容|结果|状态|"
    r"요구사항|요구사양|규격|사양|기준|목표|내용|결과|판정|"
    r"要求仕様|基準|仕様|目標|結果|"
    r"anforderung|anforderungen|spezifikation|zielwert|sollwert)$"
)
_COL_UNIT = re.compile(r"^(?:units?|单位|단위|単位|einheit)$")
_COL_REMARK = re.compile(
    r"^(?:remarks?|notes?|notestandard|comments?|conditions?|"
    r"备注|说明|条件|"
    r"비고|조건|시험조건|참고|"
    r"備考|条件|試験条件|"
    r"bemerkung|hinweis|bedingung|prüfbedingung)$"
)


def _col_role(header: str) -> str:
    key = re.sub(r"[\s_\-./]+", "", header or "").lower()
    if _COL_VALUE.match(key):
        return "value"
    if _COL_KEY.match(key):
        return "key"
    if _COL_UNIT.match(key):
        return "unit"
    if _COL_REMARK.match(key):
        return "remark"
    return ""


@dataclass(frozen=True)
class TableEntry:
    item: str  # 表里的栏目名（Category / Item 几格拼起来）
    text: str  # 该行原文：表头：格 | 表头：格
    value: str  # Requirement / Specification 格原文（带单位）
    remark: str  # Remark / Note 格原文
    row: int = -1  # 在表里的行号（含表头），截图定位用
    note: str = ""  # 读不出的格不写入原文，原因写在这里


def _clean_cell(cell: str) -> str:
    return _STAMP.sub("", cell or "").strip()


def _subheader_labels(roles: list[str], labels: list[str], row: list[str]) -> list[str] | None:
    """表头下一行如果只在合并列下写了 HMC、Supplier 这种短列名，这一行是列表头，不是数据。"""
    width = len(labels)
    row = list(row) + [""] * (width - len(row))
    filled: list[int] = []
    for col, cell in enumerate(row[:width]):
        text = _clean_cell(cell)
        if not text:
            continue
        if roles[col] in {"key", "value"} or len(text) > 20 or len(text.split()) > 2:
            return None
        filled.append(col)
    if len(filled) < 2:
        return None
    renamed = list(labels)
    for col in filled:
        renamed[col] = _clean_cell(row[col])
    return renamed


def _header_roles(headers: list[str]) -> list[str]:
    """每列的角色。横向合并的表头（「Classification」后跟两个空格）后面的空列沿用前一个表头的角色；
    没有项目栏而有两组要求栏时（「Contents | Specification」），最左那组当项目栏。"""
    roles: list[str] = []
    groups: list[int] = []
    group = -1
    last = ""
    for cell in headers:
        if cell:
            group += 1
            last = _col_role(cell)
        roles.append(last if group >= 0 else "")
        groups.append(group)
    # 两组以上要求栏（「Contents | Specification」「Category | Contents | Target」）：最右那组才是值，左边的都是项目
    value_groups = sorted({g for g, r in zip(groups, roles) if r == "value"})
    if len(value_groups) >= 2:
        roles = ["key" if r == "value" and g != value_groups[-1] else r for g, r in zip(groups, roles)]
    return roles


def _find_header(grid: Grid) -> tuple[int | None, list[str]]:
    for at, row in enumerate(grid[:2]):
        if sum(1 for cell in row if cell) < 2:
            continue
        roles = _header_roles(list(row))
        if "key" in roles and "value" in roles:
            return at, roles
    # 首行是横跨全表的合并标题格（如「Mechanical part - Material」）、下方的行左列是短栏目名、末列是要求正文
    if (
        len(grid) >= 4
        and 2 <= len(grid[0]) <= 3
        and grid[0][0]
        and len(grid[0][0]) <= 60
        and all(not c for c in grid[0][1:])
    ):
        body = grid[1:]
        long_right = sum(1 for r in body if len(r[-1] or "") >= 20)
        short_left = all(len(c or "") <= 50 for r in body for c in r[:-1] if c)
        if long_right * 2 >= len(body) and short_left:
            return 0, ["key"] * (len(grid[0]) - 1) + ["value"]
    return None, []


def table_entries(grid: Grid) -> list[TableEntry]:
    """有「项目」和「要求」两类栏的表，每行出一条：项目格是 key，要求格是 value。认不出表头的表返回空。

    纵向合并的格（Category 跨几行）在后续行为空，沿用上一行。只读格子，不解释。
    """
    header_at, roles = _find_header(grid)
    if header_at is None:
        return []
    headers = grid[header_at]
    banner = header_at == 0 and bool(headers[0]) and all(not c for c in headers[1:])
    labels: list[str] = []
    for cell in headers:  # 合并表头下的空列用前一个表头名标注；整行合并的总标题不重复贴到每一列
        labels.append("" if banner else (_clean_cell(cell) or (labels[-1] if labels else "")))
    body_at = header_at + 1
    if body_at < len(grid):
        renamed = _subheader_labels(roles, labels, grid[body_at])
        if renamed:
            labels = renamed
            body_at += 1
    entries: list[TableEntry] = []
    carried = [""] * len(headers)
    for row_at, row in enumerate(grid[body_at:], start=body_at):
        row = [_clean_cell(cell) for cell in list(row) + [""] * (len(headers) - len(row))]
        if not any(row):
            continue
        keys: list[str] = []
        values: list[str] = []
        units: list[str] = []
        remarks: list[str] = []
        parts: list[str] = []
        sides: list[str] = []
        mark_unread = False
        reset = False  # 上一级项目格换了内容，右边更细一级的沿用值作废
        for col, cell in enumerate(row[: len(headers)]):
            role = roles[col]
            if role == "key":
                if cell:
                    carried[col] = cell
                    reset = True
                elif reset:
                    carried[col] = ""
                cell = carried[col]
            if not cell:
                continue
            # 圆圈落在「Role sharing」这种没写明 HMC / Supplier 的列上时，不把「角色分担：○」写进原文
            if _MARK_CELL.fullmatch(cell) and not _SIDE_NAME.search(labels[col] or ""):
                mark_unread = True
                continue
            parts.append(f"{labels[col]}：{cell}" if labels[col] else cell)
            if role == "key" and cell not in keys:
                keys.append(cell)
            elif role == "value":
                values.append(cell)
            elif role == "unit":
                units.append(cell)
            elif role == "remark":
                remarks.append(cell)
            elif labels[col] and _SIDE_NAME.search(labels[col]) and _MARK_CELL.fullmatch(cell):
                sides.append(f"{labels[col]}：{cell}")
            elif labels[col]:
                # 认不出角色的栏（「Settings for evaluation」「Document name」）带表头放进条件列，不丢
                remarks.append(f"{labels[col]}：{cell}")
        if not values and not remarks and not any(cell for col, cell in enumerate(row[: len(headers)]) if roles[col] == "key"):
            continue  # 这一行自己什么都没写（全靠沿用）才跳过；有项目没要求的照列，值留空，不替它填
        value = " ".join(values)
        if units and value and not re.search(r"[A-Za-z%℃°Ω]", value):
            value = f"{value} {' '.join(units)}"  # 数值格里没带单位时，补上单位栏的原文
        item = " / ".join(keys)
        if not value and not remarks and len(item) > 60:
            item = ""  # 项目格里是一整句、又没有要求格的，是表尾的说明行，不当栏目名
        # 摘录只留「项目：要求」和责任方，不再把 Item／Details 标签中英各抄一遍
        head = f"{item}：{value}" if item and value else (value or item)
        text = "；".join(bit for bit in (head, *sides) if bit)
        entries.append(TableEntry(item, text, value, " ".join(remarks), row_at, NOTE_MARK_COL if mark_unread else ""))
    return entries


def grid_text(grid: Grid) -> str:
    return "\n".join(" | ".join(cell for cell in row) for row in grid)


def strip_table_lines(body: str, grids: list[Grid]) -> str:
    """把已按格线读出的表格的字从页面文字里去掉，剩下的才按条款拆。

    文字层的分行和格子不一致（「Categor」「y」），所以按「这一行是不是表格文字的一段」认；
    太短的行（「-」「5」）只有紧挨着被认掉的行时才一起去掉。
    """
    # 文字层和格子的断词位置不一样（「Categor」+「y」对「Catego ry」），两边都去掉空白再比
    table_text = re.sub(r"\s+", "", " ".join(grid_text(grid).replace("|", " ") for grid in grids))
    lines = body.splitlines()
    hits = []
    for line in lines:
        key = re.sub(r"\s+", "", line)
        strong = len(re.findall(r"[A-Za-z0-9\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]", key)) >= 4
        hits.append((bool(key) and key in table_text, strong))
    # 连续命中的几行算一段：一段里有一行够长，或几行加起来够 4 个字母数字（「Vin=」「110」「~310V」），整段去掉
    kept: list[str] = []
    pos = 0
    while pos < len(lines):
        if not hits[pos][0]:
            kept.append(lines[pos])
            pos += 1
            continue
        end = pos
        while end + 1 < len(lines) and hits[end + 1][0]:
            end += 1
        run_alnum = sum(len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", lines[i])) for i in range(pos, end + 1))
        if not (any(hits[i][1] for i in range(pos, end + 1)) or run_alnum >= 4):
            kept.extend(lines[pos : end + 1])
        pos = end + 1
    return "\n".join(kept)


_CONTINUATION_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
)


def _word_split_continuation(flat: str) -> bool:
    """按词拆开的「as」「the」是上一句的续词，不是识读碎片。"""
    return (flat or "").strip().lower() in _CONTINUATION_WORDS


def _scrap_line(flat: str) -> bool:
    """识读剩下来的碎片或粘上的表头，不能并进上一条要求。"""
    text = (flat or "").strip()
    if _word_split_continuation(text):
        return False
    if re.match(r"^(?:Table\s*\d\b|Load\s*\(|Speed rate\b|Step\s*:|\(?\s*±)", text, re.I):
        return True
    if re.fullmatch(r"[A-Za-z]{1,3}", text):
        return True
    digits = len(re.findall(r"\d", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    if digits >= 8 and digits > letters:
        return True
    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 3 or any(len(word) > 4 for word in words):
        return False
    short = sum(1 for word in words if len(word) <= 2)
    return short * 2 >= len(words)


def break_before_marks(text: str) -> str:
    """同一段里的「1)」「2. 标题」「①」各起一行，后面才能拆成各自的条目。"""
    text = re.sub(r"[ \t]+(?=\d{1,2}\)\s)", "\n", text or "")
    text = re.sub(r"[ \t]+(?=\d{1,2}\.\s+[A-Z])", "\n", text)
    text = re.sub(r"[ \t]*(?=[①②③④⑤⑥⑦⑧⑨⑩])", "\n", text)
    return text


def _cell_holds_clauses(cell: str) -> bool:
    """一格里塞进了两条以上的编号要求，或一条很长的编号要求。这种格子不留在表里。"""
    marks = re.findall(r"(?:^|\s)(?:\d{1,2}[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩])", cell or "")
    return len(marks) >= 2 or (len(marks) >= 1 and len(cell) >= 60)


def _without_clauses(grid: tuple[tuple[str, ...], ...] | tuple) -> tuple[tuple[tuple[str, ...], ...], list[str]]:
    """把表格格子里的编号要求拆成条款。表上只留下负荷、转速这类短格。"""
    blobs: list[str] = []
    kept: list[tuple[str, ...]] = []
    for row in grid:
        cells: list[str] = []
        for cell in row:
            if _cell_holds_clauses(cell):
                blobs.append(cell)
                cells.append("")
            else:
                cells.append(cell)
        if any(cell.strip() for cell in cells):
            kept.append(tuple(cells))
    clauses: list[str] = []
    for blob in blobs:
        for _section, _mark, text in split_clauses(blob, [], ""):
            if text.strip():
                clauses.append(text)
    return tuple(kept), clauses


def split_document(doc: SourceDoc) -> tuple[list[list[object]], list[list[object]]]:
    """按条款拆条。返回 (条目行, 整表行)，序号由调用方补。"""
    boilerplate = boilerplate_lines(doc.pages)
    heads, toc_pages = toc_headings(doc.pages)
    obj = object_of(doc)
    total = len(doc.pages)
    drop_hangul = hangul_is_minor(doc.pages)
    rows: list[list[object]] = []
    tables: list[list[object]] = []

    def plain(index: int, inner: str, section: str, mark: str, text: str, qty: str, cond: str, note: str, item: str = "", shot=None) -> list[object]:
        # 末尾多一格放截图位置（Shot），不进「条目对照」工作表，出需求清单时用
        return [None, obj, doc.name, index, inner, section, mark, item, text, qty, cond, STATUS_PENDING, "", "", "", note, shot]

    def located(index: int, text: str):
        """正文条目在页面上的位置；算不出就不截。"""
        lines = doc.lines.get(index)
        if not lines:
            return None
        from electrical_krow.arch_shots import Shot, clause_box

        box = clause_box(lines, text)
        return Shot(index, box) if box else None

    def row(index: int, inner: str, section: str, mark: str, text: str, note: str) -> list[object]:
        return plain(index, inner, section, mark, text, quantities(text), conditions(text), note, shot=located(index, text))

    def _append_chart_caption(index: int, inner: str, section: str, figure_text: str) -> None:
        """曲线标题和说明按行摘录。纯数字和表头不摘。"""
        for line in (figure_text or "").splitlines():
            line = line.strip()
            if not line or " | " in line:
                continue
            if re.fullmatch(r"[\d\s.,/%~+-]+", line):
                continue
            if len(re.findall(r"[A-Za-z]", line)) < 3:
                continue
            rows.append(
                plain(
                    index,
                    inner,
                    section,
                    "",
                    line,
                    "",
                    "",
                    "曲线标题和说明按版面摘出",
                )
            )

    def emit_tables(index: int, inner: str, section: str, grids: list[Grid]) -> None:
        """按格线读出的表：认得出「项目／要求」表头的每行一条，key 进「项目」、要求格进「数值与单位」；
        认不出表头的整表作为一条：截图是整张表，原文摘录写在同一格，按表行换行。
        图片里 OCR 识读出的表同样处理，但备注标明是 OCR，字符要对照原图核对。
        图表（坐标图、曲线、框图）作为一条独立 REQ 并入「需求清单」（附整图截图与图中文字），不拆条、不取数。"""
        from electrical_krow.arch_shots import Shot

        for figure in doc.figures.get(index, []):
            from electrical_krow.arch_figures import _axis_scale_grid, _chart_data_table, order_clauses, transcript_kind

            figure_text = order_clauses(getattr(figure, "transcript", "") or "")
            kind = transcript_kind(figure_text)
            # 横轴刻度和纯数字数据表只留在截图里，不写成格子、也不翻译。
            figure_grid = getattr(figure, "grid", ())
            if _axis_scale_grid(figure_grid) or (figure_grid and _chart_data_table([list(row) for row in figure_grid])):
                figure_grid = ()
            drawn = _without_clauses(figure_grid)
            clauses = drawn[1]
            drawn = drawn[0]
            shot = Shot(index, None, figure.png)

            def _append_original_block(text: str, note: str, block_shot) -> None:
                """同一段编号正文收成一条，换行保留原文的行。"""
                text = (text or "").strip()
                if not text:
                    return
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        text,
                        quantities(text),
                        conditions(text),
                        note,
                        shot=block_shot,
                    )
                )

            for clause in clauses:
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        clause,
                        quantities(clause),
                        conditions(clause),
                        "按编号摘出的要求",
                        shot=shot,
                    )
                )
                shot = None
            if len(drawn) >= 2 and max(len(row) for row in drawn) >= 2:
                text = "\n".join(" | ".join(cell for cell in row) for row in drawn)
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        "本页线框表格：\n" + text,
                        "",
                        "",
                        "按图中格线画出的表格，截图保留原样",
                        shot=shot,
                    )
                )
                if kind != "prose":
                    _append_chart_caption(index, inner, section, figure_text)
                if kind == "prose":
                    _append_original_block(figure_text, "格线表以外的正文按原文换行摘出", shot)
            elif kind == "table":
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        "本页线框表格：\n" + figure_text,
                        "",
                        "",
                        "矢量线框里的表格按版面摘出，截图保留原样",
                        shot=shot,
                    )
                )
            elif kind == "prose":
                _append_original_block(figure_text, "矢量线框里的文字按原文换行摘出，截图保留原样", shot)
            else:
                from electrical_krow.arch_figures import chart_hint

                hint = chart_hint(figure.labels)
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        f"本页图表（{figure.kind}）{hint}",
                        "",
                        "",
                        "图表（整图截图，供对照原文；不拆条、不取数）",
                        shot=shot,
                    )
                )
                _append_chart_caption(index, inner, section, figure_text)
        ocr_grids = doc.image_tables.get(index, [])
        row_boxes = doc.table_rows.get(index, [])
        parsed = [table_entries(g) for g in grids]
        spans: list[tuple[float, float, float, float] | None] = []
        for g_at in range(len(grids)):
            valid = [b for b in (row_boxes[g_at] if g_at < len(row_boxes) else []) if b is not None]
            spans.append((min(b[0] for b in valid), min(b[1] for b in valid), max(b[2] for b in valid), max(b[3] for b in valid)) if valid else None)
        for grid_at, grid in enumerate([*grids, *ocr_grids]):
            ocr = grid_at >= len(grids)
            span = spans[grid_at] if not ocr and grid_at < len(spans) else None
            if _inside_chart_shot(doc, index, span):
                continue
            boxes = row_boxes[grid_at] if not ocr and grid_at < len(row_boxes) else []
            how = NOTE_OCR if ocr else "按格线读出的表格"
            entries = table_entries(grid) if ocr else parsed[grid_at]
            if not entries:
                tbox = spans[grid_at] if not ocr and grid_at < len(spans) else None
                if tbox and any(
                    other_at != grid_at
                    and parsed[other_at]
                    and spans[other_at] is not None
                    and tbox[0] >= spans[other_at][0] - 4
                    and tbox[2] <= spans[other_at][2] + 4
                    and tbox[1] >= spans[other_at][1] - 4
                    and tbox[3] <= spans[other_at][3] + 4
                    for other_at in range(len(grids))
                ):
                    continue  # 嵌在已拆成行的外层表格单元格里的小附表，已在所在行内展示与截图，不再重复成条
                tables.append([None, obj, doc.name, index, section, ATTACH_OCR if ocr else ATTACH_TABLE, grid_text(grid), f"{how}，表头认不出项目／要求栏，未拆成单条"])
                shape = f"{len(grid)} 行 × {len(grid[0])} 列"
                what = "本页图片表格" if ocr else "本页表格"
                rows.append(
                    plain(
                        index,
                        inner,
                        section,
                        "",
                        f"{what}（{shape}）：\n{grid_text(grid)}",
                        "",
                        "",
                        _join_notes(NOTE_OCR if ocr else "", "整表保留（表头认不出项目／要求栏，未拆成单条）"),
                        shot=Shot(index, tbox) if tbox else None,
                    )
                )
                continue
            for entry in entries:
                box = boxes[entry.row] if 0 <= entry.row < len(boxes) else None
                note = _join_notes(NOTE_OCR if ocr else "", "表格行", entry.note)
                entry_text, entry_val = entry.text, entry.value
                if box and not ocr:
                    inner_split = [
                        (other_at, spans[other_at])
                        for other_at in range(len(grids))
                        if other_at != grid_at
                        and parsed[other_at]
                        and spans[other_at] is not None
                        and spans[other_at][0] >= box[0] - 4
                        and spans[other_at][2] <= box[2] + 4
                        and spans[other_at][1] >= box[1] - 4
                        and spans[other_at][3] <= box[3] + 4
                    ]
                    if inner_split:
                        inner_bottom = max(tb[3] for _, tb in inner_split if tb is not None)
                        if box[3] - inner_bottom >= 24.0:
                            box = (box[0], inner_bottom, box[2], box[3])
                            inner_words = [
                                w
                                for other_at, _ in inner_split
                                for r in grids[other_at][1:]
                                for cell in r
                                for w in (cell or "").split()
                                if len(w) >= 8 and w in entry_val
                            ]
                            if inner_words:
                                tail = entry_val[max(entry_val.find(w) + len(w) for w in inner_words) :].strip()
                                if tail:
                                    entry_val = tail
                                    entry_text = f"{entry.item}：{tail}" if entry.item else tail
                rows.append(plain(index, inner, section, "", entry_text, entry_val, entry.remark, note, entry.item, shot=Shot(index, box) if box else None))

    carried = ""  # 上一页末尾所在的章节；本页没有标题时沿用
    skipped = {item.page for item in doc.unread if item.page}
    for index, raw in doc.pages:
        if index in skipped:
            continue
        inner = inner_page(raw, total)
        body = page_body(raw, boilerplate, inner, drop_hangul=drop_hangul)
        grids = doc.tables.get(index, [])
        any_table = bool(grids or doc.image_tables.get(index) or doc.figures.get(index))
        if index == 1 and toc_pages:
            # 有目录的整本文件，第一页是封面。单独的附表没有封面。
            section = SECTION_COVER
        elif index in toc_pages:
            section = SECTION_TOC
        else:
            section = ""
        if section in {SECTION_COVER, SECTION_TOC}:
            text, note = _excerpt(body, keep_short=True)
            rows.append(plain(index, inner, section, "", text, "", "", note))
            continue
        figures = doc.figures.get(index, [])
        body = stitch_broken_tokens(body)
        if grids:
            body = strip_table_lines(body, grids)
        body = drop_axis_chrome(body)
        if figures:
            from electrical_krow.arch_figures import transcript_kind

            chunks: list[Grid] = []
            for figure in figures:
                transcript = getattr(figure, "transcript", "")
                if transcript_kind(transcript) in {"table", "prose"}:
                    chunks.append([[line.replace(" | ", " ")] for line in transcript.splitlines() if line.strip()])
                elif figure.labels:
                    chunks.append([[figure.labels]])
            if chunks:
                body = strip_table_lines(body, chunks)
        found = page_headings(body, heads)
        if not found and not carried and toc_pages and index > max(toc_pages) and heads:
            carried = f"{heads[0][0]} {heads[0][1]}"
        section = found[0] if found else carried
        carry_note = "" if found or not carried else "章节沿用上一页"
        if is_table_page(body):
            tables.append([None, obj, doc.name, index, section, ATTACH_PAGE, body, "整页保留，不拆成单条，不判断是否满足"])
            rows.append(plain(index, inner, section, "", f"本页为数值表：\n{body}", "", "", "数值页（整页保留，不拆成单条）", shot=located(index, body)))
            emit_tables(index, inner, section, grids)
            carried = found[-1] if found else carried
            continue
        if len(_compact(body)) < _MIN_TEXT:
            if _compact(body) or not any_table:
                # 表格之外还有几个字，或整页本来就没什么字：照旧留一条；表格占满整页的不另起空条
                text, note = _excerpt(body, keep_short=any_table)
                rows.append(plain(index, inner, section, "", text, "", "", _join_notes(note, carry_note)))
            emit_tables(index, inner, section, grids)
            carried = found[-1] if found else carried
            continue
        clauses = split_clauses(body, heads, carried)
        if clauses:
            carried = clauses[-1][0] or carried
        elif found:
            carried = found[-1]
        if any_table and (
            not clauses
            or (len(clauses) == 1 and re.fullmatch(r"[-–—_\s()（）]*(?:continued|cont'?d)[.:\s()（）]*", clauses[0][2], re.I))
        ):
            emit_tables(index, inner, carried or section, grids)
            continue
        if len(clauses) <= 1:
            # 整页没有条款标记：整页一条，原文保留换行
            text, note = _excerpt(body, keep_short=True)
            rows.append(row(index, inner, section, "", text, _join_notes(note or "本页无条款标记，整页一条", carry_note)))
            emit_tables(index, inner, section, grids)
            continue
        for sec, mark, text in clauses:
            sec = sec or section
            from electrical_krow.arch_translate import strip_column_headers

            text = strip_column_headers(text)
            if not _compact(text) or re.fullmatch(r"\d+[).）]", _compact(text)):
                continue
            if is_table_block(text):
                # 坐标轴刻度、反复出现的表头：整块作为一条保留，不取数
                tables.append([None, obj, doc.name, index, sec, ATTACH_BLOCK, text, "条内表格块，整块保留，不拆成单条，不判断是否满足"])
                rows.append(plain(index, inner, sec, mark, f"本页表格块：\n{text}", "", "", "表格块（整块保留，不拆成单条）", shot=located(index, text)))
                continue
            note = ""
            if len(text) > _EXCERPT_CAP:
                text, note = text[:_EXCERPT_CAP] + "……（其余见原 PDF）", f"摘录在 {_EXCERPT_CAP} 字处截断"
            rows.append(row(index, inner, sec, mark, text, _join_notes(note, carry_note)))
        emit_tables(index, inner, carried or section, grids)
    return rows, tables


def _join_notes(*notes: str) -> str:
    return "；".join(note for note in notes if note)


def _opinion_for(row: list[object], text_col: int, note_col: int) -> tuple[str, str]:
    """对上标准、图号、接口或同文件冲突才写入。对不上的那句「尚无对应口径」不占每一行。"""
    from electrical_krow.arch_opinion import assign_opinion

    opinion, reason = assign_opinion(str(row[text_col] or ""), str(row[note_col] or ""))
    if not opinion or "尚无对应口径" in opinion:
        return "", str(row[note_col] or "")
    note = _join_notes(str(row[note_col] or ""), f"【初步意见理由】{reason}")
    return opinion, note


_LINE_POINTS = 14  # 宋体 10 号一行约 14 磅
_MAX_ROW_HEIGHT = 409  # Excel 行高上限


def _display_width(text: str) -> float:
    """按 Excel 列宽单位估字宽：汉字、全角标点算 2，其余算 1。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _lines_needed(text: str, width: float) -> int:
    """折行后要占几行。列宽单位和字符数大致对应，留 1 个单位给格边距。"""
    usable = max(1.0, width - 1)
    total = 0
    for part in str(text).split("\n"):
        total += max(1, -(-int(_display_width(part)) // int(usable)))
    return total


def _fitted_width(sheet, col: int, floor: int, cap: int = 255, rows=None) -> int:
    """列宽按指定行里每一行字的宽度。规格表不要被旁边的长段落撑开。"""
    needed = floor
    chosen = rows if rows is not None else range(2, sheet.max_row + 1)
    for row in chosen:
        value = sheet.cell(row, col).value
        if value is None or value == "":
            continue
        for line in str(value).split("\n"):
            line = line.strip()
            if not line:
                continue
            span = int(_display_width(line))
            needed = max(needed, span + max(6, span // 10))
    return min(cap, needed)


def _fit_row_height(cells, widths: dict[str, int], minimum: int) -> int:
    """行高按本行最长的那格算，不让折行的字被截掉。"""
    lines = 1
    for cell in cells:
        if cell.value is None or cell.value == "":
            continue
        width = widths.get(cell.column_letter, 10)
        lines = max(lines, _lines_needed(str(cell.value), width))
    return min(_MAX_ROW_HEIGHT, max(minimum, lines * _LINE_POINTS + 4))


def _style_sheet(
    sheet,
    header_row: int,
    widths: dict[str, int],
    *,
    body_height: int = 48,
    fit_width: bool = True,
    zoom: int = 110,
    tab: str = "2878B9",
) -> None:
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width
    for cell in sheet[header_row]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = _THIN
    sheet.row_dimensions[header_row].height = 30
    last = sheet.max_column
    for cells in sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row, max_col=last):
        band = _BAND_FILL if cells[0].row % 2 == 0 else None
        for cell in cells:
            cell.font = _ID_FONT if cell.column == 1 and cell.value not in (None, "") else _BODY_FONT
            cell.alignment = _WRAP
            cell.border = _THIN
            if band is not None:
                cell.fill = band
        sheet.row_dimensions[cells[0].row].height = _fit_row_height(cells, widths, body_height)
    sheet.freeze_panes = f"A{header_row + 1}"
    if sheet.max_row > header_row:
        from openpyxl.utils import get_column_letter

        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(last)}{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = zoom
    sheet.sheet_view.view = "normal"
    sheet.sheet_properties.tabColor = tab
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.pageOrder = "downThenOver"
    sheet.page_setup.horizontalCentered = True
    if fit_width:
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
    else:
        sheet.page_setup.fitToWidth = 0
        sheet.page_setup.fitToHeight = 0
        sheet.page_setup.scale = 100
        sheet.sheet_properties.pageSetUpPr.fitToPage = False
    sheet.page_margins.left = 0.5
    sheet.page_margins.right = 0.5
    sheet.page_margins.top = 0.55
    sheet.page_margins.bottom = 0.5
    sheet.page_margins.header = 0.25
    sheet.page_margins.footer = 0.25
    sheet.print_title_rows = f"{header_row}:{header_row}"
    sheet.oddHeader.left.text = sheet.title
    sheet.oddHeader.left.font = "微软雅黑"
    sheet.oddHeader.left.size = 9
    sheet.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    sheet.oddFooter.center.font = "微软雅黑"
    sheet.oddFooter.center.size = 9


_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def _excel_sheet_titles(names: list[str]) -> dict[str, str]:
    """每个需求文件一张表，表名用文件名。Excel 表名最长 31 字，同名再加序号。"""
    used = {SHEET_NOTE.casefold()}
    titles: dict[str, str] = {}
    for index, name in enumerate(names, start=1):
        stem = _SHEET_BAD.sub("_", Path(name).stem).strip("._ ") or f"需求{index}"
        base = stem[:31]
        title = base
        number = 2
        while title.casefold() in used:
            suffix = f"-{number}"
            title = f"{base[: 31 - len(suffix)]}{suffix}"
            number += 1
        used.add(title.casefold())
        titles[name] = title
    return titles


def _mark_suspected_duplicates(docs: list[SourceDoc], rows: list[list[object]]) -> None:
    """摘录相同的只在备注里互相标明，不合并、不删除。跨文件写明另一边的文件、页码和章节。"""
    sec_col, file_col, seq_col = COLUMNS.index("章节"), COLUMNS.index("文件"), COLUMNS.index("序号")
    text_col, page_col, note_col = COLUMNS.index("原文摘录"), COLUMNS.index("PDF页码"), COLUMNS.index("备注")
    doc_has_sections = {
        doc.name: any(str(r[sec_col] or "") not in {"", SECTION_COVER, SECTION_TOC} for r in rows if r[file_col] == doc.name)
        for doc in docs
    }
    doc_has_lines = {doc.name: bool(doc.lines) for doc in docs}
    buckets: dict[str, list[list[object]]] = {}
    for row in rows:
        if not _is_requirement_row(
            row,
            has_sections=doc_has_sections.get(str(row[file_col]), False),
            has_lines=doc_has_lines.get(str(row[file_col]), False),
        ):
            continue
        key = _compact(str(row[text_col] or ""))
        if len(key) < 24:
            continue
        buckets.setdefault(key, []).append(row)
    for group in buckets.values():
        if len(group) < 2:
            continue
        for row in group:
            hints = []
            for other in group:
                if other is row:
                    continue
                hints.append(f"{other[file_col]} 第 {other[page_col]} 页 {other[sec_col] or ''}".strip())
            row[note_col] = _join_notes(str(row[note_col] or ""), "疑似重复：" + "；".join(hints[:3]))


def _quantity_on_page(qty: str, excerpt: str, page_text: str) -> tuple[str, str]:
    """数值里的数字必须出现在当页或摘录里。对不上的整格留空，不另写一个数。"""
    text = (qty or "").strip()
    if not text:
        return "", ""
    hay = re.sub(r"\s+", "", f"{excerpt}\n{page_text}")
    missing = [number for number in re.findall(r"\d+(?:\.\d+)?", text) if not re.search(rf"(?<!\d){re.escape(number)}(?!\d)", hay)]
    if missing:
        return "", "待人工确认：数值不在当页原文，已留空"
    return text, ""


def _row_confidence(excerpt: str, page_text: str, *, review: bool) -> str:
    """摘录里的词要能在当页找到。对不上、或已经标明要人工看的，不升成已确认。"""
    if review:
        return "待人工确认"
    words = re.findall(r"[A-Za-z]{4,}|[\u4e00-\u9fff]{2,}", excerpt or "")
    if not words:
        return "中"
    page = (page_text or "").lower()
    hit = sum(1 for word in words if word.lower() in page)
    if hit * 5 >= len(words) * 4:
        return "高"
    return "待人工确认"


_NOTE_FOCUS = PatternFill("solid", fgColor="FFF1D6")
_NOTE_PASS = PatternFill("solid", fgColor="E5F4EA")
_NOTE_BAD = PatternFill("solid", fgColor="FCE4E4")
_NOTE_TBD = PatternFill("solid", fgColor="FFF1D6")
_NOTE_KIND = {
    "中英数值冲突": "中英数值不一致",
    "中英语义冲突": "中英语义不一致",
    "内部逻辑冲突": "内部逻辑冲突",
    "跨处参数冲突": "取值不一致",
    "未定项": "待定项",
    "可读性": "未能读清",
}
_NOTE_BAD_LABELS = {"中英数值不一致", "中英语义不一致", "内部逻辑冲突", "取值不一致"}


def _quality_headline(quality) -> str:
    bits: list[str] = []
    if quality.bilingual_conflicts:
        bits.append(f"中英数值不一致 {quality.bilingual_conflicts}")
    if quality.logic_conflicts:
        bits.append(f"内部逻辑冲突 {quality.logic_conflicts}")
    if quality.param_conflicts:
        bits.append(f"取值不一致 {quality.param_conflicts}")
    if quality.tbd_count:
        bits.append(f"待定项 {quality.tbd_count}")
    if not bits:
        return "通过。未发现中英冲突、内部算式冲突或同参数前后取值不一致。"
    return "需注意：" + " · ".join(bits) + "。下面每一条对应需求清单里标红的一行。"


def _issue_place(issue, req_map: dict[int, tuple[int, str]] | None, sheet_names: dict[str, str]) -> str:
    if req_map and issue.row_seq in req_map:
        xl_row, req_id = req_map[issue.row_seq]
        sheet = sheet_names.get(issue.file, "") if len(sheet_names) > 1 else ""
        where = f"「{sheet}」" if sheet else "需求清单"
        page = f"第 {issue.page} 页 · " if issue.page else ""
        return f"{page}{where}第 {xl_row} 行（{req_id}）"
    if issue.page:
        return f"{issue.file} 第 {issue.page} 页"
    return issue.file


def _fill_note_sheet(note, docs, unreadable, quality, req_map, sheet_titles, param_notes, used_model) -> None:
    """确认说明先写结论和一条一行的问题，读表方法收在最后。"""
    note.append(["项目", "位置", "内容"])
    note.append(["结论", "先看", _quality_headline(quality)])
    if len(docs) == 1:
        note.append(["来源", f"{len(docs[0].pages)} 页", docs[0].name])
    else:
        listed = "；".join(
            f"「{sheet_titles.get(doc.name, doc.name)}」{doc.name}（{len(doc.pages)} 页）" for doc in docs
        )
        note.append(["来源", f"{len(docs)} 份", f"每个需求文件单独一张表：{listed}"])
    for item in unreadable:
        if item.page:
            place = f"第 {item.page} 页"
            text = f"{item.name}：{item.reason}未补写内容。"
        else:
            place = f"{item.pages} 页" if item.pages else ""
            text = f"{item.name}" + (f"（{item.pages} 页）" if item.pages else "") + f"：{item.reason}未补写内容。"
        note.append(["未能读取", place, text])
    unread_keys = {(item.name, item.page) for item in unreadable}
    issues = [
        issue for issue in quality.issues
        if not (issue.kind == "可读性" and (issue.file, issue.page) in unread_keys)
    ]
    shown = issues[:40]
    for issue in shown:
        label = _NOTE_KIND.get(issue.kind, issue.kind)
        note.append([label, _issue_place(issue, req_map, sheet_titles), issue.text])
    left = len(issues) - len(shown)
    if left > 0:
        note.append(["其余", f"{left} 条", "其余问题在需求清单里仍整行标红，备注可筛「内容质检」。"])
    note.append(["读表", "", "一行一条。外文和中文写在同一格，中间用 / 隔开。类别以「建议：」开头。意见只在对上标准、图号、接口或同文件冲突时填写。截不到图的条目仍留下，备注写未能截图。"])
    note.append(["状态", "", "Currently status 默认 To be confirmed（待确认）。优先级、提出人、客户反馈和人工修改留给人填。"])
    note.append(["图表", "", "曲线和旁边的数据表收成一张整图，不从格子中间裁开。"])
    if param_notes:
        note.append(["参数", "", "本次说明：" + "；".join(param_notes)])
    elif used_model:
        note.append(["参数", "", "本次已用模型给参数起名，并生成外文条款的中文对照。"])
    widths = {"A": 16, "B": 42, "C": 88}
    _style_sheet(note, 1, widths, body_height=22, tab="142B49", zoom=110)
    bold = Font(name="微软雅黑", bold=True, size=12, color="142B49")
    for row in range(2, note.max_row + 1):
        label = str(note.cell(row, 1).value or "")
        fill = None
        if label == "结论":
            fill = _NOTE_PASS if str(note.cell(row, 3).value or "").startswith("通过") else _NOTE_FOCUS
            note.cell(row, 3).font = bold
        elif label in _NOTE_BAD_LABELS:
            fill = _NOTE_BAD
        elif label in {"待定项", "未能读清", "未能读取"}:
            fill = _NOTE_TBD
        if fill is not None:
            for col in range(1, 4):
                note.cell(row, col).fill = fill
    note.auto_filter.ref = f"A1:C{note.max_row}"
    note.page_setup.fitToHeight = 0
    note.freeze_panes = "A3"


def write_contrast(docs: list[SourceDoc], unreadable: list[Unreadable], dest: Path, ask=None, now: datetime | None = None, on_progress=None) -> ContrastResult:
    """ask：可选的模型调用（messages → 回包文本），只用于给正文参数起名和归并同义参数名；None 为纯规则。now：REQ-ID 里的日期。
    一份文件时是确认说明和需求清单。多份文件合成一本，确认说明之后每个文件一张表。"""
    from electrical_krow.arch_params import collect_params
    from electrical_krow.arch_qa import check_arch_quality

    if not docs:
        reasons = "；".join(f"{u.name}（{u.reason.rstrip('。')}）" for u in unreadable)
        raise ValueError(f"文件内容质检未通过：{reasons or '所选文件都读不出文字'}，无法拆条。")

    def tick(inner: float, stage: str, detail: str = "") -> None:
        if on_progress is None:
            return
        try:
            on_progress(inner, stage, detail)
        except Exception:  # noqa: BLE001
            return

    tick(2, "check", "")
    all_rows: list[list[object]] = []
    all_tables: list[list[object]] = []
    for doc in docs:
        rows, tables = split_document(doc)
        for row in rows:
            all_rows.append(row)
            row[0] = len(all_rows)
        for row in tables:
            all_tables.append(row)
            row[0] = len(all_tables)
    _mark_suspected_duplicates(docs, all_rows)
    ts = now or datetime.now()
    pngs, keep_seqs = _render_requirement_pngs(docs, all_rows, on_progress)
    sheet_titles = _excel_sheet_titles([doc.name for doc in docs]) if len(docs) > 1 else {}
    req_map = _req_row_map(docs, all_rows, ts, with_shot=keep_seqs)
    tick(12, "check", "")
    params = collect_params(all_rows, ask)
    quality = check_arch_quality(docs, unreadable, all_rows, params, req_map, sheet_names=sheet_titles or None)
    tick(18, "check", "")
    note_col = COLUMNS.index("备注")
    for row in all_rows:
        extra = quality.row_notes.get(int(row[0]))
        if extra:
            row[note_col] = _join_notes(str(row[note_col] or ""), extra)
    conflict_seqs = set(quality.flagged_seqs)

    book = Workbook()
    note = book.active
    note.title = SHEET_NOTE
    file_col = COLUMNS.index("文件")
    if len(docs) > 1:
        req_count = shot_count = figure_count = 0
        trans_model_used = False
        for doc in docs:
            sheet = book.create_sheet(sheet_titles[doc.name])
            rows = [row for row in all_rows if row[file_col] == doc.name]
            count, shots, figures, used = _write_reqs(
                sheet, [doc], rows, ts, conflict_seqs, ask=ask, on_progress=tick, pngs=pngs, keep_seqs=keep_seqs,
            )
            req_count += count
            shot_count += shots
            figure_count += figures
            trans_model_used = trans_model_used or used
    else:
        reqs_sheet = book.create_sheet(SHEET_REQS)
        req_count, shot_count, figure_count, trans_model_used = _write_reqs(
            reqs_sheet, docs, all_rows, ts, conflict_seqs, ask=ask, on_progress=tick, pngs=pngs, keep_seqs=keep_seqs,
        )
    used_model = params.model_used or trans_model_used

    _fill_note_sheet(
        note, docs, unreadable, quality, req_map, sheet_titles, params.notes, used_model,
    )

    book.active = book[sheet_titles[docs[0].name] if sheet_titles else SHEET_REQS]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tick(97, "save", "")
    book.save(dest)
    book.close()
    return ContrastResult(
        dest, len(docs), len(all_rows), len(all_tables), tuple(unreadable),
        params=len(params.params),
        conflicts=max(params.conflicts, quality.param_conflicts) + quality.bilingual_conflicts + quality.logic_conflicts,
        model_used=used_model,
        image_tables=sum(len(grids) for doc in docs for grids in doc.image_tables.values()),
        figures=figure_count, reqs=req_count, shots=shot_count,
        quality_summary=quality.summary,
        bilingual_conflicts=quality.bilingual_conflicts,
        logic_conflicts=quality.logic_conflicts,
        tbd_count=quality.tbd_count,
        quality_issues=tuple(quality.detail_lines[1:]),
    )


_REQ_SHOT_COL_WIDTH = 96  # 截图列宽（字符），WPS/Excel 里约 580~670 像素
_REQ_SHOT_MAX_PX = 530  # 截图格内显示宽度上限（留足右侧余量，macOS WPS 按 1px=1pt 画也不会越过 D 列）
_REQ_SHOT_MAX_H_PX = 360  # 单条截图格内显示高度上限（像素，加 _REQ_SHOT_ROW_PAD 后不超过 Excel 行高上限 409）
_REQ_SHOT_ROW_PAD = 24  # 行高比截图像素高出的间距（磅）：兼顾 macOS WPS 1px≈1pt，避免上下两行图片贴在一起
_BITMAP_OVERSAMPLE = 2.5  # PNG 位图实际像素相对格内显示尺寸的倍率：保证 Retina 屏与 WPS「图片预览」放大看依然清晰


def _scaled_xl_image(png: bytes, max_width_px: int, max_height_px: int):
    """按格内显示宽高设置 openpyxl Image 尺寸，同时保留高分辨率 PNG 位图（供 Retina 屏与 WPS 图片预览清晰查看）。"""
    from io import BytesIO

    from openpyxl.drawing.image import Image as XlImage
    from PIL import Image as PilImage, ImageOps

    with PilImage.open(BytesIO(png)) as raw:
        w, h = max(1, raw.width), max(1, raw.height)
        # arch_shots 默认按 216 DPI（1 磅 = 3 像素）渲染，折算回约 100 DPI 的格内阅读尺寸再按宽高上限缩放
        natural_w, natural_h = w * 0.46, h * 0.46
        scale = min(1.0, (max_width_px - 10) / max(natural_w, 1.0), (max_height_px - 10) / max(natural_h, 1.0))
        disp_w = max(1, int(round(natural_w * scale)))
        disp_h = max(1, int(round(natural_h * scale)))
        # 位图本身保留 2.5 倍以上像素（若原图因高度被大幅缩小，位图至少保留可读宽度），配合对应 DPI 写入 PNG
        bmp_ratio = max(_BITMAP_OVERSAMPLE, min(w / max(disp_w, 1), 1200.0 / max(disp_w, 1)))
        bmp_w = max(disp_w, int(round(disp_w * bmp_ratio)))
        bmp_h = max(disp_h, int(round(disp_h * bmp_ratio)))
        border_px = max(1, int(round(bmp_ratio)))
        pad_px = max(4, int(round(4 * bmp_ratio)))
        resized = raw.convert("RGB").resize((bmp_w, bmp_h), PilImage.Resampling.LANCZOS)
        framed = ImageOps.expand(resized, border=border_px, fill=(218, 222, 228))
        padded = ImageOps.expand(framed, border=pad_px, fill=(255, 255, 255))
        dpi_val = max(96, int(round(96 * bmp_ratio)))
        buf = BytesIO()
        padded.save(buf, format="PNG", dpi=(dpi_val, dpi_val))
        buf.seek(0)
    image = XlImage(buf)
    image.width, image.height = disp_w + 10, disp_h + 10
    return image


def _place_image(sheet, image, col: int, row: int) -> None:
    """把图钉在 (col, row) 这一格里，留出格内左、上边距。"""
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.utils.units import pixels_to_EMU

    width, height = pixels_to_EMU(image.width), pixels_to_EMU(image.height)
    pad_x, pad_y = pixels_to_EMU(8), pixels_to_EMU(8)
    image.anchor = OneCellAnchor(
        _from=AnchorMarker(col=col - 1, colOff=pad_x, row=row - 1, rowOff=pad_y),
        ext=XDRPositiveSize2D(width, height),
    )
    sheet.add_image(image)


def _is_requirement_row(row: list[object], *, has_sections: bool = False, has_lines: bool = False) -> bool:
    section = str(row[COLUMNS.index("章节")] or "")
    item = str(row[COLUMNS.index("项目（表格栏目）")] or "")
    text = str(row[COLUMNS.index("原文摘录")] or "")
    qty = str(row[COLUMNS.index("数值与单位")] or "")
    shot = row[SHOT_SLOT] if len(row) > SHOT_SLOT else None
    if section in {SECTION_COVER, SECTION_TOC}:
        return False
    if has_sections and not section:
        return False  # 有目录章节的文件里，目录之前的扉页/修订履历还不属于任何章节，不进需求清单
    is_whole_block = text.startswith(("本页表格", "本页图片表格", "本页为数值表", "本页图表", "本页表格块", "本页线框表格"))
    note = str(row[COLUMNS.index("备注")] or "")
    if "按编号摘出" in note or "按版面摘出" in note:
        return bool(_compact(text))
    if has_lines and not is_whole_block and shot is None and not item and not qty and len(_alnum(text)) < 35:
        return False  # 表格上方的孤立小标题或续表头（「2)」「(1)」「5.1 ES/MS - Continued」），不是需求条
    return bool(_compact(text))


def _render_requirement_pngs(
    docs: list[SourceDoc],
    all_rows: list[list[object]],
    on_progress=None,
) -> tuple[dict[int, bytes], set[int]]:
    """渲染原文截图。截不到或被斜章挡住的条目仍留下，截图空着，备注写未能截图。挡住的图不放回去。"""
    from electrical_krow.arch_shots import render_shots

    sec_col, file_col, seq_col = COLUMNS.index("章节"), COLUMNS.index("文件"), COLUMNS.index("序号")
    doc_has_sections = {
        doc.name: any(str(r[sec_col] or "") not in {"", SECTION_COVER, SECTION_TOC} for r in all_rows if r[file_col] == doc.name)
        for doc in docs
    }
    doc_has_lines = {doc.name: bool(doc.lines) for doc in docs}
    picked = [
        row for row in all_rows
        if _is_requirement_row(
            row,
            has_sections=doc_has_sections.get(str(row[file_col]), False),
            has_lines=doc_has_lines.get(str(row[file_col]), False),
        )
    ]
    pngs: dict[int, bytes] = {}
    keep = {int(row[seq_col]) for row in picked}
    note_col = COLUMNS.index("备注")
    page_col = COLUMNS.index("PDF页码")
    by_doc: dict[str, list[list[object]]] = {}
    for row in picked:
        by_doc.setdefault(str(row[file_col]), []).append(row)
    shot_jobs: list[tuple[SourceDoc, list[tuple[int, object]]]] = []
    for doc in docs:
        rows = by_doc.get(doc.name, [])
        if not doc.path:
            for row in rows:
                shot = row[SHOT_SLOT] if len(row) > SHOT_SLOT else None
                if shot is not None and shot.png:
                    pngs[int(row[seq_col])] = shot.png
            continue
        pending = [
            (int(row[seq_col]), row[SHOT_SLOT])
            for row in rows
            if len(row) > SHOT_SLOT and row[SHOT_SLOT] is not None
        ]
        if pending:
            shot_jobs.append((doc, pending))
    shot_total = sum(len(pending) for _, pending in shot_jobs)
    shot_done = 0
    for doc, pending in shot_jobs:
        def _shot_tick(done: int, _total: int, base: int = shot_done) -> None:
            if on_progress is None:
                return
            seen = base + done
            on_progress(55 + 23 * seen / max(shot_total, 1), "shots", f"{seen}/{shot_total}")

        rendered = render_shots(Path(doc.path), [shot for _, shot in pending], on_progress=_shot_tick)
        for (seq, _), png in zip(pending, rendered):
            if png:
                pngs[seq] = png
        shot_done += len(pending)
    docs_by_name = {doc.name: doc for doc in docs}
    for row in picked:
        note = str(row[note_col] or "")
        if "按编号摘出" in note or "按版面摘出" in note:
            continue
        doc = docs_by_name.get(str(row[file_col]))
        if doc and doc.path and int(row[seq_col]) not in pngs:
            row[note_col] = _join_notes(note, f"未能截图，见第 {row[page_col]} 页")
    return pngs, keep


def _req_row_map(
    docs: list[SourceDoc],
    all_rows: list[list[object]],
    now: datetime,
    with_shot: set[int] | None = None,
) -> dict[int, tuple[int, str]]:
    """计算将进入「需求清单」的每条序号对应的 (Excel行号, REQ-ID)。截不到图的条目也进入清单。"""
    sec_col, file_col, seq_col = COLUMNS.index("章节"), COLUMNS.index("文件"), COLUMNS.index("序号")
    doc_has_sections = {
        doc.name: any(str(r[sec_col] or "") not in {"", SECTION_COVER, SECTION_TOC} for r in all_rows if r[file_col] == doc.name)
        for doc in docs
    }
    doc_has_lines = {doc.name: bool(doc.lines) for doc in docs}
    picked = [
        row for row in all_rows
        if _is_requirement_row(
            row,
            has_sections=doc_has_sections.get(str(row[file_col]), False),
            has_lines=doc_has_lines.get(str(row[file_col]), False),
        )
        and (with_shot is None or int(row[seq_col]) in with_shot)
    ]
    stamp = now.strftime("%Y%m%d")
    if len(docs) <= 1:
        return {int(row[seq_col]): (number + 1, f"REQ-{stamp}-{number:03d}") for number, row in enumerate(picked, start=1)}
    found: dict[int, tuple[int, str]] = {}
    for doc in docs:
        doc_rows = [row for row in picked if row[file_col] == doc.name]
        for number, row in enumerate(doc_rows, start=1):
            found[int(row[seq_col])] = (number + 1, f"REQ-{stamp}-{number:03d}")
    return found


_DRAWN_TABLE = "本页线框表格：\n"
_GRID_BORDER = Border(
    left=Side(style="thin", color="000000"),
    right=Side(style="thin", color="000000"),
    top=Side(style="thin", color="000000"),
    bottom=Side(style="thin", color="000000"),
)
_GRID_HEADER_FILL = PatternFill("solid", fgColor="EAF2FC")
_GRID_HEADER_FONT = Font(name="微软雅黑", bold=True, size=10, color="142B49")


def _ready_grid(text: str) -> list[list[str]]:
    """凡是已经读成行列的表，都按原列写入。最右空列上的转速挪回有表头的那一列。"""
    raw = str(text)
    grid = _pipe_grid(raw) if raw.startswith(("本页线框表格", "本页表格", "本页图片表格")) else []
    if not grid:
        return []
    from electrical_krow.arch_figures import pull_orphan_column

    pulled = [list(row) for row in pull_orphan_column(tuple(tuple(cell) for cell in grid))]
    return pulled if len(pulled) >= 2 and len(pulled[0]) >= 2 else grid


def _req_headers(extra: int) -> list[object]:
    """表比一列宽时，多出来的列算在「原文摘录」里，「数值与单位」整体右移。"""
    headers = list(REQ_COLUMNS)
    at = REQ_COLUMNS.index("原文摘录") + 1
    for _ in range(max(extra, 0)):
        headers.insert(at, None)
    return headers


def _pipe_grid(text: str) -> list[list[str]]:
    """「列 | 列」摘录还原成同样的行列。短行补空格，表是一个完整的矩形。"""
    body = text.split("：\n", 1)[1] if "：\n" in text else text
    parsed = [[cell.strip() for cell in line.split("|")] for line in body.splitlines() if line.strip()]
    width = max((len(row) for row in parsed), default=0)
    if width < 2 or len(parsed) < 2:
        return []
    for row in parsed:
        row.extend([""] * (width - len(row)))
    return parsed


def _grid_cell_text(text: str) -> str:
    from electrical_krow.arch_translate import _cell_bilingual

    return _cell_bilingual(text) if text else ""


def _write_drawn_table(sheet, grid: list[list[str]], identity: list[object], extra: int = 0) -> tuple[int, int, int, int]:
    """按原表的行、列写入，每格四边都有线。编号、章节、截图在表左侧并成一块。

    表从「原文摘录」起向右占列。多出来的列已经插在「数值与单位」之前，所以这里的状态、备注、页码要跟着右移。
    """
    excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
    width = len(grid[0])
    grid_end = excerpt_col + width - 1
    start = sheet.max_row + 1
    side = [
        (8 + extra, identity[7]),
        (9 + extra, identity[8]),
        (11 + extra, identity[10]),
        (13 + extra, identity[12]),
        (14 + extra, identity[13]),
        (15 + extra, identity[14]),
        (16 + extra, identity[15]),
    ]
    overflow = [value for col, value in side if value not in (None, "") and col <= grid_end]
    for index, cells in enumerate(grid):
        first = index == 0
        values = [None] * (excerpt_col - 1 + width)
        if first:
            values[0] = identity[0]
            values[2] = identity[2]
        for col, cell in enumerate(cells):
            values[excerpt_col - 1 + col] = _grid_cell_text(cell)
        sheet.append(values)
        if first:
            for col, value in side:
                if value not in (None, "") and col > grid_end:
                    sheet.cell(sheet.max_row, col, value)
            for offset, value in enumerate(overflow, start=1):
                sheet.cell(sheet.max_row, grid_end + offset, value)
    end = sheet.max_row
    _merge_source_spans(sheet, start, end, excerpt_col, grid_end)
    if end > start:
        for col in (1, 3, 4):
            sheet.merge_cells(start_row=start, start_column=col, end_row=end, end_column=col)
        for col, value in side:
            if value not in (None, "") and col > grid_end:
                sheet.merge_cells(start_row=start, start_column=col, end_row=end, end_column=col)
        for offset, value in enumerate(overflow, start=1):
            if value not in (None, ""):
                sheet.merge_cells(start_row=start, start_column=grid_end + offset, end_row=end, end_column=grid_end + offset)
    return start, end, excerpt_col, grid_end


def _merge_source_spans(sheet, start: int, end: int, left: int, right: int) -> None:
    """原表里竖向或横向合并的格子，摘出来是一格有字、旁边几格为空。按这个把空格并回去。"""
    for col in range(left, right + 1):
        row = start
        while row <= end:
            if not _text(sheet.cell(row, col).value):
                row += 1
                continue
            last = row
            while last + 1 <= end and not _text(sheet.cell(last + 1, col).value):
                filled = [other for other in range(left, right + 1) if _text(sheet.cell(last + 1, other).value)]
                if len(filled) == 1 and filled[0] < col:
                    break
                if filled:
                    last += 1
                    continue
                break
            if last > row:
                sheet.merge_cells(start_row=row, start_column=col, end_row=last, end_column=col)
            row = last + 1
    for row in range(start, end + 1):
        col = left
        while col <= right:
            if not _text(sheet.cell(row, col).value):
                col += 1
                continue
            if any(_text(sheet.cell(row, other).value) for other in range(col + 1, right + 1)):
                col += 1
                continue
            if col < right:
                sheet.merge_cells(start_row=row, start_column=col, end_row=row, end_column=right)
            break


def _paint_drawn_tables(sheet, ranges: list[tuple[int, int, int, int]], flagged: set[int]) -> None:
    """样式铺完后再画表线，避免被整表的浅灰边框盖住。"""
    align = Alignment(wrap_text=True, vertical="center")
    for start, end, left, right in ranges:
        from openpyxl.cell.cell import MergedCell

        for row in range(start, end + 1):
            for col in range(left, right + 1):
                cell = sheet.cell(row, col)
                if isinstance(cell, MergedCell):
                    continue
                cell.border = _GRID_BORDER
                cell.alignment = align
                if row == start and row not in flagged:
                    cell.font = _GRID_HEADER_FONT
                    cell.fill = _GRID_HEADER_FILL


def _write_reqs(
    sheet,
    docs: list[SourceDoc],
    all_rows: list[list[object]],
    now: datetime,
    conflict_seqs: set[int] = frozenset(),
    ask: Callable[[str], str] | None = None,
    on_progress=None,
    pngs: dict[int, bytes] | None = None,
    keep_seqs: set[int] | None = None,
) -> tuple[int, int, int, bool]:
    """「需求清单」：一行一条需求，带原文截图、双语原文摘录、数值、条件和程序备注；取值与别处不一致的行标红。返回 (条数, 带截图条数, 图表张数, 是否用到模型翻译)。"""
    from electrical_krow.arch_shots import render_shots
    from electrical_krow.arch_translate import format_bilingual_excerpt, needs_translation, table_excerpt_blocks, translate_excerpts

    sec_col, item_col, text_col, page_col, file_col, seq_col, qty_col, cond_col, note_col = (
        COLUMNS.index(k) for k in ("章节", "项目（表格栏目）", "原文摘录", "PDF页码", "文件", "序号", "数值与单位", "适用条件（原文括注）", "备注")
    )
    doc_has_sections = {
        doc.name: any(str(r[sec_col] or "") not in {"", SECTION_COVER, SECTION_TOC} for r in all_rows if r[file_col] == doc.name)
        for doc in docs
    }
    doc_has_lines = {doc.name: bool(doc.lines) for doc in docs}
    picked = [
        row for row in all_rows
        if _is_requirement_row(
            row,
            has_sections=doc_has_sections.get(str(row[file_col]), False),
            has_lines=doc_has_lines.get(str(row[file_col]), False),
        )
    ]
    if keep_seqs is not None:
        picked = [row for row in picked if int(row[seq_col]) in keep_seqs]
    stamp = now.strftime("%Y%m%d")
    raw_excerpts: dict[int, str] = {}
    for row in picked:
        seq = int(row[seq_col])
        item = str(row[item_col] or "")
        text = str(row[text_col] or "")
        raw_excerpts[seq] = f"{item}：{text}" if item and not text.startswith(item) else text
    grids = {seq: _ready_grid(text) for seq, text in raw_excerpts.items()}
    extra = max((len(grid[0]) - 1 for grid in grids.values() if grid), default=0)
    excerpt_col = REQ_COLUMNS.index("原文摘录") + 1
    sheet.append(_req_headers(extra))
    if extra:
        sheet.merge_cells(start_row=1, start_column=excerpt_col, end_row=1, end_column=excerpt_col + extra)
    translations, trans_model_used = translate_excerpts(
        list(raw_excerpts.items()),
        ask,
        on_progress=(lambda done, total: on_progress(20 + 35 * done / max(total, 1), "translate", f"{done}/{total}")) if on_progress else None,
    )
    if pngs is None:
        from electrical_krow.arch_shots import render_shots

        pngs = {}
        shot_jobs: list[tuple[SourceDoc, list[tuple[int, object]]]] = []
        for doc in docs:
            pending = [(int(row[seq_col]), row[SHOT_SLOT]) for row in picked if row[file_col] == doc.name and len(row) > SHOT_SLOT and row[SHOT_SLOT] is not None]
            if pending:
                shot_jobs.append((doc, pending))
        shot_total = sum(len(pending) for _, pending in shot_jobs)
        shot_done = 0
        for doc, pending in shot_jobs:
            def _shot_tick(done: int, _total: int, base: int = shot_done) -> None:
                if on_progress is None:
                    return
                seen = base + done
                on_progress(55 + 23 * seen / max(shot_total, 1), "shots", f"{seen}/{shot_total}")

            rendered = render_shots(Path(doc.path), [shot for _, shot in pending], on_progress=_shot_tick) if doc.path else [shot.png for _, shot in pending]
            if on_progress and not doc.path:
                _shot_tick(len(pending), len(pending))
            for (seq, _), png in zip(pending, rendered):
                if png:
                    pngs[seq] = png
            shot_done += len(pending)
        page_col_src = COLUMNS.index("PDF页码")
        for row in picked:
            note = str(row[note_col] or "")
            if "按编号摘出" in note or "按版面摘出" in note:
                continue
            doc = next((item for item in docs if item.name == row[file_col]), None)
            if doc and doc.path and int(row[seq_col]) not in pngs:
                row[note_col] = _join_notes(note, f"未能截图，见第 {row[page_col_src]} 页")
    shots = 0
    figures = sum(
        1
        for row in picked
        if len(row) > SHOT_SLOT and getattr(row[SHOT_SLOT], "png", b"")
    )
    flagged: list[int] = []
    groups: list[tuple[int, int, bytes]] = []
    drawn_ranges: list[tuple[int, int, int, int]] = []
    shot_col = REQ_COLUMNS.index("SR content\n原文截图") + 1
    page_bodies = {(doc.name, index): body for doc in docs for index, body in doc.pages}
    for number, row in enumerate(picked, start=1):
        seq = int(row[seq_col])
        section = str(row[sec_col] or "")
        item = str(row[item_col] or "")
        text = str(row[text_col] or "")
        source = raw_excerpts[seq]
        opinion, noted = _opinion_for(row, text_col, note_col)
        if needs_translation(source) and seq not in translations:
            noted = _join_notes(noted, "未翻译")
        page_body = page_bodies.get((row[file_col], row[page_col]), "")
        qty, qty_note = _quantity_on_page(str(row[qty_col] or ""), source, page_body)
        if qty_note:
            noted = _join_notes(noted, qty_note)
        review = bool(qty_note) or NOTE_OCR in noted
        confidence = _row_confidence(source, page_body, review=review)
        category = "建议：" + suggest_category(section, f"{item} {text}")
        grid = grids.get(seq) or []
        if grid:
            start, end, left, right = _write_drawn_table(
                sheet,
                grid,
                [
                    f"REQ-{stamp}-{number:03d}",
                    None,
                    section,
                    None,
                    None,
                    None,
                    None,
                    category,
                    opinion,
                    None,
                    STATUS_CURRENT,
                    None,
                    noted,
                    row[page_col],
                    confidence,
                    None,
                ],
                extra,
            )
            drawn_ranges.append((start, end, left, right))
            if seq in conflict_seqs:
                flagged.extend(range(start, end + 1))
            png = pngs.get(seq)
            if png:
                groups.append((start, end, png))
            continue
        blocks = table_excerpt_blocks(source) if source.startswith(("本页表格", "本页图片表格")) else []
        if not blocks:
            blocks = [format_bilingual_excerpt(source, translations.get(seq, ""))]
        start = sheet.max_row + 1
        for index, block in enumerate(blocks):
            first = index == 0
            values = [
                f"REQ-{stamp}-{number:03d}" if first else None,
                None,
                section if first else None,
                None,
                block[:_EXCERPT_CAP],
            ]
            values.extend([None] * extra)
            values.extend([
                qty if first else None,
                (row[cond_col] or "") if first else None,
                category if first else None,
                opinion if first else None,
                None,
                STATUS_CURRENT if first else None,
                None,
                noted if first else None,
                row[page_col] if first else None,
                confidence if first else None,
                None,
            ])
            sheet.append(values)
            if extra:
                sheet.merge_cells(start_row=sheet.max_row, start_column=excerpt_col, end_row=sheet.max_row, end_column=excerpt_col + extra)
            if seq in conflict_seqs:
                flagged.append(sheet.max_row)
        end = sheet.max_row
        if end > start:
            for col in (1, 3, shot_col, *(c + extra for c in (6, 7, 8, 9, 11, 13, 14, 15, 16))):
                sheet.merge_cells(start_row=start, start_column=col, end_row=end, end_column=col)
        png = pngs.get(seq)
        if png:
            groups.append((start, end, png))
    heights = {r: sheet.row_dimensions[r].height for r in range(2, sheet.max_row + 1) if sheet.row_dimensions[r].height}
    from openpyxl.utils import get_column_letter

    base_widths = [20, 9, 26, _REQ_SHOT_COL_WIDTH, 36, 28, 26, 16, 36, 12, 28, 36, 36, 9, 14, 12]
    for _ in range(extra):
        base_widths.insert(5, 24)
    qty_excel = REQ_COLUMNS.index("数值与单位") + 1 + extra
    table_rows = [row for start, end, _left, _right in drawn_ranges for row in range(start, end + 1)]
    if table_rows:
        # 表列只按表内的格子定宽。旁边整段工况再长，也不把 Load / Speed 表拉到一整屏。
        base_widths[4] = _fitted_width(sheet, excerpt_col, 16, cap=110, rows=table_rows)
        for offset in range(extra):
            base_widths[5 + offset] = _fitted_width(sheet, excerpt_col + 1 + offset, 14, cap=28, rows=table_rows)
    else:
        base_widths[4] = _fitted_width(sheet, excerpt_col, base_widths[4], cap=220)
    base_widths[5 + extra] = _fitted_width(sheet, qty_excel, base_widths[5 + extra], cap=80)
    _style_sheet(
        sheet, 1,
        {get_column_letter(index + 1): width for index, width in enumerate(base_widths)},
        body_height=20,
        fit_width=False,
        zoom=100,
    )
    one_line = Alignment(wrap_text=False, vertical="center", horizontal="left")
    for col in (qty_excel,):
        letter = get_column_letter(col)
        width = sheet.column_dimensions[letter].width or 36
        for excel_row in range(2, sheet.max_row + 1):
            cell = sheet.cell(excel_row, col)
            value = str(cell.value or "")
            if value and "\n" not in value and _display_width(value) + 4 <= width + 0.5:
                cell.alignment = one_line
    for r, height in heights.items():
        sheet.row_dimensions[r].height = max(height, sheet.row_dimensions[r].height or 0)
    image_total = len(groups)
    for image_at, (start, end, png) in enumerate(groups, start=1):
        if on_progress and (image_at == 1 or image_at == image_total or image_at % 8 == 0):
            on_progress(78 + 16 * image_at / max(image_total, 1), "images", f"{image_at}/{image_total}")
        image = _scaled_xl_image(png, _REQ_SHOT_MAX_PX, _REQ_SHOT_MAX_H_PX)
        total = sum(sheet.row_dimensions[r].height or 20 for r in range(start, end + 1))
        drawn = any(start == box[0] and end == box[1] for box in drawn_ranges)
        if drawn:
            # 规格表每行只留一行字的高度，避免被整页截图或折行撑高。
            for r in range(start, end + 1):
                sheet.row_dimensions[r].height = 18
            room = max(1, (end - start + 1) * 18 - 6)
            if image.height > room:
                ratio = image.width / max(image.height, 1)
                image.height = room
                image.width = max(1, int(room * ratio))
        else:
            need = min(_MAX_ROW_HEIGHT, image.height + _REQ_SHOT_ROW_PAD)
            if total < need:
                grow = (need - total) / (end - start + 1)
                for r in range(start, end + 1):
                    sheet.row_dimensions[r].height = (sheet.row_dimensions[r].height or 20) + grow
        _place_image(sheet, image, shot_col, start)
        shots += 1
    for r in flagged:
        for cell in sheet[r]:
            cell.fill = _DIFF_FILL
    _paint_drawn_tables(sheet, drawn_ranges, set(flagged))
    if sheet.max_row >= 2:
        status_col = REQ_COLUMNS.index("Currently status\n状态") + 1 + extra
        letter = sheet.cell(1, status_col).column_letter
        choices = DataValidation(type="list", formula1=f'"{",".join(STATUS_CHOICES)}"', allow_blank=False)
        choices.error = "请从列表中选择状态"
        choices.errorTitle = "Currently status"
        choices.add(f"{letter}2:{letter}1048576")
        sheet.add_data_validation(choices)
    return len(picked), shots, figures, trans_model_used


_FIGURE_MAX_PX = 480  # 嵌进 Excel 的图最宽多少像素，再大按比例缩
_FIGURE_MAX_H_PX = 220


def _write_attachments(sheet, docs: list[SourceDoc], all_rows: list[list[object]], all_tables: list[list[object]]) -> int:
    """「附件」：整表原文一行一表，图表一行一张（PNG 嵌在「图」列，行高按图高）；按文件、页码排。返回图表张数。"""
    sheet.append(list(ATTACH_COLUMNS))
    section_col, file_col, page_col = COLUMNS.index("章节"), COLUMNS.index("文件"), COLUMNS.index("PDF页码")
    order = {doc.name: at for at, doc in enumerate(docs)}
    # (文件序, 页码, 先表后图, 行内容, 图)
    entries: list[tuple[int, int, int, list[object], bytes]] = []
    for table in all_tables:
        _, obj, name, page_no, section, kind, text, remark = table
        entries.append((order.get(name, 0), int(page_no), 0, [obj, name, page_no, section, kind, text, "", remark], b""))
    count = 0
    for doc in docs:
        obj = object_of(doc)
        for page_no, figures in sorted(doc.figures.items()):
            section = next((str(r[section_col] or "") for r in all_rows if r[file_col] == doc.name and r[page_col] == page_no), "")
            if section in {SECTION_COVER, SECTION_TOC}:
                continue  # 封面上的 logo、目录页的装饰不算图表
            for figure in figures:
                count += 1
                entries.append((order[doc.name], page_no, 1, [obj, doc.name, page_no, section, figure.kind, figure.labels, "", "整图截图，供对照原文；不拆条、不取数"], figure.png))
    entries.sort(key=lambda e: e[:3])
    heights: dict[int, float] = {}
    for number, (_, _, _, cells, png) in enumerate(entries, start=1):
        sheet.append([number, *cells])
        if not png:
            continue
        image = _scaled_xl_image(png, _FIGURE_MAX_PX, _FIGURE_MAX_H_PX)
        row = sheet.max_row
        heights[row] = min(_MAX_ROW_HEIGHT, image.height + _REQ_SHOT_ROW_PAD)
        _place_image(sheet, image, ATTACH_COLUMNS.index("图") + 1, row)
    _style_sheet(
        sheet, 1,
        {"A": 8, "B": 14, "C": 36, "D": 10, "E": 26, "F": 14, "G": 90, "H": 92, "I": 30},
        body_height=60,
        fit_width=False,
        zoom=100,
    )
    # 图高决定行高，样式里按文字算的行高要让位
    for row, height in heights.items():
        sheet.row_dimensions[row].height = max(height, sheet.row_dimensions[row].height or 0)
    return count


def read_progress_detail(file_at: int, file_count: int, name: str, page: int, total: int) -> str:
    """多份文件时先写第几份，再写这一份的第几页。单份只写页码和文件名。"""
    page_part = f"第 {page}/{max(total, 1)} 页"
    if file_count > 1:
        return f"第 {file_at + 1}/{file_count} 份 · {page_part} · {name}"
    return f"{page_part} · {name}"


def build_contrast(sources: list[Path], dest: Path, ask=None, on_progress=None, now: datetime | None = None) -> ContrastResult:
    """on_progress(percent, stage, detail)。读文件占前 68%，写入从 70% 走到 99%，按核对、翻译、截图、保存分开报。"""
    docs: list[SourceDoc] = []
    unreadable: list[Unreadable] = []
    file_count = max(len(sources), 1)
    spans = {"text": (0, 18), "tables": (18, 55), "ocr": (55, 82), "figures": (82, 90), "lines": (90, 94)}

    def report(percent: float, stage: str, detail: str = "") -> None:
        if on_progress is None:
            return
        try:
            on_progress(max(0, min(99, int(percent))), stage, detail)
        except Exception:  # noqa: BLE001
            return

    for file_at, path in enumerate(sources):
        name = Path(path).name

        def page_progress(phase: str, page: int, total: int, *, _at: int = file_at, _name: str = name) -> None:
            lo, hi = spans.get(phase, (0, 18))
            local = lo + (hi - lo) * (page / max(total, 1))
            report(((_at + local / 100) / file_count) * 68, phase, read_progress_detail(_at, file_count, _name, page, total))

        read = read_pdf_pages(Path(path), progress=page_progress)
        if isinstance(read, Unreadable):
            unreadable.append(read)
        else:
            docs.append(read)
            unreadable.extend(read.unread)

    def write_progress(inner: float, stage: str, detail: str = "") -> None:
        report(70 + max(0.0, min(100.0, inner)) * 0.29, stage, detail)

    return write_contrast(docs, unreadable, dest, ask, now, on_progress=write_progress)


_FILE_STEM = re.compile(r"[^\w\u4e00-\u9fff.-]+")


def _source_label(sources: list[str] | tuple[str, ...]) -> str:
    """输入文件名（去掉扩展名）拼进出表文件名。同名只留一次。"""
    stems: list[str] = []
    for name in sources:
        stem = Path(str(name or "")).stem
        stem = _FILE_STEM.sub("_", stem).strip("._")
        if stem and stem not in stems:
            stems.append(stem[:80])
    return "+".join(stems)[:120]


def contrast_file_name(
    now: datetime | None = None,
    sources: list[str] | tuple[str, ...] | None = None,
) -> str:
    """出表文件名：架构对照-输入文件名-时间。多份输入用加号连起来。"""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    label = _source_label(sources or ())
    if label:
        return f"架构对照-{label}-{stamp}.xlsx"
    return f"架构对照-{stamp}.xlsx"
