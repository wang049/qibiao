"""按甲方确认的 CE BOM 表格式，从当份物料手册抽出尺寸和重量。

表头和列序跟模板走。格子里的字只来自手册原文，不换算单位，不用经验值补空。
同一物料规格出现多个值、单位和模板不一致、或手册没写的，CE BOM 留空，核验记录标成待确认。
完整度和取值一致性只记实测计数，不设通过阈值。
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.views import Selection
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
    standard: bool = False


DEFAULT_CE_BOM_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "资料"
    / "CE BOM"
    / "3DHT200-CE BOM-V2-20260730.xlsx"
)
DEFAULT_CE_BOM_NAME_RULES = (
    Path(__file__).resolve().parents[2]
    / "资料"
    / "CE BOM"
    / "CE BOM 器件中文名称对应规则示例_20261110.xlsx"
)


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


def _compact_name(header: str) -> str:
    name, _unit = _split_header(header)
    return name


def _is_size_header(header: str) -> bool:
    return "产品尺寸" in _compact_name(header)


def _is_weight_header(header: str) -> bool:
    return "产品净重" in _compact_name(header)


@dataclass(frozen=True)
class StandardLayout:
    sheet: str
    header_row: int
    sub_row: int
    data_start: int
    axes: dict[str, int]
    weight_col: int
    name_col: int


def _find_standard_layout(path: Path) -> StandardLayout | None:
    book = load_workbook(path, data_only=False)
    try:
        for name in book.sheetnames:
            rows = _sheet_rows(book[name])
            for index, row in enumerate(rows):
                if index + 1 >= len(rows):
                    continue
                size_at = [col for col, cell in enumerate(row) if _is_size_header(cell)]
                weight_at = [col for col, cell in enumerate(row) if _is_weight_header(cell)]
                if not size_at or not weight_at:
                    continue
                nxt = rows[index + 1]
                axes: dict[str, int] = {}
                for col in range(size_at[0], min(size_at[0] + 6, len(nxt))):
                    label = nxt[col].strip().upper()
                    if label in {"X", "Y", "Z"} and label not in axes:
                        axes[label] = col
                if set(axes) != {"X", "Y", "Z"}:
                    continue
                name_col = next((col for col, cell in enumerate(row) if "零件中文名称" in _compact_name(cell)), -1)
                return StandardLayout(
                    name,
                    index + 1,
                    index + 2,
                    index + 3,
                    axes,
                    weight_at[0] + 1,
                    name_col + 1,
                )
    finally:
        book.close()
    return None


def _cell_is_formula(value: object) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _standard_fields(header: list[str], sub: list[str]) -> dict[str, list[int]]:
    """标准表上已经能对上的列。对不上的列不猜。"""
    fields = {key: [] for key in ("序号", "级别", "名称", "零件号", "图片", "用量", "厚度", "原材料", "规格型号")}
    width = max(len(header), len(sub))
    for col in range(width):
        top = header[col] if col < len(header) else ""
        below = sub[col] if col < len(sub) else ""
        label = _compact_name(top or below)
        if "零件中文名称" in label:
            fields["名称"].append(col)
        elif "零件号" in label:
            fields["零件号"].append(col)
        elif "序号" in label:
            fields["序号"].append(col)
        elif "级别" in label:
            fields["级别"].append(col)
        elif "图片" in label:
            fields["图片"].append(col)
        elif label == "用量" or label.endswith("用量"):
            fields["用量"].append(col)
        elif "材料厚度" in label:
            fields["厚度"].append(col)
        elif "原材料" in label and "标准" not in label:
            fields["原材料"].append(col)
        elif label == "规格型号":
            fields["规格型号"].append(col)
    return fields


def _column_rule(col: int, layout: StandardLayout, fields: dict[str, list[int]]) -> tuple[str, str, str]:
    if col in fields["序号"]:
        return "序号", "", "必填。空则记入核验，不补造"
    if col in fields["级别"]:
        return "级别", "", "必填。空则记入核验，不补造"
    if col in fields["名称"]:
        return "零件中文名称", "", "必填。空则记入核验，不补造"
    if col in fields["用量"]:
        return "用量", "", "必填。空则记入核验，不补造"
    if col in fields["零件号"]:
        return "零件号", "", "有则填。空着不补"
    if col in fields["图片"]:
        return "图片", "", "暂不处理"
    if col == layout.axes["X"]:
        return "尺寸X", "mm", "电子件可不填，结构件必填。结构件没有外形尺寸时记入核验，不从标注里取"
    if col == layout.axes["Y"]:
        return "尺寸Y", "mm", "电子件可不填，结构件必填。结构件没有外形尺寸时记入核验，不从标注里取"
    if col == layout.axes["Z"]:
        return "尺寸Z", "mm", "电子件可不填，结构件必填。结构件没有外形尺寸时记入核验，不从标注里取"
    if col == layout.weight_col - 1:
        return "净重", "g", "结构件必填，按体积×密度。体积或密度未给定时不计算。图纸质量栏带 g 的写入，没有单位的不写入。电子件可不填"
    if col in fields["厚度"]:
        return "材料厚度", "", "仅盖板类必填。名称含盖板且图纸没有板料厚度时记入核验，不补造"
    if col in fields["原材料"]:
        return "原材料", "", "结构件必填。材料标记有值则写入，没有则记入核验。电子件可不填"
    if col in fields.get("规格型号", []):
        return "规格型号", "", "EDF 的 Design Item ID 写入。没有则写 Value。不当作零件号，也不当作产品尺寸"
    return "未指定", "", "填写规则未到，不写入"


def read_name_rules(path: Path) -> dict[str, str]:
    """Type 到零件中文名称。各页都读。同一 Type 多行时用第一次写出的类型。"""
    if not path.is_file():
        return {}
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        found: dict[str, str] = {}
        for ws in book.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header = [_text(cell).casefold() for cell in rows[0]]
            type_at = next((index for index, label in enumerate(header) if label == "type"), None)
            name_at = next((index for index, label in enumerate(header) if label in {"类型", "中文名称"}), None)
            if type_at is None or name_at is None:
                continue
            for row in rows[1:]:
                kind = _text(row[type_at]) if type_at < len(row) else ""
                name = _text(row[name_at]) if name_at < len(row) else ""
                if not kind or not name or kind in {"*", "type"} or name == "（未定义）":
                    continue
                found.setdefault(kind.casefold(), name)
        return found
    finally:
        book.close()


@dataclass(frozen=True)
class AdBomLine:
    kind: str
    quantity: str
    part_no: str
    spec: str = ""


def read_ad_bom(path: Path) -> list[AdBomLine] | None:
    """Altium 导出的 BOM。表头含 Type 和 Quantity 才认。不是这种表则返回 None。"""
    if path.suffix.lower() not in {".xlsx", ".xlsm"} or not path.is_file():
        return None
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = book[book.sheetnames[0]]
        header: list[str] = []
        header_at = -1
        for index, row in enumerate(ws.iter_rows(max_row=8, max_col=20, values_only=True)):
            labels = [_text(cell) for cell in row]
            folded = [label.casefold() for label in labels]
            if "type" in folded and "quantity" in folded:
                header = labels
                header_at = index
                break
        if header_at < 0:
            return None
        folded = [label.casefold() for label in header]
        type_at = folded.index("type")
        qty_at = folded.index("quantity")
        pn_at = folded.index("manufacture pn") if "manufacture pn" in folded else -1
        fitted_at = folded.index("fitted") if "fitted" in folded else -1
        spec_at = folded.index("comment") if "comment" in folded else -1
        lines: list[AdBomLine] = []
        for row in ws.iter_rows(min_row=header_at + 2, max_col=len(header), values_only=True):
            cells = [_text(cell) for cell in row]
            if not any(cells):
                continue
            if fitted_at >= 0 and fitted_at < len(cells) and cells[fitted_at] and cells[fitted_at].casefold() != "fitted":
                continue
            kind = cells[type_at] if type_at < len(cells) else ""
            if not kind:
                continue
            lines.append(
                AdBomLine(
                    kind,
                    cells[qty_at] if qty_at < len(cells) else "",
                    cells[pn_at] if pn_at >= 0 and pn_at < len(cells) else "",
                    cells[spec_at] if spec_at >= 0 and spec_at < len(cells) else "",
                )
            )
        return lines
    finally:
        book.close()


def _edf_blocks(text: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"\(Instance ", text):
        depth = 0
        for index in range(match.start(), len(text)):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    found.append(text[match.start() : index + 1])
                    break
    return found


def _edf_prop(block: str, name: str) -> str:
    direct = re.search(rf'\(Property {name} \(String "([^"]*)"', block)
    if direct:
        return direct.group(1).strip()
    renamed = re.search(rf'\(rename {name} "[^"]*"\) \(String "([^"]*)"', block)
    return renamed.group(1).strip() if renamed else ""


@dataclass(frozen=True)
class EdfPart:
    ref: str
    kind: str
    value: str
    footprint: str
    item: str
    part_no: str


def read_edf_parts(path: Path) -> list[EdfPart]:
    """从 Altium EDIF 统计已放置器件。零件号用 Manufacture PN。没有中文名称和产品尺寸。"""
    if path.suffix.lower() != ".edf" or not path.is_file():
        return []
    raw = path.read_bytes()
    text = ""
    for encoding in ("utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        text = raw.decode("latin1", errors="replace")
    parts: list[EdfPart] = []
    for block in _edf_blocks(text):
        ref = block.split()[1].rstrip(")") if len(block.split()) > 1 else ""
        if not ref:
            continue
        comment = _edf_prop(block, "Comment")
        value = _edf_prop(block, "Value") or comment
        parts.append(
            EdfPart(
                ref,
                _edf_prop(block, "Type"),
                value,
                _edf_prop(block, "Footprint"),
                _edf_prop(block, "Design_Item_ID"),
                _edf_prop(block, "Manufacture_PN"),
            )
        )
    return parts


def _edf_summary(parts: list[EdfPart]) -> list[tuple[str, ...]]:
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for part in parts:
        key = (part.kind, part.item, part.value, part.footprint, part.part_no)
        grouped.setdefault(key, []).append(part.ref)
    rows: list[tuple[str, ...]] = []
    for (kind, item, value, footprint, part_no), refs in grouped.items():
        shown = "、".join(refs[:8])
        if len(refs) > 8:
            shown += f" 等{len(refs)}个"
        rows.append((kind, item, value, footprint, part_no, str(len(refs)), shown))
    rows.sort(key=lambda row: (-int(row[5]), row[0], row[2]))
    return rows


@dataclass(frozen=True)
class SupplierFill:
    name: str
    part_no: str = ""
    quantity: str = ""
    thickness: str = ""
    weight: str = ""
    material: str = ""
    note: str = ""
    parent: str = ""
    spec: str = ""
    level: int = 0
    size_x: str = ""
    size_y: str = ""
    size_z: str = ""


_FORM_LABELS = frozenset({"项目", "PSS", "选型单元", "预选供应商", "研发部门", "总成图", "爆炸图"})


_ELECTRONIC_LEVEL = 4


def _level_columns(rows: list[list[str]], header_i: int, sub_i: int, fields: dict[str, list[int]]) -> list[int]:
    """级别 1 到 5 按表头下一行的数字从左到右。

    表头只在第一格写「级别」，后面 2、3、4、5 写在下一行。
    """
    sub = rows[sub_i] if 0 <= sub_i < len(rows) else []
    header = rows[header_i] if 0 <= header_i < len(rows) else []
    cols: list[int] = []
    for col in fields.get("级别") or []:
        if col not in cols:
            cols.append(col)
        nxt = col + 1
        while nxt < len(sub):
            head = header[nxt].strip() if nxt < len(header) else ""
            if head and "级别" not in _compact_name(head):
                break
            label = sub[nxt].strip()
            if not label.isdigit() or not (1 <= int(label) <= 5):
                break
            if nxt not in cols:
                cols.append(nxt)
            nxt += 1
    numbered: list[tuple[int, int]] = []
    plain: list[int] = []
    for col in cols:
        label = sub[col].strip() if col < len(sub) else ""
        if label.isdigit():
            numbered.append((int(label), col))
        else:
            plain.append(col)
    if numbered:
        numbered.sort()
        return [col for _number, col in numbered]
    return plain


def _bom_levels(rows: list) -> list[int]:
    """有图纸的本图零件是 2 级，明细里没有单独图纸的子件是 3 级。上级总成不在本表时不降级。"""
    keys: dict[str, int] = {}
    for index, row in enumerate(rows):
        if row.part_no and row.part_no not in keys:
            keys[row.part_no] = index
        if row.name and row.name not in keys:
            keys[row.name] = index

    def depth(index: int, seen: set[int]) -> int:
        if index in seen:
            return 2
        parent = rows[index].parent
        if not parent or parent not in keys or keys[parent] == index:
            return 2
        return min(depth(keys[parent], seen | {index}) + 1, 5)

    return [depth(index, set()) for index in range(len(rows))]


def _clear_supplier_body(sheet: Worksheet, data_start: int, header_row: int) -> None:
    """清掉模板里已经填好的内容。栏目标签和两行表头保留。"""
    if header_row > 1 and sheet.max_column:
        for row in sheet.iter_rows(min_row=1, max_row=header_row - 1, max_col=sheet.max_column):
            for cell in row:
                if isinstance(cell, MergedCell) or cell.value is None:
                    continue
                if str(cell.value).strip() in _FORM_LABELS:
                    continue
                cell.value = None
    for merged in list(sheet.merged_cells.ranges):
        if merged.max_row >= data_start:
            sheet.unmerge_cells(range_string=str(merged))
    if sheet.max_row >= data_start and sheet.max_column:
        for row in sheet.iter_rows(min_row=data_start, max_row=sheet.max_row, max_col=sheet.max_column):
            for cell in row:
                cell.value = None
    images = getattr(sheet, "_images", None)
    if images is not None:
        images.clear()


def _show_supplier_data(sheet: Worksheet, data_start: int) -> None:
    """打开时停在表头下一行。模板原先冻在第 105 行，清掉零件后那里是空白。"""
    anchor = f"A{data_start}"
    sheet.freeze_panes = anchor
    view = sheet.views.sheetView[0]
    if view.pane is not None:
        view.pane.topLeftCell = anchor
        view.pane.xSplit = None
        view.pane.activePane = "bottomLeft"
    view.topLeftCell = "A1"
    view.selection = [Selection(activeCell=anchor, sqref=anchor)]
    if sheet.auto_filter is not None and sheet.auto_filter.ref:
        sheet.auto_filter.ref = None


def bom_field_check(
    name: str,
    quantity: str,
    spec: str,
    level: int,
    previous: dict[str, tuple[str, str, int]] | None,
) -> str:
    """和已有 CE BOM 对名称。只标差异，不改当次抽出的数。"""
    if previous is None:
        return ""
    key = (name or "").strip()
    if not key or key not in previous:
        return "上一版没有"
    old_qty, old_spec, old_level = previous[key]
    diffs: list[str] = []
    if (quantity or "") != (old_qty or ""):
        diffs.append("用量")
    if (spec or "") != (old_spec or ""):
        diffs.append("规格型号")
    if level and old_level and level != old_level:
        diffs.append("级别")
    return "一致" if not diffs else "不一致：" + "、".join(diffs)


def _read_previous_bom(path: Path) -> dict[str, tuple[str, str, int]]:
    """已有 CE BOM 按零件中文名称索引用量和规格。读不到表头就返回空。"""
    book = load_workbook(path, data_only=True)
    found: dict[str, tuple[str, str, int]] = {}
    try:
        for sheet in book.worksheets:
            width = min(sheet.max_column or 1, 40)
            height = min(sheet.max_row or 1, 30)
            header = name_col = qty_col = spec_col = 0
            for row in range(1, height + 1):
                name_at = qty_at = spec_at = 0
                for col in range(1, width + 1):
                    compact = re.sub(r"\s+", "", str(sheet.cell(row, col).value or ""))
                    if "零件中文名称" in compact or compact in {"中文名称", "名称"}:
                        name_at = col
                    elif "用量" in compact and not qty_at:
                        qty_at = col
                    elif "规格" in compact and not spec_at:
                        spec_at = col
                if name_at and qty_at:
                    header, name_col, qty_col, spec_col = row, name_at, qty_at, spec_at
                    break
            if not header or not name_col:
                continue
            for row in range(header + 1, (sheet.max_row or header) + 1):
                name = str(sheet.cell(row, name_col).value or "").strip()
                if not name or "名称" in name:
                    continue
                qty = str(sheet.cell(row, qty_col).value or "").strip() if qty_col else ""
                if qty.endswith(".0"):
                    qty = qty[:-2]
                spec = str(sheet.cell(row, spec_col).value or "").strip() if spec_col else ""
                found.setdefault(name, (qty, spec, 0))
    finally:
        book.close()
    return found


def _supplier_match(line: SupplierFill, structural: bool) -> str:
    """这一行里，输入对上了哪些列。3 级件的尺寸按会议留空，不算没对上。"""
    items = [
        ("中文名称", bool(line.name)),
        ("零件号", bool(line.part_no)),
        ("用量", bool(line.quantity)),
        ("级别", bool(line.level)),
    ]
    if not structural:
        items.append(("规格型号", bool(line.spec)))
    ok = [name for name, flag in items if flag]
    miss = [name for name, flag in items if not flag]
    text = f"{len(ok)}/{len(items)} 已对上"
    if miss:
        text += "；未对上 " + "、".join(miss)
    if structural and line.level >= 3:
        text += "；三级件无独立图纸，尺寸不提取"
    elif structural and line.size_x:
        text += "；尺寸取自外形尺寸"
    elif structural:
        text += "；外形尺寸未标注，不从散落尺寸读取"
    return text


def _match_column(sheet: Worksheet, header_row: int, level_cols: list[int] | None = None) -> int:
    last = 0
    width = sheet.max_column or 1
    for col in range(1, width + 1):
        if sheet.cell(header_row, col).value not in (None, ""):
            last = max(last, col)
        below = header_row + 1
        if below <= (sheet.max_row or 1) and sheet.cell(below, col).value not in (None, ""):
            last = max(last, col)
    for col in level_cols or []:
        last = max(last, col + 1)
    column = last + 1
    while not _cell_writable(sheet, header_row, column):
        column += 1
    sheet.cell(header_row, column, "匹配")
    return column


def _cell_writable(sheet: Worksheet, row: int, col: int) -> bool:
    return not isinstance(sheet.cell(row, col), MergedCell)


def _field_rows(kind: str, line: SupplierFill) -> list[tuple[str, str, str, str, str, str]]:
    """每个字段一行。已对上表示输入里有这个值并且写进了表。"""
    fields = [
        ("中文名称", line.name),
        ("零件号", line.part_no),
        ("用量", line.quantity),
        ("级别", str(line.level or "")),
    ]
    if kind == "电子件":
        fields.append(("规格型号", line.spec))
    else:
        size = "×".join(value for value in (line.size_x, line.size_y, line.size_z) if value)
        if line.level >= 3:
            fields.append(("尺寸", ""))
            fields.append(("材料", line.material))
        else:
            fields.append(("尺寸", size))
            fields.append(("材料", line.material))
    rows: list[tuple[str, str, str, str, str, str]] = []
    for field_name, value in fields:
        if kind == "结构件" and line.level >= 3 and field_name == "尺寸":
            result, note = "未提取", "三级件无独立图纸"
        elif value:
            result, note = "已对上", "电子件默认4级" if kind == "电子件" and field_name == "级别" else ""
        else:
            result, note = "未对上", ""
        rows.append((kind, line.name or line.part_no, field_name, value, result, note))
    return rows


def _write_field_match(book, electronic: list[SupplierFill], structural: list[SupplierFill]) -> None:
    if "字段匹配" in book.sheetnames:
        del book["字段匹配"]
    sheet = book.create_sheet("字段匹配")
    sheet.append(["类别", "零件", "字段", "写入值", "结果", "说明"])
    body: list[tuple[str, str, str, str, str, str]] = []
    for line in electronic:
        body.extend(_field_rows("电子件", line))
    for line in structural:
        body.extend(_field_rows("结构件", line))
    for row in body:
        sheet.append(list(row))
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    ok_fill = PatternFill("solid", fgColor="C6EFCE")
    miss_fill = PatternFill("solid", fgColor="FFE699")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(name="宋体", bold=True, color="FFFFFF")
    for row in range(2, sheet.max_row + 1):
        result = str(sheet.cell(row, 5).value or "")
        fill = ok_fill if result == "已对上" else miss_fill
        for col in range(1, 7):
            cell = sheet.cell(row, col)
            cell.fill = fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    totals = [row for row in body if row[0] == "电子件"]
    matched = sum(1 for row in totals if row[4] == "已对上")
    sheet.cell(1, 8, "电子件字段")
    sheet.cell(1, 9, f"{matched}/{len(totals)} 已对上" if totals else "无电子件")
    for col, width in enumerate((12, 22, 12, 28, 12, 28), start=1):
        sheet.column_dimensions[get_column_letter(col)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:F{max(sheet.max_row, 1)}"


def _place_issue_version(sheet: Worksheet, header_row: int) -> None:
    """版本写在表头上方的空格。合并单元格不能写，改写到表头右侧。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for row in range(header_row - 1, 0, -1):
        if not (_cell_writable(sheet, row, 1) and _cell_writable(sheet, row, 2)):
            continue
        if sheet.cell(row, 1).value in (None, "") and sheet.cell(row, 2).value in (None, ""):
            sheet.cell(row, 1, "出表版本")
            sheet.cell(row, 2, stamp)
            return
    col = (sheet.max_column or 1) + 1
    while not _cell_writable(sheet, header_row, col):
        col += 1
    sheet.cell(header_row, col, f"出表版本 {stamp}")


