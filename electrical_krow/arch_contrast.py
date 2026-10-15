"""电驱需求拆解：把当份需求文件按条款拆成可回溯的材料对照稿。

每条要求一条：行首「1)」「•」「※」等标记起一条，没有标记的页整页一条。原文只来自该页可复制文字。
章节按行首的目录章节号认，本页没有标题时沿用上一页。数值与单位、括注条件从该条原文里机械挑出，不是认条，须对照原文。
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
SHEET_ROWS = "条目对照"
SHEET_TABLES = "整表附件"
SHEET_MISSING = "未能读取"

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
    "原文摘录",
    "数值与单位",
    "适用条件（原文括注）",
    "状态",
    "责任人",
    "客户反馈",
    "能否满足",
    "备注",
)
_TABLE_COLUMNS = ("序号", "对象", "文件", "PDF页码", "整表原文", "备注")
_MISSING_COLUMNS = ("文件", "页数", "原因")

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
_HEADER_FONT = Font(name="宋体", bold=True, color="FFFFFF", size=11)
_BODY_FONT = Font(name="宋体", size=10)
_WRAP = Alignment(wrap_text=True, vertical="top")
_THIN = Border(
    left=Side(style="thin", color="D9D9D9"),
    right=Side(style="thin", color="D9D9D9"),
    top=Side(style="thin", color="D9D9D9"),
    bottom=Side(style="thin", color="D9D9D9"),
)


@dataclass(frozen=True)
class SourceDoc:
    """一份已读出文字的 PDF。pages 为 (PDF 页码, 原文)。"""

    name: str
    pages: tuple[tuple[int, str], ...]


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


def _text(value: object) -> str:
    return str(value or "").strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
                pages.append((index, page.extract_text() or ""))
            except Exception:  # noqa: BLE001
                pages.append((index, ""))
    except Exception:  # noqa: BLE001
        return Unreadable(path.name, 0, "文件打不开，不是可读的 PDF。")
    if not pages:
        return Unreadable(path.name, 0, "PDF 没有页面。")
    if sum(len(_compact(text)) for _, text in pages) < _MIN_TEXT:
        return Unreadable(path.name, len(pages), "没有文字层，未拆条，未补写内容。")
    return SourceDoc(path.name, tuple(pages))


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


def quantities(text: str) -> str:
    """原文里带单位的数，按出现顺序以「；」连接。只认数字紧跟常见工程单位的写法，是机械挑出，不是认条。"""
    found: list[str] = []
    for match in _QUANTITY.finditer(text or ""):
        item = _compact(match.group(0))
        if item not in found:
            found.append(item)
    return "；".join(found)


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


def split_document(doc: SourceDoc) -> tuple[list[list[object]], list[list[object]]]:
    """按条款拆条。返回 (条目行, 整表行)，序号由调用方补。"""
    boilerplate = boilerplate_lines(doc.pages)
    heads, toc_pages = toc_headings(doc.pages)
    obj = object_of(doc)
    total = len(doc.pages)
    drop_hangul = hangul_is_minor(doc.pages)
    rows: list[list[object]] = []
    tables: list[list[object]] = []

    def row(index: int, inner: str, section: str, mark: str, text: str, note: str) -> list[object]:
        return [None, obj, doc.name, index, inner, section, mark, text, quantities(text), conditions(text), STATUS_PENDING, "", "", "", note]

    carried = ""  # 上一页末尾所在的章节；本页没有标题时沿用
    for index, raw in doc.pages:
        inner = inner_page(raw, total)
        body = page_body(raw, boilerplate, inner, drop_hangul=drop_hangul)
        if index == 1 and toc_pages:
            # 有目录的整本文件，第一页是封面。单独的附表没有封面。
            section = SECTION_COVER
        elif index in toc_pages:
            section = SECTION_TOC
        else:
            section = ""
        if section in {SECTION_COVER, SECTION_TOC}:
            text, note = _excerpt(body, keep_short=True)
            rows.append([None, obj, doc.name, index, inner, section, "", text, "", "", STATUS_PENDING, "", "", "", note])
            continue
        found = page_headings(body, heads)
        section = found[0] if found else carried
        carry_note = "" if found or not carried else "章节沿用上一页"
        if is_table_page(body):
            tables.append([None, obj, doc.name, index, body, "整页保留，不拆成单条，不判断是否满足"])
            rows.append(
                [None, obj, doc.name, index, inner, section, "", f"本页为数值表，整页见「{SHEET_TABLES}」。", "", "", STATUS_PENDING, "", "", "", "不拆成单条需求"]
            )
            carried = found[-1] if found else carried
            continue
        if len(_compact(body)) < _MIN_TEXT:
            text, note = _excerpt(body, keep_short=False)
            rows.append([None, obj, doc.name, index, inner, section, "", text, "", "", STATUS_PENDING, "", "", "", _join_notes(note, carry_note)])
            carried = found[-1] if found else carried
            continue
        clauses = split_clauses(body, heads, carried)
        if clauses:
            carried = clauses[-1][0] or carried
        if len(clauses) <= 1:
            # 整页没有条款标记：整页一条，原文保留换行
            text, note = _excerpt(body, keep_short=True)
            rows.append(row(index, inner, section, "", text, _join_notes(note or "本页无条款标记，整页一条", carry_note)))
            continue
        for sec, mark, text in clauses:
            sec = sec or section
            if is_table_block(text):
                # 坐标轴刻度、反复出现的表头：整块进整表附件，条目里留一条索引，不取数
                tables.append([None, obj, doc.name, index, text, "条内表格块，整块保留，不拆成单条，不判断是否满足"])
                hint = _compact(text)[:60]
                rows.append(
                    [None, obj, doc.name, index, inner, sec, mark, f"{hint}……（表格块，整块见「{SHEET_TABLES}」）", "", "", STATUS_PENDING, "", "", "", "表格块，不拆成单条需求"]
                )
                continue
            note = ""
            if len(text) > _EXCERPT_CAP:
                text, note = text[:_EXCERPT_CAP] + "……（其余见原 PDF）", f"摘录在 {_EXCERPT_CAP} 字处截断"
            rows.append(row(index, inner, sec, mark, text, _join_notes(note, carry_note)))
    return rows, tables


def _join_notes(*notes: str) -> str:
    return "；".join(note for note in notes if note)


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
        sheet.row_dimensions[cells[0].row].height = body_height
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


def write_contrast(docs: list[SourceDoc], unreadable: list[Unreadable], dest: Path) -> ContrastResult:
    if not docs:
        raise ValueError("所选文件都读不出文字，无法拆条。")
    book = Workbook()
    note = book.active
    note.title = SHEET_NOTE
    sources = "；".join(f"{doc.name}（{len(doc.pages)} 页）" for doc in docs)
    lines = [
        ("用途", "把需求文件按条款拆成条目，供人工逐条确认。本表只摘原文，不写能否满足。"),
        ("来源文件", sources),
        ("拆分方式", "行首「1)」「•」「※」等标记各起一条；标记前的短引导句并入其后那条；整页没有标记的按整页一条。原文只来自该页可复制文字。章节按行首的目录章节号和标题词认；本页没有标题的沿用上一页末尾的章节并在备注注明，文件开头还没有章节的留空。"),
        ("数值与条件", "「数值与单位」是从该条原文里机械挑出的带单位的数，「适用条件（原文括注）」是原文括号里带数或带条件词的话。两列都不是认条，不改写、不换算，须对照「原文摘录」核对。"),
        ("整表", f"数值占一半以上的页按整页保留在「{SHEET_TABLES}」；一条里全是刻度或反复表头的表格块也整块放入，条目里只留索引。页眉页脚、页码和保密声明行不算原文。"),
        ("留空栏目", "状态一律为待确认。责任人、客户反馈、能否满足由确认人填写。"),
        ("未能读取", "没有文字层或读不开的文件列在「" + SHEET_MISSING + "」，未补写内容。" if unreadable else "所选文件均已读出文字。"),
    ]
    note.append(["项目", "内容"])
    for item in lines:
        note.append(list(item))
    _style_sheet(note, 1, {"A": 18, "B": 108}, body_height=36)
    note.page_setup.fitToHeight = 1
    note.auto_filter.ref = None

    rows_sheet = book.create_sheet(SHEET_ROWS)
    rows_sheet.append(list(COLUMNS))
    tables_sheet = book.create_sheet(SHEET_TABLES)
    tables_sheet.append(list(_TABLE_COLUMNS))
    row_seq = 0
    table_seq = 0
    for doc in docs:
        rows, tables = split_document(doc)
        for row in rows:
            row_seq += 1
            row[0] = row_seq
            rows_sheet.append(row)
        for row in tables:
            table_seq += 1
            row[0] = table_seq
            tables_sheet.append(row)
    _style_sheet(
        rows_sheet,
        1,
        {
            "A": 8, "B": 12, "C": 36, "D": 9, "E": 9, "F": 30, "G": 8, "H": 70, "I": 24, "J": 30,
            "K": 10, "L": 12, "M": 14, "N": 12, "O": 24,
        },
    )
    _style_sheet(tables_sheet, 1, {"A": 8, "B": 14, "C": 40, "D": 10, "E": 110, "F": 30}, body_height=60)

    missing = book.create_sheet(SHEET_MISSING)
    missing.append(list(_MISSING_COLUMNS))
    for item in unreadable:
        missing.append([item.name, item.pages or "", item.reason])
    _style_sheet(missing, 1, {"A": 60, "B": 10, "C": 60}, body_height=32)
    missing.page_setup.fitToHeight = 1

    book.active = book[SHEET_ROWS]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    book.save(dest)
    book.close()
    return ContrastResult(dest, len(docs), row_seq, table_seq, tuple(unreadable))


def build_contrast(sources: list[Path], dest: Path) -> ContrastResult:
    docs: list[SourceDoc] = []
    unreadable: list[Unreadable] = []
    for path in sources:
        read = read_pdf_pages(Path(path))
        if isinstance(read, Unreadable):
            unreadable.append(read)
        else:
            docs.append(read)
    return write_contrast(docs, unreadable, dest)


def contrast_file_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"架构对照-{stamp}.xlsx"
