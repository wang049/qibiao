"""按吉利 HSI 模板出一份手册对应的 HSI。

端口表的引脚只写当份手册。端口命名和约束只在吉利模板有同一引脚符号时对照填入，
并标成待人工确认。缺项、多个候选、方向冲突单独标出，不写成已确认。
人工修订和验收实测只保留上一版已经写下的内容。没有上一版时，变更记录只留表头。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook

from electrical_krow.hsi_qa import (
    Ask,
    SubSheetEntry,
    _is_llm_candidate,
    check_peripheral_capability,
    check_template_row_anomalies,
    extract_subsheet_entries,
    norm_symbol,
    pin_lookup_keys,
    run_llm_pin_qa,
    split_symbol_parts,
)
from electrical_krow.mcu_pins import (
    ChipPin,
    mcu_name,
    parse_pin_pages,
    parse_pins,
    read_pdf_pages,
)

DEFAULT_HSI_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "PCM-HSI-吉利模板-V1.0-20251024.xlsx"
)

SHEET_COVER = "0_Cover"
SHEET_HISTORY = "1_Chang History"
SHEET_PORT = "2_Port Assignment"
SHEET_EVIDENCE = "手册依据"
SHEET_CONSTRAINT = "约束配置"
SHEET_REVISION = "人工修订记录"
SHEET_ACCEPT = "验收记录"

COL_STATUS = 22
COL_MARK = 23
COL_HUMAN = 24

STATUS_GAP = "缺项"
STATUS_MULTI = "多候选"
STATUS_CONFLICT = "约束冲突"
STATUS_DRAFT = "待人工确认"

_HISTORY_HEADERS = ("编号", "变更日期", "详细描述", "影响分析", "备注")
_EVIDENCE_HEADERS = ("引脚符号", "球号", "方向", "缓冲", "功能", "复用", "页码", "原文摘录")
_CONSTRAINT_HEADERS = (
    "引脚符号",
    "端口名",
    "功能描述",
    "电平",
    "ASIL",
    "模板方向",
    "复位时弱上拉",
    "高电平或上升沿",
    "低电平或下降沿",
    "初始设置",
    "使用指引",
    "来源",
    "核对状态",
    "标记说明",
)
_REVISION_HEADERS = ("引脚符号", "修订内容", "修订人", "修订日期", "说明")
_ACCEPT_NOTE = (
    "本表只保留已填写的实测值。生成时不计算匹配率、安全率；"
    "技术协议未规定这两项的数值阈值，口径须书面确认。"
)
_ACCEPT_HEADERS = (
    "引脚符号",
    "匹配实测",
    "降额实测",
    "安全相关实测",
    "与手册是否一致",
    "与确认约束是否一致",
)
_CONSTRAINT_SOURCE = "吉利模板"
_COLUMN_CAP = 40
_COLUMN_FLOOR = 12
_NC_NAMES = frozenset({"NC", "N.C.", "N/A", "NA"})
_VERSION = re.compile(r"^(?P<body>.+)-(?P<n>\d+)$")


@dataclass(frozen=True)
class HsiResult:
    path: Path
    mcu: str
    package: str
    version: str
    pins: int
    changes: int
    issued: str = ""
    conflicts: int = 0
    model_used: bool = False


@dataclass(frozen=True)
class _PortRow:
    symbol: str
    ball: str
    buffer: str
    pull: str
    supply: str
    extra: str
    direction: str
    function: str
    mux: str
    page: str
    project: tuple[object, ...]


def _split_buffer(buffer: str) -> tuple[str, str, str, str]:
    parts = [part.strip() for part in buffer.split("/") if part.strip()]
    speed = parts[0] if parts else ""
    pull = parts[1] if len(parts) > 1 else ""
    supply = parts[2] if len(parts) > 2 else ""
    extra = " / ".join(parts[3:])
    return speed, pull, supply, extra


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_version(workbook: Workbook) -> str:
    if SHEET_COVER not in workbook.sheetnames:
        return ""
    sheet = workbook[SHEET_COVER]
    for row in sheet.iter_rows(min_row=1, max_row=8, max_col=4):
        for cell in row:
            if _text(cell.value) == "Version" and cell.column == 4:
                return _text(sheet.cell(cell.row + 1, 4).value)
    return ""


def _next_version(mcu: str, package: str, previous: str) -> str:
    base = f"{mcu}-{package}"
    matched = _VERSION.match(previous.strip())
    if matched and matched.group("body") == base:
        return f"{base}-{int(matched.group('n')) + 1}"
    return f"{base}-1"


def _project_cells(sheet, row: int) -> tuple[object, ...]:
    return tuple(sheet.cell(row, column).value for column in range(10, 20))


def _port_rows(workbook: Workbook) -> list[_PortRow]:
    if SHEET_PORT not in workbook.sheetnames:
        return []
    sheet = workbook[SHEET_PORT]
    found: list[_PortRow] = []
    for row in range(5, sheet.max_row + 1):
        symbol = _text(sheet.cell(row, 2).value)
        if not symbol or symbol.lower() in {"pin_symbol", "bga436\\ball"}:
            continue
        found.append(
            _PortRow(
                symbol=symbol,
                ball=_text(sheet.cell(row, 3).value),
                buffer=_text(sheet.cell(row, 4).value),
                pull=_text(sheet.cell(row, 5).value),
                supply=_text(sheet.cell(row, 6).value),
                extra=_text(sheet.cell(row, 7).value),
                direction=_text(sheet.cell(row, 8).value),
                function=_text(sheet.cell(row, 9).value),
                mux=_text(sheet.cell(row, 14).value),
                page=_text(sheet.cell(row, 20).value),
                project=_project_cells(sheet, row),
            )
        )
    return found


def _rows_from_sheet(workbook: Workbook) -> dict[str, _PortRow]:
    found: dict[str, _PortRow] = {}
    for row in _port_rows(workbook):
        found[row.symbol] = row
    return found


def _pin_row(pin: ChipPin, project: tuple[object, ...]) -> _PortRow:
    speed, pull, supply, extra = _split_buffer(pin.buffer)
    return _PortRow(
        pin.symbol,
        pin.ball,
        speed,
        pull,
        supply,
        extra,
        pin.direction,
        pin.function,
        pin.mux,
        pin.page,
        project,
    )


def _project_name(project: tuple[object, ...]) -> str:
    if not project:
        return ""
    return _text(project[0])


def _distinct_rows(rows: list[_PortRow]) -> list[_PortRow]:
    found: list[_PortRow] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(_text(value) for value in row.project)
        if key in seen:
            continue
        seen.add(key)
        found.append(row)
    return found


def _dir_flags(text: str) -> frozenset[str]:
    compact = re.sub(r"\s+", "", text).lower()
    if not compact:
        return frozenset()
    if compact in {"input/output", "i/o", "io"} or "输入/输出" in text or "双向" in text:
        return frozenset({"in", "out"})
    flags: set[str] = set()
    if "input" in compact or compact in {"i", "in"} or "输入" in text:
        flags.add("in")
    if "output" in compact or compact in {"o", "out"} or "输出" in text:
        flags.add("out")
    return frozenset(flags)


def _match_template_rows(pin: ChipPin, grouped: dict[str, list[_PortRow]]) -> list[_PortRow]:
    """按精确符号优先、组合/别名符号（如 `AN17/P40_10`）次之的顺序查找模板候选行。"""
    exact = grouped.get(pin.symbol)
    if exact:
        return exact
    found: list[_PortRow] = []
    seen_ids: set[int] = set()
    pin_keys = set(pin_lookup_keys(pin))
    if not pin_keys:
        return []
    for sym, rows in grouped.items():
        if pin_keys & set(split_symbol_parts(sym)):
            for row in rows:
                if id(row) not in seen_ids:
                    seen_ids.add(id(row))
                    found.append(row)
    return found


def _shared_names(pins: tuple[ChipPin, ...], grouped: dict[str, list[_PortRow]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for pin in pins:
        distinct = _distinct_rows(_match_template_rows(pin, grouped))
        if len(distinct) != 1:
            continue
        name = _project_name(distinct[0].project)
        if not name or name.upper() in _NC_NAMES:
            continue
        owners.setdefault(name, []).append(pin.symbol)
    return {name: symbols for name, symbols in owners.items() if len(symbols) > 1}


def _sub_entries_for(pin: ChipPin, sub_map: dict[str, list[SubSheetEntry]]) -> list[SubSheetEntry]:
    out: list[SubSheetEntry] = []
    seen: set[tuple[str, str, str, str]] = set()
    for key in pin_lookup_keys(pin):
        for entry in sub_map.get(key, []):
            sig_key = (entry.sheet, entry.symbol, entry.signal, entry.ball)
            if sig_key not in seen:
                seen.add(sig_key)
                out.append(entry)
    return out


def _assess(
    pin: ChipPin,
    matches: list[_PortRow],
    shared: dict[str, list[str]],
    sub_entries: list[SubSheetEntry] | None = None,
    llm_findings: list[tuple[str, str]] | None = None,
) -> tuple[str, str, tuple[object, ...]]:
    distinct = _distinct_rows(matches)
    flags: list[str] = []
    notes: list[str] = []
    project: tuple[object, ...] = tuple()

    def add_flag(flag: str) -> None:
        if flag not in flags:
            flags.append(flag)

    def add_note(text: str) -> None:
        if text and text not in notes:
            notes.append(text)

    if not distinct:
        add_flag(STATUS_GAP)
        add_note("吉利模板没有该引脚符号")
    else:
        if len(distinct) > 1:
            add_flag(STATUS_MULTI)
            names = [_project_name(row.project) or "空" for row in distinct]
            add_note("吉利模板中该符号有多个端口名：" + "、".join(names))
        else:
            row0 = distinct[0]
            project = row0.project
            if row0.symbol != pin.symbol:
                add_note(f"按模板组合/别名符号 {row0.symbol} 对齐")
            name = _project_name(project)
            others = [item for item in shared.get(name, []) if item != pin.symbol]
            if others:
                add_flag(STATUS_MULTI)
                add_note(f"模板端口名 {name} 还对应 " + "、".join(others))
        template_flags = [_dir_flags(row.direction) for row in distinct]
        nonempty = [item for item in template_flags if item]
        pin_flags = _dir_flags(pin.direction)
        if nonempty and pin_flags and all(item.isdisjoint(pin_flags) for item in nonempty):
            add_flag(STATUS_CONFLICT)
            shown = "、".join(dict.fromkeys(row.direction for row in distinct if row.direction))
            add_note(f"手册方向为 {pin.direction}，吉利模板方向为 {shown}")

        if len(distinct) == 1:
            row0 = distinct[0]
            name = _project_name(row0.project)
            for c_note in check_peripheral_capability(pin, row0.function, name, row0.direction):
                add_flag(STATUS_CONFLICT)
                add_note(c_note)
            qa_finding = check_template_row_anomalies(
                pin,
                row0.direction,
                row0.function,
                row0.project,
                sub_entries or [],
                template_ball=row0.ball,
            )
            for c_note in qa_finding.conflict_notes:
                add_flag(STATUS_CONFLICT)
                add_note(c_note)
            for w_note in qa_finding.warn_notes:
                add_note(w_note)
            if STATUS_MULTI in flags:
                for hint in qa_finding.sub_hints:
                    add_note(hint)

        for level, reason in llm_findings or []:
            if level == "conflict":
                add_flag(STATUS_CONFLICT)
            add_note(f"【工程质检】{reason}")

    status = "；".join(flags) if flags else STATUS_DRAFT
    return status, "；".join(notes), project


def _field(project: tuple[object, ...], index: int) -> str:
    if index >= len(project):
        return ""
    return _text(project[index])


def _snapshot(workbook: Workbook, title: str) -> list[list[object]] | None:
    if title not in workbook.sheetnames:
        return None
    sheet = workbook[title]
    rows: list[list[object]] = []
    for row in sheet.iter_rows(max_row=sheet.max_row, max_col=max(sheet.max_column, 1), values_only=True):
        rows.append(list(row))
    return rows


def _human_by_symbol(workbook: Workbook) -> dict[str, object]:
    if SHEET_PORT not in workbook.sheetnames:
        return {}
    sheet = workbook[SHEET_PORT]
    found: dict[str, object] = {}
    for row in range(5, sheet.max_row + 1):
        symbol = _text(sheet.cell(row, 2).value)
        value = sheet.cell(row, COL_HUMAN).value
        if symbol and value not in (None, ""):
            found[symbol] = value
    return found


def _fresh_sheet(workbook: Workbook, title: str):
    if title in workbook.sheetnames:
        workbook.remove(workbook[title])
    return workbook.create_sheet(title)


def _write_rows(sheet, rows: list[list[object]]) -> None:
    for row_index, row in enumerate(rows, start=1):
        for column, value in enumerate(row, start=1):
            if value not in (None, ""):
                sheet.cell(row_index, column, value)


def _units(value: object) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in _text(value))


def _fit_columns(sheet, *, skip_rows: frozenset[int] = frozenset(), header_row: int = 1) -> None:
    """按表头和单元格内容设列宽。新建表默认列宽约 8，中文显示不全。"""
    last_column = max(sheet.max_column, 1)
    widths: dict[int, int] = {}
    for row in sheet.iter_rows(max_row=sheet.max_row, max_col=last_column):
        if not row or row[0].row in skip_rows:
            continue
        for cell in row:
            if cell.value in (None, ""):
                continue
            widths[cell.column] = max(widths.get(cell.column, 0), _units(cell.value))
    for column, units in widths.items():
        sheet.column_dimensions[get_column_letter(column)].width = min(max(units + 2, _COLUMN_FLOOR), _COLUMN_CAP)
    for row in sheet.iter_rows(max_row=sheet.max_row, max_col=last_column):
        if not row or row[0].row in skip_rows:
            continue
        lines = 1
        for cell in row:
            text = _text(cell.value)
            if not text:
                continue
            width = sheet.column_dimensions[get_column_letter(cell.column)].width or _COLUMN_FLOOR
            capacity = max(int(width) - 1, 1)
            pieces = 0
            for line in text.splitlines():
                pieces += max(1, (_units(line) + capacity - 1) // capacity)
            if pieces > 1:
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            lines = max(lines, pieces)
        if lines > 1 and row[0].row:
            sheet.row_dimensions[row[0].row].height = min(15 * lines + 4, 48)
    if sheet.max_row >= header_row:
        sheet.freeze_panes = f"A{header_row + 1}"
        sheet.auto_filter.ref = f"A{header_row}:{get_column_letter(last_column)}{max(sheet.max_row, header_row)}"


def _diff(previous: dict[str, _PortRow], current: dict[str, _PortRow]) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    for symbol in sorted(set(previous) | set(current)):
        old = previous.get(symbol)
        new = current.get(symbol)
        if old is None and new is not None:
            changes.append((symbol, f"新增 {symbol}，球号 {new.ball}，功能 {new.function}".strip("，")))
            continue
        if new is None and old is not None:
            changes.append((symbol, f"删除 {symbol}，原球号 {old.ball}"))
            continue
        assert old is not None and new is not None
        parts: list[str] = []
        pairs = (
            ("球号", old.ball, new.ball),
            ("缓冲", old.buffer, new.buffer),
            ("上拉", old.pull, new.pull),
            ("供电", old.supply, new.supply),
            ("方向", old.direction, new.direction),
            ("功能", old.function, new.function),
            ("复用", old.mux, new.mux),
        )
        for label, before, after in pairs:
            if before != after:
                parts.append(f"{label}由{before or '空'}变更为{after or '空'}")
        if parts:
            changes.append((symbol, f"{symbol}：" + "；".join(parts)))
    return changes


def _clear_below(sheet, header_row: int) -> None:
    if sheet.max_row > header_row:
        sheet.delete_rows(header_row + 1, sheet.max_row - header_row)


def _write_cover(sheet, today: str, summary: str, version: str, remark: str) -> None:
    header_row = 0
    for row in range(1, 9):
        if _text(sheet.cell(row, 4).value) == "Version":
            header_row = row
            break
    if header_row == 0:
        return
    target = header_row + 1
    sheet.cell(target, 2, today)
    sheet.cell(target, 3, summary)
    sheet.cell(target, 4, version)
    sheet.cell(target, 5, remark)


def _write_history(sheet, today: str, changes: list[tuple[str, str]]) -> None:
    if _text(sheet.cell(1, 1).value) != _HISTORY_HEADERS[0]:
        for column, header in enumerate(_HISTORY_HEADERS, start=1):
            sheet.cell(1, column, header)
    _clear_below(sheet, 1)
    for index, (symbol, detail) in enumerate(changes, start=1):
        sheet.cell(index + 1, 1, index)
        sheet.cell(index + 1, 2, today)
        sheet.cell(index + 1, 3, detail)
        sheet.cell(index + 1, 4, "需人工确认")
        sheet.cell(index + 1, 5, symbol)


def _write_ports(
    sheet,
    mcu: str,
    package: str,
    drafts: list[tuple[_PortRow, str, str]],
    pins: tuple[ChipPin, ...],
    human: dict[str, object],
) -> None:
    sheet["A2"] = f"{mcu} Port Assignment [Main Table]"
    sheet["B3"] = f"MCU_{mcu}"
    sheet["B4"] = "Pin_Symbol"
    sheet["C4"] = f"{package}\\Ball"
    if not _text(sheet.cell(4, 14).value):
        sheet.cell(4, 14, "复用")
    sheet.cell(4, 20, "页码")
    sheet.cell(4, 21, "原文摘录")
    sheet.cell(4, COL_STATUS, "核对状态")
    sheet.cell(4, COL_MARK, "标记说明")
    sheet.cell(4, COL_HUMAN, "人工修改")
    _clear_below(sheet, 4)
    excerpts = {pin.symbol: pin.excerpt for pin in pins}
    for index, (row, status, note) in enumerate(drafts, start=1):
        excel_row = index + 4
        values = (
            index,
            row.symbol,
            row.ball,
            row.buffer,
            row.pull,
            row.supply,
            row.extra or None,
            row.direction,
            row.function,
        )
        for column, value in enumerate(values, start=1):
            sheet.cell(excel_row, column, value)
        for offset, value in enumerate(row.project):
            if value not in (None, ""):
                sheet.cell(excel_row, 10 + offset, value)
        sheet.cell(excel_row, 14, row.mux)
        sheet.cell(excel_row, 20, row.page)
        sheet.cell(excel_row, 21, excerpts.get(row.symbol, ""))
        sheet.cell(excel_row, COL_STATUS, status)
        if note:
            sheet.cell(excel_row, COL_MARK, note)
        if row.symbol in human:
            sheet.cell(excel_row, COL_HUMAN, human[row.symbol])


def _write_evidence(workbook: Workbook, pins: tuple[ChipPin, ...]) -> None:
    sheet = _fresh_sheet(workbook, SHEET_EVIDENCE)
    _write_rows(sheet, [list(_EVIDENCE_HEADERS)])
    for index, pin in enumerate(pins, start=2):
        values = (
            pin.symbol,
            pin.ball,
            pin.direction,
            pin.buffer,
            pin.function,
            pin.mux,
            pin.page,
            pin.excerpt,
        )
        for column, value in enumerate(values, start=1):
            if value not in (None, ""):
                sheet.cell(index, column, value)
    _fit_columns(sheet)


def _constraint_values(row: _PortRow, status: str, note: str) -> list[object]:
    project = row.project
    return [
        row.symbol,
        _field(project, 0),
        _field(project, 1),
        _field(project, 2),
        _field(project, 3),
        row.direction,
        _field(project, 5),
        _field(project, 6),
        _field(project, 7),
        _field(project, 8),
        _field(project, 9),
        _CONSTRAINT_SOURCE,
        status,
        note,
    ]


def _write_constraints(
    workbook: Workbook,
    pins: tuple[ChipPin, ...],
    grouped: dict[str, list[_PortRow]],
    shared: dict[str, list[str]],
    sub_map: dict[str, list[SubSheetEntry]] | None = None,
    llm_by_sym: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
    sheet = _fresh_sheet(workbook, SHEET_CONSTRAINT)
    body: list[list[object]] = [list(_CONSTRAINT_HEADERS)]
    seen: set[str] = set()
    for pin in pins:
        seen.add(pin.symbol)
        matches = _match_template_rows(pin, grouped)
        for row in matches:
            seen.add(row.symbol)
        distinct = _distinct_rows(matches)
        subs = _sub_entries_for(pin, sub_map or {})
        status, note, _project = _assess(
            pin,
            distinct,
            shared,
            sub_entries=subs,
            llm_findings=(llm_by_sym or {}).get(pin.symbol),
        )
        if not distinct:
            body.append([pin.symbol, "", "", "", "", "", "", "", "", "", "", "", status, note])
            continue
        for row in distinct:
            body.append(_constraint_values(row, status, note))
    for symbol, rows in grouped.items():
        if symbol in seen:
            continue
        distinct = _distinct_rows(rows)
        flags = [STATUS_GAP]
        notes = ["当份手册未出现该引脚符号"]
        if len(distinct) > 1:
            flags.append(STATUS_MULTI)
            names = [_project_name(row.project) or "空" for row in distinct]
            notes.append("吉利模板中该符号有多个端口名：" + "、".join(names))
        status = "；".join(flags)
        note = "；".join(notes)
        for row in distinct:
            body.append(_constraint_values(row, status, note))
    _write_rows(sheet, body)
    _fit_columns(sheet)


def _write_kept_sheet(workbook: Workbook, title: str, snapshot: list[list[object]] | None, default: list[list[object]]) -> None:
    sheet = _fresh_sheet(workbook, title)
    _write_rows(sheet, snapshot if snapshot is not None else default)
    skip: frozenset[int] = frozenset()
    header_row = 1
    if (
        title == SHEET_ACCEPT
        and _text(sheet.cell(1, 1).value).startswith("本表只保留")
        and sheet.cell(1, 2).value in (None, "")
    ):
        span = max(sheet.max_column, len(_ACCEPT_HEADERS))
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
        sheet.cell(1, 1).alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 32
        skip = frozenset({1})
        header_row = 2
    _fit_columns(sheet, skip_rows=skip, header_row=header_row)


def write_hsi_workbook(
    template: Path,
    dest: Path,
    *,
    mcu: str,
    package: str,
    pins: tuple[ChipPin, ...],
    previous: Path | None = None,
    ask: Ask | None = None,
) -> HsiResult:
    if not pins:
        raise ValueError(f"手册中没有读到 {package} 的引脚表。")
    template_book = load_workbook(template)
    previous_rows: dict[str, _PortRow] = {}
    previous_version = ""
    human: dict[str, object] = {}
    revision_snapshot: list[list[object]] | None = None
    accept_snapshot: list[list[object]] | None = None
    if previous is not None and previous.is_file():
        previous_book = load_workbook(previous, data_only=True)
        try:
            previous_rows = _rows_from_sheet(previous_book)
            previous_version = _read_version(previous_book)
            human = _human_by_symbol(previous_book)
            revision_snapshot = _snapshot(previous_book, SHEET_REVISION)
            accept_snapshot = _snapshot(previous_book, SHEET_ACCEPT)
        finally:
            previous_book.close()
    grouped: dict[str, list[_PortRow]] = {}
    for row in _port_rows(template_book):
        grouped.setdefault(row.symbol, []).append(row)
    shared = _shared_names(pins, grouped)
    sub_map = extract_subsheet_entries(template_book)
    llm_candidates: list[tuple[ChipPin, str, str, tuple[object, ...], list[SubSheetEntry]]] = []
    if ask is not None:
        for pin in pins:
            distinct = _distinct_rows(_match_template_rows(pin, grouped))
            if len(distinct) != 1:
                continue
            row0 = distinct[0]
            subs = _sub_entries_for(pin, sub_map)
            finding = check_template_row_anomalies(
                pin,
                row0.direction,
                row0.function,
                row0.project,
                subs,
                template_ball=row0.ball,
            )
            if _is_llm_candidate(pin, row0.direction, row0.function, row0.project, finding):
                llm_candidates.append((pin, row0.direction, row0.function, row0.project, subs))
    llm_by_sym, model_used = run_llm_pin_qa(llm_candidates, ask)

    drafts: list[tuple[_PortRow, str, str]] = []
    current_rows: dict[str, _PortRow] = {}
    conflict_count = 0
    for pin in pins:
        matches = _match_template_rows(pin, grouped)
        subs = _sub_entries_for(pin, sub_map)
        status, note, project = _assess(
            pin,
            matches,
            shared,
            sub_entries=subs,
            llm_findings=llm_by_sym.get(pin.symbol),
        )
        if STATUS_CONFLICT in status:
            conflict_count += 1
        row = _pin_row(pin, project)
        drafts.append((row, status, note))
        current_rows[pin.symbol] = row
    changes = _diff(previous_rows, current_rows) if previous_rows else []
    version = _next_version(mcu, package, previous_version)
    today = date.today().strftime("%Y%m%d")
    if previous_rows:
        summary = f"相对上一版 {len(changes)} 处端口差异"
    else:
        summary = "首次按手册生成端口表"
    remark = (
        "初始配置表的引脚、球号、方向、功能和复用来自当份手册。"
        "端口命名、电平、ASIL 和硬件逻辑按吉利模板对照填写，状态为待人工确认。"
        "模板没有该符号记缺项；同一符号多个端口名，或同一端口名对应多个符号，记多候选；"
        "手册方向与模板方向相反，或硬件外设复用能力与模板定义不符记约束冲突。这些行都不写成已确认。"
        "人工修订记录和验收实测只保留表上已有内容。"
    )
    _write_cover(template_book[SHEET_COVER], today, summary, version, remark)
    _write_history(template_book[SHEET_HISTORY], today, changes)
    _write_ports(template_book[SHEET_PORT], mcu, package, drafts, pins, human)
    _write_evidence(template_book, pins)
    _write_constraints(template_book, pins, grouped, shared, sub_map=sub_map, llm_by_sym=llm_by_sym)
    _write_kept_sheet(
        template_book,
        SHEET_REVISION,
        revision_snapshot,
        [list(_REVISION_HEADERS)],
    )
    _write_kept_sheet(
        template_book,
        SHEET_ACCEPT,
        accept_snapshot,
        [[_ACCEPT_NOTE], list(_ACCEPT_HEADERS)],
    )
    template_book.active = template_book[SHEET_PORT]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    template_book.save(dest)
    template_book.close()
    return HsiResult(
        dest,
        mcu,
        package,
        version,
        len(drafts),
        len(changes),
        today,
        conflicts=conflict_count,
        model_used=model_used,
    )


def build_hsi(
    template: Path,
    datasheet: Path,
    dest: Path,
    *,
    package: str = "",
    previous: Path | None = None,
    ask: Ask | None = None,
) -> HsiResult:
    pages = read_pdf_pages(datasheet)
    mcu = mcu_name(datasheet.name, pages)
    choices = parse_pin_pages(pages)
    if not choices:
        raise ValueError("手册中没有读到封装引脚表。")
    chosen = package.strip().upper().replace("-", "").replace(" ", "")
    if not chosen:
        if len(choices) != 1:
            raise ValueError("手册里有多种封装，请指定：" + "、".join(choices))
        chosen = choices[0]
    else:
        normalized = {item.upper().replace("-", "").replace(" ", ""): item for item in choices}
        if chosen not in normalized:
            raise ValueError("手册中没有封装 " + package + "。可读到：" + "、".join(choices))
        chosen = normalized[chosen]
    pins = parse_pins(pages, chosen)
    return write_hsi_workbook(
        template,
        dest,
        mcu=mcu,
        package=chosen,
        pins=pins,
        previous=previous,
        ask=ask,
    )
