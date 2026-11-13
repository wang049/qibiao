"""按客户《电机控制需求清单》写出可核对 Excel。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.pagebreak import Break

from electrical import schema as _schema
from electrical.pending_rulings import (
    apply_pending_rulings,
    note_without_pending,
    pending_text,
)
from electrical.schema import (
    ExtractedCell,
    STATUS_FIX,
    STATUS_FOUND,
    STATUS_MISS,
    STATUS_NA,
    STATUS_PARTIAL,
    STATUS_PASS,
    VALUE_MARKERS,
    finalize_retrieval_statuses,
    item_group,
    load_template_fields,
    review_item_no,
    template_title,
)

HEADERS = (
    "核对状态",
    "分组",
    "需求序号",
    "需求条目",
    "抽出值",
    "页码",
    "条款号",
    "原文摘录",
    "人工填写",
    "复核备注",
    "置信度",
)

SHEET_COVER = "01_封面"
SHEET_MAIN = "02_需求核对"
SHEET_REVIEW = "03_提取质量审查"
SHEET_OFF = "04_清单外"
SHEET_GUIDE = "05_条目说明"
SHEET_ORDER = (SHEET_COVER, SHEET_MAIN, SHEET_REVIEW, SHEET_OFF, SHEET_GUIDE)

GUIDE_HEADERS = (
    "需求序号",
    "需求条目",
    "需求说明",
    "必要性及影响",
    "参考示例（非本份抽出）",
)

OFF_LIST_HEADERS = (
    "名称",
    "抽出值",
    "页码",
    "条款号",
    "原文摘录",
)

REVIEW_CHOICES = (
    f'"{STATUS_FOUND},{STATUS_MISS},局部对应,'
    f'{STATUS_PASS},{STATUS_FIX},{STATUS_NA}"'
)
YELLOW = PatternFill("solid", fgColor="F6CACA")
PARTIAL_FILL = PatternFill("solid", fgColor="F8D48A")
FILLED = PatternFill("solid", fgColor="D4EDDA")
HEADER_FILL = PatternFill("solid", fgColor="142B49")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="微软雅黑", size=12)
TITLE_FONT = Font(bold=True, size=22, name="微软雅黑", color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=11, color="263445")
VALUE_FONT = Font(name="微软雅黑", size=11, bold=True, color="142B49")
FOUND_FONT = Font(name="微软雅黑", size=11, bold=True, color="146C43")
PARTIAL_FONT = Font(name="微软雅黑", size=11, bold=True, color="8A5A12")
MISS_FONT = Font(name="微软雅黑", size=11, bold=True, color="B42318")
MARKER_FONT = Font(name="微软雅黑", size=11, color="7B8794", italic=True)
# 复核备注里带「待专家口径」的格子用深红标出来，和普通备注区分
PENDING_FONT = Font(name="微软雅黑", size=10, color="9C0006")
_BAND = PatternFill("solid", fgColor="D9E4F2")
_PAPER_FILL = PatternFill("solid", fgColor="FFFFFF")
_INPUT_FILL = PatternFill("solid", fgColor="C5D8F0")
_EXAMPLE_FILL = PatternFill("solid", fgColor="D5DCE3")
_NOTE_FONT = Font(name="微软雅黑", size=10, color="5C6B7A")
_NAME_FONT = Font(name="微软雅黑", size=11, bold=True, color="142B49")
_MUTED_FONT = Font(name="微软雅黑", size=10, color="5C6B7A")
WRAP = Alignment(wrap_text=True, vertical="top")
_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


# 冻结到 E：左侧是条目栏。原文摘录约占半张表，抽出和复核是窄栏。
COL_WIDTHS = (11, 11, 6, 22, 28, 8, 11, 136, 18, 20, 8)
GUIDE_WIDTHS = (8, 22, 26, 24, 78)
OFF_LIST_WIDTHS = (20, 26, 8, 12, 108)
_GROUPS_MAIN = (
    (1, 4, "条目", "142B49"),
    (5, 7, "抽出", "1B4F72"),
    (8, 8, "原文", "2878B9"),
    (9, 11, "复核", "1E4D3A"),
)
_GROUPS_OFF = (
    (1, 2, "要求", "142B49"),
    (3, 4, "位置", "1B4F72"),
    (5, 5, "原文", "2878B9"),
)
_GROUPS_GUIDE = (
    (1, 2, "条目", "142B49"),
    (3, 4, "说明", "1B4F72"),
    (5, 5, "示例", "5C6B7A"),
)
_READ_FILL = PatternFill("solid", fgColor="FBF6EE")
_POS_FILL = PatternFill("solid", fgColor="E7EEF6")
_NOTE_FILL = PatternFill("solid", fgColor="F4F6F8")
_RAIL_FILL = PatternFill("solid", fgColor="F4F7FB")
_FIELD_TONE = {
    "142B49": ("E8EEF5", "142B49"),
    "1B4F72": ("E5F0F7", "1B4F72"),
    "2878B9": ("E7F1FA", "1B4F72"),
    "1E4D3A": ("E7F6EE", "1E4D3A"),
    "5C6B7A": ("EEF1F4", "3D4A57"),
}
LINE_PT = 18
MIN_ROW_PT = 26
_RECORD_FLOOR = 48
MAX_ROW_PT = 409


def _clean_text(text: str) -> str:
    value = _WS.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    return _NL.sub("\n\n", value).strip()


_STORED_PREFIX = re.compile(r"^[0-9a-f]{8}_", re.I)


def _display_source_name(name: str) -> str:
    """说明页写上传时的文件名。落盘名前面的 8 位记号不给工程师看。"""
    text = Path(name or "").name
    shown = _STORED_PREFIX.sub("", text, count=1)
    return shown or text


def _lexicon_kb_version() -> str:
    fn = getattr(_schema, "lexicon_knowledge_version", None)
    if not callable(fn):
        return ""
    return str(fn() or "").strip()


def _knowledge_version_label(explicit: str = "") -> str:
    for candidate in (
        (explicit or "").strip(),
        (os.environ.get("SPEC_SHEET_KB_VERSION") or "").strip(),
        _lexicon_kb_version(),
    ):
        if candidate:
            return candidate
    return "未发布"


def _display_units(text: str) -> float:
    width = 0.0
    for char in text or "":
        width += 2.0 if ord(char) > 127 else 1.0
    return width


def _wrapped_lines(text: str, col_width: float) -> int:
    usable = max(col_width - 1.8, 8)
    lines = 0
    for para in str(text or "").split("\n"):
        units = _display_units(para) or 1.0
        lines += max(1, int((units + usable - 0.01) // usable))
    return max(1, lines)


def _row_height(
    values: list[object],
    widths: tuple[float, ...] = COL_WIDTHS,
    *,
    limit_lines: int = 0,
    floor: float | None = None,
) -> float:
    lines = 1
    for item, width in zip(values, widths):
        lines = max(lines, _wrapped_lines(item, width))
    if limit_lines:
        lines = min(lines, limit_lines)
    elif lines > 1:
        # 按字宽估行数容易少一行，最后一行会被行高裁掉。
        lines += 1
    return max(floor if floor is not None else MIN_ROW_PT, min(MAX_ROW_PT, 6 + lines * LINE_PT))


def _status_label(status: str) -> str:
    """核对表状态列用短词，避免「局部对应/需人工复核」把行撑高。"""
    if status == STATUS_PARTIAL:
        return "局部对应"
    return status


def _status_from_sheet(text: str) -> str:
    if text == "局部对应":
        return STATUS_PARTIAL
    return text


_GRID = Border(
    left=Side(style="thin", color="DCE3EB"),
    right=Side(style="thin", color="DCE3EB"),
    top=Side(style="thin", color="DCE3EB"),
    bottom=Side(style="thin", color="DCE3EB"),
)
_NAVY = PatternFill("solid", fgColor="142B49")
_HUMAN_FILL = PatternFill("solid", fgColor="A9D7B8")
_HUMAN_FONT = Font(bold=True, color="142B49", name="微软雅黑", size=12)
_HEAD_EDGE = Border(
    left=Side(style="thin", color="142B49"),
    right=Side(style="thin", color="142B49"),
    top=Side(style="thin", color="142B49"),
    bottom=Side(style="medium", color="2878B9"),
)
_CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")


def _field_tone(color: str) -> tuple[str, str]:
    return _FIELD_TONE.get(color, ("E8EEF5", "142B49"))


def _panel_border(col: int, *, section: bool) -> Border:
    """四块阅读区用竖线分开。分组换了，这一行顶上加一道横线。"""
    top = Side(style="medium", color="142B49") if section else Side(style="thin", color="E6EBF1")
    left_on = col in {1, 5, 8, 9}
    return Border(
        left=Side(style="medium" if left_on else "thin", color="142B49" if left_on else "E6EBF1"),
        right=Side(style="thin", color="E6EBF1"),
        top=top,
        bottom=Side(style="thin", color="E6EBF1"),
    )


def _write_group_row(ws, row: int, groups: tuple) -> None:
    """分区表头。只标阅读分区，不增加业务字段。"""
    font = Font(name="微软雅黑", size=13, bold=True, color="FFFFFF")
    align = Alignment(horizontal="left", vertical="center", indent=1)
    for start, end, label, color in groups:
        ws.merge_cells(start_row=row, start_column=start, end_row=row, end_column=end)
        fill = _solid(color)
        edge = Border(
            left=Side(style="thin", color=color),
            right=Side(style="thin", color=color),
            top=Side(style="thin", color=color),
            bottom=Side(style="medium", color="FFFFFF"),
        )
        for col in range(start, end + 1):
            cell = ws.cell(row, col, label if col == start else None)
            cell.font = font
            cell.fill = fill
            cell.alignment = align
            cell.border = edge
    ws.row_dimensions[row].height = 32


def _group_color(col: int, groups: tuple) -> str:
    for start, end, _label, color in groups:
        if start <= col <= end:
            return color
    return "142B49"


def _mark_border(ink: str, *, section: bool = False) -> Border:
    return Border(
        left=Side(style="medium", color=ink),
        right=Side(style="thin", color="E6EBF1"),
        top=Side(style="medium" if section else "thin", color="142B49" if section else "E6EBF1"),
        bottom=Side(style="thin", color="E6EBF1"),
    )


def _navy_title(ws, text: str, cols: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
    font = Font(name="微软雅黑", size=22, bold=True, color="FFFFFF")
    align = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, cols + 1):
        cell = ws.cell(1, col, text if col == 1 else None)
        cell.font = font
        cell.fill = _NAVY
        cell.alignment = align
        cell.border = _HEAD_EDGE
    ws.row_dimensions[1].height = 52


def _page_number(ws) -> None:
    ws.oddFooter.center.text = "第 &P 页 / 共 &N 页"
    ws.oddFooter.center.font = "微软雅黑"
    ws.oddFooter.center.size = 9
    ws.evenFooter.center.text = "第 &P 页 / 共 &N 页"
    ws.evenFooter.center.font = "微软雅黑"
    ws.evenFooter.center.size = 9


def _dress_sheet(ws, tab: str, *, fit_width: bool = True, zoom: int = 110) -> None:
    ws.sheet_properties.tabColor = tab
    ws.sheet_view.zoomScale = zoom
    ws.sheet_view.view = "normal"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.pageOrder = "downThenOver"
    if fit_width:
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    else:
        ws.page_setup.fitToWidth = 0
        ws.page_setup.fitToHeight = 0
        ws.page_setup.scale = 100
        ws.sheet_properties.pageSetUpPr.fitToPage = False
    ws.page_setup.horizontalCentered = True
    ws.print_title_rows = "1:2"
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.55
    ws.page_margins.bottom = 0.5
    ws.page_margins.header = 0.25
    ws.page_margins.footer = 0.25
    ws.oddHeader.left.text = ws.title
    ws.oddHeader.left.font = "微软雅黑"
    ws.oddHeader.left.size = 9
    _page_number(ws)
    last = get_column_letter(ws.max_column or 1)
    ws.print_area = f"A1:{last}{max(ws.max_row, 1)}"


def _order_sheets(book: Workbook) -> None:
    for index, name in enumerate(SHEET_ORDER):
        if name not in book.sheetnames:
            continue
        book.move_sheet(name, offset=index - book.sheetnames.index(name))


def _find_sheet(book: Workbook, *names: str):
    for name in names:
        if name in book.sheetnames:
            return book[name]
    return None


def _display_value(row: ExtractedCell, status: str = "") -> str:
    text = _clean_text(row.value)
    unit = (row.unit or "").strip()
    if unit and unit not in text:
        text = f"{text} {unit}".strip()
    if text:
        return text
    st = status or _review_status(row)
    if st == STATUS_MISS:
        return STATUS_MISS
    if st == STATUS_PARTIAL:
        return STATUS_PARTIAL
    return ""


def _review_status(row: ExtractedCell) -> str:
    status = (row.review_status or "").strip()
    if status in {
        STATUS_FOUND,
        STATUS_MISS,
        STATUS_PARTIAL,
        STATUS_PASS,
        STATUS_FIX,
        STATUS_NA,
    }:
        return status
    if status == "不适用":
        return STATUS_NA
    has_val = bool((row.value or "").strip())
    plain_note = note_without_pending(row.note)
    has_note = bool(plain_note)
    if has_val:
        if row.confidence < 0.8 or has_note:
            return STATUS_PARTIAL
        return STATUS_FOUND
    if has_note and plain_note.startswith("企标方法对照"):
        return STATUS_MISS
    if has_note:
        return STATUS_PARTIAL
    return STATUS_MISS


def _write_off_list_sheet(wb: Workbook, cells: list[ExtractedCell], *, extract: bool) -> int:
    from electrical.extract import is_off_list_requirement

    ws = wb.create_sheet(SHEET_OFF)
    last = get_column_letter(len(OFF_LIST_HEADERS))
    _navy_title(ws, "当份原文里对不上清单的要求", len(OFF_LIST_HEADERS))
    _write_group_row(ws, 2, _GROUPS_OFF)
    for col, name in enumerate(OFF_LIST_HEADERS, start=1):
        cell = ws.cell(3, col, name)
        wash, ink = _field_tone(_group_color(col, _GROUPS_OFF))
        cell.fill = _solid(wash)
        cell.font = Font(name="微软雅黑", size=10, bold=True, color=ink)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = _HEAD_EDGE
    ws["B3"].comment = Comment(
        "只写当份规格书原文。不用知识库、清单示例或常识补格。"
        "能对上 1–120 的要求不出现在本页。",
        "KMind",
    )
    count = 0
    if extract:
        for row in cells:
            if not is_off_list_requirement(row):
                continue
            values = [
                _clean_text(row.name),
                _clean_text(row.value),
                _clean_text(row.page),
                _clean_text(getattr(row, "clause", "") or ""),
                _clean_text(row.excerpt),
            ]
            if not values[1]:
                continue
            ws.append(values)
            excel_row = ws.max_row
            ws.row_dimensions[excel_row].height = _row_height(values, OFF_LIST_WIDTHS, floor=36)
            band = _BAND if excel_row % 2 == 0 else _PAPER_FILL
            for col in range(1, len(OFF_LIST_HEADERS) + 1):
                cell = ws.cell(excel_row, col)
                cell.font = VALUE_FONT if col == 2 else (_NAME_FONT if col == 1 else BODY_FONT)
                if col == 5:
                    cell.alignment = Alignment(wrap_text=True, vertical="top", indent=2)
                else:
                    cell.alignment = _CENTER if col in {3, 4} else WRAP
                cell.border = _panel_border(5 if col == 5 else 2, section=False) if col == 5 else _GRID
                if col == 2:
                    cell.fill = FILLED
                elif col == 5:
                    cell.fill = _READ_FILL
                else:
                    cell.fill = band
            count += 1
    for idx, width in enumerate(OFF_LIST_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.auto_filter.ref = f"A3:{last}{max(ws.max_row, 3)}"
    ws.freeze_panes = "A4"
    ws.row_dimensions[3].height = 32
    _dress_sheet(ws, "4A6FA5")
    ws.print_title_rows = "1:3"
    return count


def write_review_workbook(
    cells: list[ExtractedCell],
    output_path: Path,
    *,
    source_name: str,
    likely_scan: bool,
    parser: str,
    kind_label: str = "",
    kind_note: str = "",
    extract: bool = True,
    family: str = "",
    coverage: str = "",
    model: str = "",
    knowledge_version: str = "",
    extract_warning: str = "",
    qa=None,
) -> Path:
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from electrical.extract import scrub_cells_ocr_notes

    scrub_cells_ocr_notes(cells)
    # 还没定口径的格子在复核备注里标「待专家口径：…」；不改抽出值和检索结论
    if extract:
        apply_pending_rulings(cells, family)
    n_pending = sum(1 for c in cells if not c.extra and pending_text(c.note)) if extract else 0
    finalize_retrieval_statuses(cells)

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_MAIN

    last_col = get_column_letter(len(HEADERS))
    _navy_title(ws, "电控设计需求核对", len(HEADERS))
    _write_group_row(ws, 2, _GROUPS_MAIN)

    for col, name in enumerate(HEADERS, start=1):
        cell = ws.cell(3, col, name)
        human = name == "人工填写"
        if human:
            cell.fill = _HUMAN_FILL
            cell.font = _HUMAN_FONT
        else:
            wash, ink = _field_tone(_group_color(col, _GROUPS_MAIN))
            cell.fill = _solid(wash)
            cell.font = Font(name="微软雅黑", size=10, bold=True, color=ink)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = _HEAD_EDGE
    ws["E3"].comment = Comment(
        "本份规格书抽出的值。"
        "「未检索到」「局部对应/需人工复核」为检索结论占位，不是规格书原文。"
        "不要用「05_条目说明」里的参考示例顶替。"
        "缺项可由当份规格书已出现的量按公式算出，状态为局部对应；所用公式写在「复核备注」。"
        "当份未给出、条目需参考试验方法标准时，抽出值显示未检索到，方法号写在复核备注。",
        "KMind",
    )
    ws["F3"].comment = Comment(
        "打开后印在页眉或页脚上的页码。例如 60 (116) 填 60。不是条款号。",
        "KMind",
    )
    ws["G3"].comment = Comment(
        "正文条款号，如 2.3.3.3、6.5.11.1。没有则空。",
        "KMind",
    )
    ws["I3"].comment = Comment(
        "核对后在此填写认定的正确值（含单位）。",
        "KMind",
    )
    ws["J3"].comment = Comment(
        "公式推算的格子在此写清用了哪条公式、代入了原文哪些量。"
        "例如：由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）。"
        "当份未给出、需参考试验方法的格子：抽出值未检索到，复核备注写企标方法对照。"
        "抽出值只写当份算出的数，不把定律名称或方法号写进去。",
        "KMind",
    )
    ws["A3"].comment = Comment(
        "检索结论三类：已检索到 / 未检索到 / 局部对应需人工复核。"
        "人工核对后再改为：通过 / 需修改 / 不适用。",
        "KMind",
    )

    n_found = 0
    n_miss = 0
    n_partial = 0
    template_n = 0
    previous_group = None
    # 入口仍传入解析器/模型/覆盖说明，但不写入甲方可见的说明页。
    _ = (likely_scan, parser, family, coverage, model)
    for row in cells:
        if row.extra:
            continue
        template_n += 1
        status = _review_status(row)
        if status == STATUS_FOUND:
            n_found += 1
        elif status == STATUS_MISS:
            n_miss += 1
        elif status == STATUS_PARTIAL:
            n_partial += 1
        display = _display_value(row, status)
        item_no = review_item_no(row.seq)
        values = [
            _status_label(status),
            item_group(row.name, row.seq),
            item_no or "",
            row.name,
            display,
            _clean_text(row.page),
            _clean_text(getattr(row, "clause", "") or ""),
            _clean_text(row.excerpt),
            "",
            _clean_text(row.note),
            row.confidence if (row.value or "").strip() else None,
        ]
        group_name = values[1]
        section = group_name != previous_group
        previous_group = group_name
        ws.append(values)
        excel_row = ws.max_row
        if section and excel_row > 4:
            ws.row_breaks.append(Break(id=excel_row - 1))
        dim = ws.row_dimensions[excel_row]
        dim.height = _row_height(values, COL_WIDTHS, floor=_RECORD_FLOOR)
        for col in range(1, len(HEADERS) + 1):
            cell = ws.cell(excel_row, col)
            if col == 4:
                cell.font = _NAME_FONT
            elif col == 5:
                cell.font = VALUE_FONT
            elif col == 2:
                cell.font = _MUTED_FONT
            else:
                cell.font = BODY_FONT
            if col == 8:
                cell.alignment = Alignment(wrap_text=True, vertical="top", indent=2)
            elif col in {1, 3, 6, 7, 11}:
                cell.alignment = _CENTER
            else:
                cell.alignment = Alignment(wrap_text=True, vertical="top", indent=1)
            cell.border = _panel_border(col, section=section)
            if col == 9:
                cell.fill = _INPUT_FILL
            elif col == 8:
                cell.fill = _READ_FILL
            elif col in {6, 7}:
                cell.fill = _POS_FILL
            elif col in {10, 11}:
                cell.fill = _NOTE_FILL
            elif col not in {1, 5}:
                cell.fill = _RAIL_FILL
        conf = ws.cell(excel_row, 11)
        if conf.value not in (None, ""):
            conf.font = _MUTED_FONT
            conf.alignment = _CENTER
        value_cell = ws.cell(excel_row, 5)
        status_cell = ws.cell(excel_row, 1)
        if status == STATUS_PARTIAL:
            value_cell.font = PARTIAL_FONT if (row.value or "").strip() else MARKER_FONT
            value_cell.fill = PARTIAL_FILL
            status_cell.font = PARTIAL_FONT
            status_cell.fill = PARTIAL_FILL
            status_cell.border = _mark_border("8A5A12", section=section)
            value_cell.border = _mark_border("8A5A12", section=section)
        elif extract and status == STATUS_MISS:
            value_cell.font = MARKER_FONT
            value_cell.fill = YELLOW
            status_cell.font = MISS_FONT
            status_cell.fill = YELLOW
            status_cell.border = _mark_border("B42318", section=section)
            value_cell.border = _mark_border("B42318", section=section)
        elif (row.value or "").strip():
            value_cell.font = VALUE_FONT
            value_cell.fill = FILLED
            status_cell.font = FOUND_FONT
            status_cell.fill = FILLED
            status_cell.border = _mark_border("146C43", section=section)
            value_cell.border = _mark_border("146C43", section=section)
        note_text = _clean_text(row.note)
        plain = note_without_pending(note_text)
        if plain.startswith("由物理公式计算") or plain.startswith("企标方法对照"):
            value_cell.comment = Comment(note_text, "KMind")
        elif pending_text(note_text):
            value_cell.comment = Comment(pending_text(note_text), "KMind")
        if pending_text(note_text):
            ws.cell(excel_row, 10).font = PENDING_FONT

    dv = DataValidation(type="list", formula1=REVIEW_CHOICES, allow_blank=True)
    dv.error = (
        "请选择：已检索到 / 未检索到 / 局部对应 / 通过 / 需修改 / 不适用"
    )
    dv.errorTitle = "核对状态"
    ws.add_data_validation(dv)
    if ws.max_row >= 4:
        dv.add(f"A4:A{ws.max_row}")

    for idx, width in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.sheet_format.defaultRowHeight = MIN_ROW_PT
    ws.auto_filter.ref = f"A3:{last_col}{ws.max_row}"
    ws.freeze_panes = "E4"
    ws.row_dimensions[3].height = 24
    _dress_sheet(ws, "2878B9", fit_width=False, zoom=90)
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.print_title_rows = "1:3"
    n_off = _write_off_list_sheet(wb, cells, extract=extract)

    guide = wb.create_sheet(SHEET_GUIDE)
    _navy_title(guide, "条目说明。这一页不是本份规格书的抽出值。", len(GUIDE_HEADERS))
    _write_group_row(guide, 2, _GROUPS_GUIDE)
    for col, name in enumerate(GUIDE_HEADERS, start=1):
        cell = guide.cell(3, col, name)
        wash, ink = _field_tone(_group_color(col, _GROUPS_GUIDE))
        cell.fill = _solid(wash)
        cell.font = Font(name="微软雅黑", size=10, bold=True, color=ink)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = _HEAD_EDGE
    for row in cells:
        if row.extra:
            continue
        vals = [
            review_item_no(row.seq) or "",
            row.name,
            _clean_text(row.hint),
            _clean_text(row.impact),
            _clean_text(row.example),
        ]
        guide.append(vals)
        excel_row = guide.max_row
        dim = guide.row_dimensions[excel_row]
        dim.height = _row_height(vals, GUIDE_WIDTHS)
        band = _BAND if excel_row % 2 == 0 else _PAPER_FILL
        for col in range(1, len(GUIDE_HEADERS) + 1):
            cell = guide.cell(excel_row, col)
            if col == 5:
                cell.font = _MUTED_FONT
                cell.fill = _EXAMPLE_FILL
                cell.alignment = Alignment(wrap_text=True, vertical="top", indent=2)
            elif col == 2:
                cell.font = _NAME_FONT
                cell.fill = band
            elif col == 4:
                cell.font = Font(name="微软雅黑", size=10, color="142B49")
                cell.fill = band
            else:
                cell.font = BODY_FONT
                cell.fill = band
            if col != 5:
                cell.alignment = _CENTER if col == 1 else WRAP
            cell.border = _panel_border(8, section=False) if col == 5 else _GRID
    for idx, width in enumerate(GUIDE_WIDTHS, start=1):
        guide.column_dimensions[get_column_letter(idx)].width = width
    guide.freeze_panes = "C4"
    guide.auto_filter.ref = f"A3:E{max(guide.max_row, 3)}"
    guide.row_dimensions[3].height = 24
    _dress_sheet(guide, "7B8794", zoom=100)
    guide.print_title_rows = "1:3"

    _write_cover_sheet(
        wb,
        source_name=source_name,
        kind_label=kind_label or "未标注",
        knowledge_version=_knowledge_version_label(knowledge_version),
        template_n=template_n,
        extract=extract,
        n_found=n_found if extract else 0,
        n_miss=n_miss if extract else 0,
        n_partial=n_partial if extract else 0,
        n_off=n_off if extract else 0,
        n_pending=n_pending if extract else 0,
        extract_warning=(extract_warning or "").strip(),
        kind_note=(kind_note or "").strip() if not extract else "",
    )
    _write_content_review_sheet(wb, qa)
    _order_sheets(wb)

    wb.save(output_path)
    return output_path


_COVER_COLS = 2
_INK = "142B49"
_TEAL = "0F766E"
_PAPER = "F7F8FA"
_LINE = Border(bottom=Side(style="thin", color="E6E8EC"))


def _solid(color: str) -> PatternFill:
    return PatternFill("solid", fgColor=color)


def _paint(ws, row: int, cols: int, fill: PatternFill) -> None:
    for col in range(1, cols + 1):
        ws.cell(row, col).fill = fill


def _span(ws, row: int, cols: int, text: str, font: Font, fill: PatternFill, height: float) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=cols)
    align = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, cols + 1):
        cell = ws.cell(row, col, text if col == 1 else None)
        cell.font = font
        cell.fill = fill
        cell.alignment = align
    ws.row_dimensions[row].height = height


_BOX = Border(
    left=Side(style="thin", color="DCE3EB"),
    right=Side(style="thin", color="DCE3EB"),
    top=Side(style="thin", color="DCE3EB"),
    bottom=Side(style="thin", color="DCE3EB"),
)
_LABEL_FILL = PatternFill("solid", fgColor="F3F6FA")


def _form_title(ws, text: str) -> None:
    ws.merge_cells("A1:B1")
    font = Font(name="微软雅黑", size=16, bold=True, color=_INK)
    align = Alignment(horizontal="left", vertical="center")
    cell = ws["A1"]
    cell.value = text
    cell.font = font
    cell.alignment = align
    ws["B1"].font = font
    ws["B1"].alignment = align
    ws.row_dimensions[1].height = 28


def _form_head(ws, row: int, left: str, right: str) -> None:
    for col, name in enumerate((left, right), start=1):
        cell = ws.cell(row, col, name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")
        cell.border = _BOX
    ws.row_dimensions[row].height = 24


def _form_row(ws, row: int, key: str, value: object, widths: tuple[float, float]) -> None:
    ws.cell(row, 1, key)
    ws.cell(row, 2, value)
    for col in range(1, 3):
        cell = ws.cell(row, col)
        cell.font = Font(name="微软雅黑", size=11, bold=col == 1, color="1F2933")
        cell.fill = _LABEL_FILL if col == 1 else _solid("FFFFFF")
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = _BOX
    ws.row_dimensions[row].height = _row_height([key, value], widths)


def _form_sheet(ws, widths: tuple[int, int]) -> None:
    ws.sheet_view.showGridLines = True
    ws.sheet_view.zoomScale = 100
    ws.sheet_view.view = "normal"
    ws.sheet_properties.tabColor = _INK
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.freeze_panes = "A3"
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.print_area = f"A1:B{max(ws.max_row, 1)}"
    ws.page_setup.horizontalCentered = True
    ws.sheet_format.defaultRowHeight = 22


def _sheet_frame(ws, tab: str, cols: int, widths: tuple[int, ...]) -> None:
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 120
    ws.sheet_properties.tabColor = tab
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = 0.55
    ws.page_margins.right = 0.55
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.45
    ws.sheet_view.view = "normal"
    ws.print_options.horizontalCentered = True
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.sheet_format.defaultRowHeight = 22
    ws.print_area = f"A1:{get_column_letter(cols)}{max(ws.max_row, 1)}"


_COUNT_FILL = {
    "已检索到": FILLED,
    "局部对应/需人工复核": PARTIAL_FILL,
    "未检索到": YELLOW,
    "清单外需求": PatternFill("solid", fgColor="EAF2FC"),
}


def _brief_title(ws, text: str, cols: int) -> None:
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
    font = Font(name="微软雅黑", size=20, bold=True, color="FFFFFF")
    align = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, cols + 1):
        cell = ws.cell(1, col, text if col == 1 else None)
        cell.font = font
        cell.fill = _solid(_INK)
        cell.alignment = align
    ws.row_dimensions[1].height = 44


def _brief_sheet(ws, widths: tuple[int, ...], *, landscape: bool) -> None:
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 120
    ws.sheet_view.view = "normal"
    ws.freeze_panes = "A3"
    ws.sheet_properties.tabColor = _INK
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.horizontalCentered = True
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.55
    ws.page_margins.bottom = 0.5
    ws.page_margins.header = 0.25
    ws.page_margins.footer = 0.25
    ws.sheet_view.view = "normal"
    ws.oddHeader.left.text = "需求核对"
    ws.oddHeader.left.font = "微软雅黑"
    ws.oddHeader.left.size = 9
    _page_number(ws)
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    last = get_column_letter(len(widths))
    ws.print_area = f"A1:{last}{max(ws.max_row, 1)}"
    ws.sheet_format.defaultRowHeight = 22
    ws.auto_filter.ref = None
    ws.sheet_view.showRowColHeaders = True
    ws.page_setup.scale = 100


def _cover_card(ws, row: int, key: str, value: object, hint: str, fill: str, ink: str, start: int = 1) -> None:
    wash = _solid(fill)
    edge = Border(
        left=Side(style="medium", color=ink),
        right=Side(style="thin", color="DCE3EB"),
        top=Side(style="thin", color="DCE3EB"),
        bottom=Side(style="thin", color="DCE3EB"),
    )
    hair = Border(
        left=Side(style="thin", color="DCE3EB"),
        right=Side(style="thin", color="DCE3EB"),
        top=Side(style="thin", color="DCE3EB"),
        bottom=Side(style="thin", color="DCE3EB"),
    )
    label = ws.cell(row, start, key)
    label.font = Font(name="微软雅黑", size=12, bold=True, color=ink)
    label.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    number = ws.cell(row, start + 1, value)
    number.font = Font(name="微软雅黑", size=32, bold=True, color=ink)
    number.alignment = Alignment(horizontal="center", vertical="center")
    note = ws.cell(row, start + 2, hint)
    note.font = Font(name="微软雅黑", size=11, color="5C6B7A")
    note.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
    for offset in range(3):
        cell = ws.cell(row, start + offset)
        cell.fill = wash
        cell.border = edge if offset == 0 else hair
    ws.row_dimensions[row].height = 96


def _cover_fact(ws, row: int, key: str, value: object, *, emphasize: bool = False, end_col: int = 3) -> None:
    hair = Border(bottom=Side(style="thin", color="DCE3EB"))
    label = ws.cell(row, 1, key)
    label.font = Font(name="微软雅黑", size=10, color="7B8794")
    label.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    label.fill = _solid("F3F6FA")
    label.border = hair
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=end_col)
    body = ws.cell(row, 2, value)
    body.font = Font(
        name="微软雅黑",
        size=12 if emphasize else 11,
        bold=emphasize,
        color="142B49" if emphasize else "263445",
    )
    body.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
    for col in range(2, end_col + 1):
        cell = ws.cell(row, col)
        cell.fill = _solid("FFFFFF")
        cell.border = hair
    text = "" if value is None else str(value)
    ws.row_dimensions[row].height = 28 if len(text) < 36 else min(52, 18 + 14 * ((len(text) // 36) + 1))


def _write_cover_sheet(
    wb: Workbook,
    *,
    source_name: str,
    kind_label: str,
    knowledge_version: str,
    template_n: int,
    extract: bool,
    n_found: int,
    n_miss: int,
    n_partial: int,
    n_off: int,
    n_pending: int,
    extract_warning: str,
    kind_note: str,
) -> None:
    """封面。两行统计卡中间空一行，文件信息仍从第 6 行起。不冻窗。"""
    cover = wb.create_sheet(SHEET_COVER, 0)
    widths = (24, 16, 34, 24, 16, 34)
    _brief_title(cover, "电控设计需求核对", 6)
    cover.row_dimensions[1].height = 64
    cover["A1"].font = Font(name="微软雅黑", size=24, bold=True, color="FFFFFF")
    cards = (
        ("已检索到", n_found, "D4EDDA", "146C43", "原文对上了。在「02_需求核对」里是绿色。"),
        ("局部对应/需人工复核", n_partial, "F8D48A", "8A5A12", "只对上一部分。琥珀底，看这一行原文。"),
        ("未检索到", n_miss, "F6CACA", "B42318", "当份没有写出这项。浅红底。"),
        ("清单外需求", n_off, "D6E4F5", "142B49", "在「04_清单外」。"),
    )
    placed = ((0, 2, 1), (1, 2, 4), (2, 4, 1), (3, 4, 4))
    for index, row, start in placed:
        key, value, fill, ink, hint = cards[index]
        _cover_card(cover, row, key, value, hint, fill, ink, start=start)
    for row in (3, 5):
        cover.row_dimensions[row].height = 20
    facts: list[tuple[str, object, bool]] = [
        ("源文件", _display_source_name(source_name), True),
        ("文档类型", kind_label, False),
        ("对照清单", template_title(), False),
        ("知识库版本", knowledge_version, False),
        ("清单条目", template_n, False),
    ]
    if extract and n_pending:
        facts.append(("待专家口径", f"{n_pending} 格。取值来自当份原文，填法还没定。", False))
    if extract_warning:
        facts.append(("识别完整性", extract_warning, False))
    if kind_note:
        facts.append(("说明", kind_note, False))
    facts.append(
        (
            "用法",
            "在「02_需求核对」里对抽出值和同一行的原文摘录。"
            "核对后把状态改成通过或需修改。「人工填写」留给核对后的值。",
            False,
        )
    )
    for offset, (key, value, emphasize) in enumerate(facts):
        _cover_fact(cover, 6 + offset, key, value, emphasize=emphasize, end_col=6)
    _brief_sheet(cover, widths, landscape=False)
    cover.freeze_panes = None
    cover.sheet_view.zoomScale = 110
    cover.sheet_view.topLeftCell = "A1"
    cover.sheet_properties.tabColor = "142B49"
    cover.page_setup.fitToHeight = 1
    cover.page_setup.orientation = "portrait"
    cover.oddHeader.left.text = "电控设计需求核对"
    cover.oddFooter.right.text = "电控设计需求核对"


def _write_content_review_sheet(wb: Workbook, qa) -> None:
    """当份正文里要对一下的地方。一条一行，类型和原句分开，不标等级。"""
    findings = list(getattr(qa, "content_findings", None) or [])
    if not findings:
        return
    sheet = wb.create_sheet(SHEET_REVIEW)
    widths = (8, 16, 10, 12, 120)
    _brief_title(sheet, "提取质量审查", 5)
    sheet.row_dimensions[1].height = 56
    sheet["A1"].font = Font(name="微软雅黑", size=22, bold=True, color="FFFFFF")
    sheet.merge_cells("A2:E2")
    lead = sheet.cell(
        2,
        1,
        f"共 {len(findings)} 条。先看类型，再对页码和条款号。抽出值在「02_需求核对」，不在这里改。",
    )
    lead.font = _NOTE_FONT
    lead.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, 6):
        sheet.cell(2, col).fill = _solid("EAF2FC")
        sheet.cell(2, col).border = Border(bottom=Side(style="thin", color="DCE3EB"))
    sheet.row_dimensions[2].height = 32
    _write_group_row(sheet, 3, ((1, 4, "位置", "142B49"), (5, 5, "问题", "2878B9")))
    headers = ("序号", "类型", "页码", "条款号", "要对照的地方")
    for col, name in enumerate(headers, start=1):
        cell = sheet.cell(4, col, name)
        wash, ink = _field_tone("2878B9" if col == 5 else "142B49")
        cell.font = Font(name="微软雅黑", size=10, bold=True, color=ink)
        cell.fill = _solid(wash)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = _HEAD_EDGE
    sheet.row_dimensions[4].height = 32
    kind_style = {
        "中英冲突": ("F8D48A", "8A5A12"),
        "内部不一致": ("F6CACA", "B42318"),
        "语义相反": ("F6CACA", "B42318"),
        "模板残留": ("D6E4F5", "142B49"),
        "占位未填": ("D9E4F2", "263445"),
        "日期格式": ("D9E4F2", "263445"),
        "空表": ("D9E4F2", "263445"),
    }
    for offset, item in enumerate(findings, start=1):
        row = 4 + offset
        wash, ink = kind_style.get(item.kind, ("FFFFFF", "1C1917"))
        page = str(getattr(item, "page", "") or "")
        clause = str(getattr(item, "clause", "") or "")
        values = (offset, item.kind, page, clause, item.text)
        fonts = (
            Font(name="微软雅黑", size=10, color="7B8794"),
            Font(name="微软雅黑", size=10, bold=True, color=ink),
            Font(name="微软雅黑", size=10, color="263445"),
            Font(name="微软雅黑", size=10, bold=True, color="142B49"),
            Font(name="微软雅黑", size=10, color="263445"),
        )
        for col, (value, font) in enumerate(zip(values, fonts), start=1):
            cell = sheet.cell(row, col, value)
            cell.font = font
            cell.fill = _solid(wash)
            cell.alignment = Alignment(
                horizontal="center" if col in {1, 3, 4} else "left",
                vertical="top",
                wrap_text=True,
            )
            cell.border = _GRID
        sheet.row_dimensions[row].height = max(32, _row_height(list(values), widths))
    _brief_sheet(sheet, widths, landscape=True)
    sheet.freeze_panes = "A5"
    sheet.auto_filter.ref = f"A4:E{4 + len(findings)}"
    sheet.sheet_view.zoomScale = 110
    sheet.sheet_properties.tabColor = "1F4E79"
    sheet.print_title_rows = "1:4"
    sheet.oddHeader.left.text = "提取质量审查"
    sheet.oddFooter.right.text = "提取质量审查"


def load_review_cells(path: Path) -> tuple[list[ExtractedCell], dict[str, str]]:
    """读已导出的核对表，便于改版式后重出（不重跑抽取）。"""
    wb = load_workbook(path, data_only=True)
    meta: dict[str, str] = {}
    cover = _find_sheet(wb, SHEET_COVER, "说明")
    if cover is not None:
        for row in cover.iter_rows(min_row=2, max_col=2, values_only=True):
            key, val = (list(row) + [None, None])[:2]
            if key:
                meta[str(key).strip()] = "" if val is None else str(val).strip()

    hint_by_seq: dict[int, tuple[str, str, str]] = {}
    guide_sheet = _find_sheet(wb, SHEET_GUIDE, "清单口径")
    if guide_sheet is not None:
        gws = guide_sheet
        grow = 2
        for i, row in enumerate(gws.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
            if "需求条目" in [str(v or "") for v in row]:
                grow = i
                break
        for row in gws.iter_rows(min_row=grow + 1, values_only=True):
            cells = list(row) + [None] * 5
            try:
                seq = int(cells[0])
            except (TypeError, ValueError):
                continue
            hint_by_seq[seq] = (
                str(cells[2] or "").strip(),
                str(cells[3] or "").strip(),
                str(cells[4] or "").strip(),
            )

    found = _find_sheet(wb, SHEET_MAIN, "电控设计需求")
    ws = found if found is not None else wb.active
    header_row = 2
    headers: list[str] = []
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=5, values_only=True), start=1):
        texts = [str(v or "") for v in row]
        if "需求条目" in texts:
            header_row = i
            headers = texts
            break
    index = {name: i for i, name in enumerate(headers)}

    def col(*names: str) -> int | None:
        for name in names:
            if name in index:
                return index[name]
        return None

    seq_i = col("需求序号")
    name_i = col("需求条目", "字段")
    value_i = col("抽出值", "值")
    page_i = col("页码")
    clause_i = col("条款号", "节号")
    excerpt_i = col("原文摘录")
    conf_i = col("置信度")
    status_i = col("核对状态")
    note_i = col("复核备注")
    hint_i = col("需求说明")
    impact_i = col("必要性及影响")
    example_i = col("参考示例（非本份抽出）", "参考示例")

    specs = {spec.seq: spec for spec in load_template_fields()}
    specs_by_name = {spec.name: spec for spec in specs.values()}

    rows: list[ExtractedCell] = []
    for raw in ws.iter_rows(min_row=header_row + 1, values_only=True):
        data = list(raw)
        if not data:
            continue
        name = str(data[name_i] or "").strip() if name_i is not None and name_i < len(data) else ""
        if not name:
            continue
        seq = 0
        if seq_i is not None and seq_i < len(data) and data[seq_i] not in {None, ""}:
            try:
                seq = int(data[seq_i])
            except (TypeError, ValueError):
                seq = 0
        hint, impact, example = hint_by_seq.get(seq, ("", "", ""))
        if hint_i is not None and hint_i < len(data) and data[hint_i]:
            hint = str(data[hint_i]).strip()
        if impact_i is not None and impact_i < len(data) and data[impact_i]:
            impact = str(data[impact_i]).strip()
        if example_i is not None and example_i < len(data) and data[example_i]:
            example = str(data[example_i]).strip()
        if name in specs_by_name:
            seq = specs_by_name[name].seq
        value = (
            str(data[value_i] or "").strip()
            if value_i is not None and value_i < len(data)
            else ""
        )
        if value in VALUE_MARKERS:
            value = ""
        conf = 0.0
        if conf_i is not None and conf_i < len(data) and data[conf_i] not in {None, ""}:
            try:
                conf = float(data[conf_i])
            except (TypeError, ValueError):
                conf = 0.0
        status_raw = (
            str(data[status_i] or "").strip()
            if status_i is not None and status_i < len(data)
            else ""
        )
        if status_raw in {"待核对", "未抽出"}:
            status_raw = ""
        status_raw = _status_from_sheet(status_raw)
        rows.append(
            ExtractedCell(
                name=name,
                seq=seq,
                value=value,
                page=(
                    str(data[page_i] or "").strip()
                    if page_i is not None and page_i < len(data)
                    else ""
                ),
                clause=(
                    str(data[clause_i] or "").strip()
                    if clause_i is not None and clause_i < len(data)
                    else ""
                ),
                excerpt=(
                    str(data[excerpt_i] or "").strip()
                    if excerpt_i is not None and excerpt_i < len(data)
                    else ""
                ),
                confidence=conf,
                hint=hint,
                impact=impact,
                example=example,
                review_status=status_raw,
                note=(
                    str(data[note_i] or "").strip()
                    if note_i is not None and note_i < len(data)
                    else ""
                ),
                extra=name not in specs_by_name,
            )
        )
    for cell in rows:
        spec = specs.get(cell.seq)
        if spec is None:
            continue
        cell.hint = cell.hint or spec.hint
        cell.impact = cell.impact or spec.impact
        cell.example = cell.example or spec.example
        cell.name = spec.name
    return rows, meta


def _paint_title_bar(ws, cols: int) -> None:
    """只改标题行的字体和底色，不写单元格的字。"""
    font = Font(name="微软雅黑", size=22, bold=True, color="FFFFFF")
    align = Alignment(horizontal="left", vertical="center", indent=1)
    for col in range(1, cols + 1):
        cell = ws.cell(1, col)
        cell.font = font
        cell.fill = _NAVY
        cell.alignment = align
        cell.border = _HEAD_EDGE
    ws.row_dimensions[1].height = 52


def _paint_header_row(ws, row: int, cols: int, groups: tuple | None = None) -> None:
    align = Alignment(wrap_text=True, vertical="center", horizontal="center")
    for col in range(1, cols + 1):
        cell = ws.cell(row, col)
        name = "" if cell.value is None else str(cell.value)
        human = name == "人工填写"
        if human:
            cell.fill = _HUMAN_FILL
            cell.font = _HUMAN_FONT
        elif groups:
            wash, ink = _field_tone(_group_color(col, groups))
            cell.fill = _solid(wash)
            cell.font = Font(name="微软雅黑", size=10, bold=True, color=ink)
        else:
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
        cell.alignment = align
        cell.border = _HEAD_EDGE
    ws.row_dimensions[row].height = 24


def _unmerge_touching(ws, top: int, bottom: int) -> None:
    refs = [
        str(merged)
        for merged in ws.merged_cells.ranges
        if merged.min_row <= bottom and merged.max_row >= top
    ]
    for ref in refs:
        ws.unmerge_cells(ref)


def _reflow_cover(ws) -> None:
    """四张统计卡改成两行两列，中间空一行。文件信息仍从第 6 行起，文字不改。"""
    if str(ws.cell(4, 1).value or "").startswith("未检索到") and not ws.cell(3, 1).value:
        return
    if ws.cell(2, 4).value and str(ws.cell(3, 1).value or "").startswith("未检索到"):
        left = [ws.cell(3, col).value for col in range(1, 4)]
        right = [ws.cell(3, col).value for col in range(4, 7)]
        for col in range(1, 7):
            ws.cell(3, col).value = None
        for offset, value in enumerate(left):
            ws.cell(4, 1 + offset).value = value
        for offset, value in enumerate(right):
            ws.cell(4, 4 + offset).value = value
        ws.row_dimensions[3].height = 20
        ws.row_dimensions[5].height = 20
        return
    if not str(ws.cell(3, 1).value or "").startswith("局部"):
        return
    cards = [[ws.cell(row, col).value for col in range(1, 4)] for row in range(2, 6)]
    _unmerge_touching(ws, 1, 5)
    for row in range(2, 6):
        for col in range(1, 7):
            ws.cell(row, col).value = None
    for (row, start), values in zip(((2, 1), (2, 4), (4, 1), (4, 4)), cards):
        for offset, value in enumerate(values):
            ws.cell(row, start + offset).value = value
    for row in (3, 5):
        ws.row_dimensions[row].height = 20
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    for row in range(6, (ws.max_row or 5) + 1):
        if ws.cell(row, 2).value in (None, ""):
            continue
        _unmerge_touching(ws, row, row)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)


def _insert_group_row(ws, row: int, marker: str, groups: tuple) -> None:
    if ws.cell(row, 1).value != marker:
        return
    ws.insert_rows(row)
    _write_group_row(ws, row, groups)


def _chrome(
    ws,
    tab: str,
    *,
    landscape: bool,
    fit_width: bool,
    zoom: int,
    titles: str,
) -> None:
    """打印和标签。不改冻结、筛选和单元格的值。"""
    ws.sheet_properties.tabColor = tab
    ws.sheet_view.zoomScale = zoom
    ws.sheet_view.view = "normal"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.pageOrder = "downThenOver"
    ws.page_setup.horizontalCentered = True
    if fit_width:
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
    else:
        ws.page_setup.fitToWidth = 0
        ws.page_setup.fitToHeight = 0
        ws.page_setup.scale = 100
        ws.sheet_properties.pageSetUpPr.fitToPage = False
    ws.print_title_rows = titles
    ws.page_margins.left = 0.5
    ws.page_margins.right = 0.5
    ws.page_margins.top = 0.55
    ws.page_margins.bottom = 0.5
    ws.page_margins.header = 0.25
    ws.page_margins.footer = 0.25
    ws.oddHeader.left.text = ws.title
    ws.oddHeader.left.font = "微软雅黑"
    ws.oddHeader.left.size = 9
    _page_number(ws)
    last = get_column_letter(ws.max_column or 1)
    ws.print_area = f"A1:{last}{max(ws.max_row, 1)}"


def _row_values(ws, row: int, cols: int) -> list[object]:
    return [ws.cell(row, col).value for col in range(1, cols + 1)]


def _keep_height(ws, row: int, values: list[object], widths: tuple[float, ...]) -> None:
    needed = _row_height(["" if item is None else item for item in values], widths)
    current = ws.row_dimensions[row].height or 0
    ws.row_dimensions[row].height = max(current, needed)


def _status_style(label: object) -> tuple[PatternFill, Font, Font] | None:
    text = "" if label is None else str(label).strip()
    if text in {STATUS_FOUND, STATUS_PASS, "已检索到", "通过"}:
        return FILLED, FOUND_FONT, VALUE_FONT
    if text in {STATUS_PARTIAL, "局部对应", STATUS_FIX, "需修改"} or text.startswith("局部"):
        return PARTIAL_FILL, PARTIAL_FONT, PARTIAL_FONT
    if text in {STATUS_MISS, "未检索到"}:
        return YELLOW, MISS_FONT, MARKER_FONT
    if text in {STATUS_NA, "不适用"}:
        return _BAND, _MUTED_FONT, MARKER_FONT
    return None


def _restyle_cover(ws) -> None:
    _reflow_cover(ws)
    cols = 6
    _paint_title_bar(ws, cols)
    card_ink = {
        "已检索到": ("D4EDDA", "146C43"),
        "局部对应/需人工复核": ("F8D48A", "8A5A12"),
        "未检索到": ("F6CACA", "B42318"),
        "清单外需求": ("D6E4F5", "142B49"),
    }
    box = Border(
        left=Side(style="thin", color="DCE3EB"),
        right=Side(style="thin", color="DCE3EB"),
        top=Side(style="thin", color="DCE3EB"),
        bottom=Side(style="thin", color="DCE3EB"),
    )
    hair = Border(bottom=Side(style="thin", color="DCE3EB"))
    for row in range(2, (ws.max_row or 1) + 1):
        for start in (1, 4):
            key = "" if ws.cell(row, start).value is None else str(ws.cell(row, start).value).strip()
            if key not in card_ink:
                continue
            fill, ink = card_ink[key]
            wash = _solid(fill)
            for offset in range(3):
                cell = ws.cell(row, start + offset)
                cell.fill = wash
                cell.border = box
            ws.cell(row, start).font = Font(name="微软雅黑", size=12, bold=True, color=ink)
            ws.cell(row, start).alignment = Alignment(horizontal="left", vertical="center", indent=1)
            ws.cell(row, start).border = Border(
                left=Side(style="medium", color=ink),
                right=Side(style="thin", color="DCE3EB"),
                top=Side(style="thin", color="DCE3EB"),
                bottom=Side(style="thin", color="DCE3EB"),
            )
            ws.cell(row, start + 1).font = Font(name="微软雅黑", size=32, bold=True, color=ink)
            ws.cell(row, start + 1).alignment = Alignment(horizontal="center", vertical="center")
            ws.cell(row, start + 2).font = Font(name="微软雅黑", size=11, color="5C6B7A")
            ws.cell(row, start + 2).alignment = Alignment(
                horizontal="left", vertical="center", indent=1, wrap_text=True
            )
            ws.row_dimensions[row].height = 96
        key = "" if ws.cell(row, 1).value is None else str(ws.cell(row, 1).value).strip()
        if key in card_ink:
            continue
        if not key:
            blank = PatternFill(fill_type="solid", fgColor="FFFFFF")
            for col in range(1, 7):
                cell = ws.cell(row, col)
                cell.fill = blank
                cell.border = Border()
            if row in {3, 5}:
                ws.row_dimensions[row].height = 20
            continue
        emphasize = key == "源文件"
        ws.cell(row, 1).font = Font(name="微软雅黑", size=10, color="7B8794")
        ws.cell(row, 1).fill = _solid("F3F6FA")
        ws.cell(row, 1).alignment = Alignment(horizontal="left", vertical="center", indent=1)
        ws.cell(row, 1).border = hair
        body_font = Font(
            name="微软雅黑",
            size=12 if emphasize else 11,
            bold=emphasize,
            color="142B49" if emphasize else "263445",
        )
        body = ws.cell(row, 2)
        body.font = body_font
        body.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
        for col in range(2, 7):
            extra = ws.cell(row, col)
            extra.fill = _PAPER_FILL
            extra.border = hair
            extra.font = body_font
        text = "" if body.value is None else str(body.value)
        needed = 28 if len(text) < 36 else min(52, 18 + 14 * ((len(text) // 36) + 1))
        ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 0, needed)
    for index, width in enumerate((24, 16, 34, 24, 16, 34), start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    _chrome(ws, "142B49", landscape=False, fit_width=True, zoom=110, titles="1:1")
    ws.freeze_panes = None
    ws.page_setup.fitToHeight = 1
    ws.page_setup.orientation = "portrait"
    ws.oddHeader.left.text = "电控设计需求核对"


def _restyle_main(ws) -> None:
    _insert_group_row(ws, 2, "核对状态", _GROUPS_MAIN)
    cols = len(HEADERS)
    header = 3 if ws.cell(2, 1).value == "条目" else 2
    _paint_title_bar(ws, cols)
    _paint_header_row(ws, header, cols, _GROUPS_MAIN if header == 3 else None)
    for index, width in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    previous_group = None
    for row in range(header + 1, (ws.max_row or header) + 1):
        if all(ws.cell(row, col).value in (None, "") for col in range(1, cols + 1)):
            continue
        values = _row_values(ws, row, cols)
        group_name = values[1]
        section = group_name != previous_group
        previous_group = group_name
        if section and row > header + 1:
            ws.row_breaks.append(Break(id=row - 1))
        for col in range(1, cols + 1):
            cell = ws.cell(row, col)
            if col == 4:
                cell.font = _NAME_FONT
            elif col == 5:
                cell.font = VALUE_FONT
            elif col == 2:
                cell.font = _MUTED_FONT
            else:
                cell.font = BODY_FONT
            if col == 8:
                cell.alignment = Alignment(wrap_text=True, vertical="top", indent=2)
            elif col in {1, 3, 6, 7, 11}:
                cell.alignment = _CENTER
            else:
                cell.alignment = Alignment(wrap_text=True, vertical="top", indent=1)
            cell.border = _panel_border(col, section=section)
            if col == 9:
                cell.fill = _INPUT_FILL
            elif col == 8:
                cell.fill = _READ_FILL
            elif col in {6, 7}:
                cell.fill = _POS_FILL
            elif col in {10, 11}:
                cell.fill = _NOTE_FILL
            elif col not in {1, 5}:
                cell.fill = _RAIL_FILL
        painted = _status_style(ws.cell(row, 1).value)
        if painted is not None:
            fill, status_font, value_font = painted
            status_cell = ws.cell(row, 1)
            value_cell = ws.cell(row, 5)
            status_cell.fill = fill
            status_cell.font = status_font
            value_cell.fill = fill
            value_cell.font = value_font if (value_cell.value or "") else MARKER_FONT
            ink = "146C43"
            label = "" if status_cell.value is None else str(status_cell.value)
            if label.startswith("局部") or label in {"需修改"}:
                ink = "8A5A12"
            elif label in {"未检索到"}:
                ink = "B42318"
            mark = _mark_border(ink, section=section)
            status_cell.border = mark
            value_cell.border = mark
        note = ws.cell(row, 10)
        if pending_text("" if note.value is None else str(note.value)):
            note.font = PENDING_FONT
        conf = ws.cell(row, 11)
        if conf.value not in (None, ""):
            conf.font = _MUTED_FONT
            conf.alignment = _CENTER
        needed = _row_height(["" if item is None else item for item in values], COL_WIDTHS, floor=_RECORD_FLOOR)
        current = ws.row_dimensions[row].height or 0
        ws.row_dimensions[row].height = max(current, needed)
    _chrome(ws, "2878B9", landscape=True, fit_width=False, zoom=90, titles="1:3")
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.freeze_panes = "E4"
    ws.auto_filter.ref = f"A3:{get_column_letter(cols)}{ws.max_row}"
    for dv in ws.data_validations.dataValidation:
        dv.sqref = f"A4:A{ws.max_row}"


def _restyle_review(ws) -> None:
    _insert_group_row(ws, 3, "序号", ((1, 4, "位置", "142B49"), (5, 5, "问题", "2878B9")))
    cols = max(ws.max_column or 1, 5)
    header = 4 if ws.cell(3, 1).value == "位置" else 3
    _paint_title_bar(ws, cols)
    for col in range(1, cols + 1):
        cell = ws.cell(2, col)
        cell.font = _NOTE_FONT
        cell.fill = _solid("EAF2FC")
        cell.alignment = Alignment(horizontal="left", vertical="center", indent=1, wrap_text=True)
        cell.border = Border(bottom=Side(style="thin", color="DCE3EB"))
    ws.row_dimensions[2].height = max(ws.row_dimensions[2].height or 0, 32)
    _paint_header_row(ws, header, cols, ((1, 4, "位置", "142B49"), (5, 5, "问题", "2878B9")) if header == 4 else None)
    kind_style = {
        "中英冲突": ("F8D48A", "8A5A12"),
        "内部不一致": ("F6CACA", "B42318"),
        "语义相反": ("F6CACA", "B42318"),
        "模板残留": ("D6E4F5", "142B49"),
        "占位未填": ("D9E4F2", "263445"),
        "日期格式": ("D9E4F2", "263445"),
        "空表": ("D9E4F2", "263445"),
    }
    widths = (8, 16, 10, 12, 120)
    for index, width in enumerate(widths, start=1):
        if index <= cols:
            ws.column_dimensions[get_column_letter(index)].width = width
    for row in range(header + 1, (ws.max_row or header) + 1):
        kind = "" if ws.cell(row, 2).value is None else str(ws.cell(row, 2).value).strip()
        if not kind and ws.cell(row, 5).value in (None, ""):
            continue
        wash, ink = kind_style.get(kind, ("FFFFFF", "263445"))
        fonts = (
            Font(name="微软雅黑", size=10, color="7B8794"),
            Font(name="微软雅黑", size=10, bold=True, color=ink),
            Font(name="微软雅黑", size=10, color="263445"),
            Font(name="微软雅黑", size=10, bold=True, color="142B49"),
            Font(name="微软雅黑", size=10, color="263445"),
        )
        for col in range(1, min(cols, 5) + 1):
            cell = ws.cell(row, col)
            cell.font = fonts[col - 1]
            cell.fill = _solid(wash)
            cell.alignment = Alignment(
                horizontal="center" if col in {1, 3, 4} else "left",
                vertical="top",
                wrap_text=True,
            )
            cell.border = _GRID
        _keep_height(ws, row, _row_values(ws, row, min(cols, 5)), widths)
    _chrome(ws, "1F4E79", landscape=True, fit_width=True, zoom=110, titles="1:4")
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:E{ws.max_row}"
    ws.oddHeader.left.text = "提取质量审查"


def _restyle_off(ws) -> None:
    _insert_group_row(ws, 2, "名称", _GROUPS_OFF)
    cols = len(OFF_LIST_HEADERS)
    header = 3 if ws.cell(2, 1).value == "要求" else 2
    _paint_title_bar(ws, cols)
    _paint_header_row(ws, header, cols, _GROUPS_OFF if header == 3 else None)
    for index, width in enumerate(OFF_LIST_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in range(header + 1, (ws.max_row or header) + 1):
        if all(ws.cell(row, col).value in (None, "") for col in range(1, cols + 1)):
            continue
        band = _BAND if row % 2 == 0 else _PAPER_FILL
        for col in range(1, cols + 1):
            cell = ws.cell(row, col)
            cell.font = VALUE_FONT if col == 2 else (_NAME_FONT if col == 1 else BODY_FONT)
            cell.alignment = _CENTER if col in {3, 4} else WRAP
            cell.border = _GRID
            if col == 2:
                cell.fill = FILLED
            elif col == 5:
                cell.fill = _READ_FILL
            else:
                cell.fill = band
        _keep_height(ws, row, _row_values(ws, row, cols), OFF_LIST_WIDTHS)
    _chrome(ws, "4A6FA5", landscape=True, fit_width=True, zoom=110, titles="1:3")
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:E{ws.max_row}"


def _restyle_guide(ws) -> None:
    _insert_group_row(ws, 2, "需求序号", _GROUPS_GUIDE)
    cols = len(GUIDE_HEADERS)
    header = 3 if ws.cell(2, 1).value == "条目" else 2
    _paint_title_bar(ws, cols)
    _paint_header_row(ws, header, cols, _GROUPS_GUIDE if header == 3 else None)
    for index, width in enumerate(GUIDE_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    impact_font = Font(name="微软雅黑", size=10, color="142B49")
    for row in range(header + 1, (ws.max_row or header) + 1):
        if all(ws.cell(row, col).value in (None, "") for col in range(1, cols + 1)):
            continue
        band = _BAND if row % 2 == 0 else _PAPER_FILL
        for col in range(1, cols + 1):
            cell = ws.cell(row, col)
            if col == 5:
                cell.font = _MUTED_FONT
                cell.fill = _EXAMPLE_FILL
            elif col == 2:
                cell.font = _NAME_FONT
                cell.fill = band
            elif col == 4:
                cell.font = impact_font
                cell.fill = band
            else:
                cell.font = BODY_FONT
                cell.fill = band
            cell.alignment = _CENTER if col == 1 else WRAP
            cell.border = _GRID
        _keep_height(ws, row, _row_values(ws, row, cols), GUIDE_WIDTHS)
    _chrome(ws, "7B8794", landscape=True, fit_width=True, zoom=100, titles="1:3")
    ws.freeze_panes = "C4"
    ws.auto_filter.ref = f"A3:E{ws.max_row}"


def restyle_review_workbook(src: Path, dest: Path) -> Path:
    """已生成的核对表只改外观。单元格的字、公式、表名、筛选和冻结保持原样。"""
    wb = load_workbook(src)
    routers = {
        "01_": _restyle_cover,
        "02_": _restyle_main,
        "03_": _restyle_review,
        "04_": _restyle_off,
        "05_": _restyle_guide,
    }
    for name in list(wb.sheetnames):
        for prefix, painter in routers.items():
            if name.startswith(prefix):
                painter(wb[name])
                break
    dest = Path(dest).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dest)
    return dest