def _write_supplier_lines(
    sheet: Worksheet,
    layout: StandardLayout,
    fields: dict[str, list[int]],
    lines: list[SupplierFill],
    *,
    structural: bool,
    level_cols: list[int] | None = None,
    previous: dict[str, tuple[str, str, int]] | None = None,
) -> tuple[int, list[tuple[str, ...]]]:
    """从数据区第一行写入。序号从 1 起。产品尺寸不补造。"""
    name_col = fields["名称"][0] if fields["名称"] else -1
    qty_col = fields["用量"][0] if fields["用量"] else -1
    pn_col = fields["零件号"][0] if fields["零件号"] else -1
    serial_col = fields["序号"][0] if fields["序号"] else -1
    thick_col = fields["厚度"][0] if fields["厚度"] else -1
    material_col = fields["原材料"][0] if fields["原材料"] else -1
    spec_cols = fields.get("规格型号") or []
    spec_col = spec_cols[0] if spec_cols else -1
    levels = level_cols if level_cols is not None else (fields.get("级别") or [])
    if name_col < 0:
        return 0, []
    match_col = _match_column(sheet, layout.header_row, levels)
    check_col = 0
    if previous is not None:
        check_col = match_col + 1
        while not _cell_writable(sheet, layout.header_row, check_col):
            check_col += 1
        sheet.cell(layout.header_row, check_col, "校核")
        sheet.column_dimensions[get_column_letter(check_col)].width = 22
    excel_row = layout.data_start
    notes: list[tuple[str, ...]] = []
    named = 0
    for serial, line in enumerate(lines, start=1):
        if serial_col >= 0:
            sheet.cell(excel_row, serial_col + 1, serial)
        sheet.cell(excel_row, name_col + 1, line.name or None)
        if qty_col >= 0 and line.quantity:
            quantity: object = int(line.quantity) if line.quantity.isdigit() else line.quantity
            sheet.cell(excel_row, qty_col + 1, quantity)
        if pn_col >= 0 and line.part_no:
            sheet.cell(excel_row, pn_col + 1, line.part_no)
        if thick_col >= 0 and line.thickness:
            sheet.cell(excel_row, thick_col + 1, line.thickness)
        if line.weight:
            sheet.cell(excel_row, layout.weight_col, line.weight)
        if material_col >= 0 and line.material:
            sheet.cell(excel_row, material_col + 1, line.material)
        if spec_col >= 0 and line.spec:
            sheet.cell(excel_row, spec_col + 1, line.spec)
        if structural and line.level == 2:
            for axis, value in (("X", line.size_x), ("Y", line.size_y), ("Z", line.size_z)):
                col = layout.axes.get(axis)
                if col is not None and value:
                    sheet.cell(excel_row, col + 1, value)
        if line.level and 1 <= line.level <= len(levels):
            sheet.cell(excel_row, levels[line.level - 1] + 1, "●")
        sheet.cell(excel_row, match_col, _supplier_match(line, structural))
        if check_col:
            verdict = bom_field_check(line.name, line.quantity, line.spec, line.level, previous)
            sheet.cell(excel_row, check_col, verdict)
            if verdict and verdict != "一致":
                notes.append(("校核", line.name or f"第{excel_row}行", "", "", verdict))
        who = line.name or f"第{excel_row}行"
        if line.name:
            named += 1
        else:
            notes.append(("名称", who, "", "", f"第{excel_row}行零件中文名称留空"))
        if not line.quantity:
            notes.append(("用量", who, "", "", f"{who} 用量留空"))
        if "盖板" in line.name and not line.thickness:
            notes.append(("盖板", line.name, "", "", f"第{excel_row}行盖板缺材料厚度，不补造"))
        if structural and line.level >= 3:
            notes.append(("尺寸", who, "", "", f"{who} 为3级件，无图，尺寸手动填写"))
        elif structural:
            notes.append(("尺寸", who, "", "", f"{who} 缺产品尺寸。2级件不从散落标注里取长宽高"))
            if not line.weight:
                notes.append(("净重", who, "", "", f"{who} 缺净重。结构件必填，按体积×密度。体积或密度未给定，不计算"))
            if not line.material:
                notes.append(("原材料", who, "", "", f"{who} 缺原材料"))
        if line.note:
            notes.append(("备注", line.name, "", "", line.note))
        if line.parent:
            notes.append(("上级总成", line.name, line.parent, "", f"{line.name} 上级总成 {line.parent}"))
        excel_row += 1
    missing_levels = [line for line in lines if not line.level]
    if missing_levels:
        notes.append(("级别", "", str(len(missing_levels)), "", "级别必填。这些行没有明细层级，不补级别"))
    return named, notes


