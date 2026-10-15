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

SHEET_NOTE = "确认说明"
SHEET_ATTACH = "附件"  # 整表原文和图表截图合在一张
SHEET_TABLES = SHEET_ATTACH  # 旧名，条目索引文字里仍用

STATUS_PENDING = "待确认"
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
_BULLET_MARK = re.compile(r"^[•·▪■◦●○]\s*")
_NOTE_MARK = re.compile(r"^[※*]\s*")
_LEAD_CAP = 80
# 数值与单位：数（可带符号、千分位、小数、范围）后跟常见工程单位。单位表只用于识别，不用于取值。
_UNIT = (
    r"(?:k|m|M|µ|μ|u|G)?(?:V(?:dc|ac|DC|AC)?|A(?:h|C|DC)?|W(?:h)?|VA|Hz|Nm|N·m|N\.m|rpm|r/min|"
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
    r"보호받습니다|정보자산|기아의|관련 법령|confidential|proprietary|all rights reserved|保密|机密|版权所有|不得外传|仅供内部",
    re.I,
)
# 一条内的表格块：词数够多，且数字占四成以上，或重复词太多（表头「Torque Nm Power kW」反复出现）。
_TABLE_MIN_TOKENS = 10
_TABLE_NUMERIC = 0.5
_TABLE_UNIQUE = 0.2

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_DIFF_FILL = PatternFill("solid", fgColor="FCE4E4")  # 参数清单里取值不一致的行
_HEADER_FONT = Font(name="宋体", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="宋体", size=10)
_WRAP = Alignment(wrap_text=True, vertical="top")
_THIN = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
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


@dataclass(frozen=True)
class Unreadable:
    name: str
    pages: int
    reason: str


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
    "Remark\n备注", "PDF页码",
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


