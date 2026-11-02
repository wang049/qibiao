"""按甲方确认的 CE BOM 表格式，从当份物料手册抽出尺寸和重量。

表头和列序跟模板走。格子里的字只来自手册原文，不换算单位，不用经验值补空。
同一物料规格出现多个值、单位和模板不一致、或手册没写的，CE BOM 留空，核验记录标成待确认。
完整度和取值一致性只记实测计数，不设通过阈值。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

_UNIT_IN_HEADER = re.compile(r"[（(\[]\s*([A-Za-zμµ]+)\s*[）)\]]")
_VALUE_UNIT = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([A-Za-zμµ]+)?\s*$")

_ALIASES = {
    "material": ("物料名称", "器件名称", "零件名称", "品名", "物料", "material", "partname", "component"),
    "spec": ("规格型号", "物料编码", "订货号", "料号", "规格", "型号", "spec", "mpn", "partnumber"),
    "length": ("长度", "长", "length"),
    "width": ("宽度", "宽", "width"),
    "height": ("高度", "厚度", "高", "厚", "height", "thickness"),
    "weight": ("重量", "质量", "weight", "mass"),
}
_ALIAS_OF = {alias: key for key, names in _ALIASES.items() for alias in names}


@dataclass(frozen=True)
class TemplateColumn:
    header: str
    key: str
    unit: str


@dataclass(frozen=True)
class Observation:
    material: str
    spec: str
    key: str
    value: str
    unit: str
    source: str
    place: str


@dataclass
class CeBomResult:
    path: Path
    rows: int
    filled: int
    blank: int
    conflicts: int
    mapping: list[tuple[str, str, str]] = field(default_factory=list)


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").replace("\n", " ").strip()
    return re.sub(r" +", " ", text)


def _norm_unit(unit: str) -> str:
    return unit.replace("µ", "μ").lower()


def _split_header(header: str) -> tuple[str, str]:
    unit = ""
    matched = _UNIT_IN_HEADER.search(header)
    if matched:
        unit = _norm_unit(matched.group(1))
    name = _UNIT_IN_HEADER.sub("", header)
    name = re.sub(r"\s+", "", name).lower()
    return name, unit


def _field_key(header: str) -> tuple[str, str]:
    name, unit = _split_header(header)
    if not name:
        return "", unit
    if name in _ALIAS_OF:
        return _ALIAS_OF[name], unit
    if name in {"l", "w", "h"}:
        return {"l": "length", "w": "width", "h": "height"}[name], unit
    return "col:" + name, unit


def _value_unit(value: str) -> str:
    matched = _VALUE_UNIT.match(value.replace(" ", ""))
    if not matched or not matched.group(2):
        return ""
    return _norm_unit(matched.group(2))


def _sheet_rows(ws: Worksheet) -> list[list[str]]:
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
            values.append(_text(raw))
        found.append(values)
    return found


def _header_index(rows: list[list[str]]) -> int:
    best = 0
    best_score = -1
    for index, row in enumerate(rows[:20]):
        score = sum(1 for cell in row if _field_key(cell)[0])
        if score > best_score:
            best, best_score = index, score
    if best_score > 0:
        return best
    for index, row in enumerate(rows[:20]):
        if sum(1 for cell in row if cell) >= 2:
            return index
    return 0


def _template_columns(path: Path) -> list[TemplateColumn]:
    book = load_workbook(path, data_only=False)
    try:
        ws = book[book.sheetnames[0]]
        rows = _sheet_rows(ws)
    finally:
        book.close()
    if not rows or not any(any(cell for cell in row) for row in rows):
        raise ValueError("CE BOM 模板是空的。")
    header = rows[_header_index(rows)]
    columns: list[TemplateColumn] = []
    seen: set[str] = set()
    for cell in header:
        if not cell or cell in seen:
            continue
        seen.add(cell)
        key, unit = _field_key(cell)
        if not key:
            continue
        columns.append(TemplateColumn(cell, key, unit))
    if not columns:
        raise ValueError("CE BOM 模板没有读到表头。")
    return columns


def _observations_from_table(rows: list[list[str]], source: str, place: str) -> list[Observation]:
    if not rows:
        return []
    header_at = _header_index(rows)
    header = rows[header_at]
    columns: list[tuple[int, str]] = []
    material_at = -1
    spec_at = -1
    for index, cell in enumerate(header):
        key, _unit = _field_key(cell)
        if not key:
            continue
        if key == "material" and material_at < 0:
            material_at = index
        elif key == "spec" and spec_at < 0:
            spec_at = index
        else:
            columns.append((index, key))
    if material_at < 0 and spec_at < 0:
        return []
    found: list[Observation] = []
    for row in rows[header_at + 1:]:
        if not any(row):
            continue
        material = row[material_at] if material_at >= 0 and material_at < len(row) else ""
        spec = row[spec_at] if spec_at >= 0 and spec_at < len(row) else ""
        if not material and spec:
            material, spec = spec, ""
        if not material and not spec:
            continue
        for index, key in columns:
            if key in {"material", "spec"}:
                continue
            if index >= len(row) or not row[index]:
                continue
            found.append(Observation(material, spec, key, row[index], _value_unit(row[index]), source, place))
        if not any(item.material == material and item.spec == spec for item in found):
            found.append(Observation(material, spec, "material", material, "", source, place))
    return found


def _read_excel(path: Path) -> list[Observation]:
    book = load_workbook(path, data_only=False)
    found: list[Observation] = []
    try:
        for name in book.sheetnames:
            found.extend(_observations_from_table(_sheet_rows(book[name]), path.name, name))
    finally:
        book.close()
    return found


def _read_pdf(path: Path) -> list[Observation]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("当前环境读不了 PDF 物料手册。") from exc
    found: list[Observation] = []
    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            for table in tables:
                rows = [[_text(cell) for cell in (row or [])] for row in table]
                found.extend(_observations_from_table(rows, path.name, f"第{index}页"))
    return found


def _read_docx(path: Path) -> list[Observation]:
    from docx import Document

    document = Document(str(path))
    found: list[Observation] = []
    for index, table in enumerate(document.tables, start=1):
        rows = [[_text(cell.text) for cell in row.cells] for row in table.rows]
        found.extend(_observations_from_table(rows, path.name, f"表{index}"))
    return found


def _read_manual(path: Path) -> list[Observation]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_excel(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    raise ValueError(f"{path.name} 不是物料手册。请用 Excel、PDF 或 Word。")


def _style_header(ws: Worksheet, width: int) -> None:
    fill = PatternFill("solid", fgColor="1E3A5F")
    font = Font(name="宋体", bold=True, color="FFFFFF", size=11)
    for cell in ws[1]:
        cell.fill = fill
        cell.font = font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(width, 1))}1"
    ws.row_dimensions[1].height = 22


def _write_sheet(ws: Worksheet, header: tuple[str, ...], rows: list[tuple[str, ...]], widths: tuple[int, ...]) -> None:
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


def build_ce_bom(manuals: list[Path], template: Path, dest: Path) -> CeBomResult:
    columns = _template_columns(template)
    observations: list[Observation] = []
    unread: list[str] = []
    for path in manuals:
        found = _read_manual(path)
        if found:
            observations.extend(found)
        else:
            unread.append(path.name)
    if not observations:
        raise ValueError("物料手册里没有读到可关联的物料和尺寸。")

    order: list[tuple[str, str]] = []
    grouped: dict[tuple[str, str], dict[str, list[Observation]]] = {}
    for item in observations:
        identity = (item.material, item.spec)
        if identity not in grouped:
            grouped[identity] = {}
            order.append(identity)
        grouped[identity].setdefault(item.key, []).append(item)

    bom_rows: list[tuple[str, ...]] = []
    issues: list[tuple[str, str, str, str, str]] = []
    filled = 0
    blank = 0
    conflict_keys: set[tuple[str, str, str]] = set()
    for identity in order:
        material, spec = identity
        values: list[str] = []
        bucket = grouped[identity]
        for column in columns:
            if column.key in {"material", "spec"}:
                values.append(material if column.key == "material" else spec)
                if values[-1]:
                    filled += 1
                else:
                    blank += 1
                    issues.append((material, spec, column.header, "", "信息缺失"))
                continue
            items = bucket.get(column.key) or []
            distinct = []
            for item in items:
                if item.value not in distinct:
                    distinct.append(item.value)
            usable = []
            for item in items:
                source_unit = item.unit
                if column.unit and source_unit and source_unit != column.unit:
                    conflict_keys.add((material, spec, column.header))
                    issues.append((material, spec, column.header, item.value, "单位不一致"))
                    continue
                if item.value not in usable:
                    usable.append(item.value)
            if len(usable) == 1 and (material, spec, column.header) not in conflict_keys:
                values.append(usable[0])
                filled += 1
            else:
                values.append("")
                blank += 1
                if len(usable) > 1:
                    conflict_keys.add((material, spec, column.header))
                    issues.append((material, spec, column.header, "；".join(usable), "多规格"))
                elif not items:
                    issues.append((material, spec, column.header, "", "信息缺失"))
        bom_rows.append(tuple(values))

    by_column: dict[str, list[str]] = {}
    for column in columns:
        if column.key in {"material", "spec"}:
            continue
        seen: list[str] = []
        for item in observations:
            if item.key != column.key:
                continue
            label = f"{item.source} / {item.place} / {item.value}"
            if label not in seen:
                seen.append(label)
        by_column[column.header] = seen

    mapping_rows: list[tuple[str, ...]] = []
    for column in columns:
        places = by_column.get(column.header) or []
        if column.key in {"material", "spec"}:
            note = "按物料或规格关联"
        elif places:
            note = "手册表头与模板栏目对应"
        else:
            note = "手册没有这个栏目，留空"
        mapping_rows.append((column.header, column.key, column.unit, "；".join(places[:8]), note))

    field_stats: list[tuple[str, ...]] = []
    for index, column in enumerate(columns):
        total = len(bom_rows)
        wrote = sum(1 for row in bom_rows if index < len(row) and row[index])
        field_stats.append((column.header, str(total), str(wrote), str(total - wrote), f"{wrote}/{total}"))

    book = Workbook()
    bom = book.active
    bom.title = "CE BOM"
    _write_sheet(bom, tuple(column.header for column in columns), bom_rows, tuple(16 for _ in columns))
    mapping = book.create_sheet("字段映射")
    _write_sheet(mapping, ("模板栏目", "对应", "模板单位", "手册出处", "说明"), mapping_rows, (18, 14, 12, 42, 28))
    check = book.create_sheet("核验记录")
    check_rows: list[tuple[str, ...]] = [("栏目完整度", "", "", "", "")]
    check_rows.extend(field_stats)
    check_rows.append(())
    check_rows.append(("取值记录", "物料", "规格", "栏目", "原文 / 标记"))
    if issues:
        for material, spec, header, value, mark in issues:
            check_rows.append(("", material, spec, header, f"{value}（{mark}）" if value else mark))
    else:
        check_rows.append(("", "", "", "", "同一物料规格下未见多个取值"))
    if unread:
        check_rows.append(())
        check_rows.append(("未读出表格", "", "", "", "；".join(unread)))
    check_rows.append(())
    check_rows.append(("说明", "", "", "", "技术协议第七章未规定完整度或一致性的通过阈值。这里只记录实测计数。"))
    _write_sheet(check, ("记录", "应填", "已填", "空缺", "完整度或标记"), check_rows, (18, 22, 18, 18, 36))
    dest.parent.mkdir(parents=True, exist_ok=True)
    book.save(dest)
    book.close()
    return CeBomResult(dest, len(bom_rows), filled, blank, len(conflict_keys), [(row[0], row[3], row[4]) for row in mapping_rows])


def ce_bom_file_name(day: date | None = None, now: datetime | None = None) -> str:
    stamp = (day or date.today()).strftime("%Y%m%d")
    clock = (now or datetime.now()).strftime("%H%M%S")
    return f"CEBOM-{stamp}-{clock}.xlsx"
