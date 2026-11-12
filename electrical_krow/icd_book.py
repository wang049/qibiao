"""从当份接插件 ICD 工作簿抽出引脚和接插件信息。

只抄当份表上已经写明的格子。空脚、没写信号、型号写着暂不，都标成待确认，不另补。
有上一版时，按连接器表和引脚号对照，列出新增、删除和变更。差异总结写两版版本号、本次出表时间和关键变化，不把每只脚再列一遍。
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter
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
    pin_col: int = 0


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
    maker_col: int = 0
    model_col: int = 0
    part_col: int = 0
    plate_col: int = 0


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
            groups.append((
                side, maker, model, part_no, plating, offset + 2,
                maker_at + 1, model_at + 1, part_at + 1, plate_at + 1,
            ))
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
    for side, maker, model, part_no, plating, excel_row, maker_col, model_col, part_col, plate_col in groups:
        parts.append(IcdPart(
            name, side, maker, model, part_no, plating, _part_status(model), excel_row,
            maker_col, model_col, part_col, plate_col,
        ))
    if pin_header >= 0:
        signal_at = (pin_columns.get("signal") or [0])[0] + 1
        pin_at = (pin_columns.get("pin") or [0])[0] + 1
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
                pin_at,
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
    old_exact: dict[tuple[str, str], IcdPin] = {}
    old_loose: dict[tuple[str, str], IcdPin] = {}
    for pin in previous:
        token = _pin_key(pin.pin)
        if not token:
            continue
        old_exact[(pin.sheet, token)] = pin
        old_loose.setdefault(_pin_match_key(pin), pin)
    used: set[int] = set()
    pairs: list[tuple[IcdPin | None, IcdPin | None]] = []
    for pin in current:
        token = _pin_key(pin.pin)
        before = old_exact.get((pin.sheet, token)) if token else None
        if token and (before is None or id(before) in used):
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
        where = after.sheet if after is not None else before.sheet  # type: ignore[union-attr]
        if before is None and after is not None and _is_explanation(after):
            changes.append(IcdChange(where, "说明", "新增", "说明", "", _explanation_text(after)))
            continue
        if after is None and before is not None and _is_explanation(before):
            changes.append(IcdChange(where, "说明", "删除", "说明", _explanation_text(before), ""))
            continue
        label = (after or before).pin  # type: ignore[union-attr]
        if before is None and after is not None:
            changes.append(IcdChange(where, label, "新增", "引脚", "", after.signal))
            continue
        if after is None and before is not None:
            changes.append(IcdChange(where, label, "删除", "引脚", before.signal, ""))
            continue
        assert before is not None and after is not None
        if _is_explanation(before) or _is_explanation(after):
            left = _explanation_text(before)
            right = _explanation_text(after)
            if _loose(left) != _loose(right):
                changes.append(IcdChange(where, "说明", "变更", "说明", left, right))
            continue
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
    issued = datetime.now().strftime("%Y%m%d-%H%M%S")
    sheet.cell(1, 1, f"上一版：{previous.source_name}　　版本 {previous_version}")
    sheet.cell(2, 1, f"当版：{current.source_name}　　版本 {current_version}　　本次出表 {issued}")
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


def _paint_span(sheet: Worksheet, row: int, kind: str, start: int, end: int) -> None:
    """只涂这一段。接插件和引脚写在同一行时，不能把另一边一起涂上。"""
    fill = _DIFF_FILL.get(kind)
    if fill is None or row <= 0 or start <= 0:
        return
    from openpyxl.cell.cell import MergedCell

    end = min(max(end, start), 24)
    for col in range(start, end + 1):
        cell = sheet.cell(row, col)
        if isinstance(cell, MergedCell):
            continue
        cell.fill = fill


_PART_COL = {
    "厂家": "maker_col",
    "型号": "model_col",
    "供应商料号": "part_col",
    "镀层": "plate_col",
}
# 这两张引脚表很长，小结放在表下要翻到底。改到表头右侧。
_SIDE_SUMMARY = ("整车低压连接器", "变速器连接器")


def _summary_beside(title: str) -> bool:
    name = title.replace("—", "-").replace("–", "-")
    return any(label in name for label in _SIDE_SUMMARY)


def _mark_source_sheets(
    book: Workbook,
    current: IcdBook,
    changes: list[IcdChange],
    display: list[IcdChange] | None = None,
) -> dict[str, dict[str, int]]:
    """在当版原表上涂改过的行，并在表下写小结。不改原表已有列宽。"""
    grouped: dict[str, list[IcdChange]] = {}
    for change in changes:
        title = _sheet_for_change(book, change.where)
        if title:
            grouped.setdefault(title, []).append(change)
    pin_at = {
        (pin.sheet, _pin_key(pin.pin)): pin
        for pin in current.pins
        if pin.row and _pin_key(pin.pin)
    }
    part_at = {(part.sheet, part.side): part for part in current.parts if part.row}
    hv_at = {(item.sheet, item.connector): item for item in current.hv if item.row}
    totals: dict[str, dict[str, int]] = {}
    beside: dict[str, tuple[dict[str, int], list[IcdChange]]] = {}
    for title, items in grouped.items():
        sheet = book[title]
        counts = {"新增": 0, "修改": 0, "删除": 0}
        painted: set[tuple[str, str]] = set()
        for change in items:
            label = "修改" if change.kind == "变更" else change.kind
            if label not in counts:
                continue
            token = _pin_key(change.key) or change.key
            if _is_pinless_signal_delete(change):
                token = (change.previous or "").strip() or token
            mark = (label, token)
            if mark not in painted:
                counts[label] += 1
                painted.add(mark)
            if change.kind == "删除":
                continue
            pin_key = _pin_key(change.key)
            pin = pin_at.get((title, pin_key)) or pin_at.get((change.where, pin_key)) if pin_key else None
            if pin is not None:
                _paint_span(sheet, pin.row, change.kind, pin.pin_col or 1, sheet.max_column or 1)
                continue
            part = part_at.get((title, change.key)) or part_at.get((change.where, change.key))
            if part is not None:
                if change.field == "条目":
                    columns = [part.maker_col, part.model_col, part.part_col, part.plate_col]
                else:
                    attr = _PART_COL.get(change.field)
                    columns = [getattr(part, attr)] if attr else []
                for col in columns:
                    _paint_span(sheet, part.row, change.kind, col, col)
                continue
            item = hv_at.get((title, change.key)) or hv_at.get((change.where, change.key))
            if item is not None:
                _paint_span(sheet, item.row, change.kind, 1, sheet.max_column or 1)
                continue
            if change.field == "说明":
                wanted = (change.current or change.previous or "").strip()
                for pin in current.pins:
                    if pin.sheet not in {title, change.where} or not pin.row or not _is_explanation(pin):
                        continue
                    if wanted and _loose(_explanation_text(pin)) != _loose(wanted):
                        continue
                    _paint_span(sheet, pin.row, change.kind, pin.pin_col or 1, sheet.max_column or 1)
        sheet_items = items if display is None else [
            item for item in display if _sheet_for_change(book, item.where) == title
        ]
        totals[title] = counts
        if _summary_beside(title):
            beside[title] = (counts, sheet_items)
            continue
        start = (sheet.max_row or 1) + 2
        stale = [str(merged) for merged in sheet.merged_cells.ranges if merged.max_row >= start]
        for ref in stale:
            sheet.unmerge_cells(ref)
        _write_sheet_table(sheet, start, counts, sheet_items, folded=display is not None)
    book._icd_side_summaries = beside
    return totals


def _lookup_width(sheet: Worksheet, col: int) -> float | None:
    """读已有列宽。不访问缺失的列，避免 openpyxl 新建一列并写成默认 13。"""
    letter = get_column_letter(col)
    holder = sheet.column_dimensions
    if letter in holder and holder[letter].width:
        return float(holder[letter].width)
    for dim in holder.values():
        start = int(dim.min or 0)
        end = int(dim.max or start)
        if dim.width and start <= col <= end and end - start <= 40:
            return float(dim.width)
    return None


def _col_width(sheet: Worksheet, col: int) -> float:
    return _lookup_width(sheet, col) or 8.43


_GRID = Border(
    left=Side(style="thin", color="8A8A8A"),
    right=Side(style="thin", color="8A8A8A"),
    top=Side(style="thin", color="8A8A8A"),
    bottom=Side(style="thin", color="8A8A8A"),
)


def _new_pin_line(change: IcdChange) -> str:
    pin = change.key or "无引脚号"
    signal = (change.current or "").strip()
    if not signal:
        return pin
    return f"{pin}  {signal}"


def _filled_pin_line(change: IcdChange) -> str:
    current = (change.current or "").strip()
    pin = (change.key or "").strip()
    if not current:
        return pin or "无引脚号"
    if not pin or current.startswith(pin):
        return current
    return f"{pin}  {current}"


def _is_pinless_signal_delete(change: IcdChange) -> bool:
    """没有引脚号、上一版有信号名的删除。多条是同一类，可以收成一段。"""
    if change.kind != "删除" or change.field != "引脚" or _pin_key(change.key):
        return False
    return _is_pin_signal(change.previous)


def _chunk_deleted_signals(where: str, lines: list[str]) -> list[IcdChange]:
    chunks: list[IcdChange] = []
    for start in range(0, len(lines), 16):
        part = lines[start:start + 16]
        chunks.append(IcdChange(
            where,
            f"{len(lines)}只" if start == 0 else "续",
            "删除",
            "引脚",
            "\n".join(part),
            "（空）",
        ))
    return chunks


def _is_new_pin(change: IcdChange) -> bool:
    return change.kind == "新增" and change.field == "引脚" and bool(_pin_key(change.key))


def _is_filled_pin_number(change: IcdChange) -> bool:
    if change.kind != "变更" or change.field != "引脚号":
        return False
    previous = (change.previous or "").strip()
    return previous in {"", "无引脚号", "（空）"}


def _chunk_lines(where: str, kind: str, field: str, label: str, lines: list[str]) -> list[IcdChange]:
    """一段里最多 16 只脚，避免一行高过 Excel 上限后被裁掉。"""
    chunks: list[IcdChange] = []
    for start in range(0, len(lines), 16):
        part = lines[start:start + 16]
        chunks.append(IcdChange(
            where,
            label if start == 0 else "续",
            kind,
            field,
            "（空）" if kind == "新增" else "无引脚号",
            "\n".join(part),
        ))
    return chunks


def _fold_pin_lists(changes: list[IcdChange]) -> list[IcdChange]:
    """同一张表里成批新增的脚、成批补上的引脚号，各收成一段清单。"""
    new_pins: dict[str, list[IcdChange]] = {}
    filled: dict[str, list[IcdChange]] = {}
    pinless: dict[str, list[IcdChange]] = {}
    for change in changes:
        if _is_new_pin(change):
            new_pins.setdefault(change.where, []).append(change)
        elif _is_filled_pin_number(change):
            filled.setdefault(change.where, []).append(change)
        elif _is_pinless_signal_delete(change):
            pinless.setdefault(change.where, []).append(change)
    emitted_new: set[str] = set()
    emitted_filled: set[str] = set()
    emitted_pinless: set[str] = set()
    shown: list[IcdChange] = []
    for change in changes:
        if _is_new_pin(change):
            group = new_pins[change.where]
            if len(group) < 2:
                shown.append(change)
                continue
            if change.where in emitted_new:
                continue
            emitted_new.add(change.where)
            lines = []
            seen: set[str] = set()
            for item in group:
                line = _new_pin_line(item)
                if line in seen:
                    continue
                seen.add(line)
                lines.append(line)
            shown.extend(_chunk_lines(change.where, "新增", "引脚", f"{len(lines)}只", lines))
            continue
        if _is_filled_pin_number(change):
            group = filled[change.where]
            if len(group) < 2:
                shown.append(change)
                continue
            if change.where in emitted_filled:
                continue
            emitted_filled.add(change.where)
            lines = []
            seen_lines: set[str] = set()
            for item in group:
                line = _filled_pin_line(item)
                if line in seen_lines:
                    continue
                seen_lines.add(line)
                lines.append(line)
            shown.extend(_chunk_lines(change.where, "变更", "引脚号", f"{len(lines)}只", lines))
            continue
        if _is_pinless_signal_delete(change):
            group = pinless[change.where]
            if len(group) < 2:
                shown.append(change)
                continue
            if change.where in emitted_pinless:
                continue
            emitted_pinless.add(change.where)
            lines = []
            seen_lines: set[str] = set()
            for item in group:
                line = (item.previous or "").strip()
                if not line or line in seen_lines:
                    continue
                seen_lines.add(line)
                lines.append(line)
            shown.extend(_chunk_deleted_signals(change.where, lines))
            continue
        shown.append(change)
    return _fold_same_values(shown)


def _cover_used_range(sheet: Worksheet) -> None:
    """原表的打印区域停在数据末行时，表下小结会在分页预览里变成灰色。"""
    from openpyxl.utils import range_boundaries

    max_row = sheet.max_row or 1
    max_col = sheet.max_column or 1
    area = sheet.print_area
    if area:
        ref = str(area).split("!")[-1].replace("$", "")
        _min_c, _min_r, area_col, area_row = range_boundaries(ref)
        max_row = max(max_row, area_row)
        max_col = max(max_col, area_col)
    sheet.print_area = f"A1:{get_column_letter(max_col)}{max_row}"


def _ensure_summary_widths(sheet: Worksheet, start_col: int = 1) -> None:
    """上一版、当版至少能放下一条信号名，避免一只脚折成好几行。"""
    floors = (12, 14, 12, 16, 32)
    for offset, floor in enumerate(floors):
        col = start_col + offset
        letter = get_column_letter(col)
        current = _lookup_width(sheet, col)
        if current is None or current < floor:
            sheet.column_dimensions[letter].width = floor


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


def _sheet_has_pictures(sheet: Worksheet) -> bool:
    return bool(getattr(sheet, "_images", None))


def _picture_span(sheet: Worksheet) -> tuple[int, int]:
    """图片锚点盖到的最后一列、最后一行。0 起算，返回时改成 1 起算。"""
    last_col = 0
    last_row = 0
    for image in getattr(sheet, "_images", []) or []:
        anchor = image.anchor
        for marker in (getattr(anchor, "_from", None), getattr(anchor, "to", None)):
            if marker is None:
                continue
            last_col = max(last_col, int(getattr(marker, "col", 0) or 0) + 1)
            last_row = max(last_row, int(getattr(marker, "row", 0) or 0) + 1)
    return last_col, last_row


def _column_widths(sheet: Worksheet) -> dict[str, float]:
    """按已有列宽区间展开。不逐列去取，否则区间里的第二列会被建成默认宽度 13。"""
    found: dict[int, float] = {}
    for dim in sheet.column_dimensions.values():
        if not dim.width:
            continue
        start = int(dim.min or column_index_from_string(str(dim.index or "A")))
        end = int(dim.max or start)
        if end - start > 40:
            found[start] = float(dim.width)
            continue
        for index in range(start, end + 1):
            found[index] = float(dim.width)
    return {get_column_letter(index): width for index, width in found.items()}


def _snapshot_geometry(sheet: Worksheet) -> tuple[dict[str, float | None], dict[int, float | None]]:
    """记下已有列宽和行高。图片按格子缩放，后面改宽高会把图撑大。"""
    _picture_col, picture_row = _picture_span(sheet)
    last_row = max(sheet.max_row or 1, picture_row)
    rows = {
        index: sheet.row_dimensions[index].height
        for index in range(1, last_row + 1)
        if index in sheet.row_dimensions
    }
    return _column_widths(sheet), rows


def _restore_geometry(
    sheet: Worksheet,
    cols: dict[str, float | None],
    rows: dict[int, float | None],
) -> None:
    for letter, width in cols.items():
        sheet.column_dimensions[letter].width = width
    for index, height in rows.items():
        sheet.row_dimensions[index].height = height


def _keep_row_height(sheet: Worksheet, row: int, height: float, *, protect_through: int) -> None:
    """原表里已有的行不改高。连接器图按格子缩放，行一高，图就被拉长。"""
    if protect_through and row <= protect_through:
        return
    sheet.row_dimensions[row].height = height


def _paint_legend_cell(sheet: Worksheet, row: int, col: int, text: str, color: str) -> None:
    cell = sheet.cell(row, col, text)
    cell.fill = PatternFill("solid", fgColor=color)
    cell.font = Font(name="宋体", bold=True, size=11)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _write_side_legend(sheet: Worksheet, row: int, start_col: int) -> None:
    """没有左侧标题区时，说明仍写在小结表格上方。"""
    labels = (
        (0, "绿色：新增", "C6EFCE"),
        (2, "黄色：修改", "FFE699"),
        (4, "红色：删除", "FFC7CE"),
    )
    for offset, text, color in labels:
        _paint_legend_cell(sheet, row, start_col + offset, text, color)
        if offset < 4 and _span_free(sheet, row, start_col + offset + 1):
            sheet.merge_cells(
                start_row=row,
                start_column=start_col + offset,
                end_row=row,
                end_column=start_col + offset + 1,
            )


def _title_band(sheet: Worksheet):
    for merged in sheet.merged_cells.ranges:
        if merged.min_row == 1 and merged.max_row == 1 and merged.min_col == 1 and merged.max_col >= 6:
            return merged
    return None


def _width_emu(width: float) -> int:
    pixels = int(((256 * float(width) + int(128 / 7)) / 256) * 7)
    return pixels * 9525


def _shift_column_widths(sheet: Worksheet, note_width: float) -> None:
    from openpyxl.worksheet.dimensions import ColumnDimension

    holder = sheet.column_dimensions
    records = []
    for key in list(holder.keys()):
        dim = holder[key]
        records.append((int(dim.min or 1), int(dim.max or dim.min or 1), dim.width))
        del holder[key]
    for min_col, max_col, width in records:
        letter = get_column_letter(min_col + 1)
        holder[letter] = ColumnDimension(
            sheet,
            index=letter,
            min=min_col + 1,
            max=max_col + 1,
            width=width,
        )
    holder["A"] = ColumnDimension(sheet, index="A", min=1, max=1, width=note_width)


def _shift_geometry_snapshot(book: Workbook, title: str, note_width: float) -> None:
    store = getattr(book, "_icd_geometry", None)
    if not store or title not in store:
        return
    cols, rows = store[title]
    shifted = {
        get_column_letter(column_index_from_string(letter) + 1): width
        for letter, width in cols.items()
    }
    shifted["A"] = note_width
    store[title] = (shifted, rows)


def _note_rich() -> CellRichText:
    """最上面这一行。关键词加粗，绿黄红用对应的字色。"""
    title = InlineFont(rFont="宋体", b=True, sz=12, color="1F2933")
    body = InlineFont(rFont="宋体", sz=11, color="334155")
    green = InlineFont(rFont="宋体", b=True, sz=11, color="006600")
    gold = InlineFont(rFont="宋体", b=True, sz=11, color="8A6A00")
    red = InlineFont(rFont="宋体", b=True, sz=11, color="9C1B1B")
    return CellRichText(
        TextBlock(title, "备注"),
        TextBlock(body, "　　"),
        TextBlock(green, "绿色　新增"),
        TextBlock(body, "　这一格是当版多出来的，上一版没有。　　"),
        TextBlock(gold, "黄色　修改"),
        TextBlock(body, "　只涂和上一版不一样的那一格，不把整行涂黄。　　"),
        TextBlock(red, "红色　删除"),
        TextBlock(body, "　当版已经没有的内容不写回原表，逐条写在右侧本表小结。"),
    )


def _note_plain() -> str:
    return "".join(block.text for block in _note_rich())


def _style_note_cell(cell) -> None:
    cell.value = _note_rich()
    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
    cell.fill = PatternFill("solid", fgColor="F8FAFC")
    cell.border = Border(bottom=Side(style="thin", color="CBD5E1"))


def _shift_geometry_rows(book: Workbook, title: str) -> None:
    store = getattr(book, "_icd_geometry", None)
    if not store or title not in store:
        return
    cols, rows = store[title]
    store[title] = (cols, {index + 1: height for index, height in rows.items()})


def _shift_row_breaks(sheet: Worksheet) -> None:
    """最上面插入一行后，手动行分页符下移一行。列分页符不动。"""
    for brk in list(getattr(sheet.row_breaks, "brk", None) or []):
        if brk.id is not None:
            brk.id = int(brk.id) + 1


def _insert_note_row(sheet: Worksheet, book: Workbook) -> None:
    """最上面插入一行。原表下移，列不动。图片不在这里改，保存后只把行号加 1。"""
    bands = [
        (merged.min_row, merged.min_col, merged.max_row, merged.max_col)
        for merged in sheet.merged_cells.ranges
    ]
    for merged in list(sheet.merged_cells.ranges):
        sheet.unmerge_cells(
            start_row=merged.min_row,
            start_column=merged.min_col,
            end_row=merged.max_row,
            end_column=merged.max_col,
        )
    heights = [
        (int(index), dim.height)
        for index, dim in list(sheet.row_dimensions.items())
        if getattr(dim, "height", None)
    ]
    for index, _height in heights:
        sheet.row_dimensions[index].height = None
    sheet.insert_rows(1)
    for index, height in heights:
        sheet.row_dimensions[index + 1].height = height
    default = getattr(sheet.sheet_format, "defaultRowHeight", None) or 16.5
    sheet.row_dimensions[1].height = float(default)
    for min_row, min_col, max_row, max_col in bands:
        sheet.merge_cells(
            start_row=min_row + 1,
            start_column=min_col,
            end_row=max_row + 1,
            end_column=max_col,
        )
    _shift_row_breaks(sheet)
    note_rows = getattr(book, "_icd_note_rows", None)
    if note_rows is None:
        note_rows = set()
        book._icd_note_rows = note_rows
    note_rows.add(sheet.title)
    _shift_geometry_rows(book, sheet.title)


def _write_note_on_left_row(sheet: Worksheet, end_col: int, stop_before: int = 0) -> None:
    """备注独占第 1 行，从第 1 列起。原表已经下移，不再盖住标题。"""
    span = end_col
    if stop_before > span + 1:
        span = stop_before - 1
    while span > end_col and not _span_free(sheet, 1, span):
        span -= 1
    _style_note_cell(sheet.cell(1, 1))
    if span > 1 and _span_free(sheet, 1, 1):
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
    sheet.row_dimensions[1].height = 24 if span >= 12 else 42
    if not _sheet_has_pictures(sheet):
        _show_sheet_from_top(sheet)


def _write_note_row(sheet: Worksheet, row: int, start_col: int) -> None:
    _style_note_cell(sheet.cell(row, start_col))
    if _span_free(sheet, row, start_col):
        sheet.merge_cells(
            start_row=row,
            start_column=start_col,
            end_row=row,
            end_column=start_col + 4,
        )
    if not _sheet_has_pictures(sheet):
        _show_sheet_from_top(sheet)


def _note_rules() -> CellRichText:
    """给工程师看的规则。标题和条目名加粗，正文用宋体。"""
    title = InlineFont(rFont="宋体", b=True, sz=14)
    body = InlineFont(rFont="宋体", sz=11)
    green = InlineFont(rFont="宋体", b=True, sz=11, color="006600")
    gold = InlineFont(rFont="宋体", b=True, sz=11, color="8A6A00")
    red = InlineFont(rFont="宋体", b=True, sz=11, color="9C1B1B")
    head = InlineFont(rFont="宋体", b=True, sz=11)
    return CellRichText(
        TextBlock(title, "备注"),
        TextBlock(body, "\n对照上一版之后，用颜色和右侧的表说明改了什么。\n\n"),
        TextBlock(green, "绿色：新增"),
        TextBlock(body, "\n当版多出来的格子。上一版没有这一条。\n\n"),
        TextBlock(gold, "黄色：修改"),
        TextBlock(body, "\n这一格和上一版不一样。只涂改过的那一项，不把整行都涂黄。\n\n"),
        TextBlock(red, "红色：删除"),
        TextBlock(body, "\n当版已经没有的内容不写回原表，写在右侧本表小结里，这一行是红色。\n\n"),
        TextBlock(head, "本表小结"),
        TextBlock(body, "\n写在表格右侧，逐条列出新增、修改、删除。"),
    )


def _shift_col_breaks(sheet: Worksheet) -> None:
    """最左边插入一列后，手动列分页符右移一列。行分页符不动。"""
    for brk in list(getattr(sheet.col_breaks, "brk", None) or []):
        if brk.id is not None:
            brk.id = int(brk.id) + 1


def _show_sheet_from_top(sheet: Worksheet) -> None:
    """原表若停在分页预览，打开就是一屏「第 N 页」。出表改回普通视图，从 A1 看。"""
    for view in sheet.views.sheetView:
        view.view = "normal"
        view.topLeftCell = "A1"
        for sel in list(view.selection or []):
            sel.activeCell = "A1"
            sel.sqref = "A1"


def _insert_note_column(sheet: Worksheet, book: Workbook) -> None:
    """最左边插入备注列。原表从第 2 列起，图片跟着格子走。"""
    note_width = 32
    bands = [
        (merged.min_row, merged.min_col, merged.max_row, merged.max_col)
        for merged in sheet.merged_cells.ranges
    ]
    for merged in list(sheet.merged_cells.ranges):
        sheet.unmerge_cells(
            start_row=merged.min_row,
            start_column=merged.min_col,
            end_row=merged.max_row,
            end_column=merged.max_col,
        )
    sheet.insert_cols(1)
    _shift_column_widths(sheet, note_width)
    for min_row, min_col, max_row, max_col in bands:
        sheet.merge_cells(
            start_row=min_row,
            start_column=min_col + 1,
            end_row=max_row,
            end_column=max_col + 1,
        )
    # 不在内存里改图片锚点。openpyxl 一改就会按图片像素重算，图会被撑大。
    # 保存后再改图纸 XML，只把列号加 1。分页符也要跟着右移，否则仍切在插列之前的位置。
    _shift_col_breaks(sheet)
    _show_sheet_from_top(sheet)
    shifts = getattr(book, "_icd_note_shifts", None)
    if shifts is None:
        shifts = {}
        book._icd_note_shifts = shifts
    shifts[sheet.title] = _width_emu(note_width)
    _shift_geometry_snapshot(book, sheet.title, note_width)


def _write_left_legend(sheet: Worksheet, book: Workbook) -> bool:
    """有标题行时，备注单独占第 1 列。原表右移一列，图只跟着列号走。"""
    if _title_band(sheet) is None:
        return False
    _insert_note_column(sheet, book)
    cell = sheet.cell(1, 1, _note_rules())
    cell.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True, indent=1)
    cell.fill = PatternFill("solid", fgColor="F7F9FC")
    last = max(sheet.max_row or 1, 12)
    sheet.merge_cells(start_row=1, start_column=1, end_row=last, end_column=1)
    return True


def _write_sheet_table(
    sheet: Worksheet,
    start: int,
    counts: dict[str, int],
    items: list[IcdChange],
    *,
    folded: bool = False,
    start_col: int = 1,
    protect_through: int = 0,
) -> None:
    """默认写在原表最下方、从 A 列起。整车低压和变速器改写在表头右侧。文字靠左。"""
    _ensure_summary_widths(sheet, start_col)
    columns = tuple(range(start_col, start_col + 5))
    title = (
        f"本表小结　新增 {counts['新增']}　修改 {counts['修改']}　删除 {counts['删除']}"
        "。绿色为新增，黄色为修改，红色为删除"
    )
    _write_summary_cell(
        sheet,
        start,
        start_col,
        title,
        font=Font(name="宋体", bold=True, size=12),
        fill=PatternFill("solid", fgColor="F2F2F2"),
    )
    sheet.merge_cells(
        start_row=start,
        start_column=start_col,
        end_row=start,
        end_column=start_col + 4,
    )
    title_width = sum(_col_width(sheet, col) for col in columns)
    _keep_row_height(
        sheet,
        start,
        _row_height(_wrapped_lines(title, title_width)),
        protect_through=protect_through,
    )
    header_row = start + 1
    header_font = Font(name="宋体", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    for col, name in zip(columns, ("差异", "对象", "字段", "上一版", "当版"), strict=True):
        _write_summary_cell(sheet, header_row, col, name, font=header_font, fill=header_fill)
    _keep_row_height(sheet, header_row, 22, protect_through=protect_through)
    body_font = Font(name="宋体", size=11)
    for index, change in enumerate(items if folded else _fold_pin_lists(items), start=1):
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
        _keep_row_height(sheet, row, _row_height(lines), protect_through=protect_through)
    _cover_used_range(sheet)


def _write_color_legend(sheet: Worksheet, row: int, columns: int) -> None:
    """绿色新增、黄色修改、红色删除。原表和差异总结用的是同三种颜色。"""
    labels = (
        (1, "绿色：新增", "C6EFCE"),
        (3, "黄色：修改", "FFE699"),
        (5, "红色：删除", "FFC7CE"),
    )
    for col, text, color in labels:
        cell = sheet.cell(row, col, text)
        cell.fill = PatternFill("solid", fgColor=color)
        cell.font = Font(name="宋体", size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        end = min(col + 1, columns)
        if end > col:
            sheet.merge_cells(start_row=row, start_column=col, end_row=row, end_column=end)
    sheet.row_dimensions[row].height = 22


def _write_overall_summary(
    book: Workbook,
    previous: IcdBook,
    current: IcdBook,
    totals: dict[str, dict[str, int]],
    changes: list[IcdChange],
    lead: str = "",
) -> None:
    if "差异总结" in book.sheetnames:
        del book["差异总结"]
    sheet = book.create_sheet("差异总结")
    columns = 6
    summary_widths = (22, 14, 14, 14, 36, 36)
    _set_widths(sheet, summary_widths)
    _write_banner(sheet, previous, current, columns)
    _write_color_legend(sheet, 3, columns)
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
    note_row = total_row + 2
    title = sheet.cell(note_row, 1, "关键变化")
    title.font = Font(name="宋体", bold=True, size=12, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1E3A5F")
    title.alignment = Alignment(horizontal="left", vertical="center")
    if columns > 1:
        sheet.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=columns)
    sheet.row_dimensions[note_row].height = 22
    written = _write_key_changes(sheet, note_row + 1, lead, columns, sum(summary_widths))
    _widen_columns(sheet, skip_rows=frozenset({1, 2, note_row, *written}))


def _write_key_changes(sheet: Worksheet, start: int, text: str, columns: int, width: float) -> list[int]:
    """一张表一个标题，一条重点占一行。不要把所有改动挤进同一个格子。"""
    body = (text or "").strip() or "没有可归纳的差异。"
    written: list[int] = []
    row = start
    blocks = [block for block in re.split(r"\n\s*\n", body) if block.strip()]
    for index, block in enumerate(blocks):
        if index:
            sheet.row_dimensions[row].height = 8
            written.append(row)
            row += 1
        for line in [item.strip() for item in block.splitlines() if item.strip()]:
            heading = line.startswith("【") and line.endswith("】") and "。" not in line and "；" not in line
            shown = line[1:-1] if heading else line
            if columns > 1:
                sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=columns)
            cell = sheet.cell(row, 1, shown)
            if heading:
                cell.font = Font(name="宋体", bold=True, size=12, color="1E3A5F")
                cell.fill = PatternFill("solid", fgColor="D6E3F0")
                cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                sheet.row_dimensions[row].height = 24
            else:
                cell.font = Font(name="宋体", size=11, color="1F2933")
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True, indent=1)
                sheet.row_dimensions[row].height = max(24, _row_height(_wrapped_lines(shown, width)))
            written.append(row)
            row += 1
    return written


def _widen_columns(sheet: Worksheet, *, skip_rows: frozenset[int] = frozenset(), floor: int = 12, cap: int = 48) -> None:
    """按格子里的字加宽。已经更宽的列不缩小，表头横幅不参与。"""
    for col in range(1, (sheet.max_column or 1) + 1):
        longest = 0
        for row in range(1, (sheet.max_row or 1) + 1):
            if row in skip_rows:
                continue
            longest = max(longest, _display_units(sheet.cell(row, col).value))
        if longest <= 0:
            continue
        width = min(max(longest + 2, floor), cap)
        letter = get_column_letter(col)
        current = sheet.column_dimensions[letter].width or 0
        if width > current:
            sheet.column_dimensions[letter].width = width


def _span_free(sheet: Worksheet, row: int, col: int) -> bool:
    """这一格不在合并区域里，或就是合并区域的左上角。不新建格子。"""
    for merged in sheet.merged_cells.ranges:
        if merged.min_row <= row <= merged.max_row and merged.min_col <= col <= merged.max_col:
            return (row, col) == (merged.min_row, merged.min_col)
    return True


def _match_header_row(sheet: Worksheet) -> int:
    for row in range(1, min(sheet.max_row or 1, 8) + 1):
        for col in range(1, min(sheet.max_column or 1, 30) + 1):
            if str(sheet.cell(row, col).value or "").strip() in {"引脚号", "连接器", "厂家"}:
                return row
    return 1


def _blank_side_gaps(book: Workbook) -> None:
    """原表和本表小结之间空一列。这一列不留原来的底色，避免两张表贴在一起。"""
    pending = getattr(book, "_icd_side_summaries", None) or {}
    empty = PatternFill(fill_type=None)
    for title in pending:
        if title not in book.sheetnames:
            continue
        sheet = book[title]
        summary_col = 0
        for row in range(1, min(sheet.max_row or 1, 8) + 1):
            for col in range(1, (sheet.max_column or 1) + 1):
                if str(sheet.cell(row, col).value or "").startswith("本表小结"):
                    summary_col = col
                    break
            if summary_col:
                break
        if summary_col <= 1:
            continue
        gap = summary_col - 1
        from openpyxl.cell.cell import MergedCell

        for row in range(1, (sheet.max_row or 1) + 1):
            cell = sheet.cell(row, gap)
            if isinstance(cell, MergedCell):
                continue
            if str(cell.value or "") in {"接插件信息", "绿色：新增", "黄色：修改", "红色：删除"}:
                continue
            cell.value = None
            cell.fill = empty
            cell.border = Border()
        letter = get_column_letter(gap)
        if _lookup_width(sheet, gap) is None:
            sheet.column_dimensions[letter].width = 8


def _place_side_summaries(book: Workbook) -> None:
    """长表的本表小结写在原表右边、空一列，从表头那一行起。打开不用翻到表底。"""
    pending = getattr(book, "_icd_side_summaries", None) or {}
    for title, (counts, items) in pending.items():
        if title not in book.sheetnames:
            continue
        sheet = book[title]
        band = _title_band(sheet)
        note_span = band.max_col if band is not None else 0
        if note_span:
            _insert_note_row(sheet, book)
        header_row = _match_header_row(sheet)
        start_col = _content_last_column(sheet) + 2
        limit = start_col + 24
        while start_col <= limit and not all(
            _span_free(sheet, row, start_col + offset)
            for row in range(header_row, header_row + 8)
            for offset in range(5)
        ):
            start_col += 1
        if start_col > limit:
            start = (sheet.max_row or 1) + 2
            if note_span:
                _write_note_on_left_row(sheet, note_span, start_col)
            _write_sheet_table(sheet, start, counts, items, folded=True)
            continue
        protected = sheet.max_row or 1 if _sheet_has_pictures(sheet) else 0
        if note_span:
            _write_note_on_left_row(sheet, note_span, start_col)
        else:
            _write_note_row(sheet, header_row, start_col)
        _write_sheet_table(
            sheet,
            header_row + 1,
            counts,
            items,
            folded=True,
            start_col=start_col,
            protect_through=protected,
        )


def _content_last_column(sheet: Worksheet) -> int:
    last = 1
    for row in range(1, (sheet.max_row or 1) + 1):
        for col in range(1, (sheet.max_column or 1) + 1):
            if sheet.cell(row, col).value not in (None, ""):
                last = max(last, col)
    return last


def _count_lead(changes: list[IcdChange]) -> str:
    buckets: dict[str, dict[str, int]] = {}
    seen: dict[str, set[tuple[str, str]]] = {}
    for change in changes:
        label = "修改" if change.kind == "变更" else change.kind
        if label not in {"新增", "修改", "删除"}:
            continue
        token = _pin_key(change.key) or change.key
        marks = seen.setdefault(change.where, set())
        if (label, token) in marks:
            continue
        marks.add((label, token))
        buckets.setdefault(change.where, {"新增": 0, "修改": 0, "删除": 0})[label] += 1
    parts: list[str] = []
    for title, counts in buckets.items():
        bits = [f"{name}{counts[name]}" for name in ("新增", "修改", "删除") if counts[name]]
        if bits:
            parts.append(f"{title}：" + "，".join(bits))
    return "。".join(parts) + "。" if parts else ""


_SIGNAL_FAMILIES = ("CANFD", "CAN", "LIN", "KL30", "KL15", "KL87", "GND", "PWM")


def _signal_families(text: str) -> list[str]:
    upper = (text or "").upper()
    found: list[str] = []
    for name in _SIGNAL_FAMILIES:
        if name in upper:
            found.append(name)
            upper = upper.replace(name, " ")
    return found


def _is_batch(change: IcdChange) -> bool:
    key = (change.key or "").strip()
    return "\n" in (change.previous or "") or "\n" in (change.current or "") or key.endswith(("只", "处"))


def _focus_from_to(change: IcdChange) -> str:
    """厂家、型号、料号这类写清由什么改为什么。多处同一改动带上电器端、线束端。"""
    field = change.field or ""
    previous = (change.previous or "").strip()
    current = (change.current or "").strip()
    sides = ""
    if "\n" in current:
        current, sides = current.split("\n", 1)
        current = current.strip()
        sides = sides.strip()
    left = previous.split("\n", 1)[0].strip() or "（空）"
    right = current or "（空）"
    key = (change.key or "").strip()
    side_list = [item.strip() for item in re.split(r"[、,，]", sides) if item.strip()]
    named = bool(side_list) and len(side_list) <= 3 and all(len(item) <= 16 and "PIN" not in item.upper() for item in side_list)
    if named:
        label = "、".join(side_list) + "的" + field
        suffix = ""
    elif key and not key.endswith(("处", "只")):
        label = f"{key}的{field}"
        suffix = ""
    else:
        label = field
        suffix = f"（{key}）" if key.endswith("处") else ""
    return f"{label}由{left}改为{right}{suffix}"


def _secondary_line(changes: list[IcdChange]) -> str:
    fields = {change.field or "" for change in changes}
    if fields & {"引脚定义", "引脚数"}:
        return "引脚定义有改动，见本表小结"
    if fields & {"引脚", "引脚号", "信号定义", "信号名称", "电流", "信号类型"}:
        return "引脚有变动，见本表小结"
    return "其余改动见本表小结"


def _digest_phrase(change: IcdChange) -> str:
    """一句关键变化。成批引脚只说数量和信号类别，不把脚号再抄一遍。"""
    kind = "修改" if change.kind == "变更" else change.kind
    key = (change.key or "").strip()
    field = change.field or ""
    previous = (change.previous or "").strip()
    current = (change.current or "").strip()
    if field in _FOCUS_FIELDS:
        return _focus_from_to(change)
    if _is_batch(change):
        families = _signal_families(f"{previous}\n{current}")
        if field == "电流":
            value = current.split("\n", 1)[0].strip()
            return f"{key}的电流改为{value}" if value else f"{key}的电流有改动"
        family = f"，信号里有{'、'.join(families)}" if families else ""
        return f"{kind}{key}{field}{family}"
    if kind == "新增" and field == "引脚":
        return f"新增引脚{key}" + (f" {current}" if current else "")
    if kind == "删除" and field == "引脚":
        return f"删除引脚{key}" + (f" {previous}" if previous else "")
    if kind == "新增" and field in {"条目", "说明"}:
        extra = f"：{current}" if current else ""
        return f"新增{key}{extra}" if key else f"新增{field}{extra}"
    if kind == "删除" and field in {"条目", "说明"}:
        extra = f"：{previous}" if previous else ""
        return f"删除{key}{extra}" if key else f"删除{field}{extra}"
    left = previous or "（空）"
    right = current or "（空）"
    if left != right:
        label = f"{key}的{field}" if key else field
        return f"{label}由{left}改为{right}"
    return f"{kind}{key}的{field}" if key else f"{kind}{field}"


def _engineer_digest(changes: list[IcdChange]) -> str:
    grouped: dict[str, list[IcdChange]] = {}
    order: list[str] = []
    for change in changes:
        if (change.key or "").strip() == "续":
            continue
        if change.where not in grouped:
            order.append(change.where)
            grouped[change.where] = []
        grouped[change.where].append(change)
    blocks: list[str] = []
    for title in order:
        items = grouped[title]
        focus = [change for change in items if (change.field or "") in _FOCUS_FIELDS]
        rest = [change for change in items if (change.field or "") not in _FOCUS_FIELDS]
        lines = [_focus_from_to(change) for change in focus[:4]]
        if lines and (rest or len(focus) > 4):
            lines.append(_secondary_line(rest) if rest else "其余见本表小结")
        elif not lines:
            lines = _choose_focus([(_phrase_rank(change), _digest_phrase(change)) for change in items])
        if not lines:
            continue
        blocks.append(f"【{title}】\n" + "\n".join(f"· {phrase}" for phrase in lines))
    return "\n\n".join(blocks)


_CONNECTOR_FIELDS = frozenset({
    "厂家", "型号", "供应商料号", "镀层", "供应商", "用途", "电流要求", "引脚定义", "引脚数", "条目",
})
# 工程师先看这几项，关键变化要写由什么改为什么。引脚定义、引脚数收成一句。
_FOCUS_FIELDS = frozenset({"厂家", "型号", "供应商料号", "镀层", "供应商", "用途"})


def _phrase_rank(change: IcdChange) -> tuple[int, int]:
    """接插件的厂家、供应商、型号、料号优先。引脚增减排在后面。"""
    field = change.field or ""
    if field in _CONNECTOR_FIELDS:
        return (0, 0)
    if field in {"备注", "说明"} or field.startswith(("备注", "说明")):
        return (1, 0)
    return (9, 0)


def _choose_focus(pairs: list[tuple[tuple[int, int], str]]) -> list[str]:
    connector = [phrase for rank, phrase in sorted(pairs, key=lambda item: item[0]) if rank[0] == 0]
    if connector:
        return connector[:4]
    notes = [phrase for rank, phrase in sorted(pairs, key=lambda item: item[0]) if rank[0] == 1]
    if notes:
        return notes[:2]
    if pairs:
        return ["引脚有变动，见本表小结"]
    return []


def _summary_stays_inside(text: str, changes: list[IcdChange]) -> bool:
    if not text or len(text) > 360:
        return False
    pins = re.findall(r"PIN\d+", text, flags=re.I)
    if len(pins) > 6:
        return False
    corpus = "\n".join(
        f"{item.where} {item.key} {item.field} {item.previous} {item.current}" for item in changes
    ).upper()
    for pin in pins:
        if pin.upper() not in corpus:
            return False
    for amp in re.findall(r"\d+(?:\.\d+)?A", text, flags=re.I):
        if amp.upper() not in corpus:
            return False
    return True


def _sheet_mentioned(label: str, changes: list[IcdChange]) -> bool:
    name = re.sub(r"^[\d\s\-—–]+", "", label.strip())
    if len(name) < 2:
        return False
    for item in changes:
        where = item.where or ""
        if name in where or where in label or label in where:
            return True
    return False


def _points_text(points: object, changes: list[IcdChange]) -> str:
    """模型按表给出的短句。某一条过长或用了表上没有的脚号、电流，整段不用。"""
    if not isinstance(points, list) or not points:
        return ""
    blocks: list[str] = []
    for point in points:
        if not isinstance(point, dict):
            return ""
        sheet = str(point.get("sheet") or "").strip()
        lines = point.get("lines")
        if not _sheet_mentioned(sheet, changes) or not isinstance(lines, list) or not 1 <= len(lines) <= 3:
            return ""
        cleaned: list[str] = []
        for line in lines:
            text = re.sub(r"\s+", " ", str(line)).strip().lstrip("·").strip()
            if not text or len(text) > 72 or "；" in text or not _summary_stays_inside(text, changes):
                return ""
            cleaned.append(text)
        blocks.append(f"【{sheet}】\n" + "\n".join(f"· {line}" for line in cleaned))
    return "\n\n".join(blocks)


def _plain_brief(text: str, changes: list[IcdChange]) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(text or "").replace("\r", "").split("\n")]
    lines = [line for line in lines if line]
    if not lines or any(len(line) > 80 or line.count("；") >= 2 for line in lines):
        return ""
    joined = "\n".join(lines)
    if not _summary_stays_inside(joined, changes):
        return ""
    return joined


def _llm_object(text: str) -> dict[str, object]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


_ICD_LLM_PROMPT = (
    "你在帮电气工程师看两版 ICD。工程师先看接插件，不看每一只脚。\n"
    "关键数据只写：厂家、供应商、型号、供应商料号、镀层、用途。必须写成由上一版改为当版。\n"
    "这些有变化时，不要写引脚新增、删除、补引脚号、信号类别，也不要展开引脚定义。\n"
    "引脚定义、引脚数、只有引脚变化时，写一条「见本表小结」，不要把脚位逐条抄上。\n"
    "points：每张有差异的表一项。sheet 用 JSON 里的表名。lines 最多 4 条，每条只写一件事。\n"
    "不得发明 JSON 里没有的厂家、型号、料号。\n"
    "wording：上一版和当版意思相同、只是措辞不同的备注或说明，填它们的 id。\n"
    "notes：对象不是引脚号、内容是说明句的 id。\n"
    "只输出 JSON：{\"points\":[{\"sheet\":\"\",\"lines\":[]}],\"wording\":[],\"notes\":[]}。"
)


def _pin_focus_line(line: str) -> bool:
    text = line.lstrip("· ").strip()
    return bool(re.search(r"只引脚|信号类别|补充引脚|信号里有", text))


def _same_sheet(label: str, where: str) -> bool:
    if not label or not where:
        return False
    if label == where:
        return True
    name = re.sub(r"^[\d\s\-—–]+", "", label.strip())
    return len(name) >= 2 and (name in where or where in label)


def _sheet_has_connector_change(label: str, changes: list[IcdChange]) -> bool:
    return any(
        _same_sheet(label, change.where) and (change.field or "") in _CONNECTOR_FIELDS
        for change in changes
    )


def _sheet_has_focus_change(label: str, changes: list[IcdChange]) -> bool:
    return any(
        _same_sheet(label, change.where) and (change.field or "") in _FOCUS_FIELDS
        for change in changes
    )


def _text_blocks(text: str) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith("【") and lines[0].endswith("】"):
            body = [line[1:].strip() if line.startswith("·") else line for line in lines[1:]]
            blocks.append((lines[0][1:-1], body))
        else:
            blocks.append(("", lines))
    return blocks


def _focus_lead(candidate: str, digest: str, changes: list[IcdChange]) -> str:
    """有接插件变化时，丢掉模型写成的引脚清单，改用厂家、供应商、型号、料号。"""
    if not candidate:
        return digest
    model = {title: lines for title, lines in _text_blocks(candidate) if title}
    if not model:
        if any((change.field or "") in _CONNECTOR_FIELDS for change in changes):
            return digest
        return candidate
    digest_map = {title: lines for title, lines in _text_blocks(digest)}
    order = list(dict.fromkeys([*digest_map, *model]))
    blocks: list[str] = []
    for title in order:
        if _sheet_has_focus_change(title, changes):
            lines = digest_map.get(title, [])
        else:
            lines = [line for line in model.get(title, []) if line]
            if _sheet_has_connector_change(title, changes):
                lines = [line for line in lines if not _pin_focus_line(line)]
            if not lines:
                lines = digest_map.get(title, [])
        if not lines:
            continue
        body = "\n".join(f"· {line.lstrip('· ').strip()}" for line in lines)
        blocks.append(f"【{title}】\n{body}")
    return "\n\n".join(blocks)


def _llm_change(index: int, change: IcdChange) -> dict[str, object]:
    kind = "修改" if change.kind == "变更" else change.kind
    previous = change.previous or ""
    current = change.current or ""
    item: dict[str, object] = {
        "id": index,
        "sheet": change.where,
        "key": change.key,
        "kind": kind,
        "field": change.field,
    }
    if _is_batch(change) and change.field in {"引脚", "引脚号"}:
        item["pin_list"] = True
    elif _is_batch(change):
        item["previous"] = previous.split("\n", 1)[0][:80]
        item["current"] = current.split("\n", 1)[0][:80]
    else:
        item["previous"] = previous[:120]
        item["current"] = current[:120]
    return item


def _llm_polish(
    folded: list[IcdChange],
    raw: list[IcdChange],
    ask: Callable[[list[dict[str, str]]], str] | None,
) -> tuple[list[IcdChange], str]:
    """模型写关键变化，并标措辞和说明。脚号和取值仍是表上的原文。模型不可用时用对照结果归纳。"""
    candidate = ""
    wording: set[int] = set()
    notes: set[int] = set()
    if ask is not None and folded:
        payload = [
            _llm_change(index, change)
            for index, change in enumerate(folded[:40])
            if (change.key or "").strip() != "续"
        ]
        try:
            reply = ask([
                {"role": "system", "content": _ICD_LLM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ])
            data = _llm_object(reply or "")
            candidate = _points_text(data.get("points"), folded) or _plain_brief(str(data.get("summary") or ""), folded)
            wording = {int(item) for item in data.get("wording") or [] if str(item).isdigit()}
            notes = {int(item) for item in data.get("notes") or [] if str(item).isdigit()}
        except Exception:
            candidate = ""
            wording = set()
            notes = set()
    polished: list[IcdChange] = []
    for index, change in enumerate(folded):
        field = change.field
        key = change.key
        if index in wording and field in {"备注", "说明"} and (change.previous or "").strip() and (change.current or "").strip():
            if "措辞，请看" not in field:
                field = f"{field}·措辞，请看"
        if (
            index in notes
            and not _pin_key(key)
            and key not in {"说明", "本表备注", "本表说明", "续"}
            and not str(key).endswith(("只", "处"))
        ):
            key = "说明"
            field = "说明"
        if field != change.field or key != change.key:
            polished.append(IcdChange(change.where, key, change.kind, field, change.previous, change.current))
        else:
            polished.append(change)
    digest = _engineer_digest(polished) or _count_lead(raw)
    lead = _focus_lead(candidate, digest, polished) or digest
    return polished, lead


def write_icd_review(
    book: Workbook,
    current: IcdBook,
    previous: IcdBook | None = None,
    ask: Callable[[list[dict[str, str]]], str] | None = None,
) -> list:
    """原表保持版式。有上一版时涂改过的行，表下写小结，并加差异总结。"""
    pictures = {
        sheet.title: _snapshot_geometry(sheet)
        for sheet in book.worksheets
        if _sheet_has_pictures(sheet)
    }
    book._icd_geometry = pictures
    changes: list[IcdChange] = []
    if previous is not None:
        changes = _all_changes(previous, current)
        folded, lead = _llm_polish(_fold_pin_lists(changes), changes, ask)
        totals = _mark_source_sheets(book, current, changes, display=folded)
        _write_overall_summary(book, previous, current, totals, folded, lead)
    _place_side_summaries(book)
    for title, (cols, rows) in pictures.items():
        if title in book.sheetnames:
            _restore_geometry(book[title], cols, rows)
    _blank_side_gaps(book)
    for name in list(book.sheetnames):
        if "变更记录" in name or name == "版本差异":
            del book[name]
    if previous is not None and "差异总结" in book.sheetnames:
        book.active = book.worksheets[0]
    return changes


def _loose(text: str) -> str:
    return re.sub(r"[\s_]+", "", text or "")


def _prose(text: str) -> bool:
    """带句读的说明。脚名、料号、引脚定义不算。"""
    return bool(re.search(r"[，。；;、]", text or ""))


def _is_explanation(pin: IcdPin) -> bool:
    return _prose(pin.pin) or _prose(pin.signal)


def _explanation_text(pin: IcdPin) -> str:
    if _prose(pin.signal):
        return pin.signal.strip()
    if _prose(pin.pin):
        return pin.pin.strip()
    return (pin.signal or pin.pin or "").strip()


def _same_value_group(change: IcdChange) -> bool:
    if change.kind != "变更":
        return False
    if change.field in {"引脚", "引脚号", "引脚定义", "说明"}:
        return False
    key = (change.key or "").strip()
    if not key or _prose(key) or _prose(change.previous) or _prose(change.current):
        return False
    return True


def _fold_same_values(changes: list[IcdChange]) -> list[IcdChange]:
    """同一张表、同一字段、同一取值的改动收成一行，脚号列在当版。"""
    groups: dict[tuple[str, str, str, str, str], list[IcdChange]] = {}
    tokens: list[tuple[str, str, str, str, str] | None] = []
    for change in changes:
        if not _same_value_group(change):
            tokens.append(None)
            continue
        token = (change.where, change.kind, change.field, _loose(change.previous), _loose(change.current))
        tokens.append(token)
        groups.setdefault(token, []).append(change)
    emitted: set[tuple[str, str, str, str, str]] = set()
    shown: list[IcdChange] = []
    for change, token in zip(changes, tokens, strict=True):
        if token is None or len(groups[token]) < 2:
            shown.append(change)
            continue
        if token in emitted:
            continue
        emitted.add(token)
        group = groups[token]
        names: list[str] = []
        seen: set[str] = set()
        for item in group:
            name = item.key or "无引脚号"
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        previous = (group[0].previous or "").strip() or "（空）"
        current = (group[0].current or "").strip() or "（空）"
        for start in range(0, len(names), 12):
            part = names[start:start + 12]
            shown.append(IcdChange(
                group[0].where,
                f"{len(names)}处" if start == 0 else "续",
                group[0].kind,
                group[0].field,
                previous,
                current + "\n" + "、".join(part),
            ))
    return shown


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


def _zip_drawing_map(zip_file: "zipfile.ZipFile") -> dict[str, str]:
    """表名到图纸路径。"""
    import zipfile
    from xml.etree import ElementTree as ET

    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    root = ET.fromstring(zip_file.read("xl/workbook.xml"))
    rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
    found: dict[str, str] = {}
    for sheet in root.findall(f"{{{main}}}sheets/{{{main}}}sheet"):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get(f"{{{rel_ns}}}id", "")
        target = targets.get(rid, "").lstrip("/")
        if not target:
            continue
        if not target.startswith("xl/"):
            target = "xl/" + target
        rel_path = str(Path(target).parent / "_rels" / (Path(target).name + ".rels"))
        try:
            sheet_rels = ET.fromstring(zip_file.read(rel_path))
        except KeyError:
            continue
        for item in sheet_rels:
            if not item.attrib.get("Type", "").endswith("/drawing"):
                continue
            drawing = item.attrib["Target"]
            if drawing.startswith("/"):
                drawing_path = drawing.lstrip("/")
            elif drawing.startswith("../"):
                drawing_path = "xl/" + drawing.replace("../", "")
            else:
                drawing_path = str(Path(target).parent / drawing)
            found[name] = drawing_path
    return found


def _png_size(blob: bytes) -> tuple[int, int] | None:
    if len(blob) < 24 or blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    import struct

    return struct.unpack(">II", blob[16:24])


def _row_emu(height: float) -> int:
    return int(round(float(height) * 12700))


def _origins(sizes: list[int]) -> list[int]:
    origin = 0
    found: list[int] = []
    for size in sizes:
        found.append(origin)
        origin += size
    found.append(origin)
    return found


def _marker_at(origins: list[int], pos: int) -> tuple[int, int]:
    index = 0
    for cursor, origin in enumerate(origins[:-1]):
        if origin <= pos:
            index = cursor
        else:
            break
    return index, max(0, pos - origins[index])


def _picture_wells(sheet_xml: bytes) -> tuple[list[int], list[int], list[tuple[int, int, int, int]]]:
    """列宽、行高，以及像图片格那样的合并区。坐标和图纸锚点一样，从 0 起。"""
    from xml.etree import ElementTree as ET

    root = ET.fromstring(sheet_xml)
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    default_row = 15.0
    for fmt in root.findall(f"{ns}sheetFormatPr"):
        if fmt.attrib.get("defaultRowHeight"):
            default_row = float(fmt.attrib["defaultRowHeight"])
    col_widths = [8.43] * 40
    for col in root.findall(f"{ns}cols/{ns}col"):
        start = int(col.attrib.get("min") or 1) - 1
        end = int(col.attrib.get("max") or start + 1) - 1
        width = float(col.attrib.get("width") or 8.43)
        for index in range(max(0, start), min(len(col_widths), end + 1)):
            col_widths[index] = width
    row_heights = [_row_emu(default_row)] * 80
    for row in root.findall(f"{ns}sheetData/{ns}row"):
        index = int(row.attrib.get("r") or 1) - 1
        if "ht" in row.attrib and 0 <= index < len(row_heights):
            row_heights[index] = _row_emu(float(row.attrib["ht"]))
    wells: list[tuple[int, int, int, int]] = []
    for merge in root.findall(f"{ns}mergeCells/{ns}mergeCell"):
        ref = merge.attrib.get("ref") or ""
        found = re.match(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", ref)
        if not found:
            continue
        min_col = column_index_from_string(found.group(1)) - 1
        min_row = int(found.group(2)) - 1
        max_col = column_index_from_string(found.group(3)) - 1
        max_row = int(found.group(4)) - 1
        if max_row - min_row < 3 or max_col - min_col < 2:
            continue
        if min_row < 4 or max_row > 24 or max_col - min_col > 12:
            continue
        wells.append((min_col, min_row, max_col, max_row))
    return [_width_emu(width) for width in col_widths], row_heights, wells


def _seat_blown_pictures(
    raw: bytes,
    images: dict[str, bytes],
    col_sizes: list[int],
    row_sizes: list[int],
    wells: list[tuple[int, int, int, int]],
) -> bytes:
    """被按像素撑开的图放进它盖住的图片格，按原图比例，不压到表头文字上。"""
    if not wells:
        return raw
    text = raw.decode("utf-8")
    col_at = _origins(col_sizes)
    row_at = _origins(row_sizes)

    def one(block: str) -> str:
        embed = re.search(r'r:embed="([^"]+)"', block)
        ext = re.search(r'(<(?:[\w]+:)?ext cx=")(\d+)(" cy=")(\d+)(")', block)
        off = re.search(r'(<(?:[\w]+:)?off x=")(\d+)(" y=")(\d+)(")', block)
        if embed is None or ext is None or off is None or embed.group(1) not in images:
            return block
        size = _png_size(images[embed.group(1)])
        if size is None or size[1] <= 0:
            return block
        cx, cy = int(ext.group(2)), int(ext.group(4))
        native_cx = size[0] * 9525
        native_cy = size[1] * 9525
        rows = [int(item) for item in re.findall(r"<(?:[\w]+:)?row>(\d+)</(?:[\w]+:)?row>", block)]
        cols = [int(item) for item in re.findall(r"<(?:[\w]+:)?col>(\d+)</(?:[\w]+:)?col>", block)]
        if len(rows) < 2 or len(cols) < 2 or rows[1] - rows[0] < 8:
            return block
        home = next((well for well in wells if well[0] <= cols[0] <= well[2]), None)
        if home is None:
            return block
        min_col, min_row, max_col, max_row = home
        if max_col + 1 >= len(col_at) or max_row + 1 >= len(row_at):
            return block
        well_w = col_at[max_col + 1] - col_at[min_col]
        well_h = row_at[max_row + 1] - row_at[min_row]
        if well_w <= 0 or well_h <= 0:
            return block
        near_native = (
            abs(cx - native_cx) / native_cx <= 0.15 and abs(cy - native_cy) / native_cy <= 0.15
        )
        if not near_native and cy <= well_h * 1.2 and cx <= well_w * 1.2:
            return block
        box_w = int(well_w * 0.9)
        box_h = int(well_h * 0.9)
        aspect = size[0] / size[1]
        if box_w / box_h > aspect:
            box_w = max(1, int(box_h * aspect))
        else:
            box_h = max(1, int(box_w / aspect))
        left = col_at[min_col] + max(0, (well_w - box_w) // 2)
        top = row_at[min_row] + max(0, (well_h - box_h) // 2)
        from_col, from_off = _marker_at(col_at, left)
        from_row, from_row_off = _marker_at(row_at, top)
        to_col, to_off = _marker_at(col_at, left + box_w)
        to_row, to_row_off = _marker_at(row_at, top + box_h)

        def marker(tag: str, col: int, col_off: int, row: int, row_off: int) -> str:
            prefix = "xdr:" if f"<xdr:{tag}>" in block else ""
            return (
                f"<{prefix}{tag}>"
                f"<{prefix}col>{col}</{prefix}col><{prefix}colOff>{col_off}</{prefix}colOff>"
                f"<{prefix}row>{row}</{prefix}row><{prefix}rowOff>{row_off}</{prefix}rowOff>"
                f"</{prefix}{tag}>"
            )

        block = re.sub(
            r"<(?:[\w]+:)?from>.*?</(?:[\w]+:)?from>",
            lambda _match: marker("from", from_col, from_off, from_row, from_row_off),
            block,
            count=1,
            flags=re.S,
        )
        block = re.sub(
            r"<(?:[\w]+:)?to>.*?</(?:[\w]+:)?to>",
            lambda _match: marker("to", to_col, to_off, to_row, to_row_off),
            block,
            count=1,
            flags=re.S,
        )
        off_now = re.search(r'(<(?:[\w]+:)?off x=")(\d+)(" y=")(\d+)(")', block)
        if off_now is None:
            return block
        block = (
            block[: off_now.start()]
            + off_now.group(1) + str(left) + off_now.group(3) + str(top) + off_now.group(5)
            + block[off_now.end():]
        )
        ext_now = re.search(r'(<(?:[\w]+:)?ext cx=")(\d+)(" cy=")(\d+)(")', block)
        if ext_now is None:
            return block
        return (
            block[: ext_now.start()]
            + ext_now.group(1) + str(box_w) + ext_now.group(3) + str(box_h) + ext_now.group(5)
            + block[ext_now.end():]
        )

    return re.sub(
        r"<(?:[\w]+:)?twoCellAnchor\b.*?</(?:[\w]+:)?twoCellAnchor>",
        lambda match: one(match.group(0)),
        text,
        flags=re.S,
    ).encode("utf-8")


def _embed_images(rels: bytes, media: dict[str, bytes], drawing_path: str) -> dict[str, bytes]:
    if not rels:
        return {}
    from xml.etree import ElementTree as ET

    found: dict[str, bytes] = {}
    for item in ET.fromstring(rels):
        if not item.attrib.get("Type", "").endswith("/image"):
            continue
        target = item.attrib.get("Target", "")
        rid = item.attrib.get("Id", "")
        if not target or not rid:
            continue
        blob = media.get(_zip_join(drawing_path, target))
        if blob:
            found[rid] = blob
    return found


_COL_ATTRS = (
    "min",
    "max",
    "width",
    "style",
    "hidden",
    "bestFit",
    "customWidth",
    "phonetic",
    "outlineLevel",
    "collapsed",
)


def _normalize_cols(text: str) -> str:
    """列宽按 min、max、width 的顺序写。WPS 读不到倒序的列宽时，会把图拉到默认列宽上。"""

    def rewrite(match: re.Match[str]) -> str:
        parsed: list[dict[str, str]] = []
        for attrs in re.findall(r"<col\b([^/]*)/>", match.group(1)):
            found = dict(re.findall(r'([\w:]+)="([^"]*)"', attrs))
            if "min" in found:
                parsed.append(found)
        kept: list[dict[str, str]] = []
        for item in parsed:
            start = int(item["min"])
            end = int(item.get("max") or item["min"])
            contained = False
            for prev in kept:
                prev_start = int(prev["min"])
                prev_end = int(prev.get("max") or prev["min"])
                same_span = (start, end) == (prev_start, prev_end)
                if (
                    not same_span
                    and prev_start <= start
                    and end <= prev_end
                    and prev.get("width") == item.get("width")
                ):
                    contained = True
                    break
            if not contained:
                kept.append(item)
        parts: list[str] = []
        for item in kept:
            bits = [f'{key}="{item[key]}"' for key in _COL_ATTRS if item.get(key)]
            bits.extend(
                f'{key}="{value}"' for key, value in item.items() if key not in _COL_ATTRS and value
            )
            parts.append("<col " + " ".join(bits) + "/>")
        return "<cols>" + "".join(parts) + "</cols>"

    return re.sub(r"<cols>(.*?)</cols>", rewrite, text, count=1, flags=re.S)


def _normalize_sheet_geometry(raw: bytes) -> bytes:
    text = _normalize_cols(raw.decode("utf-8"))
    text = re.sub(r'\sbaseColWidth="[^"]*"', "", text, count=1)
    return text.encode("utf-8")


def _shift_drawing_rows(raw: bytes) -> bytes:
    """原表下移一行后，图纸行号加 1。列号、偏移和 a:ext 不动，避免把图拉开。"""
    text = raw.decode("utf-8")
    text = re.sub(
        r"(<(?:xdr:)?row>)(\d+)(</(?:xdr:)?row>)",
        lambda match: f"{match.group(1)}{int(match.group(2)) + 1}{match.group(3)}",
        text,
    )
    return text.encode("utf-8")


def _shift_face_rows(face: dict[str, object]) -> None:
    rows = face.get("rows")
    if not isinstance(rows, dict):
        return
    face["rows"] = {str(int(key) + 1): value for key, value in rows.items()}


def _shift_drawing_xml(raw: bytes, emu: int) -> bytes:
    text = raw.decode("utf-8")
    text = re.sub(
        r"(<(?:[\w]+:)?col>)(\d+)(</(?:[\w]+:)?col>)",
        lambda match: f"{match.group(1)}{int(match.group(2)) + 1}{match.group(3)}",
        text,
    )
    text = re.sub(
        r'(<a:off x=")(\d+)(")',
        lambda match: f"{match.group(1)}{int(match.group(2)) + emu}{match.group(3)}",
        text,
    )
    return text.encode("utf-8")


def _zip_join(base: str, target: str) -> str:
    """图纸关系里的相对路径，收成压缩包内的路径。"""
    if target.startswith("/"):
        return target.lstrip("/")
    parts: list[str] = []
    for part in (*Path(base).parent.parts, *Path(target).parts):
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _capture_original_drawings(
    path: Path, names: set[str] | None = None
) -> dict[str, tuple[bytes, bytes, dict[str, bytes]]]:
    """保存前记下原图纸和它引用的图片。openpyxl 保存时会按像素重算锚点，并给图片重新编号。"""
    import zipfile
    from xml.etree import ElementTree as ET

    captured: dict[str, tuple[bytes, bytes, dict[str, bytes]]] = {}
    with zipfile.ZipFile(path, "r") as source:
        for name, drawing_path in _zip_drawing_map(source).items():
            if names is not None and name not in names:
                continue
            if drawing_path not in source.namelist():
                continue
            rels_path = str(Path(drawing_path).parent / "_rels" / (Path(drawing_path).name + ".rels"))
            rels = source.read(rels_path) if rels_path in source.namelist() else b""
            media: dict[str, bytes] = {}
            if rels:
                for item in ET.fromstring(rels):
                    if not item.attrib.get("Type", "").endswith("/image"):
                        continue
                    target = item.attrib.get("Target", "")
                    if not target:
                        continue
                    media_path = _zip_join(drawing_path, target)
                    if media_path in source.namelist():
                        media[media_path] = source.read(media_path)
            captured[name] = (source.read(drawing_path), rels, media)
    return captured


def _sheet_xml(payload: dict[str, bytes], sheet_name: str) -> bytes | None:
    from xml.etree import ElementTree as ET

    book = payload.get("xl/workbook.xml")
    rels = payload.get("xl/_rels/workbook.xml.rels")
    if not book or not rels:
        return None
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in ET.fromstring(rels)}
    root = ET.fromstring(book)
    for sheet in root.findall(f"{{{main}}}sheets/{{{main}}}sheet"):
        if sheet.attrib.get("name") != sheet_name:
            continue
        target = targets.get(sheet.attrib.get(f"{{{rel_ns}}}id", ""), "")
        path = target.lstrip("/")
        if path.startswith("xl/"):
            return payload.get(path)
        return payload.get("xl/" + path)
    return None


def _sheet_paths_from_bytes(book: bytes, rels: bytes) -> dict[str, str]:
    from xml.etree import ElementTree as ET

    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in ET.fromstring(rels)}
    found: dict[str, str] = {}
    for sheet in ET.fromstring(book).findall(f"{{{main}}}sheets/{{{main}}}sheet"):
        target = targets.get(sheet.attrib.get(f"{{{rel_ns}}}id", ""), "").lstrip("/")
        if not target:
            continue
        if not target.startswith("xl/"):
            target = "xl/" + target
        found[sheet.attrib.get("name", "")] = target
    return found


def _related_parts(source: "zipfile.ZipFile", part: str) -> dict[str, bytes]:
    """带上这个部件自己的关系，以及关系指向的文件。"""
    from xml.etree import ElementTree as ET

    found: dict[str, bytes] = {}

    def walk(path: str) -> None:
        if path in found or path not in source.namelist():
            return
        found[path] = source.read(path)
        rels_path = str(Path(path).parent / "_rels" / (Path(path).name + ".rels"))
        if rels_path not in source.namelist():
            return
        found[rels_path] = source.read(rels_path)
        for item in ET.fromstring(found[rels_path]):
            target = item.attrib.get("Target", "")
            if target:
                walk(_zip_join(path, target))

    walk(part)
    return found


def _grab_xml(text: str, pattern: str) -> str:
    found = re.search(pattern, text, re.S)
    return found.group(0) if found else ""


def _capture_sheet_faces(path: Path) -> dict[str, dict[str, object]]:
    """有图的表记下客户原来的列宽、视图，以及底部附件。保存会把这些丢掉。"""
    import zipfile
    from xml.etree import ElementTree as ET

    faces: dict[str, dict[str, object]] = {}
    with zipfile.ZipFile(path, "r") as source:
        sheets = _sheet_paths_from_bytes(
            source.read("xl/workbook.xml"),
            source.read("xl/_rels/workbook.xml.rels"),
        )
        for name in _zip_drawing_map(source):
            sheet_path = sheets.get(name)
            if not sheet_path or sheet_path not in source.namelist():
                continue
            xml = source.read(sheet_path).decode("utf-8")
            rel_path = str(Path(sheet_path).parent / "_rels" / (Path(sheet_path).name + ".rels"))
            extras: list[dict[str, object]] = []
            if rel_path in source.namelist():
                for item in ET.fromstring(source.read(rel_path)):
                    kind = item.attrib.get("Type", "")
                    if kind.endswith("/drawing"):
                        continue
                    target = item.attrib.get("Target", "")
                    if not target:
                        continue
                    part = target.lstrip("/") if target.startswith("/") else _zip_join(sheet_path, target)
                    extras.append(
                        {
                            "id": item.attrib.get("Id", ""),
                            "type": kind,
                            "target": target,
                            "parts": _related_parts(source, part),
                        }
                    )
            faces[name] = {
                "cols": _grab_xml(xml, r"<cols\b.*?</cols>"),
                "format": _grab_xml(xml, r"<sheetFormatPr\b[^>]*/>"),
                "views": _grab_xml(xml, r"<sheetViews\b.*?</sheetViews>"),
                "legacy": _grab_xml(xml, r"<legacyDrawing\b[^>]*/>"),
                "picture": _grab_xml(xml, r"<picture\b[^>]*/>"),
                "ole": _grab_xml(xml, r"<oleObjects\b.*?</oleObjects>"),
                "rows": _row_height_attrs(xml),
                "page": _grab_xml(xml, r"<pageSetup\b[^>]*/>"),
                "sheetPr": _grab_xml(xml, r"<sheetPr\b.*?</sheetPr>"),
                "extras": extras,
            }
    return faces


def _col_records(fragment: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for raw in re.findall(r"<col\b[^>]*/>", fragment):
        attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', raw))
        if "min" not in attrs:
            continue
        attrs["_raw"] = raw
        records.append(attrs)
    return records


def _summary_col_tag(item: dict[str, str]) -> str:
    bits = [f'{key}="{item[key]}"' for key in _COL_ATTRS if item.get(key)]
    return "<col " + " ".join(bits) + "/>"


def _extend_cols(original: str, saved: str) -> str:
    """原表列宽原样留下。小结列只加在这些列的右边。"""
    if not original:
        return saved
    orig = _col_records(original)
    if not orig:
        return original
    body: list[str] = []
    tail = ""
    last = 0
    for item in orig:
        end = int(item.get("max") or item["min"])
        if end >= 1000:
            tail = item["_raw"]
            continue
        last = max(last, end)
        body.append(item["_raw"])
    extras: list[str] = []
    extra_end = last
    for item in _col_records(saved):
        start = int(item["min"])
        end = int(item.get("max") or item["min"])
        if end >= 1000 or start <= last:
            continue
        extras.append(_summary_col_tag(item))
        extra_end = max(extra_end, end)
    if not extras:
        return original
    if tail:
        tail = re.sub(r'\bmin="\d+"', f'min="{extra_end + 1}"', tail, count=1)
    return "<cols>" + "".join(body) + "".join(extras) + tail + "</cols>"


def _swap_xml(text: str, name: str, replacement: str, *, pair: bool) -> str:
    if not replacement:
        return text
    pattern = rf"<{name}\b.*?</{name}>" if pair else rf"<{name}\b[^>]*/>"
    if re.search(pattern, text, re.S):
        return re.sub(pattern, lambda _match: replacement, text, count=1, flags=re.S)
    end = text.find(">", text.find("<worksheet")) + 1
    return text[:end] + replacement + text[end:]


_SHEET_NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "x14": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "x14ac": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac",
}


def _ensure_sheet_ns(text: str) -> str:
    start = text.find("<worksheet")
    end = text.find(">", start)
    tag = text[start:end]
    extra = ""
    for prefix, uri in _SHEET_NS.items():
        if f"xmlns:{prefix}=" not in tag:
            extra += f' xmlns:{prefix}="{uri}"'
    if "mc:Ignorable=" not in tag:
        extra += ' mc:Ignorable="x14ac"'
    return text[:end] + extra + text[end:]


def _append_sheet_rels(rels: bytes, extras: list[dict[str, object]]) -> tuple[bytes, dict[str, str]]:
    text = rels.decode("utf-8") if rels else (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>'
    )
    used = set(re.findall(r'Id="(rId\d+)"', text))
    mapping: dict[str, str] = {}
    chunks: list[str] = []
    number = 200
    for extra in extras:
        old = str(extra.get("id") or "")
        if not old or not extra.get("parts"):
            continue
        number += 1
        while f"rId{number}" in used:
            number += 1
        new = f"rId{number}"
        used.add(new)
        mapping[old] = new
        chunks.append(
            f'<Relationship Id="{new}" Type="{extra["type"]}" Target="{extra["target"]}"/>'
        )
    if chunks:
        text = text.replace("</Relationships>", "".join(chunks) + "</Relationships>")
    return text.encode("utf-8"), mapping


def _remap_rid(fragment: str, mapping: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        old = match.group(1)
        return f'r:id="{mapping.get(old, old)}"'

    return re.sub(r'r:id="(rId\d+)"', replace, fragment)


def _ensure_content_types(payload: dict[str, bytes]) -> None:
    raw = payload.get("[Content_Types].xml")
    if not raw:
        return
    text = raw.decode("utf-8")
    defaults = {
        "vml": "application/vnd.openxmlformats-officedocument.vmlDrawing",
        "emf": "image/x-emf",
        "bin": "application/vnd.openxmlformats-officedocument.spreadsheetml.printerSettings",
    }
    insert = ""
    for ext, ctype in defaults.items():
        if any(name.endswith("." + ext) for name in payload) and f'Extension="{ext}"' not in text:
            insert += f'<Default Extension="{ext}" ContentType="{ctype}"/>'
    for name in payload:
        if "/embeddings/oleObject" not in name:
            continue
        part = "/" + name
        if part not in text:
            insert += (
                f'<Override PartName="{part}" '
                'ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>'
            )
    if insert:
        payload["[Content_Types].xml"] = text.replace("</Types>", insert + "</Types>").encode("utf-8")


def _row_height_attrs(xml: str) -> dict[str, dict[str, str]]:
    """原表每一行有没有写死行高。没写就记成空，保存后不能补上一份更高的行高。"""
    found: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"<row\b([^>]*)>", xml):
        attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', match.group(1)))
        number = attrs.get("r")
        if not number:
            continue
        found[number] = {
            key: attrs[key]
            for key in ("ht", "customHeight", "thickBot", "spans", "x14ac:dyDescent")
            if key in attrs
        }
    return found


def _restore_row_heights(text: str, rows: dict, default_height: float | None = None) -> str:
    def repl(match: re.Match[str]) -> str:
        body = match.group(1)
        attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', body))
        number = attrs.get("r")
        if number not in rows:
            return match.group(0)
        body = re.sub(
            r'\s(?:ht|customHeight|thickBot|spans|x14ac:dyDescent)="[^"]*"',
            "",
            body,
        )
        kept = dict(rows[number])
        if "ht" not in kept and default_height is not None:
            kept["ht"] = str(default_height)
            kept["customHeight"] = "1"
        extra = "".join(
            f' {key}="{kept[key]}"'
            for key in ("spans", "ht", "customHeight", "thickBot", "x14ac:dyDescent")
            if key in kept
        )
        return f"<row{body}{extra}>"

    return re.sub(r"<row\b([^>]*)>", repl, text)


def _restore_sheet_face(payload: dict[str, bytes], sheet_path: str, face: dict[str, object]) -> None:
    text = payload[sheet_path].decode("utf-8")
    saved_cols = _grab_xml(text, r"<cols\b.*?</cols>")
    text = _swap_xml(text, "cols", _extend_cols(str(face.get("cols") or ""), saved_cols), pair=True)
    text = _swap_xml(text, "sheetFormatPr", str(face.get("format") or ""), pair=False)
    text = _swap_xml(text, "sheetViews", str(face.get("views") or ""), pair=True)
    rel_path = str(Path(sheet_path).parent / "_rels" / (Path(sheet_path).name + ".rels"))
    rels, mapping = _append_sheet_rels(payload.get(rel_path, b""), list(face.get("extras") or []))
    payload[rel_path] = rels
    for extra in list(face.get("extras") or []):
        for part, blob in dict(extra.get("parts") or {}).items():
            payload[str(part)] = blob
    fragments = [
        _remap_rid(str(face[key]), mapping)
        for key in ("legacy", "picture", "ole")
        if face.get(key)
    ]
    if fragments and "<legacyDrawing" not in text and "<oleObjects" not in text:
        text = _ensure_sheet_ns(text)
        text = text.replace("</worksheet>", "".join(fragments) + "</worksheet>")
    elif "x14ac:" in text:
        text = _ensure_sheet_ns(text)
    # 分页预览会把这一页拉满，并印上「第 N 页」。图的大小由原来的两个格子决定，打开用普通视图。
    def _from_top(match: re.Match[str]) -> str:
        block = match.group(0)
        if 'view="' in block:
            block = re.sub(r'view="[^"]*"', 'view="normal"', block)
        elif "<sheetView " in block:
            block = block.replace("<sheetView ", '<sheetView view="normal" ', 1)
        if 'topLeftCell="' in block:
            block = re.sub(r'topLeftCell="[^"]*"', 'topLeftCell="A1"', block)
        elif "<sheetView " in block:
            block = block.replace("<sheetView ", '<sheetView topLeftCell="A1" ', 1)
        block = re.sub(r'activeCell="[^"]*"', 'activeCell="A1"', block)
        return re.sub(r'sqref="[^"]*"', 'sqref="A1"', block)

    text = re.sub(r"<sheetViews\b.*?</sheetViews>", _from_top, text, count=1, flags=re.S)
    setup = _remap_rid(str(face.get("page") or ""), mapping)
    if setup:
        text = _swap_xml(text, "pageSetup", setup, pair=False)
    if not face.get("sheetPr"):
        text = re.sub(r"<sheetPr\b.*?</sheetPr>", "", text, count=1, flags=re.S)
    rows = face.get("rows")
    if isinstance(rows, dict):
        default_height = None
        fmt = str(face.get("format") or "")
        found = re.search(r'defaultRowHeight="([0-9.]+)"', fmt)
        if found:
            default_height = float(found.group(1))
        text = _restore_row_heights(text, rows, default_height)
    payload[sheet_path] = text.encode("utf-8")


def _install_shifted_drawings(
    path: Path,
    originals: dict[str, tuple[bytes, bytes, dict[str, bytes]]],
    faces: dict[str, dict[str, object]],
    note_rows: set[str] | None = None,
) -> None:
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(path, "r") as source:
        drawing_of = _zip_drawing_map(source)
        payload = {item.filename: source.read(item.filename) for item in source.infolist()}
        infos = {item.filename: item for item in source.infolist()}
    moved = note_rows or set()
    for name, (raw, rels, media) in originals.items():
        drawing_path = drawing_of.get(name)
        if not drawing_path:
            continue
        # 列号、偏移和缩放保持客户原样。插过备注行的表，行号跟着原表下移一格。
        if name in moved:
            raw = _shift_drawing_rows(raw)
        payload[drawing_path] = raw
        if rels:
            rels_path = str(Path(drawing_path).parent / "_rels" / (Path(drawing_path).name + ".rels"))
            payload[rels_path] = rels
        for media_path, blob in media.items():
            # 保存会按出现顺序重排图片文件。关系仍指向原文件名，必须写回原字节，不能留着重排后的内容。
            payload[media_path] = blob
    book = payload.get("xl/workbook.xml")
    book_rels = payload.get("xl/_rels/workbook.xml.rels")
    sheets = _sheet_paths_from_bytes(book, book_rels) if book and book_rels else {}
    for name, face in faces.items():
        sheet_path = sheets.get(name)
        if sheet_path and sheet_path in payload:
            if name in moved:
                _shift_face_rows(face)
            _restore_sheet_face(payload, sheet_path, face)
    _ensure_content_types(payload)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for filename, data in payload.items():
            info = infos.get(filename)
            if info is None:
                info = zipfile.ZipInfo(filename)
                info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
    path.write_bytes(buffer.getvalue())


def build_icd(
    current: Path,
    dest: Path,
    previous: Path | None = None,
    ask: Callable[[list[dict[str, str]]], str] | None = None,
) -> IcdResult:
    current_book = read_icd(current)
    previous_book = read_icd(previous) if previous is not None else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(current, dest)
    book = load_workbook(dest)
    originals: dict[str, tuple[bytes, bytes, dict[str, bytes]]] = {}
    changes: list[IcdChange] = []
    note_rows: set[str] = set()
    saved = False
    try:
        changes = write_icd_review(book, current_book, previous_book, ask=ask)
        originals = _capture_original_drawings(dest)
        faces = _capture_sheet_faces(dest)
        note_rows = set(getattr(book, "_icd_note_rows", ()) or ())
        book.save(dest)
        saved = True
    finally:
        book.close()
    if saved and originals:
        _install_shifted_drawings(dest, originals, faces, note_rows)
    return IcdResult(dest, len(current_book.pins), len(current_book.parts), len(current_book.hv), len(changes))


def icd_file_name(day: date | None = None, now: datetime | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y%m%d")
    clock = (now or datetime.now()).strftime("%H%M%S")
    return f"ICD引脚清单-{stamp}-{clock}.xlsx"
