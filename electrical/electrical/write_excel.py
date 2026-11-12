"""按客户《电机控制需求清单》写出可核对 Excel。"""
from __future__ import annotations

import os
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

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
    f'"{STATUS_FOUND},{STATUS_MISS},{STATUS_PARTIAL},'
    f'{STATUS_PASS},{STATUS_FIX},{STATUS_NA}"'
)
YELLOW = PatternFill("solid", fgColor="FFF3CD")
PARTIAL_FILL = PatternFill("solid", fgColor="FCE4D6")
FILLED = PatternFill("solid", fgColor="D6EAF8")
HEADER_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="微软雅黑")
TITLE_FONT = Font(bold=True, size=14, name="微软雅黑")
BODY_FONT = Font(name="微软雅黑", size=10)
VALUE_FONT = Font(name="微软雅黑", size=10, bold=True)
MARKER_FONT = Font(name="微软雅黑", size=10, color="808080", italic=True)
# 复核备注里带「待专家口径」的格子用深红标出来，和普通备注区分
PENDING_FONT = Font(name="微软雅黑", size=10, color="9C0006")
WRAP = Alignment(wrap_text=True, vertical="top")
_WS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


COL_WIDTHS = (20, 12, 10, 28, 42, 9, 14, 48, 22, 36, 9)
GUIDE_WIDTHS = (10, 32, 40, 40, 36)
OFF_LIST_WIDTHS = (28, 44, 9, 14, 56)
LINE_PT = 16
MIN_ROW_PT = 22
MAX_ROW_PT = 220


def _clean_text(text: str) -> str:
    value = _WS.sub(" ", (text or "").replace("\r\n", "\n").replace("\r", "\n"))
    return _NL.sub("\n\n", value).strip()


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