def _build_standard_ce_bom(
    manuals: list[Path],
    template: Path,
    dest: Path,
    layout: StandardLayout,
    previous: Path | None = None,
) -> CeBomResult:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    book = load_workbook(dest, data_only=False)
    sheet = book[layout.sheet]
    rows = _sheet_rows(sheet)
    header_i = layout.header_row - 1
    sub_i = layout.sub_row - 1
    fields = _standard_fields(rows[header_i], rows[sub_i])
    missing_notes: list[tuple[str, ...]] = []
    width = max(len(row) for row in rows) if rows else 0
    template_rows = 0
    for row in rows[layout.data_start - 1 :]:
        name = row[layout.name_col - 1] if layout.name_col > 0 and layout.name_col - 1 < len(row) else ""
        if name:
            template_rows += 1
    _clear_supplier_body(sheet, layout.data_start, layout.header_row)
    missing_notes.append(
        (
            "模板数据",
            str(template_rows),
            "",
            "",
            "供应商表里模板原有的零件行、尺寸、净重和公式已清除",
        )
    )
    mapping_rows: list[tuple[str, ...]] = []
    for col in range(width):
        top = rows[header_i][col] if col < len(rows[header_i]) else ""
        sub = rows[sub_i][col] if col < len(rows[sub_i]) else ""
        if not top and not sub:
            continue
        label = top if not sub or sub in top else f"{top} / {sub}"
        role, unit, note = _column_rule(col, layout, fields)
        mapping_rows.append((get_column_letter(col + 1), label, role, unit, note))
    edf_parts: list[EdfPart] = []
    edf_names: list[str] = []
    for path in manuals:
        if path.suffix.lower() != ".edf":
            continue
        edf_names.append(path.name)
        edf_parts.extend(read_edf_parts(path))
    edf_rows = _edf_summary(edf_parts)
    ad_lines: list[AdBomLine] = []
    ad_names: list[str] = []
    for path in manuals:
        parsed = read_ad_bom(path)
        if parsed is None:
            continue
        ad_names.append(path.name)
        ad_lines.extend(parsed)
    rules = read_name_rules(DEFAULT_CE_BOM_NAME_RULES)
    edf_fills = [
        SupplierFill(rules.get(kind.casefold(), ""), part_no, quantity, spec=item or value, level=_ELECTRONIC_LEVEL)
        for kind, item, value, _footprint, part_no, quantity, _refs in edf_rows
    ]
    missing_types: dict[str, int] = {}
    ad_fills = [
        SupplierFill(
            rules.get(line.kind.casefold(), ""),
            line.part_no,
            line.quantity,
            spec=line.spec,
            level=_ELECTRONIC_LEVEL,
        )
        for line in ad_lines
    ]
    for line in ad_lines:
        if not rules.get(line.kind.casefold(), ""):
            missing_types[line.kind] = missing_types.get(line.kind, 0) + 1
    for kind, count in sorted(missing_types.items()):
        missing_notes.append(("名称", kind, str(count), "", f"Type {kind} 共 {count} 行不在中文名称规则表，零件中文名称留空"))
    from electrical_krow.ce_structure import read_structure_drawing

    structure_rows = []
    for path in manuals:
        structure_rows.extend(read_structure_drawing(path))
    structure_fills = [
        SupplierFill(
            row.name,
            row.part_no,
            row.quantity,
            row.thickness,
            row.weight,
            row.material,
            row.note,
            row.parent,
            level=level,
            size_x=row.size_x if level == 2 else "",
            size_y=row.size_y if level == 2 else "",
            size_z=row.size_z if level == 2 else "",
        )
        for row, level in zip(structure_rows, _bom_levels(structure_rows), strict=True)
    ]
    level_cols = _level_columns(rows, header_i, sub_i, fields)
    previous_rows = _read_previous_bom(previous) if previous is not None and previous.is_file() else None
    hardware_fills = [*edf_fills, *ad_fills]
    named = 0
    if hardware_fills and structure_fills:
        structure_sheet = book.copy_worksheet(sheet)
        structure_sheet.title = "结构"
        named, ad_notes = _write_supplier_lines(
            sheet, layout, fields, hardware_fills, structural=False, level_cols=level_cols, previous=previous_rows,
        )
        _, structure_notes = _write_supplier_lines(
            structure_sheet, layout, fields, structure_fills, structural=True, level_cols=level_cols, previous=previous_rows,
        )
        missing_notes.extend(ad_notes)
        missing_notes.extend(structure_notes)
        missing_notes.append(
            ("结构", str(len(structure_fills)), "", "", "硬件写入供应商，结构写入「结构」。电子件为4级。上传的二维图是2级，明细子件是3级。尺寸和材料只从2级图已标注处读取。")
        )
    elif structure_fills:
        named, structure_notes = _write_supplier_lines(
            sheet, layout, fields, structure_fills, structural=True, level_cols=level_cols, previous=previous_rows,
        )
        missing_notes.extend(structure_notes)
        missing_notes.append(
            ("结构", str(len(structure_fills)), "", "", "上传的二维图是2级，明细子件是3级。尺寸和材料只从2级图已标注处读取，3级件不提取。")
        )
    elif hardware_fills:
        _, ad_notes = _write_supplier_lines(
            sheet, layout, fields, hardware_fills, structural=False, level_cols=level_cols, previous=previous_rows,
        )
        missing_notes.extend(ad_notes)
    if previous_rows:
        written_names = {line.name for line in [*hardware_fills, *structure_fills] if line.name}
        for old_name in previous_rows:
            if old_name not in written_names:
                missing_notes.append(("校核", old_name, "", "", f"上一版有 {old_name}，当次输入没有，不补行"))
    blank = sum(1 for note in missing_notes if note[0] in {"名称", "用量", "盖板", "尺寸", "净重", "原材料"})
    checked = sum(1 for note in missing_notes if note[0] == "校核")
    _write_field_match(book, hardware_fills, structure_fills)
    _place_issue_version(sheet, layout.header_row)
    _show_supplier_data(sheet, layout.data_start)
    if structure_fills and hardware_fills and "结构" in book.sheetnames:
        _place_issue_version(book["结构"], layout.header_row)
        _show_supplier_data(book["结构"], layout.data_start)
    book.save(dest)
    book.close()
    written = len(structure_fills) if structure_fills and not hardware_fills else len(hardware_fills)
    return CeBomResult(dest, written, 0, blank, checked, [(row[1], row[2], row[4]) for row in mapping_rows], True)


def build_ce_bom(
    manuals: list[Path],
    template: Path,
    dest: Path,
    previous: Path | None = None,
) -> CeBomResult:
    layout = _find_standard_layout(template)
    if layout is not None:
        return _build_standard_ce_bom(manuals, template, dest, layout, previous)
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
