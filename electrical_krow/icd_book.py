"""从当份接插件 ICD 工作簿抽出引脚和接插件信息。

只抄当份表上已经写明的格子。空脚、没写信号、型号写着暂不，都标成待确认，不另补。
有上一版时，按连接器表和引脚号对照，列出新增、删除和变更。
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from electrical_krow.hsi_book import hsi_keyword_hits

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
    row: int = 0
    signal_col: int = 0


@dataclass(frozen=True)
class IcdPart:
    sheet: str
    side: str
    maker: str
    model: str
    part_no: str
    plating: str
    status: str
    row: int = 0


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
    row: int = 0


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
    source_name: str = ""
    version: str = ""


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
    """引脚号统一成 PIN30。表上只写 30 时也认。"""
    token = re.sub(r"[\s_]+", "", text).upper()
    if _PIN.fullmatch(token):
        return token
    matched = re.fullmatch(r"(\d+)", token)
    if matched:
        return f"PIN{int(matched.group(1))}"
    return ""


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
        folded = text.upper()
        if text in {"引脚号", "引脚"} or folded in {"PIN", "PINNO", "PINNO.", "PIN号"}:
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


def _connector_groups(rows: list[list[str]], header_at: int) -> list[tuple[str, str, str, str, str, int]]:
    """厂家所在行的下一行非空值，按同一行里出现的顺序分成电器端、线束端。"""
    groups: list[tuple[str, str, str, str, str, int]] = []
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
            groups.append((side, maker, model, part_no, plating, offset + 2))
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
    for side, maker, model, part_no, plating, excel_row in groups:
        parts.append(IcdPart(name, side, maker, model, part_no, plating, _part_status(model), excel_row))
    if pin_header >= 0:
        signal_at = (pin_columns.get("signal") or [0])[0] + 1
        for offset, row in enumerate(rows[pin_header + 1:], start=pin_header + 2):
            pin = _pick(row, pin_columns, "pin")
            signal = _pick(row, pin_columns, "signal")
            if not _pin_key(pin):
                if not _signal_key(signal):
                    continue
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
                offset,
                signal_at,
            ))
    if hv_header >= 0:
        for index, row in enumerate(rows[hv_header + 1:], start=hv_header + 2):
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
                index,
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
    return IcdBook(
        tuple(pins),
        tuple(parts),
        tuple(hv),
        changelog,
        path.name,
        _latest_version(changelog),
    )


def _connector_name(sheet: str) -> str:
    """表名去掉序号。`4-整车低压连接器` 和 `整车低压连接器` 视为同一个连接器。"""
    text = re.sub(r"\s+", "", sheet or "")
    text = re.sub(r"^(?:table|sheet)?[-_.]*\d+[-_.]*", "", text, flags=re.I)
    text = re.sub(r"(连接器|接口定义|接口)$", "", text)
    return text.casefold()


def _signal_key(text: str) -> str:
    """信号定义去掉空格和下划线后再比。没有字母或汉字的不算信号。"""
    compact = re.sub(r"[\s_]+", "", text or "")
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", compact):
        return ""
    if compact in {"信号定义", "信号名称"}:
        return ""
    return compact.upper()


def _pin_match_key(pin: IcdPin) -> tuple[str, str]:
    name = _connector_name(pin.sheet)
    token = _pin_key(pin.pin)
    if name:
        return name, token
    return pin.sheet, token


def _latest_version(changelog: tuple[tuple[str, ...], ...]) -> str:
    found = ""
    for row in changelog[1:]:
        for cell in row:
            matched = re.search(r"\bV\d+(?:\.\d+)*\b", cell or "", re.I)
            if matched:
                found = matched.group(0).upper()
    return found


def _pair_pins(previous: tuple[IcdPin, ...], current: tuple[IcdPin, ...]) -> list[tuple[IcdPin | None, IcdPin | None]]:
    """先按同名表配对，表名不同再按连接器名和引脚号配对。"""
    old_exact = {(pin.sheet, _pin_key(pin.pin)): pin for pin in previous}
    old_loose: dict[tuple[str, str], IcdPin] = {}
    for pin in previous:
        old_loose.setdefault(_pin_match_key(pin), pin)
    used: set[int] = set()
    pairs: list[tuple[IcdPin | None, IcdPin | None]] = []
    for pin in current:
        before = old_exact.get((pin.sheet, _pin_key(pin.pin)))
        if before is None or id(before) in used:
            before = old_loose.get(_pin_match_key(pin))
        if before is not None and id(before) in used:
            before = None
        if before is not None:
            used.add(id(before))
        pairs.append((before, pin))
    pending = [pin for pin in previous if id(pin) not in used and not _pin_key(pin.pin) and _signal_key(pin.signal)]
    by_signal: dict[tuple[str, str], list[IcdPin]] = {}
    for pin in pending:
        by_signal.setdefault((_connector_name(pin.sheet), _signal_key(pin.signal)), []).append(pin)
    repaired: list[tuple[IcdPin | None, IcdPin | None]] = []
    for before, after in pairs:
        if after is None or before is not None or not _signal_key(after.signal):
            repaired.append((before, after))
            continue
        bucket = by_signal.get((_connector_name(after.sheet), _signal_key(after.signal))) or []
        taken = next((item for item in bucket if id(item) not in used), None)
        if taken is None:
            repaired.append((before, after))
            continue
        used.add(id(taken))
        repaired.append((taken, after))
    pairs = repaired
    for pin in previous:
        if id(pin) not in used:
            pairs.append((pin, None))
    return pairs


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
    changes: list[IcdChange] = []
    for before, after in _pair_pins(previous.pins, current.pins):
        shown = after or before
        assert shown is not None
        where = after.sheet if after is not None else before.sheet  # type: ignore[union-attr]
        label = shown.pin
        if before is None and after is not None:
            changes.append(IcdChange(where, label, "新增", "引脚", "", after.signal))
            continue
        if after is None and before is not None:
            changes.append(IcdChange(where, label, "删除", "引脚", before.signal, ""))
            continue
        assert before is not None and after is not None
        if _pin_key(before.pin) != _pin_key(after.pin):
            changes.append(IcdChange(
                where,
                label,
                "变更",
                "引脚号",
                before.pin or "无引脚号",
                f"{after.pin}（{after.signal}）" if after.signal else after.pin,
            ))
        for title, attr in fields:
            left = getattr(before, attr)
            right = getattr(after, attr)
            if attr == "signal" and _signal_key(left) == _signal_key(right):
                continue
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


_DIFF_FILL = {
    "新增": PatternFill("solid", fgColor="C6EFCE"),
    "删除": PatternFill("solid", fgColor="FFC7CE"),
    "变更": PatternFill("solid", fgColor="FFE699"),
}


def _display_units(value: object) -> int:
    text = str(value or "")
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _wrapped_lines(value: object, width: float) -> int:
    """按列宽估算换行后的行数。只数换行符会把长句裁在格子里。"""
    usable = max(int(width) - 2, 4)
    lines = 0
    for paragraph in str(value or "").split("\n"):
        units = _display_units(paragraph)
        lines += 1 if units == 0 else (units + usable - 1) // usable
    return max(lines, 1)


def _row_height(lines: int) -> float:
    return float(min(409, 18 * max(lines, 1) + 10))


def _fit_columns(ws: Worksheet) -> None:
    """列宽按中文显示宽度撑开，最长不超过 48。"""
    for col in range(1, (ws.max_column or 1) + 1):
        longest = 0
        for row in range(1, (ws.max_row or 1) + 1):
            longest = max(longest, _display_units(ws.cell(row, col).value))
        ws.column_dimensions[get_column_letter(col)].width = min(48, max(10, longest + 2))


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
    _fit_columns(ws)


def _icd_status(pin: IcdPin) -> str:
    hits = hsi_keyword_hits(f"{pin.signal} {pin.name} {pin.note}")
    if not hits:
        return pin.status
    return f"{pin.status}；须进入HSI：{'、'.join(hits)}"


def _pin_match(pin: IcdPin) -> str:
    if pin.status == "待确认":
        return "信号空着"
    return "引脚和信号都有"


def _set_widths(sheet: Worksheet, widths: tuple[int, ...]) -> None:
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _write_banner(sheet: Worksheet, previous: IcdBook, current: IcdBook, columns: int) -> None:
    """文件名单独占一整行，避免把后面表格的某一列撑得很宽。"""
    previous_version = previous.version or "未写版本号"
    current_version = current.version or "未写版本号"
    sheet.cell(1, 1, f"上一版：{previous.source_name}　　版本 {previous_version}")
    sheet.cell(2, 1, f"当版：{current.source_name}　　版本 {current_version}")
    if columns > 1:
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    for row in (1, 2):
        cell = sheet.cell(row, 1)
        cell.font = Font(name="宋体", size=11)
        cell.alignment = Alignment(vertical="center", wrap_text=True, horizontal="left")
        sheet.row_dimensions[row].height = 22


def _sheet_for_change(book: Workbook, where: str) -> str:
    if where in book.sheetnames:
        return where
    name = _connector_name(where)
    if not name:
        return ""
    for title in book.sheetnames:
        if _connector_name(title) == name:
            return title
    return ""


def _sheet_text(value: str) -> str:
    text = (value or "（空）").replace(" / ", "\n")
    return text


def _paint_row(sheet: Worksheet, row: int, kind: str) -> None:
    fill = _DIFF_FILL.get(kind)
    if fill is None or row <= 0:
        return
    from openpyxl.cell.cell import MergedCell

    width = min(sheet.max_column or 1, 24)
    for col in range(1, width + 1):
        cell = sheet.cell(row, col)
        if isinstance(cell, MergedCell):
            continue
        cell.fill = fill


def _mark_source_sheets(book: Workbook, current: IcdBook, changes: list[IcdChange]) -> dict[str, dict[str, int]]:
    """在当版原表上涂改过的行，并在表下写小结。不改原表已有列宽。"""
    grouped: dict[str, list[IcdChange]] = {}
    for change in changes:
        title = _sheet_for_change(book, change.where)
        if title:
            grouped.setdefault(title, []).append(change)
    pin_row = {(pin.sheet, _pin_key(pin.pin)): pin.row for pin in current.pins if pin.row}
    part_row = {(part.sheet, part.side): part.row for part in current.parts if part.row}
    hv_row = {(item.sheet, item.connector): item.row for item in current.hv if item.row}
    totals: dict[str, dict[str, int]] = {}
    for title, items in grouped.items():
        sheet = book[title]
        counts = {"新增": 0, "修改": 0, "删除": 0}
        painted: set[tuple[str, str]] = set()
        for change in items:
            label = "修改" if change.kind == "变更" else change.kind
            if label not in counts:
                continue
            token = _pin_key(change.key) or change.key
            mark = (label, token)
            if mark not in painted:
                counts[label] += 1
                painted.add(mark)
            if change.kind == "删除":
                continue
            row = pin_row.get((title, _pin_key(change.key))) or pin_row.get((change.where, _pin_key(change.key)))
            if not row:
                row = part_row.get((title, change.key)) or hv_row.get((title, change.key))
            if row:
                _paint_row(sheet, row, change.kind)
        start = (sheet.max_row or 1) + 2
        stale = [str(merged) for merged in sheet.merged_cells.ranges if merged.max_row >= start]
        for ref in stale:
            sheet.unmerge_cells(ref)
        _write_sheet_table(sheet, start, counts, items)
        totals[title] = counts
    return totals


def _col_width(sheet: Worksheet, col: int) -> float:
    width = sheet.column_dimensions[get_column_letter(col)].width
    return float(width if width else 8.43)


_GRID = Border(
    left=Side(style="thin", color="8A8A8A"),
    right=Side(style="thin", color="8A8A8A"),
    top=Side(style="thin", color="8A8A8A"),
    bottom=Side(style="thin", color="8A8A8A"),
)


def _write_summary_cell(
    sheet: Worksheet,
    row: int,
    col: int,
    value: object,
    *,
    font: Font,
    fill: PatternFill | None = None,
) -> None:
    cell = sheet.cell(row, col, value)
    cell.font = font
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    cell.border = _GRID
    if fill is not None:
        cell.fill = fill


def _write_sheet_table(sheet: Worksheet, start: int, counts: dict[str, int], items: list[IcdChange]) -> None:
    """写在原表最下方、从 A 列起。不改原表列宽，文字靠左。"""
    columns = (1, 2, 3, 4, 5)
    title = f"本表小结　新增 {counts['新增']}　修改 {counts['修改']}　删除 {counts['删除']}"
    _write_summary_cell(
        sheet,
        start,
        1,
        title,
        font=Font(name="宋体", bold=True, size=12),
        fill=PatternFill("solid", fgColor="F2F2F2"),
    )
    sheet.merge_cells(start_row=start, start_column=1, end_row=start, end_column=5)
    title_width = sum(_col_width(sheet, col) for col in columns)
    sheet.row_dimensions[start].height = _row_height(_wrapped_lines(title, title_width))
    header_row = start + 1
    header_font = Font(name="宋体", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    for col, name in zip(columns, ("差异", "对象", "字段", "上一版", "当版"), strict=True):
        _write_summary_cell(sheet, header_row, col, name, font=header_font, fill=header_fill)
    sheet.row_dimensions[header_row].height = 22
    body_font = Font(name="宋体", size=11)
    for index, change in enumerate(items, start=1):
        row = header_row + index
        shown = "修改" if change.kind == "变更" else change.kind
        values = (
            shown,
            change.key or "无引脚号",
            change.field,
            _sheet_text(change.previous),
            _sheet_text(change.current),
        )
        lines = 1
        fill = _DIFF_FILL.get(change.kind)
        for col, value in zip(columns, values, strict=True):
            _write_summary_cell(sheet, row, col, value, font=body_font, fill=fill)
            lines = max(lines, _wrapped_lines(value, _col_width(sheet, col)))
        sheet.row_dimensions[row].height = _row_height(lines)


def _write_overall_summary(
    book: Workbook,
    previous: IcdBook,
    current: IcdBook,
    totals: dict[str, dict[str, int]],
    changes: list[IcdChange],
) -> None:
    if "差异总结" in book.sheetnames:
        del book["差异总结"]
    sheet = book.create_sheet("差异总结", 0)
    columns = 6
    summary_widths = (22, 14, 14, 14, 36, 36)
    _set_widths(sheet, summary_widths)
    _write_banner(sheet, previous, current, columns)
    count_header = 4
    for col, name in enumerate(("表", "新增", "修改", "删除"), start=1):
        cell = sheet.cell(count_header, col, name)
        cell.fill = PatternFill("solid", fgColor="1E3A5F")
        cell.font = Font(name="宋体", bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    add = change = remove = 0
    for offset, (title, counts) in enumerate(totals.items(), start=1):
        row = count_header + offset
        sheet.cell(row, 1, title)
        sheet.cell(row, 2, counts["新增"])
        sheet.cell(row, 3, counts["修改"])
        sheet.cell(row, 4, counts["删除"])
        add += counts["新增"]
        change += counts["修改"]
        remove += counts["删除"]
        for col in range(2, 5):
            sheet.cell(row, col).alignment = Alignment(horizontal="center", vertical="center")
            sheet.cell(row, col).font = Font(name="宋体", size=11)
        sheet.cell(row, 1).font = Font(name="宋体", size=11)
    total_row = count_header + len(totals) + 1
    sheet.cell(total_row, 1, "合计")
    sheet.cell(total_row, 2, add)
    sheet.cell(total_row, 3, change)
    sheet.cell(total_row, 4, remove)
    for col in range(1, 5):
        sheet.cell(total_row, col).font = Font(name="宋体", bold=True, size=11)
        if col > 1:
            sheet.cell(total_row, col).alignment = Alignment(horizontal="center")
    detail_header = total_row + 2
    for col, name in enumerate(("表", "对象", "差异", "字段", "上一版", "当版"), start=1):
        cell = sheet.cell(detail_header, col, name)
        cell.fill = PatternFill("solid", fgColor="1E3A5F")
        cell.font = Font(name="宋体", bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for index, item in enumerate(changes, start=1):
        row = detail_header + index
        title = _sheet_for_change(book, item.where) or item.where
        shown = "修改" if item.kind == "变更" else item.kind
        values = (title, item.key, shown, item.field, _sheet_text(item.previous), _sheet_text(item.current))
        lines = 1
        fill = _DIFF_FILL.get(item.kind)
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row, col, value)
            cell.font = Font(name="宋体", size=10)
            cell.alignment = Alignment(vertical="center", wrap_text=True, horizontal="center")
            if fill is not None:
                cell.fill = fill
            lines = max(lines, _wrapped_lines(value, summary_widths[col - 1]))
        sheet.row_dimensions[row].height = _row_height(lines)


def write_icd_review(book: Workbook, current: IcdBook, previous: IcdBook | None = None) -> None:
    """原表保持版式。有上一版时涂改过的行，表下写小结，并加差异总结。"""
    if previous is not None:
        changes = _all_changes(previous, current)
        totals = _mark_source_sheets(book, current, changes)
        _write_overall_summary(book, previous, current, totals, changes)
    for name in list(book.sheetnames):
        if "封面" in name or "变更记录" in name or name == "版本差异":
            del book[name]
    if previous is not None and "差异总结" in book.sheetnames:
        book.active = book["差异总结"]


def _loose(text: str) -> str:
    return re.sub(r"[\s_]+", "", text or "")


def _prose(text: str) -> bool:
    """带句读的说明。脚名、料号、引脚定义不算。"""
    return bool(re.search(r"[，。；;、]", text or ""))


def _is_pin_signal(text: str) -> bool:
    raw = (text or "").strip()
    if raw in {"", "空", "空脚", "-", "—", "（空）", "无"}:
        return False
    if _prose(raw):
        return False
    return bool(_signal_key(raw))


def _pinless_noise(change: IcdChange) -> bool:
    """没有引脚号、内容也不是脚信号的删除。说明行和空行不单列。"""
    if change.kind != "删除" or _pin_key(change.key):
        return False
    if change.field == "条目" and change.key.strip() and not _prose(change.key):
        return False
    return not _is_pin_signal(change.previous)


def _note_token(change: IcdChange) -> tuple[str, str, str, str, str] | None:
    if change.field != "备注" and not (_prose(change.previous) or _prose(change.current)):
        return None
    return (change.where, change.kind, change.field, _loose(change.previous), _loose(change.current))


def _present_changes(changes: list[IcdChange]) -> list[IcdChange]:
    """同一句说明只留一行。空脚号的删除若不带脚信号，不列出。"""
    pending: list[IcdChange] = []
    for change in changes:
        if change.kind == "变更" and change.field == "备注" and _loose(change.previous) == _loose(change.current):
            continue
        if _pinless_noise(change):
            continue
        pending.append(change)
    counts: dict[tuple[str, str, str, str, str], int] = {}
    tokens: list[tuple[str, str, str, str, str] | None] = []
    for change in pending:
        token = _note_token(change)
        tokens.append(token)
        if token is not None:
            counts[token] = counts.get(token, 0) + 1
    seen: set[tuple[str, str, str, str, str]] = set()
    shown: list[IcdChange] = []
    for change, token in zip(pending, tokens, strict=True):
        if token is not None and counts[token] > 1:
            if token in seen:
                continue
            seen.add(token)
            label = "本表备注" if change.field == "备注" else "本表说明"
            shown.append(IcdChange(change.where, label, change.kind, change.field, change.previous, change.current))
            continue
        shown.append(change)
    return shown


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
    return _present_changes(changes)


def build_icd(current: Path, dest: Path, previous: Path | None = None) -> IcdResult:
    current_book = read_icd(current)
    previous_book = read_icd(previous) if previous is not None else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(current, dest)
    book = load_workbook(dest)
    try:
        write_icd_review(book, current_book, previous_book)
        book.save(dest)
    finally:
        book.close()
    changes = len(_all_changes(previous_book, current_book)) if previous_book is not None else 0
    return IcdResult(dest, len(current_book.pins), len(current_book.parts), len(current_book.hv), changes)


def icd_file_name(day: date | None = None, now: datetime | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y%m%d")
    clock = (now or datetime.now()).strftime("%H%M%S")
    return f"ICD引脚清单-{stamp}-{clock}.xlsx"