def _row_height(values: list[object], widths: tuple[float, ...] = COL_WIDTHS) -> float:
    lines = 1
    for item, width in zip(values, widths):
        lines = max(lines, _wrapped_lines(item, width))
    return max(MIN_ROW_PT, min(MAX_ROW_PT, 6 + lines * LINE_PT))


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

    ws = wb.create_sheet("清单外需求")
    last = get_column_letter(len(OFF_LIST_HEADERS))
    ws.merge_cells(f"A1:{last}1")
    title = ws["A1"]
    title.value = "清单外需求（当份原文里对不上 1–120 的要求）"
    title.font = TITLE_FONT
    title.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22
    for col, name in enumerate(OFF_LIST_HEADERS, start=1):
        cell = ws.cell(2, col, name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws["B2"].comment = Comment(
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
            ws.row_dimensions[excel_row].height = _row_height(values, OFF_LIST_WIDTHS)
            for col in range(1, len(OFF_LIST_HEADERS) + 1):
                ws.cell(excel_row, col).font = BODY_FONT
                ws.cell(excel_row, col).alignment = WRAP
            ws.cell(excel_row, 2).font = VALUE_FONT
            ws.cell(excel_row, 2).fill = FILLED
            count += 1
    for idx, width in enumerate(OFF_LIST_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.auto_filter.ref = f"A2:{last}{max(ws.max_row, 2)}"
    ws.freeze_panes = "A3"
    ws.row_dimensions[2].height = 28
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
    ws.title = "电控设计需求"

    last_col = get_column_letter(len(HEADERS))
    ws.merge_cells(f"A1:{last_col}1")
    title = ws["A1"]
    title.value = f"{template_title()}（规格书抽取核对）"
    title.font = TITLE_FONT
    title.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 22

    for col, name in enumerate(HEADERS, start=1):
        cell = ws.cell(2, col, name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws["E2"].comment = Comment(
        "本份规格书抽出的值。"
        "「未检索到」「局部对应/需人工复核」为检索结论占位，不是规格书原文。"
        "不要用「清单口径」里的参考示例顶替。"
        "缺项可由当份规格书已出现的量按公式算出，状态为局部对应；所用公式写在「复核备注」。"
        "当份未给出、条目需参考试验方法标准时，抽出值显示未检索到，方法号写在复核备注。",
        "KMind",
    )
    ws["F2"].comment = Comment(
        "打开后印在页眉或页脚上的页码。例如 60 (116) 填 60。不是条款号。",
        "KMind",
    )
    ws["G2"].comment = Comment(
        "正文条款号，如 2.3.3.3、6.5.11.1。没有则空。",
        "KMind",
    )
    ws["I2"].comment = Comment(
        "核对后在此填写认定的正确值（含单位）。",
        "KMind",
    )
    ws["J2"].comment = Comment(
        "公式推算的格子在此写清用了哪条公式、代入了原文哪些量。"
        "例如：由物理公式计算：R=U/I（代入 1000 VDC、0.1 mA）。"
        "当份未给出、需参考试验方法的格子：抽出值未检索到，复核备注写企标方法对照。"
        "抽出值只写当份算出的数，不把定律名称或方法号写进去。",
        "KMind",
    )
    ws["A2"].comment = Comment(
        "检索结论三类：已检索到 / 未检索到 / 局部对应需人工复核。"
        "人工核对后再改为：通过 / 需修改 / 不适用。",
        "KMind",
    )

    n_found = 0
    n_miss = 0
    n_partial = 0
    template_n = 0
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
            status,
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
        ws.append(values)
        excel_row = ws.max_row
        dim = ws.row_dimensions[excel_row]
        dim.height = _row_height(values, COL_WIDTHS)
        for col in range(1, len(HEADERS) + 1):
            ws.cell(excel_row, col).font = BODY_FONT
            ws.cell(excel_row, col).alignment = WRAP
        value_cell = ws.cell(excel_row, 5)
        status_cell = ws.cell(excel_row, 1)
        if (row.value or "").strip():
            value_cell.font = VALUE_FONT
            if status == STATUS_PARTIAL:
                value_cell.fill = PARTIAL_FILL
                status_cell.fill = PARTIAL_FILL
            else:
                value_cell.fill = FILLED
        elif extract and status == STATUS_PARTIAL:
            value_cell.font = MARKER_FONT
            value_cell.fill = PARTIAL_FILL
            status_cell.fill = PARTIAL_FILL
        elif extract and status == STATUS_MISS:
            value_cell.font = MARKER_FONT
            value_cell.fill = YELLOW
            status_cell.fill = YELLOW
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
        "请选择：已检索到 / 未检索到 / 局部对应/需人工复核 / 通过 / 需修改 / 不适用"
    )
    dv.errorTitle = "核对状态"
    ws.add_data_validation(dv)
    if ws.max_row >= 3:
        dv.add(f"A3:A{ws.max_row}")

    for idx, width in enumerate(COL_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.sheet_format.defaultRowHeight = MIN_ROW_PT
    ws.auto_filter.ref = f"A2:{last_col}{ws.max_row}"
    ws.freeze_panes = "A3"
    ws.row_dimensions[2].height = 28
    n_off = _write_off_list_sheet(wb, cells, extract=extract)

    guide = wb.create_sheet("清单口径")
    guide.merge_cells("A1:E1")
    guide["A1"] = "清单口径（不是本份规格书的抽出值）"
    guide["A1"].font = TITLE_FONT
    for col, name in enumerate(GUIDE_HEADERS, start=1):
        cell = guide.cell(2, col, name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
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
        for col in range(1, len(GUIDE_HEADERS) + 1):
            guide.cell(excel_row, col).font = BODY_FONT
            guide.cell(excel_row, col).alignment = WRAP
        guide.cell(excel_row, 5).font = Font(name="微软雅黑", size=10, color="808080")
    for idx, width in enumerate(GUIDE_WIDTHS, start=1):
        guide.column_dimensions[get_column_letter(idx)].width = width
    guide.freeze_panes = "A3"
    guide.auto_filter.ref = f"A2:E{max(guide.max_row, 2)}"

    cover = wb.create_sheet("说明", 0)
    cover["A1"] = template_title()
    cover["A1"].font = Font(bold=True, size=14, name="微软雅黑")
    _write_content_review_sheet(wb, qa)
    cover.append([])
    cover.append(["源文件", source_name])
    cover.append(["文档类型", kind_label or "未标注"])
    cover.append(["知识库版本", _knowledge_version_label(knowledge_version)])
    cover.append(["清单条目", template_n])
    cover.append(["已检索到", n_found if extract else 0])
    cover.append(["未检索到", n_miss if extract else 0])
    cover.append(["局部对应/需人工复核", n_partial if extract else 0])
    cover.append(["清单外需求", n_off if extract else 0])
    if extract and n_pending:
        cover.append(
            [
                "待专家口径",
                f"{n_pending} 格。取值本身来自当份原文，但填法或算不算正式指标还没定，"
                "见「电控设计需求」复核备注中「待专家口径：」段（深红）。口径定下后该标注自动消失。",
            ]
        )
    if (extract_warning or "").strip():
        cover.append([])
        cover.append(["识别完整性", extract_warning.strip()])
    if not extract and (kind_note or "").strip():
        cover.append([])
        cover.append(["说明", kind_note.strip()])
    cover.append([])
    cover.append(
        [
            "用法",
            "先看「电控设计需求」。浅蓝 = 已检索到；橙底 = 局部对应；黄底 = 未检索到。"
            "人工确认后把核对状态改为通过 / 需修改。"
            "当份对不上 1–120 的要求在「清单外需求」。",
        ]
    )
    cover.column_dimensions["A"].width = 36
    cover.column_dimensions["B"].width = 88
    for excel_row, row in enumerate(cover.iter_rows(), start=1):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if cell.font and cell.font.bold:
                continue
            cell.font = Font(name="微软雅黑", size=11)
        vals = [cell.value for cell in row]
        if any(vals):
            cover.row_dimensions[excel_row].height = _row_height(vals, (36, 88))

    wb.save(output_path)
    return output_path


def _write_content_review_sheet(wb: Workbook, qa) -> None:
    findings = list(getattr(qa, "content_findings", None) or [])
    if not findings:
        return
    sheet = wb.create_sheet("文件审查", 1)
    title = sheet["A1"]
    title.value = "当份正文审查"
    title.font = Font(bold=True, size=13, name="微软雅黑")
    sheet.merge_cells("A1:C1")
    sheet.append([])
    headers = ["等级", "类型", "说明"]
    sheet.append(headers)
    for col in range(1, 4):
        cell = sheet.cell(3, col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    p0_fill = PatternFill("solid", fgColor="F5C6CB")
    p1_fill = PatternFill("solid", fgColor="FCE4B3")
    for item in findings:
        sheet.append([item.level, item.kind, item.text])
        excel_row = sheet.max_row
        fill = p0_fill if item.level == "P0" else p1_fill
        for col in range(1, 4):
            cell = sheet.cell(excel_row, col)
            cell.font = Font(name="微软雅黑", size=11)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if col == 1:
                cell.fill = fill
        sheet.row_dimensions[excel_row].height = _row_height(
            [item.level, item.kind, item.text], (10, 16, 88)
        )
    sheet.column_dimensions["A"].width = 10
    sheet.column_dimensions["B"].width = 16
    sheet.column_dimensions["C"].width = 88
    sheet.freeze_panes = "A4"
    sheet.append([])
    sheet.append(
        [
            "",
            "",
            "上表只记录当份正文问题。",
        ]
    )
    last = sheet.max_row
    for col in range(1, 4):
        sheet.cell(last, col).font = Font(name="微软雅黑", size=10, color="666666")
        sheet.cell(last, col).alignment = Alignment(wrap_text=True, vertical="top")


def load_review_cells(path: Path) -> tuple[list[ExtractedCell], dict[str, str]]:
    """读已导出的核对表，便于改版式后重出（不重跑抽取）。"""
    wb = load_workbook(path, data_only=True)
    meta: dict[str, str] = {}
    if "说明" in wb.sheetnames:
        for row in wb["说明"].iter_rows(min_row=2, max_col=2, values_only=True):
            key, val = (list(row) + [None, None])[:2]
            if key:
                meta[str(key).strip()] = "" if val is None else str(val).strip()

    hint_by_seq: dict[int, tuple[str, str, str]] = {}
    if "清单口径" in wb.sheetnames:
        gws = wb["清单口径"]
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

    ws = wb["电控设计需求"] if "电控设计需求" in wb.sheetnames else wb.active
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
