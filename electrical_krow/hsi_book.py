"""按 DHTE400 HSI V1.3（2026-10-23）出一份手册对应的 HSI。

端口表的引脚只写当份手册。端口命名、ATOM/DTM 和约束只在模板有同一引脚符号时对照填入，
并标成待人工确认。缺项、多个候选、方向冲突单独标出，不写成已确认。
人工修订和验收实测只保留上一版已经写下的内容。
这版模板自带的工作表、封面修改要求和已有版本记录保留。
没有版本列的旧模板仍按原规则：没有上一版时变更记录只留表头，并去掉用不到的表。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook

from electrical_krow.hsi_qa import (
    Ask,
    SubSheetEntry,
    _is_llm_candidate,
    allocation_notes,
    check_peripheral_capability,
    check_template_row_anomalies,
    extract_subsheet_entries,
    norm_symbol,
    pin_lookup_keys,
    run_llm_pin_qa,
    split_symbol_parts,
)
from electrical_krow.hsi_dead_time import apply_dead_time_sheet
from electrical_krow.hsi_schematic import BoardPin, SchematicHit, pin_key, read_board_pins, read_schematic
from electrical_krow.mcu_pins import (
    ChipPin,
    mcu_name,
    parse_pin_pages,
    parse_pins,
    present_excerpt,
    present_mux,
    read_pdf_pages,
)

DEFAULT_HSI_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "DHTE400-HSI-V1.3-20261023.xlsx"
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
_ACCEPT_HEADERS = (
    "引脚符号",
    "匹配实测",
    "降额实测",
    "安全相关实测",
    "与手册是否一致",
    "与确认约束是否一致",
)
_CONSTRAINT_SOURCE = "HSI模板"
_COLUMN_CAP = 40
_COLUMN_FLOOR = 12
_NC_NAMES = frozenset({"NC", "N.C.", "N/A", "NA"})
_VERSION = re.compile(r"^(?P<body>.+)-(?P<n>\d+)$")
_TOC_TITLES = {"Tabel of Content", "Table of Content", "Table of Contents"}
_TOC_PREFIX = re.compile(r"^\d+[_-]")
_TOC_SKIP = frozenset({SHEET_COVER, "WpsReserved_CellImgList"})
_KEEP_SHEETS = frozenset({
    SHEET_COVER,
    SHEET_HISTORY,
    SHEET_PORT,
    "3_ADC Table",
    "3-SPI总线",
    SHEET_EVIDENCE,
    SHEET_CONSTRAINT,
    SHEET_REVISION,
    SHEET_ACCEPT,
})
_TOC_REFERENCE_LABEL = {
    "3_ADC Table": "ADC Table（模板对照）",
    "3-SPI总线": "SPI总线（模板对照）",
}


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
    schematic_updates: int = 0


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
    kept: tuple[object, ...] = ()


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


def _sheet(workbook: Workbook, title: str):
    if title in workbook.sheetnames:
        return workbook[title]
    wanted = title.strip()
    for name in workbook.sheetnames:
        if name.strip() == wanted:
            return workbook[name]
    aliases = {
        "0_Cover": ("Cover",),
        "3-SPI总线": ("4-SPI总线",),
    }
    for alias in aliases.get(wanted, ()):
        for name in workbook.sheetnames:
            if name.strip() == alias:
                return workbook[name]
    return None


def _cover_sheet(workbook: Workbook):
    return _sheet(workbook, SHEET_COVER) or _sheet(workbook, "Cover")


def _port_sheet(workbook: Workbook):
    return _sheet(workbook, SHEET_PORT)


def _history_sheet(workbook: Workbook):
    return _sheet(workbook, SHEET_HISTORY)


def _keeps_template_body(workbook: Workbook) -> bool:
    """DHTE400 V1.3 整本都要留下，封面修改要求也不能重写。"""
    if any(name.strip().startswith("0_硬件") for name in workbook.sheetnames):
        return True
    cover = _cover_sheet(workbook)
    return cover is not None and _text(cover.cell(1, 4).value) == "修改人"


def _read_version(workbook: Workbook) -> str:
    sheet = _cover_sheet(workbook)
    if sheet is None:
        return ""
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


@dataclass(frozen=True)
class _PortLayout:
    header: int
    data_start: int
    legacy: bool
    direction: int = 8
    function: int = 9
    name: int = 10
    desc: int = 11
    net: int = 0
    pull: int = 5
    high: int = 16
    low: int = 17
    init: int = 18
    mux: int = 14
    page: int = 20
    excerpt: int = 21
    status: int = 22
    mark: int = 23
    human: int = 24


def _port_layout(sheet) -> _PortLayout:
    """表头决定列。DHTE400 的方向在 I、功能在 J、端口名在 L；旧表方向在 H、端口名在 J。"""
    header = 0
    for row in range(1, 8):
        labels = [_text(sheet.cell(row, col).value) for col in range(1, 20)]
        if "Function" in labels and "Direction" in labels:
            header = row
            break
    if header == 0:
        return _PortLayout(header=4, data_start=5, legacy=True)
    direction_col = function_col = net = high = low = init = 0
    pin_defs: list[int] = []
    for col in range(1, 30):
        text = _text(sheet.cell(header, col).value)
        if text == "Direction" and not direction_col:
            direction_col = col
        elif text == "Function" and not function_col:
            function_col = col
        elif text.startswith("Pin Definition"):
            pin_defs.append(col)
        elif "原理图" in text and not net:
            net = col
        elif text.startswith("High") and not high:
            high = col
        elif text.startswith("Low") and not low:
            low = col
        elif text.startswith("Initial") and not init:
            init = col
    if direction_col == 8 and function_col == 9:
        return _PortLayout(header=header, data_start=header + 1, legacy=True)
    name = pin_defs[0] if pin_defs else 12
    desc = pin_defs[1] if len(pin_defs) > 1 else name + 1
    return _PortLayout(
        header=header,
        data_start=header + 1,
        legacy=False,
        direction=direction_col,
        function=function_col,
        name=name,
        desc=desc,
        net=net,
        high=high or 16,
        low=low or 17,
        init=init or 18,
        mux=19,
    )


def _project_cells(sheet, row: int) -> tuple[object, ...]:
    return tuple(sheet.cell(row, column).value for column in range(10, 20))


def _project_from_layout(sheet, row: int, layout: _PortLayout) -> tuple[object, ...]:
    def cell(column: int) -> object:
        return sheet.cell(row, column).value if column else None

    return (
        cell(layout.name),
        cell(layout.desc),
        None,
        None,
        cell(layout.net),
        cell(layout.pull),
        cell(layout.high),
        cell(layout.low),
        cell(layout.init),
        None,
    )


def _port_rows(workbook: Workbook) -> list[_PortRow]:
    sheet = _port_sheet(workbook)
    if sheet is None:
        return []
    layout = _port_layout(sheet)
    found: list[_PortRow] = []
    for row in range(layout.data_start, (sheet.max_row or layout.data_start) + 1):
        symbol = _text(sheet.cell(row, 2).value)
        if not symbol or symbol.lower() in {"pin_symbol", "bga436\\ball"}:
            continue
        if layout.legacy:
            project = _project_cells(sheet, row)
            kept: tuple[object, ...] = ()
            direction = _text(sheet.cell(row, 8).value)
            function = _text(sheet.cell(row, 9).value)
            extra = _text(sheet.cell(row, 7).value)
            mux = _text(sheet.cell(row, 14).value)
            page = _text(sheet.cell(row, 20).value)
        else:
            project = _project_from_layout(sheet, row, layout)
            kept = tuple(sheet.cell(row, column).value for column in range(7, 19))
            direction = _text(sheet.cell(row, layout.direction).value)
            function = _text(sheet.cell(row, layout.function).value)
            extra = ""
            mux = _text(sheet.cell(row, layout.mux).value)
            page = _text(sheet.cell(row, layout.page).value)
        found.append(
            _PortRow(
                symbol=symbol,
                ball=_text(sheet.cell(row, 3).value),
                buffer=_text(sheet.cell(row, 4).value),
                pull=_text(sheet.cell(row, 5).value),
                supply=_text(sheet.cell(row, 6).value),
                extra=extra,
                direction=direction,
                function=function,
                mux=mux,
                page=page,
                project=project,
                kept=kept,
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
    extra_conflicts: list[str] | None = None,
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
        add_note("模板没有该引脚符号")
    else:
        if len(distinct) > 1:
            add_flag(STATUS_MULTI)
            names = [_project_name(row.project) or "空" for row in distinct]
            add_note("模板中该符号有多个端口名：" + "、".join(names))
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
            add_note(f"手册方向为 {pin.direction}，模板方向为 {shown}")

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

    for text in extra_conflicts or []:
        add_flag(STATUS_CONFLICT)
        add_note(text)

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
    sheet = _port_sheet(workbook)
    if sheet is None:
        return {}
    layout = _port_layout(sheet)
    found: dict[str, object] = {}
    for row in range(layout.data_start, (sheet.max_row or layout.data_start) + 1):
        symbol = _text(sheet.cell(row, 2).value)
        value = sheet.cell(row, layout.human).value
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
            ("复用", present_mux(old.mux), present_mux(new.mux)),
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


def _drop_row_highlights(sheet, header_row: int) -> None:
    """模板用整行黄、紫底色标过原端口。接插件脚不沿用这层颜色。"""
    for key in list(sheet.row_dimensions):
        if isinstance(key, int) and key > header_row:
            del sheet.row_dimensions[key]


def _toc_items(sheetnames: list[str]) -> list[str]:
    """目录项与工作表标签同一顺序。去掉表名前面的序号，封面和内部保留表不进目录。"""
    items: list[str] = []
    for name in sheetnames:
        if name in _TOC_SKIP or name.startswith("WpsReserved"):
            continue
        if name in _TOC_REFERENCE_LABEL:
            items.append(_TOC_REFERENCE_LABEL[name])
            continue
        title = _TOC_PREFIX.sub("", name).strip()
        items.append(title or name)
    return items


def _drop_unused_template_sheets(workbook: Workbook) -> None:
    """旧模板只留本次写出的表，以及仍用来对照的 ADC、SPI 表。DHTE400 整本保留。"""
    if _keeps_template_body(workbook):
        return
    for name in list(workbook.sheetnames):
        if name not in _KEEP_SHEETS:
            del workbook[name]


def _sync_cover_toc(sheet, sheetnames: list[str]) -> None:
    """按当前工作表重写封面目录，删掉模板里已不存在的项，补上多出来的表。"""
    if _text(sheet.cell(1, 4).value) == "修改人":
        return
    title_row = None
    for row in range(1, 40):
        if _text(sheet.cell(row, 2).value) in _TOC_TITLES:
            title_row = row
            break
    if title_row is None:
        return
    start = title_row + 1
    items = _toc_items(sheetnames)
    stale = [
        str(merged)
        for merged in sheet.merged_cells.ranges
        if merged.min_col == 3 and merged.max_col >= 3 and merged.min_row >= start and merged.max_row == merged.min_row
    ]
    for ref in stale:
        sheet.unmerge_cells(ref)
    old_end = start - 1
    for row in range(start, start + 80):
        number = sheet.cell(row, 2).value
        if isinstance(number, int) or (isinstance(number, str) and str(number).isdigit()):
            old_end = row
        elif old_end >= start:
            break
    sample_num = sheet.cell(start, 2)
    sample_name = sheet.cell(start, 3)
    last = max(old_end, start + len(items) - 1)
    for row in range(start, last + 1):
        sheet.cell(row, 2).value = None
        sheet.cell(row, 3).value = None
    from openpyxl.styles import Border, Side

    thin = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    for index, title in enumerate(items, start=1):
        row = start + index - 1
        number = sheet.cell(row, 2, index)
        name = sheet.cell(row, 3, title)
        number.font = copy(sample_num.font)
        number.alignment = copy(sample_num.alignment)
        number.border = thin
        name.font = copy(sample_name.font)
        name.alignment = copy(sample_name.alignment)
        name.border = thin
        sheet.merge_cells(start_row=row, start_column=3, end_row=row, end_column=5)
        for column in (4, 5):
            sheet.cell(row, column).border = thin
    for row in range(start + len(items), last + 1):
        for column in range(2, 6):
            cell = sheet.cell(row, column)
            cell.value = None
            cell.border = Border()


_COVER_REMARK = "引脚来自当份手册。命名和约束对照模板，缺项、多候选、方向冲突待确认。"


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
    end = target
    for row in range(target, target + 20):
        edge = sheet.cell(row, 5).border.right
        if edge is not None and edge.style:
            end = row
        elif row > target:
            break
    cell = sheet.cell(target, 5, remark)
    cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    if end > target:
        sheet.merge_cells(start_row=target, start_column=5, end_row=end, end_column=5)


def _fit_history_row(sheet, row: int) -> None:
    """详细描述按列宽换行，行高只跟这一格的字数走。"""
    lines = 1
    for column in range(1, 8):
        cell = sheet.cell(row, column)
        text = _text(cell.value)
        if not text:
            continue
        width = sheet.column_dimensions[get_column_letter(column)].width
        header = _text(sheet.cell(1, column).value)
        if not width:
            width = 78 if column == 3 or header == "详细描述" else 24
        capacity = max(int(width) - 1, 1)
        pieces = 0
        for line in text.splitlines():
            pieces += max(1, (_units(line) + capacity - 1) // capacity)
        if pieces > 1:
            cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
        lines = max(lines, pieces)
    if lines > 1:
        sheet.row_dimensions[row].height = min(15 * lines + 4, 409)


def _write_history(sheet, today: str, changes: list[tuple[str, str]]) -> None:
    headers = {_text(sheet.cell(1, column).value): column for column in range(1, 8)}
    if {"版本", "变更日期", "详细描述"} <= set(headers):
        if not changes:
            return
        last = 1
        count = 0
        for row in range(2, (sheet.max_row or 1) + 1):
            if sheet.cell(row, 1).value not in (None, ""):
                last = row
                count += 1
        for index, (symbol, detail) in enumerate(changes, start=1):
            row = last + index
            sheet.cell(row, 1, count + index)
            sheet.cell(row, headers["变更日期"], today)
            sheet.cell(row, headers["详细描述"], detail)
            if "影响分析" in headers:
                sheet.cell(row, headers["影响分析"], "需人工确认")
            if "备注" in headers:
                sheet.cell(row, headers["备注"], symbol)
            _fit_history_row(sheet, row)
        return
    if _text(sheet.cell(1, 1).value) != _HISTORY_HEADERS[0]:
        for column, header in enumerate(_HISTORY_HEADERS, start=1):
            sheet.cell(1, column, header)
    _clear_below(sheet, 1)
    # delete_rows 只挪单元格，模板里为长说明留下的行高还挂在原行号上
    for key in list(sheet.row_dimensions):
        if isinstance(key, int) and key > 1:
            del sheet.row_dimensions[key]
    for index, (symbol, detail) in enumerate(changes, start=1):
        row = index + 1
        sheet.cell(row, 1, index)
        sheet.cell(row, 2, today)
        sheet.cell(row, 3, detail)
        sheet.cell(row, 4, "需人工确认")
        sheet.cell(row, 5, symbol)
        _fit_history_row(sheet, row)


def _wrap_port_row(sheet, row: int, widths: dict[int, int] | None = None) -> None:
    """复用和原文摘录按功能换行，列宽够读完整的一条功能。"""
    widths = widths or {14: 56, 21: 56, 22: 18, 23: 36}
    lines = 1
    for column, width in widths.items():
        cell = sheet.cell(row, column)
        text = _text(cell.value)
        if not text:
            continue
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        capacity = max(int(width) - 1, 1)
        pieces = 0
        for line in text.splitlines():
            pieces += max(1, (_units(line) + capacity - 1) // capacity)
        lines = max(lines, pieces)
    if lines > 1:
        sheet.row_dimensions[row].height = min(15 * lines + 4, 96)


_LINK_SKIP = frozenset({"", "-", "--", "NC", "N.C.", "N/A", "NA"})


def _mark_link(cell, location: str, tooltip: str = "") -> None:
    """表内跳转写在 location。写成 target 时，Excel 会把它当成外部文件。"""
    text = _text(cell.value)
    if not text:
        return
    cell.hyperlink = Hyperlink(
        ref=cell.coordinate,
        location=location,
        display=text,
        tooltip=tooltip or None,
    )
    current = cell.font
    cell.font = Font(
        name=current.name,
        size=current.size,
        bold=current.bold,
        color="0563C1",
        underline="single",
    )


def _row_anchor(workbook: Workbook, sheet, row: int) -> str:
    """用整行名称当落点。点开后 Excel 选中这一整行，行号在左侧亮起来。"""
    title = sheet.title.upper()
    if "ADC" in title:
        key = "ADC"
    elif "SPI" in title:
        key = "SPI"
    elif "PORT" in title:
        key = "PORT"
    else:
        key = "SHEET"
    name = f"HSI_{key}_{row}"
    if name not in workbook.defined_names:
        safe = sheet.title.replace("'", "''")
        workbook.defined_names.add(DefinedName(name=name, attr_text=f"'{safe}'!${row}:${row}"))
    return name


def _sheet_cell(title: str, row: int, column: int) -> str:
    safe = title.replace("'", "''")
    return f"'{safe}'!{get_column_letter(column)}{row}"


def _header_column(sheet, label: str) -> tuple[int, int]:
    want = label.casefold()
    for row in range(1, 8):
        for column in range(1, min(sheet.max_column or 1, 40) + 1):
            if _text(sheet.cell(row, column).value).casefold().startswith(want):
                return row, column
    return 0, 0


def _indexed_column(sheet, header_row: int, column: int) -> dict[str, tuple[int, int]]:
    found: dict[str, tuple[int, int]] = {}
    if not header_row or not column:
        return found
    for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
        text = _text(sheet.cell(row, column).value)
        if text.upper() in _LINK_SKIP or text in found:
            continue
        found[text] = (row, column)
    return found


def _link_detail_sheets(workbook: Workbook) -> None:
    """端口名跳到 ADC 信号行，引脚符号和原理图网络跳到 SPI 行。对得上的格子互相跳。"""
    port = _port_sheet(workbook)
    if port is None:
        return
    layout = _port_layout(port)
    adc = _sheet(workbook, "3_ADC Table")
    spi = None
    for name in workbook.sheetnames:
        if name.strip().endswith("SPI总线"):
            spi = workbook[name]
            break
    adc_rows: dict[str, tuple[int, int]] = {}
    if adc is not None:
        header, column = _header_column(adc, "Signal name")
        adc_rows = _indexed_column(adc, header, column)
    spi_pins: dict[str, tuple[int, int]] = {}
    spi_nets: dict[str, tuple[int, int]] = {}
    if spi is not None:
        pin_header = net_header = 0
        pin_col = net_col = 0
        for row in range(1, 8):
            pins = nets = 0
            for column in range(1, min(spi.max_column or 1, 12) + 1):
                text = _text(spi.cell(row, column).value).casefold()
                if text == "pin":
                    pins = column
                elif text == "net name":
                    nets = column
            if pins and nets:
                pin_header, pin_col, net_header, net_col = row, pins, row, nets
                break
        spi_pins = _indexed_column(spi, pin_header, pin_col)
        spi_nets = _indexed_column(spi, net_header, net_col)
    seen_adc: set[str] = set()
    seen_pin: set[str] = set()
    seen_net: set[str] = set()
    for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
        symbol = _text(port.cell(row, 2).value)
        name = _text(port.cell(row, layout.name).value)
        net = _text(port.cell(row, layout.net).value) if layout.net else ""
        if adc is not None and name and name.upper() not in _LINK_SKIP and name in adc_rows:
            target_row, target_col = adc_rows[name]
            _mark_link(
                port.cell(row, layout.name),
                _row_anchor(workbook, adc, target_row),
                f"第{target_row}行 {name}",
            )
            if name not in seen_adc:
                _mark_link(
                    adc.cell(target_row, target_col),
                    _row_anchor(workbook, port, row),
                    f"第{row}行 {name}",
                )
                seen_adc.add(name)
        if spi is not None and symbol and symbol.upper() not in _LINK_SKIP and symbol in spi_pins:
            target_row, target_col = spi_pins[symbol]
            _mark_link(
                port.cell(row, 2),
                _row_anchor(workbook, spi, target_row),
                f"第{target_row}行 {symbol}",
            )
            if symbol not in seen_pin:
                _mark_link(
                    spi.cell(target_row, target_col),
                    _row_anchor(workbook, port, row),
                    f"第{row}行 {symbol}",
                )
                seen_pin.add(symbol)
        if spi is not None and layout.net and net and net.upper() not in _LINK_SKIP and net in spi_nets:
            target_row, target_col = spi_nets[net]
            _mark_link(
                port.cell(row, layout.net),
                _row_anchor(workbook, spi, target_row),
                f"第{target_row}行 {net}",
            )
            if net not in seen_net:
                _mark_link(
                    spi.cell(target_row, target_col),
                    _row_anchor(workbook, port, row),
                    f"第{row}行 {net}",
                )
                seen_net.add(net)


def _external_state_column(sheet, header: int) -> int:
    for row in (header, header - 1, 2):
        if row < 1:
            continue
        for column in range(1, min(sheet.max_column or 1, 40) + 1):
            if "外部" in _text(sheet.cell(row, column).value):
                return column
    return 0


def _schematic_note(hit: SchematicHit) -> str:
    parts = [f"原理图网络 {hit.net}"]
    if not hit.pulls:
        parts.append("未看到接到电源或地的电阻")
    else:
        for item in hit.pulls:
            parts.append(f"外部{item.kind} {item.part} {item.value} 至 {item.other}".strip())
    parts.append("待人工复核")
    return "；".join(parts)


def _apply_schematic(workbook: Workbook, schematic: Path | None) -> int:
    """只按 MCU 引脚符号写入原理图网络和外部电阻。端口名相近但不含引脚符号时不改。"""
    if schematic is None:
        return 0
    found = read_schematic(schematic)
    if not found:
        return 0
    port = _port_sheet(workbook)
    if port is None:
        return 0
    layout = _port_layout(port)
    external = _external_state_column(port, layout.header)
    updated = 0
    for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
        symbol = _text(port.cell(row, 2).value)
        hit = None
        for part in re.split(r"[/]", symbol):
            key = pin_key(part)
            if key and key in found:
                hit = found[key]
                break
        if hit is None:
            continue
        if layout.net:
            port.cell(row, layout.net, hit.net)
        if external and hit.pulls:
            kinds = {item.kind for item in hit.pulls}
            if len(kinds) == 1:
                values = "、".join(dict.fromkeys(item.value for item in hit.pulls if item.value))
                port.cell(row, external, f"{next(iter(kinds))} {values}".strip())
            else:
                port.cell(row, external, "上拉/下拉")
        mark = port.cell(row, layout.mark)
        current = _text(mark.value)
        note = _schematic_note(hit)
        mark.value = f"{current}；{note}" if current else note
        status = port.cell(row, layout.status)
        shown = _text(status.value)
        if STATUS_DRAFT not in shown and STATUS_CONFLICT not in shown:
            status.value = f"{shown}；{STATUS_DRAFT}" if shown else STATUS_DRAFT
        updated += 1
    return updated


def _pull_text(pulls: tuple) -> str:
    if not pulls:
        return ""
    kinds = {item.kind for item in pulls}
    if len(kinds) != 1:
        return "上拉/下拉"
    values = "、".join(dict.fromkeys(item.value for item in pulls if item.value))
    return f"{next(iter(kinds))} {values}".strip()


def _board_note(pin: BoardPin) -> str:
    parts = [f"接插件 {pin.label}", f"原理图网络 {pin.net}"]
    if pin.pulls:
        for item in pin.pulls:
            parts.append(f"外部{item.kind} {item.part} {item.value} 至 {item.other}".strip())
    else:
        parts.append("未看到接到电源或地的电阻")
    parts.append("待人工复核")
    return "；".join(parts)


def _write_board_pins(workbook: Workbook, pins: list[BoardPin]) -> int:
    """用接插件自己的脚重写端口数据。表头、封面和其他页保留，不保留模板里的 MCU 引脚。"""
    port = _port_sheet(workbook)
    if port is None or not pins:
        return 0
    layout = _port_layout(port)
    external = _external_state_column(port, layout.header)
    _unmerge_from(port, layout.data_start)
    _clear_below(port, layout.header)
    _drop_row_highlights(port, layout.header)
    port.sheet_view.view = "normal"
    for index, pin in enumerate(pins, start=1):
        row = layout.header + index
        port.cell(row, 1, index)
        port.cell(row, 2, pin.label)
        if layout.net:
            port.cell(row, layout.net, pin.net)
        if layout.name:
            port.cell(row, layout.name, pin.net)
        shown = _pull_text(pin.pulls)
        if external and shown:
            port.cell(row, external, shown)
        port.cell(row, layout.status, STATUS_DRAFT)
        port.cell(row, layout.mark, _board_note(pin))
    return len(pins)


def _hide_adc_spare_columns(workbook: Workbook) -> None:
    """ADC 表里这版不参与复核的 R1、R3 列隐藏，格子里的电阻值保留。"""
    sheet = _sheet(workbook, "3_ADC Table")
    if sheet is None:
        return
    for row in range(1, 8):
        for column in range(1, min(sheet.max_column or 1, 40) + 1):
            compact = _text(sheet.cell(row, column).value).replace(" ", "")
            if compact.startswith("R1(") or compact.startswith("R3("):
                sheet.column_dimensions[get_column_letter(column)].hidden = True


def _link_home(workbook: Workbook) -> None:
    """表头「返回首页」链回封面。"""
    cover = _cover_sheet(workbook)
    if cover is None:
        return
    for name in workbook.sheetnames:
        if name == cover.title:
            continue
        sheet = workbook[name]
        limit_row = min(sheet.max_row or 1, 6)
        limit_col = min(sheet.max_column or 1, 8)
        for row in sheet.iter_rows(max_row=limit_row, max_col=limit_col):
            for cell in row:
                if _text(cell.value) != "返回首页":
                    continue
                _mark_link(cell, _sheet_cell(cover.title, 1, 1))


def _unmerge_from(sheet, row: int) -> None:
    stale = [str(merged) for merged in sheet.merged_cells.ranges if merged.min_row >= row]
    for ref in stale:
        sheet.unmerge_cells(ref)


def _write_ports_v13(
    sheet,
    layout: _PortLayout,
    mcu: str,
    drafts: list[tuple[_PortRow, str, str]],
    pins: tuple[ChipPin, ...],
    human: dict[str, object],
) -> None:
    """DHTE400：手册只覆盖球号和缓冲。ATOM、DTM、方向、功能和端口名留在原列。"""
    if _text(sheet.cell(2, 2).value).startswith("MCU_"):
        sheet.cell(2, 2, f"MCU_{mcu}")
    sheet.cell(layout.header, layout.mux, "复用")
    sheet.cell(layout.header, layout.page, "页码")
    sheet.cell(layout.header, layout.excerpt, "原文摘录")
    sheet.cell(layout.header, layout.status, "核对状态")
    sheet.cell(layout.header, layout.mark, "标记说明")
    sheet.cell(layout.header, layout.human, "人工修改")
    _unmerge_from(sheet, layout.data_start)
    _clear_below(sheet, layout.header)
    excerpts = {pin.symbol: pin.excerpt for pin in pins}
    wrap = {layout.mux: 56, layout.excerpt: 56, layout.status: 18, layout.mark: 36}
    for index, (row, status, note) in enumerate(drafts, start=1):
        excel_row = layout.header + index
        sheet.cell(excel_row, 1, index)
        sheet.cell(excel_row, 2, row.symbol)
        sheet.cell(excel_row, 3, row.ball)
        sheet.cell(excel_row, 4, row.buffer or None)
        sheet.cell(excel_row, 5, row.pull or None)
        sheet.cell(excel_row, 6, row.supply or None)
        for offset, value in enumerate(row.kept):
            if value not in (None, ""):
                sheet.cell(excel_row, 7 + offset, value)
        if not row.kept:
            if row.direction:
                sheet.cell(excel_row, layout.direction, row.direction)
            if row.function:
                sheet.cell(excel_row, layout.function, row.function)
            name = _field(row.project, 0)
            desc = _field(row.project, 1)
            net = _field(row.project, 4)
            if name:
                sheet.cell(excel_row, layout.name, name)
            if desc:
                sheet.cell(excel_row, layout.desc, desc)
            if net and layout.net:
                sheet.cell(excel_row, layout.net, net)
            for column, project_index in ((layout.high, 6), (layout.low, 7), (layout.init, 8)):
                value = _field(row.project, project_index)
                if value and column:
                    sheet.cell(excel_row, column, value)
        sheet.cell(excel_row, layout.mux, present_mux(row.mux))
        sheet.cell(excel_row, layout.page, row.page)
        sheet.cell(excel_row, layout.excerpt, present_excerpt(excerpts.get(row.symbol, "")))
        sheet.cell(excel_row, layout.status, status)
        if note:
            sheet.cell(excel_row, layout.mark, note)
        if row.symbol in human:
            sheet.cell(excel_row, layout.human, human[row.symbol])
        _wrap_port_row(sheet, excel_row, wrap)
    for column, width in wrap.items():
        sheet.column_dimensions[get_column_letter(column)].width = width
    last = layout.header + len(drafts)
    sheet.auto_filter.ref = f"A{layout.header}:{get_column_letter(layout.human)}{max(last, layout.header)}"


def _write_ports(
    sheet,
    mcu: str,
    package: str,
    drafts: list[tuple[_PortRow, str, str]],
    pins: tuple[ChipPin, ...],
    human: dict[str, object],
) -> None:
    layout = _port_layout(sheet)
    if not layout.legacy:
        _write_ports_v13(sheet, layout, mcu, drafts, pins, human)
        return
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
        sheet.cell(excel_row, 14, present_mux(row.mux))
        sheet.cell(excel_row, 20, row.page)
        sheet.cell(excel_row, 21, present_excerpt(excerpts.get(row.symbol, "")))
        sheet.cell(excel_row, COL_STATUS, status)
        if note:
            sheet.cell(excel_row, COL_MARK, note)
        if row.symbol in human:
            sheet.cell(excel_row, COL_HUMAN, human[row.symbol])
        _wrap_port_row(sheet, excel_row)
    sheet.column_dimensions["N"].width = 56
    sheet.column_dimensions["U"].width = 56
    sheet.column_dimensions["V"].width = 18
    sheet.column_dimensions["W"].width = 36
    last = 4 + len(drafts)
    sheet.auto_filter.ref = f"A4:{get_column_letter(COL_HUMAN)}{max(last, 4)}"


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
            present_mux(pin.mux),
            pin.page,
            present_excerpt(pin.excerpt),
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
    allocation: dict[str, list[str]] | None = None,
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
            extra_conflicts=(allocation or {}).get(pin.symbol),
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
            notes.append("模板中该符号有多个端口名：" + "、".join(names))
        status = "；".join(flags)
        note = "；".join(notes)
        for row in distinct:
            body.append(_constraint_values(row, status, note))
    _write_rows(sheet, body)
    _fit_columns(sheet)


def _drop_accept_banner(rows: list[list[object]] | None) -> list[list[object]] | None:
    """上一版若把口径说明写在验收表首行，生成时去掉，不带到新表。"""
    if not rows:
        return rows
    first = rows[0]
    if first and _text(first[0]).startswith("本表只保留"):
        return rows[1:]
    return rows


def _write_kept_sheet(workbook: Workbook, title: str, snapshot: list[list[object]] | None, default: list[list[object]]) -> None:
    sheet = _fresh_sheet(workbook, title)
    rows = _drop_accept_banner(snapshot) if title == SHEET_ACCEPT else snapshot
    _write_rows(sheet, rows if rows is not None else default)
    _fit_columns(sheet)


def write_hsi_workbook(
    template: Path,
    dest: Path,
    *,
    mcu: str,
    package: str,
    pins: tuple[ChipPin, ...],
    previous: Path | None = None,
    ask: Ask | None = None,
    on_progress=None,
    schematic: Path | None = None,
) -> HsiResult:
    """on_progress(inner, stage, detail)。inner 0–100 由 build_hsi 映到总进度的后半段。"""
    if not pins:
        raise ValueError(f"手册中没有读到 {package} 的引脚表。")

    def tick(inner: float, stage: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(inner, stage, detail)

    tick(2, "check", "")
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

    def llm_tick(done: int, total: int) -> None:
        tick(8 + 74 * done / max(total, 1), "check", f"{done}/{total}")

    llm_by_sym, model_used = run_llm_pin_qa(
        llm_candidates,
        ask,
        on_progress=llm_tick if ask is not None and llm_candidates else None,
    )
    allocation = allocation_notes(template_book, pins)
    tick(88, "write", "")

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
            extra_conflicts=allocation.get(pin.symbol),
        )
        if STATUS_CONFLICT in status:
            conflict_count += 1
        row = _pin_row(pin, project)
        distinct = _distinct_rows(matches)
        if len(distinct) == 1 and distinct[0].kept:
            source = distinct[0]
            row = replace(row, kept=source.kept, direction=source.direction, function=source.function)
        drafts.append((row, status, note))
        current_rows[pin.symbol] = row
    changes = _diff(previous_rows, current_rows) if previous_rows else []
    version = _next_version(mcu, package, previous_version)
    today = date.today().strftime("%Y%m%d")
    if previous_rows:
        summary = f"相对上一版 {len(changes)} 处端口差异"
    else:
        summary = "首次按手册生成端口表"
    remark = _COVER_REMARK
    cover = _cover_sheet(template_book)
    history = _history_sheet(template_book)
    port = _port_sheet(template_book)
    if cover is None or history is None or port is None:
        raise ValueError("HSI 模板缺少封面、变更记录或端口表。")
    _write_cover(cover, today, summary, version, remark)
    _write_history(history, today, changes)
    _write_ports(port, mcu, package, drafts, pins, human)
    _write_evidence(template_book, pins)
    _write_constraints(
        template_book, pins, grouped, shared, sub_map=sub_map, llm_by_sym=llm_by_sym, allocation=allocation,
    )
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
        [list(_ACCEPT_HEADERS)],
    )
    _drop_unused_template_sheets(template_book)
    _sync_cover_toc(cover, template_book.sheetnames)
    _link_home(template_book)
    schematic_updates = _apply_schematic(template_book, schematic)
    _link_detail_sheets(template_book)
    _hide_adc_spare_columns(template_book)
    template_book.active = port
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tick(97, "write", "")
    template_book.save(dest)
    template_book.close()
    apply_dead_time_sheet(dest)
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
        schematic_updates=schematic_updates,
    )


def revise_hsi_from_schematic(
    base: Path,
    dest: Path,
    schematic: Path,
    *,
    on_progress=None,
) -> HsiResult:
    """按功率板网表自己的接插件脚重写端口数据。不按 MCU 的 P02.1、AN0 去对模板。"""
    if schematic.suffix.lower() != ".edf":
        raise ValueError("按原理图修改请用 EDIF（.edf）网表。")
    if on_progress is not None:
        on_progress(15, "read", schematic.name)
    pins = read_board_pins(schematic)
    if not pins:
        raise ValueError("这份网表里没有接插件脚，未修改端口表。")
    book = load_workbook(base)
    saved = False
    try:
        updated = _write_board_pins(book, pins)
        if updated == 0:
            raise ValueError("这份网表里没有接插件脚，未修改端口表。")
        port = _port_sheet(book)
        mcu = ""
        pins = updated
        if port is not None:
            raw = _text(port.cell(2, 2).value)
            if raw.upper().startswith("MCU_"):
                mcu = raw.split("_", 1)[1]
        if on_progress is not None:
            on_progress(80, "write", str(updated))
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        book.save(dest)
        saved = True
    finally:
        book.close()
    if saved:
        apply_dead_time_sheet(dest)
    today = date.today().strftime("%Y%m%d")
    return HsiResult(
        dest,
        mcu or "HSI",
        "",
        "",
        pins,
        0,
        today,
        schematic_updates=updated,
    )


def build_hsi(
    template: Path,
    datasheet: Path,
    dest: Path,
    *,
    package: str = "",
    previous: Path | None = None,
    ask: Ask | None = None,
    on_progress=None,
    schematic: Path | None = None,
    mcu: str = "",
) -> HsiResult:
    """on_progress(percent, stage, detail)。读手册约到 40%，抽引脚到 48%，核对和写入从 50% 走到 99%。"""

    def report(percent: float, stage: str, detail: str = "") -> None:
        if on_progress is None:
            return
        on_progress(max(0, min(99, int(percent))), stage, detail)

    def page_tick(done: int, total: int) -> None:
        report(2 + 38 * done / max(total, 1), "read", f"{done}/{total}")

    report(1, "read", "")
    pages = read_pdf_pages(datasheet, on_progress=page_tick)
    report(42, "pins", "")
    detected = mcu_name(datasheet.name, pages)
    mcu = mcu.strip() or detected
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
    report(48, "pins", str(len(pins)) if pins else "")

    def write_progress(inner: float, stage: str, detail: str = "") -> None:
        report(50 + float(inner) * 0.49, stage, detail)

    return write_hsi_workbook(
        template,
        dest,
        mcu=mcu,
        package=chosen,
        pins=pins,
        previous=previous,
        ask=ask,
        on_progress=write_progress,
        schematic=schematic,
    )
