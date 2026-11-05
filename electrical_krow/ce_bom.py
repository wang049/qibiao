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
    standard: bool = False


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
    fields = {key: [] for key in ("序号", "级别", "名称", "零件号", "图片", "用量", "厚度", "原材料")}
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
    return fields


def _has_value(row: list[str], cols: list[int]) -> bool:
    return any(col < len(row) and row[col] for col in cols)


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
        return "尺寸X", "mm", "电子件可不填，结构件必填。来源未到，不写入，不换算单位"
    if col == layout.axes["Y"]:
        return "尺寸Y", "mm", "电子件可不填，结构件必填。来源未到，不写入，不换算单位"
    if col == layout.axes["Z"]:
        return "尺寸Z", "mm", "电子件可不填，结构件必填。来源未到，不写入，不换算单位"
    if col == layout.weight_col - 1:
        return "净重", "g", "结构件按体积×密度。密度未给定，不计算、不写入。已有数和公式保持不动"
    if col in fields["厚度"]:
        return "材料厚度", "", "仅盖板类必填。名称含盖板且为空时记入核验，不补造"
    if col in fields["原材料"]:
        return "原材料", "", "结构件必填。表上未标明结构件或电子件，不据此判缺，不写入"
    return "未指定", "", "填写规则未到，不写入"


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


def read_edf_parts(path: Path) -> list[EdfPart]:
    """从 Altium EDIF 统计已放置器件。没有中文名称、零件号和产品尺寸。"""
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
            )
        )
    return parts


def _edf_summary(parts: list[EdfPart]) -> list[tuple[str, ...]]:
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for part in parts:
        key = (part.kind, part.item, part.value, part.footprint)
        grouped.setdefault(key, []).append(part.ref)
    rows: list[tuple[str, ...]] = []
    for (kind, item, value, footprint), refs in grouped.items():
        shown = "、".join(refs[:8])
        if len(refs) > 8:
            shown += f" 等{len(refs)}个"
        rows.append((kind, item, value, footprint, str(len(refs)), shown))
    rows.sort(key=lambda row: (-int(row[4]), row[0], row[2]))
    return rows


def _build_standard_ce_bom(manuals: list[Path], template: Path, dest: Path, layout: StandardLayout) -> CeBomResult:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, dest)
    book = load_workbook(dest, data_only=False)
    sheet = book[layout.sheet]
    rows = _sheet_rows(sheet)
    header_i = layout.header_row - 1
    sub_i = layout.sub_row - 1
    fields = _standard_fields(rows[header_i], rows[sub_i])
    kept_rows = 0
    formulas = 0
    carried = 0
    missing_rows = 0
    missing_notes: list[tuple[str, ...]] = []
    watched = [layout.axes["X"], layout.axes["Y"], layout.axes["Z"], layout.weight_col - 1]
    required = [key for key in ("序号", "级别", "名称", "用量") if fields[key]]
    width = max(len(row) for row in rows) if rows else 0
    for row_i in range(layout.data_start - 1, len(rows)):
        row = rows[row_i]
        if not any(col < len(row) and row[col] for col in range(min(width, len(row)))):
            continue
        name = row[layout.name_col - 1] if layout.name_col > 0 and layout.name_col - 1 < len(row) else ""
        if name:
            kept_rows += 1
        excel_row = row_i + 1
        for col in watched:
            if col >= len(row):
                continue
            if row[col].startswith("="):
                formulas += 1
            elif row[col]:
                carried += 1
        absent = []
        labels = {"序号": "序号", "级别": "级别", "名称": "零件中文名称", "用量": "用量"}
        for key in required:
            if not _has_value(row, fields[key]):
                absent.append(labels[key])
        if absent:
            missing_rows += 1
            who = name or f"第{excel_row}行"
            missing_notes.append(("缺必填", who, "", "", f"第{excel_row}行缺" + "、".join(absent)))
        if "盖板" in name and fields["厚度"] and not _has_value(row, fields["厚度"]):
            missing_notes.append(("盖板", name, "", "", f"第{excel_row}行盖板缺材料厚度，不补造"))
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
    if edf_rows:
        edf_sheet = book.create_sheet("EDF器件")
        _write_sheet(
            edf_sheet,
            ("类型", "设计条目", "值", "封装", "用量", "位号"),
            edf_rows,
            (16, 42, 16, 14, 10, 36),
        )
    edf_note = "未提交 EDF"
    if edf_names:
        edf_note = (
            f"{'；'.join(edf_names)} 放置 {len(edf_parts)} 个，按类型、设计条目、值和封装归成 {len(edf_rows)} 种。"
            "用量按同型号只数统计。封装是 Footprint，不是产品尺寸。"
            "没有零件中文名称、级别、零件号、材料厚度、净重和原材料，这些不写入标准表。"
            "层级不能从网表判断。本次没有 AD 导出的 BOM。"
        )
    manual_note = "未提交物料手册"
    if manuals:
        manual_note = "手册已接收，填写规则未到，未写入标准表：" + "；".join(path.name for path in manuals)
    check_rows = [
        ("标准表", layout.sheet, "", "", "沿用原工作表、两行表头和列序"),
        ("表头", f"第{layout.header_row}行 / 第{layout.sub_row}行", "", "", "尺寸列的下一行是 X、Y、Z"),
        ("已有零件行", str(kept_rows), "", "", "标准文档自带的零件、尺寸和重量不作为其他物料的填写依据"),
        ("公式格", str(formulas), "", "", "尺寸和净重中的公式保持不动，不改成计算值"),
        ("已有取值", str(carried), "", "", "尺寸和净重里已经写上的数保持不动"),
        *missing_notes,
        ("手册", "", "", "", manual_note),
        ("EDF", str(len(edf_parts)), str(len(edf_rows)), "", edf_note),
        (
            "说明",
            "",
            "",
            "",
            "序号、级别、零件中文名称、用量只核对是否为空，不补造。零件号有则填，空着不补。图片不处理。"
            "产品尺寸、材料厚度、净重、原材料的取值来源未到，不写入。密度未给定，不按体积计算净重。"
            "EDF、Altium BOM 和 PLM 未接入。技术协议第七章未规定完整度或一致性的通过阈值。",
        ),
    ]
    mapping = book.create_sheet("字段映射")
    _write_sheet(mapping, ("列", "表头", "识别", "单位", "说明"), mapping_rows, (8, 28, 12, 10, 42))
    check = book.create_sheet("核验记录")
    _write_sheet(check, ("记录", "内容", "", "", "说明"), check_rows, (16, 28, 12, 12, 42))
    book.save(dest)
    book.close()
    return CeBomResult(dest, kept_rows, 0, missing_rows, 0, [(row[1], row[2], row[4]) for row in mapping_rows], True)


def build_ce_bom(manuals: list[Path], template: Path, dest: Path) -> CeBomResult:
    layout = _find_standard_layout(template)
    if layout is not None:
        return _build_standard_ce_bom(manuals, template, dest, layout)
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