def read_pdf_pages(path: Path) -> SourceDoc | Unreadable:
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
        for index, page in enumerate(reader.pages, start=1):
            try:
                pages.append((index, _plain_glyphs(page.extract_text() or "")))
            except Exception:  # noqa: BLE001
                pages.append((index, ""))
    except Exception:  # noqa: BLE001
        return Unreadable(path.name, 0, "文件打不开，不是可读的 PDF。")
    if not pages:
        return Unreadable(path.name, 0, "PDF 没有页面。")
    if sum(len(_compact(text)) for _, text in pages) < _MIN_TEXT:
        return Unreadable(path.name, len(pages), "没有文字层，未拆条，未补写内容。")
    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    row_boxes: dict[int, list[list]] = {}
    tables = read_pdf_tables(path, boxes, row_boxes)
    image_tables = drop_duplicate_grids(tables, read_image_tables(path))
    return SourceDoc(
        path.name, tuple(pages), tables, image_tables, read_figures(path, boxes, set(image_tables)),
        path=str(path), lines=read_text_lines(path, boxes), table_rows=row_boxes,
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


def read_image_tables(path: Path) -> dict[int, list[Grid]]:
    """图片形式贴进 PDF 的表格：按格线切格、OCR 识字。识读库不可用或出错就当没有。"""
    try:
        from electrical_krow.arch_ocr import read_image_tables as _read

        return _read(path)
    except Exception:  # noqa: BLE001
        return {}


def read_pdf_tables(
    path: Path,
    boxes: dict[int, list[tuple[float, float, float, float]]] | None = None,
    row_boxes: dict[int, list[list]] | None = None,
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
            for index, page in enumerate(pdf.pages, start=1):
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
    """算得上表的：至少两行两列，且一半以上的行有两格以上有字。单行的页眉表、格里套出来的碎块不算。"""
    if len(grid) < 2 or not grid[0] or len(grid[0]) < 2:
        return False
    filled = sum(1 for row in grid if sum(1 for cell in row if cell) >= 2)
    return filled * 2 >= len(grid)


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
            if not key or len(key) > 60 or key in seen or not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", key):
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
    limit = max(3, int(len(pages) * 0.4))
    return frozenset(key for key, count in counts.items() if count >= limit)


_HANGUL = re.compile(r"[\uac00-\ud7af\u3130-\u318f]")
_LETTER = re.compile(r"[A-Za-z\u4e00-\u9fff\uac00-\ud7af\u3130-\u318f]")


def hangul_is_minor(pages: tuple[tuple[int, str], ...]) -> bool:
    """整份文件里韩文字母不到两成：英文或中文 SR 里夹的韩文只会是保密声明之类，不是需求。韩文为主的文件远超此数。"""
    letters = sum(len(_LETTER.findall(text)) for _, text in pages)
    hangul = sum(len(_HANGUL.findall(text)) for _, text in pages)
    return letters > 0 and hangul / letters < 0.2


def _hangul_only(key: str) -> bool:
    letters = _LETTER.findall(key)
    return bool(letters) and all(_HANGUL.match(ch) for ch in letters)


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
        if _NOTICE.search(key):
            continue
        # 保密声明按词拆成多行时，关键词只在其中一行；韩文占比低的文件里纯韩文行整行剔除
        if drop_hangul and _hangul_only(key):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


_FILLER = re.compile(r"^[.…·\-–—/|]+$")


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
            if len(title) < 3 or re.fullmatch(r"[\d\s./-]+", title) or number.startswith("0"):
                continue  # 页眉里的「001 Date」（版本号）不是章节
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
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text.lower())


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
    """把 PDF 里碎开的行拼回一段。单独一行的「-」是连字符，两边都是词时直接接上。"""
    out = ""
    pending_hyphen = False
    for raw in lines:
        piece = _compact(raw)
        if not piece:
            continue
        if piece == "-" and out and out[-1].isalnum():
            pending_hyphen = True
            continue
        if pending_hyphen:
            # 后一段以小写字母开头才是被拆开的词（sub-parts）；大写或数字开头的是子项破折号
            out += "-" + piece if piece[0].islower() else " - " + piece
            pending_hyphen = False
            continue
        if not out:
            out = piece
        elif out.endswith("-") and piece[0].islower():
            out += piece
        else:
            out += " " + piece
    if pending_hyphen:
        out += " -"
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
    if number.count(".") < 2 or not re.match(r"[A-Za-z\u4e00-\u9fff]", title) or len(title) < 3:
        return ""
    parent = number.rsplit(".", 1)[0]
    if not any(parent == head_no for head_no, _ in heads):
        return ""
    return f"{number} {title}"


def _is_label(line: str) -> bool:
    """像栏目标签的短行：不长、不以句末标点结尾、至少有一个字母或汉字。"""
    flat = _compact(line)
    return 0 < len(flat) <= 40 and not flat.endswith((".", "。", ":", "：", ";", "；")) and bool(
        re.search(r"[A-Za-z\u4e00-\u9fff]", flat)
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
            if _ends_sentence_then_label(clauses[-1][2], flat):
                pending_lead.append(flat)
                continue
            clauses[-1][2].extend(pending_lead)
            clauses[-1][2].append(flat)
            pending_lead = []
            held = False
            continue
        if clauses and not pending_lead and not fresh:
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
    lead = lead[drop:].lstrip(_LEAD_STRIP).strip()
    lead = _ITEM_MARK.sub("", lead) if cut == 0 else lead
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff@=<>≤≥±]", lead):
        return ""  # 只剩标点（如孤零零一个「(」）不算引导词；「@」「=」这类关系符保留
    if re.search(r"[\u4e00-\u9fff]", lead):
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
        if item in found or (qty in seen and not re.search(r"[A-Za-z\u4e00-\u9fff]", lead)):
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
        if has_qty and not re.search(r"[A-Za-z\u4e00-\u9fff]{2,}", rest):
            continue
        if inner not in found:
            found.append(inner)
    return "；".join(found)


# 表头词 → 栏目角色。只按表头认栏，不认格里的内容。
_COL_KEY = re.compile(r"^(?:(?:major|sub)?classification|catego?ry|items?|parameters?|name|test(?:items?)?|analysis|项目|分类|参数|名称|试验项目|分析项)$")
_COL_VALUE = re.compile(r"^(?:requirements?|(?:request)?specifications?|spec|targets?|values?|contents?|standard|criteria|(?:verification)?results?|要求|规格|目标|指标|标准|内容|结果)$")
_COL_UNIT = re.compile(r"^(?:units?|单位)$")
_COL_REMARK = re.compile(r"^(?:remarks?|notes?|comments?|conditions?|备注|说明|条件)$")


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
    return None, []


def table_entries(grid: Grid) -> list[TableEntry]:
    """有「项目」和「要求」两类栏的表，每行出一条：项目格是 key，要求格是 value。认不出表头的表返回空。

    纵向合并的格（Category 跨几行）在后续行为空，沿用上一行。只读格子，不解释。
    """
    header_at, roles = _find_header(grid)
    if header_at is None:
        return []
    headers = grid[header_at]
    labels: list[str] = []
    for cell in headers:  # 合并表头下的空列用前一个表头名标注
        labels.append(cell or (labels[-1] if labels else ""))
    entries: list[TableEntry] = []
    carried = [""] * len(headers)
    for row_at, row in enumerate(grid[header_at + 1 :], start=header_at + 1):
        row = list(row) + [""] * (len(headers) - len(row))
        if not any(row):
            continue
        keys: list[str] = []
        values: list[str] = []
        units: list[str] = []
        remarks: list[str] = []
        parts: list[str] = []
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
            parts.append(f"{labels[col]}：{cell}" if labels[col] else cell)
            if role == "key" and cell not in keys:
                keys.append(cell)
            elif role == "value":
                values.append(cell)
            elif role == "unit":
                units.append(cell)
            elif role == "remark":
                remarks.append(cell)
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
        entries.append(TableEntry(item, " | ".join(parts), value, " ".join(remarks), row_at))
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
        strong = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", key)) >= 4
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

    def emit_tables(index: int, inner: str, section: str, grids: list[Grid]) -> None:
        """按格线读出的表：认得出「项目／要求」表头的每行一条，key 进「项目」、要求格进「数值与单位」；认不出的整表留附件。
        图片里 OCR 识读出的表同样处理，但备注标明是 OCR，字符要对照原图核对。
        图表（坐标图、曲线、框图）只留一条索引，整图截在「图表附件」，不拆条、不取数。"""
        from electrical_krow.arch_shots import Shot

        for figure in doc.figures.get(index, []):
            hint = f"：{figure.labels[:80]}" if figure.labels else ""
            rows.append(plain(index, inner, section, "", f"本页图表（{figure.kind}）{hint}", "", "", f"图表，整图见「{SHEET_FIGURES}」，不拆成单条", shot=Shot(index, None, figure.png)))
        ocr_grids = doc.image_tables.get(index, [])
        row_boxes = doc.table_rows.get(index, [])
        for grid_at, grid in enumerate([*grids, *ocr_grids]):
            ocr = any(grid is g for g in ocr_grids)
            boxes = row_boxes[grid_at] if not ocr and grid_at < len(row_boxes) else []
            how = NOTE_OCR if ocr else "按格线读出的表格"
            entries = table_entries(grid)
            if not entries:
                # 拆成了行的表每行都在需求清单里，不再整表重复；只有没拆的表才整表进附件
                tables.append([None, obj, doc.name, index, section, ATTACH_OCR if ocr else ATTACH_TABLE, grid_text(grid), f"{how}，表头认不出项目／要求栏，未拆成单条"])
                shape = f"{len(grid)} 行 × {len(grid[0])} 列"
                what = "本页图片表格" if ocr else "本页表格"
                rows.append(plain(index, inner, section, "", f"{what}（{shape}），整表见「{SHEET_TABLES}」。", "", "", _join_notes(NOTE_OCR if ocr else "", "表头认不出项目／要求栏，未拆成单条")))
                continue
            for entry in entries:
                box = boxes[entry.row] if 0 <= entry.row < len(boxes) else None
                rows.append(plain(index, inner, section, "", entry.text, entry.value, entry.remark, _join_notes(NOTE_OCR if ocr else "", "表格行"), entry.item, shot=Shot(index, box) if box else None))

    carried = ""  # 上一页末尾所在的章节；本页没有标题时沿用
    for index, raw in doc.pages:
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
        if grids:
            body = strip_table_lines(body, grids)
        if figures:
            body = strip_table_lines(body, [[[f.labels]] for f in figures if f.labels])
        found = page_headings(body, heads)
        section = found[0] if found else carried
        carry_note = "" if found or not carried else "章节沿用上一页"
        if is_table_page(body):
            tables.append([None, obj, doc.name, index, section, ATTACH_PAGE, body, "整页保留，不拆成单条，不判断是否满足"])
            rows.append(plain(index, inner, section, "", f"本页为数值表，整页见「{SHEET_TABLES}」。", "", "", "不拆成单条需求"))
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
        if len(clauses) <= 1:
            # 整页没有条款标记：整页一条，原文保留换行
            text, note = _excerpt(body, keep_short=True)
            rows.append(row(index, inner, section, "", text, _join_notes(note or "本页无条款标记，整页一条", carry_note)))
            emit_tables(index, inner, section, grids)
            continue
        for sec, mark, text in clauses:
            sec = sec or section
            if is_table_block(text):
                # 坐标轴刻度、反复出现的表头：整块进整表附件，条目里留一条索引，不取数
                tables.append([None, obj, doc.name, index, sec, ATTACH_BLOCK, text, "条内表格块，整块保留，不拆成单条，不判断是否满足"])
                hint = _compact(text)[:60]
                rows.append(plain(index, inner, sec, mark, f"{hint}……（表格块，整块见「{SHEET_TABLES}」）", "", "", "表格块，不拆成单条需求"))
                continue
            note = ""
            if len(text) > _EXCERPT_CAP:
                text, note = text[:_EXCERPT_CAP] + "……（其余见原 PDF）", f"摘录在 {_EXCERPT_CAP} 字处截断"
            rows.append(row(index, inner, sec, mark, text, _join_notes(note, carry_note)))
        emit_tables(index, inner, carried or section, grids)
    return rows, tables


def _join_notes(*notes: str) -> str:
    return "；".join(note for note in notes if note)


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


def _fit_row_height(cells, widths: dict[str, int], minimum: int) -> int:
    """行高按本行最长的那格算，不让折行的字被截掉。"""
    lines = 1
    for cell in cells:
        if cell.value is None or cell.value == "":
            continue
        width = widths.get(cell.column_letter, 10)
        lines = max(lines, _lines_needed(str(cell.value), width))
    return min(_MAX_ROW_HEIGHT, max(minimum, lines * _LINE_POINTS + 4))


def _style_sheet(sheet, header_row: int, widths: dict[str, int], *, body_height: int = 48) -> None:
    for col, width in widths.items():
        sheet.column_dimensions[col].width = width
    for cell in sheet[header_row]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    sheet.row_dimensions[header_row].height = 22
    last = sheet.max_column
    for cells in sheet.iter_rows(min_row=header_row + 1, max_row=sheet.max_row, max_col=last):
        for cell in cells:
            cell.font = _BODY_FONT
            cell.alignment = _WRAP
            cell.border = _THIN
        sheet.row_dimensions[cells[0].row].height = _fit_row_height(cells, widths, body_height)
    sheet.freeze_panes = f"A{header_row + 1}"
    if sheet.max_row > header_row:
        from openpyxl.utils import get_column_letter

        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(last)}{sheet.max_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{header_row}:{header_row}"
    sheet.oddFooter.center.text = "第 &P 页"


def write_contrast(docs: list[SourceDoc], unreadable: list[Unreadable], dest: Path, ask=None, now: datetime | None = None) -> ContrastResult:
    """ask：可选的模型调用（messages → 回包文本），只用于给正文参数起名和归并同义参数名；None 为纯规则。now：REQ-ID 里的日期。
    三张表：确认说明、需求清单（主表，带截图、数值、备注）、附件（整表原文和图表截图）。"""
    from electrical_krow.arch_params import CONSIST_DIFF, collect_params

    if not docs:
        raise ValueError("所选文件都读不出文字，无法拆条。")
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
    params = collect_params(all_rows, ask)
    note_col = COLUMNS.index("备注")
    conflict_seqs: set[int] = set()
    for row in all_rows:
        extra = params.conflict_rows.get(int(row[0]))
        if extra:
            row[note_col] = _join_notes(str(row[note_col] or ""), extra)
            conflict_seqs.add(int(row[0]))

    book = Workbook()
    note = book.active
    note.title = SHEET_NOTE
    sources = "；".join(f"{doc.name}（{len(doc.pages)} 页）" for doc in docs)
    lines = [
        ("用途", "把需求文件按条款拆成条目，供人工逐条确认。本表只摘原文，不写能否满足。"),
        ("来源文件", sources),
        ("需求清单", f"「{SHEET_REQS}」一行一条需求，版式按偏差跟踪表：REQ-ID（REQ-日期-序号）、章节、该条在原文里的截图（表格行截那一行，正文截那一段；截图按列宽缩放，太长的段落缩小后仍是整段）、原文摘录；「类别」是按章节和条文关键词给的建议值，须人工改定；优先级、意见、提出人、客户反馈留给人填，状态一律为待确认。截图按文字位置定位，个别条目定位不到时该格留空，原文摘录仍在。"),
        ("拆分方式", "行首「1)」「•」「※」等标记各起一条；标记前的短引导句并入其后那条；整页没有标记的按整页一条。原文只来自该页可复制文字。章节按行首的目录章节号和标题词认；本页没有标题的沿用上一页末尾的章节并在备注注明，文件开头还没有章节的留空。"),
        ("表格行", f"PDF 里有格线的表按格读：表头认得出「项目」栏（Category、Item、Classification 等）和「要求」栏（Requirement、Specification、Target 等）的，每行出一条，原文摘录是「项目格：整行」，「数值与单位」是要求格原文（要求格没单位时补上单位栏），「适用条件」是 Remark／Note 格原文，表头认不出角色的栏也带表头放在这里；纵向合并的格沿用上一行。表头认不出的表不拆，整表留在附件。以图片贴进 PDF 的表格，按图里的格线切格、OCR 识字后同样处理，备注标「{NOTE_OCR}」，字符可能识错，请对照原图；流程图、示意图不识读。"),
        ("数值与条件", "正文条目的「数值与单位」是从该条原文里机械挑出的带单位的数，每个数前带原文里紧挨着的几个字（右对齐截短）以便对应，数后紧跟的「↑」「以上」「max」一起保留；「适用条件（原文括注）」是原文括号里带数或带条件词的话。两列都不是认条，不改写、不换算，须对照「原文摘录」核对。"),
        ("附件", f"「{SHEET_ATTACH}」放整表原文和图表截图，只放需求清单里看不到整体的东西，「类型」列区分：{ATTACH_TABLE}（表头认不出项目／要求栏、没拆成单条的表，整表保留）、{ATTACH_OCR}（图片里识读、没拆成单条的表）、{ATTACH_PAGE}（数值占一半以上的页整页保留）、{ATTACH_BLOCK}（一条里全是刻度或反复表头的块）、矢量图／位图（坐标图、曲线、框图、示意图整块截图，旁边列出图里能读到的文字以便检索，不拆条、不取数）。这些在需求清单里不单独成条。页眉页脚、页码和保密声明行不算原文。"),
        ("取值一致性", f"程序把全文「参数 → 取值」归到一起比对：表格里一格一个数的取项目格和要求格；一格几个数的和正文条目由模型指出每个数是哪个参数的值，程序核对该字串确在原文里。同一参数、适用条件相同而取值不同的，在需求清单该条的备注里写明别处的页码和取值，并整行标红（「{CONSIST_DIFF}」）；取值不同但适用条件也不同（不同工况、不同标准）的不算冲突。归并是否恰当、不一致是笔误还是分段落条件不同，由确认人判断。"
                     + ("本次已用模型起名和归并同义参数名。" if params.model_used else "本次未用模型，参数名是数前的引导词，归并按原名。")
                     + ("；".join(params.notes) and ("本次说明：" + "；".join(params.notes)) or "")),
        ("留空栏目", "状态一律为待确认。优先级、意见、提出人、客户反馈由确认人填写。"),
    ]
    if unreadable:
        for item in unreadable:
            lines.append(("未能读取", f"{item.name}" + (f"（{item.pages} 页）" if item.pages else "") + f"：{item.reason}未补写内容。"))
    else:
        lines.append(("未能读取", "所选文件均已读出文字。"))
    note.append(["项目", "内容"])
    for item in lines:
        note.append(list(item))
    _style_sheet(note, 1, {"A": 18, "B": 108}, body_height=36)
    note.page_setup.fitToHeight = 1
    note.auto_filter.ref = None

    reqs_sheet = book.create_sheet(SHEET_REQS)
    req_count, shot_count = _write_reqs(reqs_sheet, docs, all_rows, now or datetime.now(), conflict_seqs)
    attach_sheet = book.create_sheet(SHEET_ATTACH)
    figure_count = _write_attachments(attach_sheet, docs, all_rows, all_tables)

    book.active = book[SHEET_REQS]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    book.save(dest)
    book.close()
    return ContrastResult(
        dest, len(docs), len(all_rows), len(all_tables), tuple(unreadable),
        params=len(params.params), conflicts=params.conflicts, model_used=params.model_used,
        image_tables=sum(len(grids) for doc in docs for grids in doc.image_tables.values()),
        figures=figure_count, reqs=req_count, shots=shot_count,
    )


_REQ_SHOT_COL_WIDTH = 96  # 截图列宽（字符），WPS/Excel 里约 580~670 像素
_REQ_SHOT_MAX_PX = 460  # 截图宽度上限（留足右侧余量，macOS WPS 按 1px=1pt 画也不会越过 D 列）
_REQ_SHOT_MAX_H_PX = 180  # 单条截图高度上限（像素）
_REQ_SHOT_ROW_PAD = 24  # 行高比截图像素高出的间距（磅）：兼顾 macOS WPS 1px≈1pt，避免上下两行图片贴在一起


def _scaled_xl_image(png: bytes, max_width_px: int, max_height_px: int):
    """按目标像素宽高把 PNG 重采样成 96 DPI，四周留白边和浅灰细框，再包成 openpyxl Image。"""
    from io import BytesIO

    from openpyxl.drawing.image import Image as XlImage
    from PIL import Image as PilImage, ImageOps

    with PilImage.open(BytesIO(png)) as raw:
        w, h = max(1, raw.width), max(1, raw.height)
        # PyMuPDF 默认按 144 DPI 渲染（1 磅 = 2 像素），折算回标准阅读尺寸再按宽高上限缩放
        natural_w, natural_h = w * 0.65, h * 0.65
        scale = min(1.0, (max_width_px - 10) / max(natural_w, 1.0), (max_height_px - 10) / max(natural_h, 1.0))
        target_w = max(1, int(round(natural_w * scale)))
        target_h = max(1, int(round(natural_h * scale)))
        resized = raw.convert("RGB").resize((target_w, target_h), PilImage.Resampling.LANCZOS)
        framed = ImageOps.expand(resized, border=1, fill=(218, 222, 228))
        padded = ImageOps.expand(framed, border=4, fill=(255, 255, 255))
        buf = BytesIO()
        padded.save(buf, format="PNG", dpi=(96, 96))
        buf.seek(0)
        final_w, final_h = padded.width, padded.height
    image = XlImage(buf)
    image.width, image.height = final_w, final_h
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
    if text.startswith(("本页表格", "本页图片表格", "本页为数值表", "本页图表")) or "（表格块，整块见" in text:
        return False  # 只是索引，整表、整图在附件里另有行
    if has_lines and shot is None and not item and not qty and len(_alnum(text)) < 35:
        return False  # 表格上方的孤立小标题或续表头（「2)」「(1)」「5.1 ES/MS - Continued」），不是需求条
    return bool(_compact(text))


def _write_reqs(sheet, docs: list[SourceDoc], all_rows: list[list[object]], now: datetime, conflict_seqs: set[int] = frozenset()) -> tuple[int, int]:
    """「需求清单」：一行一条需求，带原文截图、数值、条件和程序备注；取值与别处不一致的行标红。返回 (条数, 带截图条数)。"""
    from electrical_krow.arch_shots import render_shots

    sheet.append(list(REQ_COLUMNS))
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
    stamp = now.strftime("%Y%m%d")
    # 先按文件把截图批量渲染
    pngs: dict[int, bytes] = {}
    for doc in docs:
        pending = [(int(row[seq_col]), row[SHOT_SLOT]) for row in picked if row[file_col] == doc.name and len(row) > SHOT_SLOT and row[SHOT_SLOT] is not None]
        if not pending:
            continue
        rendered = render_shots(Path(doc.path), [shot for _, shot in pending]) if doc.path or any(shot.png for _, shot in pending) else [shot.png for _, shot in pending]
        for (seq, _), png in zip(pending, rendered):
            if png:
                pngs[seq] = png
    shots = 0
    flagged: list[int] = []
    for number, row in enumerate(picked, start=1):
        seq = int(row[seq_col])
        section = str(row[sec_col] or "")
        item = str(row[item_col] or "")
        text = str(row[text_col] or "")
        excerpt = f"{item}：{text}" if item and not text.startswith(item) else text
        sheet.append([
            f"REQ-{stamp}-{number:03d}", "", section, "", excerpt[:_EXCERPT_CAP], row[qty_col] or "", row[cond_col] or "",
            suggest_category(section, f"{item} {text}"), "", "", STATUS_PENDING, "", row[note_col] or "", row[page_col],
        ])
        at = sheet.max_row
        if seq in conflict_seqs:
            flagged.append(at)
        png = pngs.get(seq)
        if not png:
            continue
        image = _scaled_xl_image(png, _REQ_SHOT_MAX_PX, _REQ_SHOT_MAX_H_PX)
        # 行高按 1px = 1pt + 上下余量给足：macOS WPS 下图片按 1px≈1pt 渲染也不会压到下一行
        sheet.row_dimensions[at].height = min(_MAX_ROW_HEIGHT, image.height + _REQ_SHOT_ROW_PAD)
        _place_image(sheet, image, REQ_COLUMNS.index("SR content\n原文截图") + 1, at)
        shots += 1
    heights = {r: sheet.row_dimensions[r].height for r in range(2, sheet.max_row + 1) if sheet.row_dimensions[r].height}
    _style_sheet(
        sheet, 1,
        {"A": 20, "B": 9, "C": 26, "D": _REQ_SHOT_COL_WIDTH, "E": 50, "F": 28, "G": 26, "H": 16, "I": 36, "J": 12, "K": 12, "L": 36, "M": 36, "N": 9},
        body_height=46,
    )
    for r, height in heights.items():
        sheet.row_dimensions[r].height = max(height, sheet.row_dimensions[r].height or 0)
    for r in flagged:
        for cell in sheet[r]:
            cell.fill = _DIFF_FILL
    return len(picked), shots


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
    _style_sheet(sheet, 1, {"A": 8, "B": 14, "C": 36, "D": 10, "E": 26, "F": 14, "G": 90, "H": 92, "I": 30}, body_height=60)
    # 图高决定行高，样式里按文字算的行高要让位
    for row, height in heights.items():
        sheet.row_dimensions[row].height = max(height, sheet.row_dimensions[row].height or 0)
    return count


def build_contrast(sources: list[Path], dest: Path, ask=None, now: datetime | None = None) -> ContrastResult:
    docs: list[SourceDoc] = []
    unreadable: list[Unreadable] = []
    for path in sources:
        read = read_pdf_pages(Path(path))
        if isinstance(read, Unreadable):
            unreadable.append(read)
        else:
            docs.append(read)
    return write_contrast(docs, unreadable, dest, ask, now)


def contrast_file_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"架构对照-{stamp}.xlsx"
