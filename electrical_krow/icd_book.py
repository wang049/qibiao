"""从当份接插件 ICD 工作簿抽出引脚和接插件信息。

只抄当份表上已经写明的格子。空脚、没写信号、型号写着暂不，都标成待确认，不另补。
有上一版时，按连接器表和引脚号对照，列出新增、删除和变更。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

_PIN = re.compile(r"^PIN\d+[A-Z]?$", re.I)
_PENDING_MODEL = "暂不"


@dataclass(frozen=True)
class IcdPin:
    sheet: str
    pin: str
    signal: str
    name: str
    kind: str
    current: str
    note: str
    device_maker: str
    device_model: str
    device_part: str
    harness_maker: str
    harness_model: str
    harness_part: str
    vehicles: str
    module: str
    status: str


@dataclass(frozen=True)
class IcdPart:
    sheet: str
    side: str
    maker: str
    model: str
    part_no: str
    plating: str
    status: str


@dataclass(frozen=True)
class IcdHv:
    sheet: str
    connector: str
    purpose: str
    current: str
    model: str
    part_no: str
    pin_count: str
    pin_def: str
    vendor: str
    note: str


@dataclass(frozen=True)
class IcdChange:
    where: str
    key: str
    kind: str
    field: str
    previous: str
    current: str


@dataclass(frozen=True)
class IcdBook:
    pins: tuple[IcdPin, ...]
    parts: tuple[IcdPart, ...]
    hv: tuple[IcdHv, ...]
    changelog: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class IcdResult:
    path: Path
    pins: int
    parts: int
    hv: int
    changes: int


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = str(value).replace("\xa0", " ").replace("\n", " / ").strip()
    return re.sub(r" +", " ", text)


def _rows(ws: Worksheet) -> list[list[str]]:
    width = ws.max_column or 1
    height = ws.max_row or 1
    merged: dict[tuple[int, int], object] = {}
    for area in ws.merged_cells.ranges:
        origin = ws.cell(area.min_row, area.min_col).value
        for row in range(area.min_row, area.max_row + 1):
            for col in range(area.min_col, area.max_col + 1):
                merged[(row, col)] = origin
    found: list[list[str]] = []
    for row in range(1, height + 1):
        values = []
        for col in range(1, width + 1):
            raw = merged[(row, col)] if (row, col) in merged else ws.cell(row, col).value
            values.append(_cell(raw))
        found.append(values)
    return found


def _pin_key(text: str) -> str:
    token = re.sub(r"\s+", "", text).upper()
    return token if _PIN.fullmatch(token) else ""


def _pin_status(signal: str) -> str:
    if not signal or signal in {"空", "空脚", "-", "—"}:
        return "待确认"
    return "待人工确认"


def _part_status(model: str) -> str:
    if not model or _PENDING_MODEL in model:
        return "待确认"
    return "待人工确认"


def _header_map(row: list[str]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for index, raw in enumerate(row):
        text = re.sub(r"\s+", "", raw)
        key = ""
        if text in {"引脚号", "引脚"}:
            key = "pin"
        elif text.startswith("信号定义"):
            key = "signal"
        elif text.startswith("信号名称"):
            key = "name"
        elif text.startswith("信号类型"):
            key = "kind"
        elif text in {"电流"} or text.startswith("电流要求"):
            key = "current"
        elif text.startswith("备注"):
            key = "note"
        elif text.startswith("覆盖车型"):
            key = "vehicles"
        elif text.startswith("功能模块"):
            key = "module"
        elif text == "连接器":
            key = "connector"
        elif text == "用途":
            key = "purpose"
        elif text == "型号":
            key = "model"
        elif text.startswith("供应商料号"):
            key = "part_no"
        elif text == "引脚数":
            key = "pin_count"
        elif text.startswith("引脚定义"):
            key = "pin_def"
        elif text == "供应商":
            key = "vendor"
        elif text == "厂家":
            key = "maker"
        elif text == "镀层":
            key = "plating"
        if key:
            found.setdefault(key, []).append(index)
    return found


def _pick(row: list[str], columns: dict[str, list[int]], key: str, nth: int = 0) -> str:
    indexes = columns.get(key) or []
    if nth >= len(indexes) or indexes[nth] >= len(row):
        return ""
    return row[indexes[nth]]


def _notes(row: list[str], columns: dict[str, list[int]]) -> str:
    parts = []
    for index in columns.get("note") or []:
        if index < len(row) and row[index]:
            parts.append(row[index])
    return "；".join(parts)


def _connector_groups(rows: list[list[str]], header_at: int) -> list[tuple[str, str, str, str, str]]:
    """厂家所在行的下一行非空值，按同一行里出现的顺序分成电器端、线束端。"""
    groups: list[tuple[str, str, str, str, str]] = []
    for offset, row in enumerate(rows):
        columns = _header_map(row)
        makers = columns.get("maker") or []
        if len(makers) < 1:
            continue
        if offset + 1 >= len(rows):
            break
        values = rows[offset + 1]
        labels = rows[offset - 1] if offset else []
        for nth, maker_at in enumerate(makers):
            maker = values[maker_at] if maker_at < len(values) else ""
            if not maker or maker == "厂家":
                continue
            model_at = (columns.get("model") or [maker_at + 1])[nth] if nth < len(columns.get("model") or []) else maker_at + 1
            part_at = (columns.get("part_no") or [maker_at + 2])[nth] if nth < len(columns.get("part_no") or []) else maker_at + 2
            plate_at = (columns.get("plating") or [maker_at + 3])[nth] if nth < len(columns.get("plating") or []) else maker_at + 3
            side = labels[maker_at] if maker_at < len(labels) and labels[maker_at] else ("电器端" if nth == 0 else "线束端")
            model = values[model_at] if model_at < len(values) else ""
            part_no = values[part_at] if part_at < len(values) else ""
            plating = values[plate_at] if plate_at < len(values) else ""
            groups.append((side, maker, model, part_no, plating))
        if groups:
            break
    if header_at < 0 and not groups:
        return []
    return groups


def _read_sheet(name: str, rows: list[list[str]]) -> tuple[list[IcdPin], list[IcdPart], list[IcdHv]]:
    pins: list[IcdPin] = []
    parts: list[IcdPart] = []
    hv: list[IcdHv] = []
    pin_header = -1
    hv_header = -1
    pin_columns: dict[str, list[int]] = {}
    hv_columns: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        columns = _header_map(row)
        if "pin" in columns and "signal" in columns and pin_header < 0:
            pin_header = index
            pin_columns = columns
        if "connector" in columns and "pin_def" in columns and "pin" not in columns and hv_header < 0:
            hv_header = index
            hv_columns = columns
    groups = _connector_groups(rows, pin_header)
    device = groups[0] if groups else ("", "", "", "", "")
    harness = groups[1] if len(groups) > 1 else ("", "", "", "", "")
    for side, maker, model, part_no, plating in groups:
        parts.append(IcdPart(name, side, maker, model, part_no, plating, _part_status(model)))
    if pin_header >= 0:
        for row in rows[pin_header + 1:]:
            pin = _pick(row, pin_columns, "pin")
            if not _pin_key(pin):
                continue
            signal = _pick(row, pin_columns, "signal")
            pins.append(IcdPin(
                name,
                pin.strip(),
                signal,
                _pick(row, pin_columns, "name"),
                _pick(row, pin_columns, "kind"),
                _pick(row, pin_columns, "current"),
                _notes(row, pin_columns),
                device[1],
                device[2],
                device[3],
                harness[1],
                harness[2],
                harness[3],
                _pick(row, pin_columns, "vehicles"),
                _pick(row, pin_columns, "module"),
                _pin_status(signal),
            ))
    if hv_header >= 0:
        for row in rows[hv_header + 1:]:
            connector = _pick(row, hv_columns, "connector")
            if not connector or connector == "连接器":
                continue
            hv.append(IcdHv(
                name,
                connector,
                _pick(row, hv_columns, "purpose"),
                _pick(row, hv_columns, "current"),
                _pick(row, hv_columns, "model"),
                _pick(row, hv_columns, "part_no"),
                _pick(row, hv_columns, "pin_count"),
                _pick(row, hv_columns, "pin_def"),
                _pick(row, hv_columns, "vendor"),
                _notes(row, hv_columns),
            ))
    return pins, parts, hv


def _read_changelog(name: str, rows: list[list[str]]) -> tuple[tuple[str, ...], ...]:
    if "变更" not in name:
        return ()
    start = -1
    width = 0
    for index, row in enumerate(rows):
        blob = "".join(row)
        if "版本号" in blob and "更改内容" in blob:
            start = index
            width = len(row)
            break
    if start < 0:
        return ()
    found: list[tuple[str, ...]] = []
    for row in rows[start:]:
        if not any(row):
            if found:
                break
            continue
        found.append(tuple(row[:width]))
    return tuple(found)


def read_icd(path: Path) -> IcdBook:
    book = load_workbook(path, data_only=False)
    pins: list[IcdPin] = []
    parts: list[IcdPart] = []
    hv: list[IcdHv] = []
    changelog: tuple[tuple[str, ...], ...] = ()
    try:
        for name in book.sheetnames:
            rows = _rows(book[name])
            sheet_pins, sheet_parts, sheet_hv = _read_sheet(name, rows)
            pins.extend(sheet_pins)
            parts.extend(sheet_parts)
            hv.extend(sheet_hv)
            if not changelog:
                changelog = _read_changelog(name, rows)
    finally:
        book.close()
    if not pins and not parts and not hv:
        raise ValueError("这份 ICD 里没有读到引脚表、高压接口或接插件信息。")
    return IcdBook(tuple(pins), tuple(parts), tuple(hv), changelog)


def _pin_id(pin: IcdPin) -> tuple[str, str]:
    return pin.sheet, _pin_key(pin.pin)


def _diff_pins(previous: IcdBook, current: IcdBook) -> list[IcdChange]:
    fields = (
        ("信号定义", "signal"),
        ("信号名称", "name"),
        ("信号类型", "kind"),
        ("电流", "current"),
        ("备注", "note"),
        ("覆盖车型", "vehicles"),
        ("功能模块", "module"),
    )
    old = {_pin_id(pin): pin for pin in previous.pins}
    new = {_pin_id(pin): pin for pin in current.pins}
    changes: list[IcdChange] = []
    for key in sorted(set(old) | set(new)):
        before = old.get(key)
        after = new.get(key)
        where, pin = key
        label = before.pin if before else after.pin  # type: ignore[union-attr]
        if before is None and after is not None:
            changes.append(IcdChange(where, label, "新增", "引脚", "", after.signal))
            continue
        if after is None and before is not None:
            changes.append(IcdChange(where, label, "删除", "引脚", before.signal, ""))
            continue
        assert before is not None and after is not None
        for title, attr in fields:
            left = getattr(before, attr)
            right = getattr(after, attr)
            if left != right:
                changes.append(IcdChange(where, label, "变更", title, left, right))
    return changes


def _diff_named(previous: dict[tuple[str, str], object], current: dict[tuple[str, str], object], fields: tuple[tuple[str, str], ...]) -> list[IcdChange]:
    changes: list[IcdChange] = []
    for key in sorted(set(previous) | set(current)):
        before = previous.get(key)
        after = current.get(key)
        where, label = key
        if before is None and after is not None:
            changes.append(IcdChange(where, label, "新增", "条目", "", getattr(after, fields[0][1])))
            continue
        if after is None and before is not None:
            changes.append(IcdChange(where, label, "删除", "条目", getattr(before, fields[0][1]), ""))
            continue
        assert before is not None and after is not None
        for title, attr in fields:
            left = getattr(before, attr)
            right = getattr(after, attr)
            if left != right:
                changes.append(IcdChange(where, label, "变更", title, left, right))
    return changes


def _style_header(ws: Worksheet, width: int) -> None:
    fill = PatternFill("solid", fgColor="1E3A5F")
    font = Font(name="宋体", bold=True, color="FFFFFF", size=11)
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.auto_filter.ref = f"A1:{get_column_letter(width)}1"
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22


def _write_rows(ws: Worksheet, header: tuple[str, ...], rows: list[tuple[str, ...]], widths: tuple[int, ...]) -> None:
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    _style_header(ws, len(header))
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=2, max_col=len(header)):
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            cell.font = Font(name="宋体", size=10)


def write_icd_review(current: IcdBook, dest: Path, previous: IcdBook | None = None) -> None:
    book = Workbook()
    pin_sheet = book.active
    pin_sheet.title = "引脚清单"
    _write_rows(
        pin_sheet,
        ("连接器表", "引脚号", "信号定义", "信号名称", "信号类型", "电流", "备注", "覆盖车型", "功能模块", "电器端厂家", "电器端型号", "电器端料号", "线束端厂家", "线束端型号", "线束端料号", "核对状态"),
        [
            (pin.sheet, pin.pin, pin.signal, pin.name, pin.kind, pin.current, pin.note, pin.vehicles, pin.module,
             pin.device_maker, pin.device_model, pin.device_part,
             pin.harness_maker, pin.harness_model, pin.harness_part, pin.status)
            for pin in current.pins
        ],
        (22, 12, 28, 22, 14, 12, 28, 16, 14, 14, 18, 24, 14, 18, 24, 14),
    )
    if current.hv:
        hv_sheet = book.create_sheet("高压接口")
        _write_rows(
            hv_sheet,
            ("连接器表", "连接器", "用途", "电流要求", "型号", "供应商料号", "引脚数", "引脚定义", "供应商", "备注"),
            [
                (item.sheet, item.connector, item.purpose, item.current, item.model, item.part_no, item.pin_count, item.pin_def, item.vendor, item.note)
                for item in current.hv
            ],
            (18, 14, 24, 28, 22, 24, 10, 36, 14, 24),
        )
    if current.parts:
        part_sheet = book.create_sheet("接插件")
        _write_rows(
            part_sheet,
            ("连接器表", "端", "厂家", "型号", "供应商料号", "镀层", "核对状态"),
            [(item.sheet, item.side, item.maker, item.model, item.part_no, item.plating, item.status) for item in current.parts],
            (22, 14, 14, 20, 28, 18, 14),
        )
    if previous is not None:
        diff_sheet = book.create_sheet("版本差异")
        changes = _all_changes(previous, current)
        _write_rows(
            diff_sheet,
            ("连接器表", "对象", "差异", "字段", "上一版", "当版"),
            [(item.where, item.key, item.kind, item.field, item.previous, item.current) for item in changes],
            (22, 16, 10, 14, 28, 28),
        )
    if current.changelog:
        log = book.create_sheet("变更记录")
        width = max(len(row) for row in current.changelog)
        _write_rows(
            log,
            tuple(current.changelog[0]) + ("",) * (width - len(current.changelog[0])),
            [tuple(row) + ("",) * (width - len(row)) for row in current.changelog[1:]],
            tuple(18 for _ in range(width)),
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    book.save(dest)
    book.close()


def _all_changes(previous: IcdBook, current: IcdBook) -> list[IcdChange]:
    changes = _diff_pins(previous, current)
    changes.extend(_diff_named(
        {(item.sheet, item.side): item for item in previous.parts},
        {(item.sheet, item.side): item for item in current.parts},
        (("厂家", "maker"), ("型号", "model"), ("供应商料号", "part_no"), ("镀层", "plating")),
    ))
    changes.extend(_diff_named(
        {(item.sheet, item.connector): item for item in previous.hv},
        {(item.sheet, item.connector): item for item in current.hv},
        (("用途", "purpose"), ("电流要求", "current"), ("型号", "model"), ("供应商料号", "part_no"), ("引脚数", "pin_count"), ("引脚定义", "pin_def"), ("供应商", "vendor"), ("备注", "note")),
    ))
    return changes


def build_icd(current: Path, dest: Path, previous: Path | None = None) -> IcdResult:
    current_book = read_icd(current)
    previous_book = read_icd(previous) if previous is not None else None
    write_icd_review(current_book, dest, previous_book)
    changes = len(_all_changes(previous_book, current_book)) if previous_book is not None else 0
    return IcdResult(dest, len(current_book.pins), len(current_book.parts), len(current_book.hv), changes)


def icd_file_name(day: date | None = None, now: datetime | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y%m%d")
    clock = (now or datetime.now()).strftime("%H%M%S")
    return f"ICD引脚清单-{stamp}-{clock}.xlsx"
