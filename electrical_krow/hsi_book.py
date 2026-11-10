"""按 DHTE400 HSI V1.3（2026-10-23）出一份手册对应的 HSI。

端口表的引脚只写当份手册：符号、球号、缓冲、上下拉、供电、方向、复用、页码、原文摘录。
方向列只写手册给出的 Input 或 Output。功能列写对得上的模板用法：Analog、Digital、PWM、SPI、CAN。对得上的模板端口名写入 Pin Definition，不对的由人改。ATOM/DTM 不写入格子。
ADC 表按手册复用里的转换器分组，同一组排在一起并着底色。两路 EVADC 的组号留空。项目信号名不写入。
上传网表时再写原理图网络名和外部电阻。端口名为空时不做跳转。

有原理图时：模板各页原样复制。只更新对得上的网络名和外部电阻，并写明与端口名的交叉差异。对不上的网络不新增行，也不清封面和变更记录。
无原理图时：先认 MCU、数总脚数、按手册归类，再写入复用；手册出表清空各页示例数据行。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from copy import copy
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.hyperlink import Hyperlink
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
from electrical_krow.hsi_dead_time import apply_dead_time_sheet
from electrical_krow.hsi_schematic import (
    BoardPin,
    SchematicHit,
    SchematicSymbolPin,
    pin_key,
    read_board_pins,
    read_schematic,
    read_schematic_pdf,
)
from electrical_krow.mcu_pins import (
    ChipPin,
    mcu_name,
    parse_pin_pages,
    parse_pins,
    pin_class,
    pin_supply_kind,
    present_excerpt,
    present_mux,
    read_pdf_pages,
)

DEFAULT_HSI_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "DHTE400-HSI-V1.3-20261023.xlsx"
)
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


# 按原理图归档时先选 MCU 模板。有独立文件（文件名含型号）时用它，否则先共用默认底稿。
_HSI_MCU_TEMPLATE_IDS = ("TC499", "TC387", "TC399")


def _mcu_token(mcu: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (mcu or "")).upper()


def hsi_template_for_mcu(mcu: str) -> Path:
    """按 MCU 选模板。有独立文件（文件名含型号）时用它，否则用默认 DHTE400。"""
    token = _mcu_token(mcu)
    if not token or not _TEMPLATE_DIR.is_dir():
        return DEFAULT_HSI_TEMPLATE
    hits: list[Path] = []
    for path in sorted(_TEMPLATE_DIR.glob("*HSI*.xlsx")):
        name = re.sub(r"[^A-Za-z0-9]", "", path.stem).upper()
        if token in name:
            hits.append(path)
    if not hits:
        return DEFAULT_HSI_TEMPLATE
    dedicated = [path for path in hits if path.resolve() != DEFAULT_HSI_TEMPLATE.resolve()]
    return dedicated[0] if dedicated else hits[0]


def list_hsi_templates() -> list[dict[str, str]]:
    """按 MCU 列模板（499 / 387 / 399），不是工程文件名。"""
    rows: list[dict[str, str]] = []
    for mcu in _HSI_MCU_TEMPLATE_IDS:
        path = hsi_template_for_mcu(mcu)
        if not path.is_file():
            continue
        rows.append({"id": mcu, "name": mcu, "file": path.name, "mcu": mcu})
    return rows


def hsi_template_by_id(template_id: str) -> Path | None:
    token = (template_id or "").strip()
    if not token:
        return None
    compact = _mcu_token(token)
    for mcu in _HSI_MCU_TEMPLATE_IDS:
        if compact == _mcu_token(mcu) or compact == mcu.lstrip("TC") or compact.endswith(mcu.lstrip("TC")):
            path = hsi_template_for_mcu(mcu)
            return path if path.is_file() else None
    if not _TEMPLATE_DIR.is_dir():
        return None
    for path in _TEMPLATE_DIR.glob("*HSI*.xlsx"):
        if path.stem == token or path.name == token:
            return path
    return None

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


def _match_text(items: list[tuple[str, bool]]) -> str:
    ok = [name for name, flag in items if flag]
    miss = [name for name, flag in items if not flag]
    text = f"{len(ok)}/{len(items)} 已对上"
    if miss:
        text += "；未对上 " + "、".join(miss)
    return text


def _write_port_match(sheet, header_row: int, excel_row: int, human_col: int, text: str) -> None:
    if not human_col:
        return
    column = human_col + 1
    sheet.cell(header_row, column, "匹配")
    sheet.cell(excel_row, column, text)
    sheet.column_dimensions[get_column_letter(column)].width = 42


def _stamp_issue(workbook: Workbook, note: str) -> None:
    """每次重出在变更记录记一版。模板里原来的版本号若已被清掉，就写在第一条空行。"""
    history = _history_sheet(workbook)
    if history is None:
        return
    header = None
    limit = min(history.max_row or 1, 8)
    width = min(history.max_column or 1, 8)
    for row in range(1, limit + 1):
        labels = {_text(history.cell(row, col).value) for col in range(1, width + 1)}
        if "版本" in labels:
            header = row
            break
    if header is None:
        history.cell(1, 2, "版本")
        history.cell(1, 4, "详细描述")
        header = 1
    target = header + 1
    while any(history.cell(target, col).value not in (None, "") for col in range(1, 5)):
        target += 1
        if target > header + 40:
            break
    history.cell(target, 2, datetime.now().strftime("%Y%m%d-%H%M%S"))
    history.cell(target, 3, date.today().isoformat())
    history.cell(target, 4, note)

STATUS_GAP = "缺项"
STATUS_MULTI = "多候选"
STATUS_CONFLICT = "约束冲突"
STATUS_DRAFT = "待人工确认"

_HISTORY_HEADERS = ("编号", "变更日期", "详细描述", "影响分析", "备注")
_EVIDENCE_HEADERS = ("引脚符号", "球号", "方向", "缓冲", "功能", "复用", "页码", "手册分类", "原文摘录")
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


_SYMBOL_CELL = re.compile(r"^(?:P\d{1,2}\.\d+|AN\d+|J\d+)", re.I)
_BALL_CELL = re.compile(r"^[A-Z]{1,3}\d{1,2}$", re.I)


def _header_symbol_ball(sheet, header_row: int) -> tuple[int, int] | None:
    """表头写明球号和引脚符号时，返回这两列。没有这组表头则交给调用方用旧位置。"""
    ball = symbol = 0
    for col in range(1, 8):
        compact = _text(sheet.cell(header_row, col).value).replace("\\", "").replace(" ", "").casefold()
        if "ball" in compact and not ball:
            ball = col
        elif "pin_symbol" in compact or compact in {"symbol", "pinsymbol"}:
            symbol = col
    if ball and symbol and ball != symbol:
        return symbol, ball
    return None


def _placed_symbol_ball(sheet, layout: _PortLayout) -> tuple[int, int]:
    """读已有格子。模板正文仍是符号在 B、球号在 C；按表头写出的表则反过来。"""
    found = _header_symbol_ball(sheet, layout.header)
    if found is None:
        return 2, 3
    symbol_col, ball_col = found
    header_votes = swapped_votes = 0
    last = min(sheet.max_row or layout.data_start, layout.data_start + 40)
    for row in range(layout.data_start, last + 1):
        under_symbol = _text(sheet.cell(row, symbol_col).value)
        under_ball = _text(sheet.cell(row, ball_col).value)
        if _SYMBOL_CELL.match(under_symbol) or (
            _BALL_CELL.match(under_ball) and not _SYMBOL_CELL.match(under_ball)
        ):
            header_votes += 1
        if _SYMBOL_CELL.match(under_ball) or (
            _BALL_CELL.match(under_symbol) and not _SYMBOL_CELL.match(under_symbol)
        ):
            swapped_votes += 1
    if swapped_votes > header_votes:
        return ball_col, symbol_col
    return symbol_col, ball_col


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
    symbol_col, ball_col = _placed_symbol_ball(sheet, layout)
    found: list[_PortRow] = []
    for row in range(layout.data_start, (sheet.max_row or layout.data_start) + 1):
        symbol = _text(sheet.cell(row, symbol_col).value)
        if not symbol or symbol.lower() in {"pin_symbol", "bga436\\ball", "ball"}:
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
                ball=_text(sheet.cell(row, ball_col).value),
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


_TEMPLATE_FUNCTIONS = frozenset(
    {"Analog", "Digital", "PWM", "SPI", "CAN", "PMS", "JTAG", "LIN", "SMU", "SENT"}
)


def _template_function(matches: list[_PortRow]) -> str:
    """模板 Function 是项目用法。同一只脚对上同一个词才写入，不把手册分类 ADC、Timer 写进这一列。"""
    words: list[str] = []
    for row in _distinct_rows(matches):
        text = _text(row.function)
        if text and text not in words:
            words.append(text)
    if len(words) == 1 and words[0] in _TEMPLATE_FUNCTIONS:
        return words[0]
    return ""


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

        names: list[str] = []
        for row in distinct:
            name = _project_name(row.project)
            if name and name not in names:
                names.append(name)
        if names and (len(distinct) != 1 or len(names) != 1):
            add_note(f"模板有端口名 {'、'.join(names)}，待人工确认")

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

    kind = pin_class(pin)
    if kind:
        add_note(f"手册分类：{kind}")
        if kind not in {"电源", "地"}:
            add_note("分配待人工确认")
    options = [
        item.split()[0]
        for item in present_mux(pin.mux).splitlines()
        if item.strip()
    ]
    if len(options) > 1:
        add_note("可选信号：" + "、".join(options) + "；复用不自动选择")
    elif options:
        add_note("可选信号：" + options[0])
    keywords = hsi_keyword_hits(" ".join((pin.symbol, pin.function, pin.mux, _project_name(project))))
    if keywords:
        add_note("须进入HSI：" + "、".join(keywords))

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
    symbol_col, _ball_col = _placed_symbol_ball(sheet, layout)
    found: dict[str, object] = {}
    for row in range(layout.data_start, (sheet.max_row or layout.data_start) + 1):
        symbol = _text(sheet.cell(row, symbol_col).value)
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
    """模板用整行黄、紫底色标过原端口。新写出的行不沿用这层颜色。"""
    for key in list(sheet.row_dimensions):
        if isinstance(key, int) and key > header_row:
            del sheet.row_dimensions[key]


def _highlight_fill(fill) -> bool:
    """模板列样式的 theme 0，WPS 会画成黄底。黄、紫是模板原来的标色。"""
    if fill is None or fill.patternType != "solid" or fill.fgColor is None:
        return False
    color = fill.fgColor
    if color.type == "theme" and color.theme == 0:
        return True
    if color.type == "rgb" and str(color.rgb).upper() in {"FFFFFF00", "FFFF66FF"}:
        return True
    return False


def _drop_column_fills(sheet) -> None:
    """列样式铺到 XFD 时，空单元格会带底色，分页也会一直排到第几百页。"""
    for dim in sheet.column_dimensions.values():
        dim.fill = PatternFill(fill_type=None)
        if dim.max and dim.max > 200:
            dim.max = dim.min or 1


def _drop_cell_highlights(sheet) -> None:
    plain = PatternFill(fill_type=None)
    for row in sheet.iter_rows():
        for cell in row:
            if _highlight_fill(cell.fill):
                cell.fill = plain


def _plain_port_sheet(sheet, header_row: int, *, keep_heights: bool = False) -> None:
    """去掉模板黄紫底，并回到普通视图，分页预览的「第 N 页」不再盖在表上。"""
    if keep_heights:
        plain = PatternFill(fill_type=None)
        for key, dim in list(sheet.row_dimensions.items()):
            if isinstance(key, int) and key > header_row and _highlight_fill(dim.fill):
                dim.fill = plain
    else:
        _drop_row_highlights(sheet, header_row)
    _drop_column_fills(sheet)
    _drop_cell_highlights(sheet)
    sheet.conditional_formatting._cf_rules.clear()
    view = sheet.sheet_view
    view.view = "normal"
    view.zoomScale = 100
    view.zoomScaleNormal = 100
    view.zoomScaleSheetLayoutView = None
    view.zoomScalePageLayoutView = None
    view.topLeftCell = "A1"
    if view.selection:
        view.selection[0].activeCell = "A1"
        view.selection[0].sqref = "A1"


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


def _share_symbol_jump(name_cell, symbol_cell) -> None:
    """端口名自己没有落点时，跟这一行符号走。一处直达，多处进同一条跳转索引。"""
    link = symbol_cell.hyperlink
    if link is None or not getattr(link, "location", None):
        return
    name = _text(name_cell.value)
    if not name:
        return
    tip = link.tooltip or ""
    if tip.startswith("第") and " " in tip:
        tip = f"{tip.split(' ', 1)[0]} {name}"
    _mark_link(name_cell, link.location, tip or name)


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
        index = workbook.sheetnames.index(sheet.title) + 1
        key = f"S{index}"
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


def _indexed_column(sheet, header_row: int, column: int) -> dict[str, list[tuple[int, int]]]:
    found: dict[str, list[tuple[int, int]]] = {}
    if not header_row or not column:
        return found
    for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
        text = _text(sheet.cell(row, column).value)
        if text.upper() in _LINK_SKIP or len(text) < 2:
            continue
        found.setdefault(text, []).append((row, column))
    return found


def _follow_cell(cell, source) -> None:
    """关联页的名称引用总表这一格。总表改名后，引用它的格子一起变。"""
    if isinstance(cell.value, str) and str(cell.value).startswith("="):
        return
    if _text(cell.value) != _text(source.value):
        return
    ref = _sheet_cell(source.parent.title, source.row, source.column)
    cell.value = f'=IF({ref}="","",{ref})'


def _tie_name_column(detail, detail_row: int, source) -> None:
    """这一行里每个信号名、端口名都引用总表名称。总表改名后，后面各页一起变。"""
    width = min(detail.max_column or 1, 40)
    found: list[tuple[int, int]] = []
    seen: set[int] = set()
    for row in range(1, 9):
        for col in range(1, width + 1):
            if col in seen:
                continue
            text = _text(detail.cell(row, col).value).casefold()
            if text.startswith(("signal name", "pin definition", "fuction des", "function des")):
                seen.add(col)
                found.append((row, col))
    ref = _sheet_cell(source.parent.title, source.row, source.column)
    formula = f'=IF({ref}="","",{ref})'
    for header, name_col in found:
        if detail_row <= header:
            continue
        target = detail.cell(detail_row, name_col)
        if isinstance(target.value, str) and target.value.startswith("="):
            continue
        target.value = formula
        target.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        width = detail.column_dimensions[get_column_letter(name_col)].width or 18
        capacity = max(int(width) - 1, 8)
        lines = max(1, (_units(source.value) + capacity - 1) // capacity)
        _grow_row(detail, detail_row, lines)


def _link_tip(first_row: int, label: str) -> str:
    return f"第{first_row}行 {label}"


def _jump_label(sheet, row: int) -> str:
    return f"{sheet.title} 第{row}行"


def _sheet_a1(sheet, row: int) -> str:
    safe = sheet.title.replace("'", "''")
    return f"'{safe}'!A{row}"


def _jump_pairs(workbook: Workbook, hits: list[tuple]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for target_sheet, target_row, _column in hits:
        label = _jump_label(target_sheet, target_row)
        if label in seen:
            continue
        seen.add(label)
        pairs.append((label, _sheet_a1(target_sheet, target_row)))
        _row_anchor(workbook, target_sheet, target_row)
    return pairs


_JUMP_INDEX = "跳转索引"


def _build_jump_index(workbook: Workbook, port, entries: list[dict]) -> None:
    """点端口格先到索引，再点其中一条蓝字打开那一行。"""
    if not entries:
        return
    if _JUMP_INDEX in workbook.sheetnames:
        del workbook[_JUMP_INDEX]
    index = workbook.create_sheet(_JUMP_INDEX)
    index["A1"] = "跳转索引"
    index["A1"].font = Font(bold=True, size=14)
    index["A2"] = "点下面的蓝字打开对应行。点分组标题回到端口表。"
    index.column_dimensions["A"].width = 36
    index.column_dimensions["B"].width = 28
    index.freeze_panes = "A4"
    row = 4
    safe_index = _JUMP_INDEX.replace("'", "''")
    for entry in entries:
        hits = entry["hits"]
        title = index.cell(row, 1, f"{entry['label']}（{len(hits)} 处）")
        title.font = Font(bold=True)
        _mark_link(
            title,
            _row_anchor(workbook, port, entry["port_row"]),
            f"回到第{entry['port_row']}行 {entry['label']}",
        )
        _mark_link(
            entry["cell"],
            f"'{safe_index}'!A{row}",
            f"{len(hits)} 处",
        )
        row += 1
        seen: set[str] = set()
        for target_sheet, target_row, _column in hits:
            label = _jump_label(target_sheet, target_row)
            if label in seen:
                continue
            seen.add(label)
            link = index.cell(row, 1, label)
            _mark_link(link, _row_anchor(workbook, target_sheet, target_row), label)
            index.cell(row, 2, target_sheet.title)
            row += 1
        row += 1


def _column_kind(text: str) -> str:
    folded = text.casefold().strip()
    if folded.startswith("signal name") or folded.startswith("pin definition") or folded.startswith("fuction des") or folded.startswith("function des"):
        return "name"
    if folded == "net name":
        return "net"
    if folded in {"pin", "symbol", "pin_symbol"} or folded.startswith("mcu_pin"):
        return "symbol"
    if folded.startswith("ball"):
        return "ball"
    return ""


def _detail_indexes(workbook: Workbook, port) -> list[tuple]:
    """总表之后各页里，名称、引脚、网络各自对上的全部行。"""
    found: list[tuple] = []
    for name in workbook.sheetnames:
        sheet = workbook[name]
        if sheet is port or name in {"Cover", "0_硬件版本识别", "1_Chang History"}:
            continue
        if name.startswith("WpsReserved"):
            continue
        seen: set[tuple[str, int]] = set()
        for row in range(1, 8):
            for column in range(1, min(sheet.max_column or 1, 24) + 1):
                kind = _column_kind(_text(sheet.cell(row, column).value))
                if not kind or (kind, column) in seen:
                    continue
                seen.add((kind, column))
                found.append((kind, sheet, _indexed_column(sheet, row, column)))
    return found


def _link_detail_sheets(workbook: Workbook) -> None:
    """一个端口名可以跳到后面每一张对得上的表。那些格子引用总表名称，改名会联动。"""
    port = _port_sheet(workbook)
    if port is None:
        return
    layout = _port_layout(port)
    indexes = _detail_indexes(workbook, port)
    used: set[tuple[str, int, int]] = set()

    def targets(kind: str, key: str) -> list[tuple]:
        rows: list[tuple] = []
        if not key or key.upper() in _LINK_SKIP:
            return rows
        for index_kind, sheet, mapping in indexes:
            if index_kind != kind or key not in mapping:
                continue
            for row, column in mapping[key]:
                mark = (sheet.title, row, column)
                if mark in used:
                    continue
                used.add(mark)
                rows.append((sheet, row, column))
        return rows

    def bind(port_cell, hits: list[tuple], port_row: int, label: str, follow=None, name_source=None, follow_value: bool = True) -> list[tuple]:
        if not hits:
            return []
        source = follow or port_cell
        if len(hits) == 1:
            _mark_link(port_cell, _row_anchor(workbook, hits[0][0], hits[0][1]), _link_tip(hits[0][1], label))
        for detail, detail_row, detail_col in hits:
            detail_cell = detail.cell(detail_row, detail_col)
            _mark_link(
                detail_cell,
                _row_anchor(workbook, port, port_row),
                f"第{port_row}行 {label}",
            )
            if follow_value:
                _follow_cell(detail_cell, source)
            if name_source is not None:
                _tie_name_column(detail, detail_row, name_source)
        return hits if len(hits) > 1 else []

    symbol_col, ball_col = _placed_symbol_ball(port, layout)
    pending: list[dict] = []
    for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
        symbol = _text(port.cell(row, symbol_col).value)
        ball = _text(port.cell(row, ball_col).value)
        name_cell = port.cell(row, layout.name) if layout.name else None
        name = _text(name_cell.value) if name_cell is not None else ""
        net = _text(port.cell(row, layout.net).value) if layout.net else ""
        pending.append({
            "row": row,
            "symbol": symbol,
            "ball": ball,
            "name": name,
            "net": net,
            "name_hits": targets("name", name),
            "symbol_hits": targets("symbol", symbol),
            "ball_hits": targets("ball", ball) if ball else [],
            "net_hits": targets("net", net) if layout.net else [],
        })
    entries: list[dict] = []
    for item in pending:
        row = item["row"]
        symbol = item["symbol"]
        name = item["name"]
        name_cell = port.cell(row, layout.name) if layout.name else None
        if name_cell is not None and len(item["name_hits"]) == 1:
            bind(name_cell, item["name_hits"], row, name, name_cell, name_cell)
        elif name_cell is not None and len(item["name_hits"]) > 1:
            entries.append({
                "cell": name_cell,
                "label": name,
                "port_row": row,
                "hits": item["name_hits"],
            })
            for detail, detail_row, detail_col in item["name_hits"]:
                detail_cell = detail.cell(detail_row, detail_col)
                _mark_link(detail_cell, _row_anchor(workbook, port, row), f"第{row}行 {name}")
                _follow_cell(detail_cell, name_cell)
                _tie_name_column(detail, detail_row, name_cell)
        if len(item["symbol_hits"]) > 1:
            symbol_cell = port.cell(row, symbol_col)
            entries.append({
                "cell": symbol_cell,
                "label": symbol,
                "port_row": row,
                "hits": item["symbol_hits"],
            })
            for detail, detail_row, detail_col in item["symbol_hits"]:
                detail_cell = detail.cell(detail_row, detail_col)
                _mark_link(detail_cell, _row_anchor(workbook, port, row), f"第{row}行 {symbol}")
                _follow_cell(detail_cell, symbol_cell)
                if name_cell is not None:
                    _tie_name_column(detail, detail_row, name_cell)
        else:
            bind(port.cell(row, symbol_col), item["symbol_hits"], row, symbol, name_source=name_cell)
        if item["ball"]:
            bind(port.cell(row, ball_col), item["ball_hits"], row, item["ball"], name_source=name_cell, follow_value=False)
        if layout.net:
            bind(port.cell(row, layout.net), item["net_hits"], row, item["net"])
    _build_jump_index(workbook, port, entries)
    if layout.name:
        for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
            name_cell = port.cell(row, layout.name)
            if name_cell.hyperlink is not None:
                continue
            if isinstance(name_cell.value, str) and name_cell.value.startswith("="):
                continue
            _share_symbol_jump(name_cell, port.cell(row, symbol_col))




def _install_jump_combos(path: Path, specs: list[dict]) -> None:
    """在名称格右侧放一个始终看得见的下拉箭头。点名称时按所选行跳转。"""
    if not specs:
        return
    import re
    import zipfile

    path = Path(path)
    with zipfile.ZipFile(path, "r") as zin:
        infos = zin.infolist()
        files = {info.filename: zin.read(info.filename) for info in infos}
    workbook_xml = files["xl/workbook.xml"].decode("utf-8")
    rid = ""
    for tag in re.findall(r"<sheet\b[^>]*/>", workbook_xml):
        name = re.search(r'name="([^"]*)"', tag)
        found = re.search(r'r:id="(rId\d+)"', tag)
        if name and found and name.group(1).startswith("2_Port"):
            rid = found.group(1)
            break
    if not rid:
        return
    book_rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    target = re.search(rf'Id="{rid}"[^>]*Target="([^"]+)"', book_rels)
    if target is None:
        target = re.search(rf'Target="([^"]+)"[^>]*Id="{rid}"', book_rels)
    if target is None:
        return
    sheet_path = "xl/" + target.group(1).replace("\\", "/").lstrip("/")
    if sheet_path.startswith("xl/xl/"):
        sheet_path = sheet_path[3:]
    if sheet_path not in files:
        return
    rel_path = sheet_path.replace("worksheets/", "worksheets/_rels/") + ".rels"
    rel_xml = files.get(rel_path, b"").decode("utf-8")
    if not rel_xml:
        rel_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            "</Relationships>"
        )
    used = [int(item) for item in re.findall(r'Id="rId(\d+)"', rel_xml)]
    new_id = f"rId{max(used) + 1 if used else 1}"
    rel_xml = rel_xml.replace(
        "</Relationships>",
        f'<Relationship Id="{new_id}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/vmlDrawing" '
        'Target="../drawings/vmlDrawingHsiJump.vml"/></Relationships>',
    )
    files[rel_path] = rel_xml.encode("utf-8")
    shapes = []
    for index, spec in enumerate(specs, start=1):
        anchor = spec["anchor"]
        shapes.append(
            f'<v:shape id="_x0000_s{2048 + index}" o:spid="_x0000_s{2048 + index}" type="#_x0000_t201" '
            f'style="position:absolute;margin-left:0;margin-top:0;width:16pt;height:14pt;z-index:{index}" '
            f'filled="t" fillcolor="#D6EAF8" stroked="t" strokecolor="#1A5276" o:insetmode="auto">'
            f'<x:ClientData ObjectType="Drop"><x:MoveWithCells/><x:SizeWithCells/>'
            f"<x:Anchor>{anchor}</x:Anchor>"
            f"<x:AutoFill>False</x:AutoFill><x:Locked>False</x:Locked>"
            f"<x:FmlaRange>{spec['list_ref']}</x:FmlaRange>"
            f"<x:LinkedCell>{spec['linked']}</x:LinkedCell>"
            f"<x:DropStyle>Combo</x:DropStyle><x:DropLines>8</x:DropLines>"
            f"<x:NoThreeD/></x:ClientData></v:shape>"
        )
    vml = (
        '<xml xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:x="urn:schemas-microsoft-com:office:excel">'
        '<o:shapelayout v:ext="edit"><o:idmap v:ext="edit" data="2"/></o:shapelayout>'
        '<v:shapetype id="_x0000_t201" coordsize="21600,21600" o:spt="201" '
        'path="m,l,21600r21600,l21600,xe"><v:stroke joinstyle="miter"/>'
        '<v:path shadowok="f" o:connecttype="rect"/></v:shapetype>'
        + "".join(shapes)
        + "</xml>"
    )
    files["xl/drawings/vmlDrawingHsiJump.vml"] = vml.encode("utf-8")
    sheet_xml = files[sheet_path].decode("utf-8")
    if "legacyDrawing" not in sheet_xml:
        sheet_xml = sheet_xml.replace(
            "</worksheet>",
            f'<legacyDrawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{new_id}"/></worksheet>',
        )
        files[sheet_path] = sheet_xml.encode("utf-8")
    ctypes = files["[Content_Types].xml"].decode("utf-8")
    extra = ""
    if 'Extension="vml"' not in ctypes:
        extra += (
            '<Default Extension="vml" '
            'ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>'
        )
    if "vmlDrawingHsiJump.vml" not in ctypes:
        extra += (
            '<Override PartName="/xl/drawings/vmlDrawingHsiJump.vml" '
            'ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/>'
        )
    if extra:
        files["[Content_Types].xml"] = ctypes.replace("</Types>", extra + "</Types>").encode("utf-8")
    tmp = path.with_suffix(".tmp.xlsx")
    known = {info.filename for info in infos}
    with zipfile.ZipFile(tmp, "w") as zout:
        for info in infos:
            zout.writestr(info, files[info.filename])
        for name, data in files.items():
            if name not in known:
                zout.writestr(name, data)
    tmp.replace(path)


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


def _signal_key(name: str) -> str:
    """端口名和原理图网络对齐。去掉分隔符，并丢掉夹在中间的单字母。"""
    parts = re.split(r"[^A-Za-z0-9]+", (name or "").upper())
    kept = [part for part in parts if len(part) > 1]
    return "".join(kept)


def _archive_edif_onto_template(workbook: Workbook, schematic: Path) -> int:
    """模板行原样留下。只改对上的原理图网络和外部电阻，并记下和端口名的交叉差异。"""
    port = _port_sheet(workbook)
    if port is None:
        return 0
    layout = _port_layout(port)
    symbol_col, _ball_col = _placed_symbol_ball(port, layout)
    external = _external_state_column(port, layout.header)
    net_col = layout.net or layout.name
    name_col = layout.name
    if not net_col:
        return 0
    hits = read_schematic(schematic)
    board = read_board_pins(schematic)
    if not hits and not board:
        return 0
    last = port.max_row or layout.header
    data_rows = [
        row
        for row in range(layout.data_start, last + 1)
        if _text(port.cell(row, symbol_col).value) or (name_col and _text(port.cell(row, name_col).value))
    ]
    by_key: dict[str, list[int]] = {}
    for row in data_rows:
        pieces = [
            _text(port.cell(row, name_col).value) if name_col else "",
            _text(port.cell(row, net_col).value),
            _text(port.cell(row, symbol_col).value),
        ]
        for piece in pieces:
            key = _signal_key(piece)
            if len(key) >= 3:
                by_key.setdefault(key, [])
                if row not in by_key[key]:
                    by_key[key].append(row)
    touched: set[int] = set()

    def write_net(row: int, net: str, pulls, port_name: str) -> None:
        if not net:
            return
        before = _text(port.cell(row, net_col).value)
        changed = before != net
        if changed:
            port.cell(row, net_col, net)
        pull = _pull_text(pulls)
        if external and pull and _text(port.cell(row, external).value) != pull:
            port.cell(row, external, pull)
            changed = True
        parts: list[str] = []
        if port_name and port_name != net:
            parts.append(f"交叉：端口名 {port_name}，原理图 {net}")
        if pulls:
            for item in pulls:
                parts.append(f"外部{item.kind} {item.part} {item.value} 至 {item.other}".strip())
        elif changed:
            parts.append("未看到接到电源或地的电阻")
        if changed or parts:
            parts.append("待人工复核")
            mark = port.cell(row, layout.mark)
            current = _text(mark.value)
            text = "；".join(dict.fromkeys(parts))
            if text and text not in current:
                mark.value = f"{current}；{text}" if current else text
            status = port.cell(row, layout.status)
            shown = _text(status.value)
            if STATUS_DRAFT not in shown:
                status.value = f"{shown}；{STATUS_DRAFT}" if shown else STATUS_DRAFT
            touched.add(row)

    for row in data_rows:
        symbol = _text(port.cell(row, symbol_col).value)
        hit = None
        for part in re.split(r"[/]", symbol):
            key = pin_key(part)
            if key and key in hits:
                hit = hits[key]
                break
        if hit is None:
            continue
        port_name = _text(port.cell(row, name_col).value) if name_col else ""
        write_net(row, hit.net, hit.pulls, port_name)
    matched: set[str] = set()
    for pin in board:
        key = _signal_key(pin.net)
        if len(key) < 3:
            continue
        for row in by_key.get(key, []):
            port_name = _text(port.cell(row, name_col).value) if name_col else ""
            write_net(row, pin.net, pin.pulls, port_name)
            matched.add(pin.net)
    if touched:
        _link_repeated_nets(workbook, port, layout, symbol_col, net_col)
    return len(touched)


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
    symbol_col, _ball_col = _placed_symbol_ball(port, layout)
    updated = 0
    for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
        symbol = _text(port.cell(row, symbol_col).value)
        hit = None
        for part in re.split(r"[/]", symbol):
            key = pin_key(part)
            if key and key in found:
                hit = found[key]
                break
        if hit is None:
            continue
        if layout.name:
            port.cell(row, layout.name, hit.net)
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
    _rename_function_description(port, layout)
    _retire_schematic_net_column(port)
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
    """脚号和网络名已经在各自的列里。标记说明只留电阻和待复核。"""
    parts: list[str] = []
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
    _clear_project_banner(port, layout.header)
    placed = _header_symbol_ball(port, layout.header)
    symbol_col = placed[0] if placed else 2
    _unmerge_from(port, layout.data_start)
    _clear_below(port, layout.header)
    _plain_port_sheet(port, layout.header)
    for index, pin in enumerate(pins, start=1):
        row = layout.header + index
        port.cell(row, 1, index)
        port.cell(row, symbol_col, pin.label)
        if layout.name and pin.net:
            port.cell(row, layout.name, pin.net)
        shown = _pull_text(pin.pulls)
        if external and shown:
            port.cell(row, external, shown)
        port.cell(row, layout.status, STATUS_DRAFT)
        if pin.net:
            port.cell(row, layout.mark, _board_note(pin))
        else:
            port.cell(row, layout.mark, "未进入任何网络；待人工复核")
        _write_port_match(
            port,
            layout.header,
            row,
            layout.human,
            _match_text([("脚号", bool(pin.label)), ("网络", bool(pin.net))]),
        )
        for column in (1, symbol_col, layout.net, external, layout.status):
            if not column:
                continue
            cell = port.cell(row, column)
            horizontal = "center" if column == 1 else "left"
            cell.alignment = Alignment(horizontal=horizontal, vertical="center")
    port.cell(layout.header, layout.status, "核对状态")
    port.cell(layout.header, layout.mark, "标记说明")
    port.cell(layout.header, layout.human, "人工修改")
    wrap = {layout.status: 18, layout.mark: 36}
    for index in range(1, len(pins) + 1):
        _wrap_port_row(port, layout.header + index, wrap)
    for column, width in wrap.items():
        port.column_dimensions[get_column_letter(column)].width = width
    if layout.human:
        port.column_dimensions[get_column_letter(layout.human)].width = 18
    last = layout.header + len(pins)
    end_col = (layout.human or 1) + 1
    port.auto_filter.ref = f"A{layout.header}:{get_column_letter(end_col)}{max(last, layout.header)}"
    _rename_function_description(port, layout)
    _retire_schematic_net_column(port)
    _link_repeated_nets(workbook, port, layout, symbol_col, layout.name)
    _plain_port_sheet(port, layout.header, keep_heights=True)
    return len(pins)


def _link_repeated_nets(
    workbook: Workbook, port, layout: _PortLayout, symbol_col: int = 2, net_col: int = 0,
) -> None:
    """同一个网络落在多只脚上时，点网络名打开这些脚。只有一只脚的网络不加链接。"""
    column = net_col or layout.name or layout.net
    if not column:
        return
    groups: dict[str, list[int]] = {}
    for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
        net = _text(port.cell(row, column).value)
        if not net or net.upper() in _LINK_SKIP:
            continue
        groups.setdefault(net, []).append(row)
    repeated = [(net, rows) for net, rows in groups.items() if len(rows) > 1]
    if not repeated:
        return
    if _JUMP_INDEX in workbook.sheetnames:
        del workbook[_JUMP_INDEX]
    index = workbook.create_sheet(_JUMP_INDEX)
    index["A1"] = "跳转索引"
    index["A1"].font = Font(bold=True, size=14)
    index["A2"] = "点下面的蓝字打开对应行。点分组标题回到第一处。"
    index.column_dimensions["A"].width = 36
    index.freeze_panes = "A4"
    cursor = 4
    safe_index = _JUMP_INDEX.replace("'", "''")
    for net, rows in repeated:
        title = index.cell(cursor, 1, f"{net}（{len(rows)} 处）")
        title.font = Font(bold=True)
        _mark_link(title, _row_anchor(workbook, port, rows[0]), f"第{rows[0]}行 {net}")
        location = f"'{safe_index}'!A{cursor}"
        for port_row in rows:
            _mark_link(port.cell(port_row, column), location, f"{len(rows)} 处")
        cursor += 1
        for port_row in rows:
            label = _text(port.cell(port_row, symbol_col).value) or net
            shown = f"第{port_row}行 {label}"
            link = index.cell(cursor, 1, shown)
            _mark_link(link, _row_anchor(workbook, port, port_row), shown)
            cursor += 1
        cursor += 1


def _port_symbol_index(port, layout: _PortLayout, symbol_col: int) -> dict[str, list[int]]:
    """模板已有行按归一化符号建索引，供原理图就地更新。"""
    found: dict[str, list[int]] = {}
    for row in range(layout.data_start, (port.max_row or layout.header) + 1):
        symbol = _text(port.cell(row, symbol_col).value)
        if not symbol:
            continue
        for key in split_symbol_parts(symbol):
            found.setdefault(key, []).append(row)
    return found


def _last_filled_port_row(port, layout: _PortLayout, symbol_col: int) -> int:
    last = layout.header
    for row in range(layout.data_start, (port.max_row or layout.header) + 1):
        if _text(port.cell(row, symbol_col).value) or _text(port.cell(row, 1).value):
            last = row
    return last


def _set_if_changed(cell, value: object) -> bool:
    if value in (None, ""):
        return False
    if _text(cell.value) == _text(value):
        return False
    cell.value = value
    return True


def _write_schematic_symbol_pins(workbook: Workbook, pins: list[SchematicSymbolPin]) -> int:
    """按原理图符号脚就地更新端口表。对得上的行只改变化的格子，对不上的追加，其余模板行不动。"""
    port = _port_sheet(workbook)
    if port is None or not pins:
        return 0
    layout = _port_layout(port)
    symbol_col, ball_col = _placed_symbol_ball(port, layout)
    port.cell(layout.header, layout.status, "核对状态")
    port.cell(layout.header, layout.mark, "标记说明")
    port.cell(layout.header, layout.human, "人工修改")
    if layout.mux and not _text(port.cell(layout.header, layout.mux).value):
        port.cell(layout.header, layout.mux, "复用")
    indexed = _port_symbol_index(port, layout, symbol_col)
    used: set[int] = set()
    cursor = _last_filled_port_row(port, layout, symbol_col)
    touched: list[int] = []
    for pin in pins:
        keys = split_symbol_parts(pin.symbol)
        candidates: list[int] = []
        for key in keys:
            for candidate in indexed.get(key, []):
                if candidate not in candidates:
                    candidates.append(candidate)
        fresh = next((item for item in candidates if item not in used), 0)
        # 同一只脚会再以别名出现，例如 AN17 和 P40.10。别名已经占了模板行时，不再追加。
        row = fresh or (candidates[0] if candidates else 0)
        added = False
        if not row:
            cursor += 1
            row = cursor
            added = True
            stale = [
                str(merged)
                for merged in port.merged_cells.ranges
                if merged.min_row <= row <= merged.max_row
            ]
            for ref in stale:
                port.unmerge_cells(ref)
            port.cell(row, 1, cursor - layout.header)
            port.cell(row, symbol_col, pin.symbol)
        else:
            used.add(row)
        changed = added
        if pin.ball and _set_if_changed(port.cell(row, ball_col), pin.ball):
            changed = True
        symbol_now = _text(port.cell(row, symbol_col).value)
        function_in_symbol = bool(
            pin.function
            and _signal_key(pin.function) in {_signal_key(part) for part in split_symbol_parts(symbol_now)}
        )
        if layout.mux and pin.function and not function_in_symbol and not _text(port.cell(row, layout.mux).value):
            if _set_if_changed(port.cell(row, layout.mux), pin.function):
                changed = True
        if layout.net and pin.net and _set_if_changed(port.cell(row, layout.net), pin.net):
            changed = True
        port_name = _text(port.cell(row, layout.name).value) if layout.name else ""
        cross = bool(pin.function and port_name and _signal_key(pin.function) != _signal_key(port_name))
        if not changed and not cross and not added:
            continue
        if changed or added:
            port.cell(row, layout.status, STATUS_DRAFT)
        parts = [f"原理图 {pin.sheet}"]
        if added:
            parts.append("模板无此符号，已追加")
        if cross:
            parts.append(f"交叉：端口名 {port_name}，符号功能 {pin.function}")
        if not pin.ball:
            parts.append("球号未在符号旁对上")
        if not pin.function:
            parts.append("符号上未标功能")
        parts.append("待人工复核")
        port.cell(row, layout.mark, "；".join(parts))
        for column in (1, symbol_col, ball_col, layout.status):
            if not column:
                continue
            horizontal = "center" if column == 1 else "left"
            port.cell(row, column).alignment = Alignment(horizontal=horizontal, vertical="center")
        if layout.mux and pin.function:
            port.cell(row, layout.mux).alignment = Alignment(wrap_text=True, vertical="center")
        _write_port_match(
            port,
            layout.header,
            row,
            layout.human,
            _match_text([
                ("球号", bool(pin.ball)),
                ("符号", bool(pin.symbol)),
                ("复用", bool(pin.function)),
            ]),
        )
        touched.append(row)
        for key in keys:
            indexed.setdefault(key, []).append(row)
    wrap = {layout.status: 18, layout.mark: 42}
    if layout.mux:
        wrap[layout.mux] = 36
    name_col = _pin_definition_column(layout)
    if name_col:
        wrap[name_col] = 28
        port.column_dimensions[get_column_letter(name_col)].width = 28
    for row in touched:
        _wrap_port_row(port, row, wrap)
    for column, width in wrap.items():
        port.column_dimensions[get_column_letter(column)].width = width
    if symbol_col:
        port.column_dimensions[get_column_letter(symbol_col)].width = 14
    if ball_col:
        port.column_dimensions[get_column_letter(ball_col)].width = 12
    last = max(touched) if touched else layout.header
    end_col = (layout.human or 1) + 1
    port.auto_filter.ref = f"A{layout.header}:{get_column_letter(end_col)}{max(last, layout.header)}"
    _rename_function_description(port, layout)
    return len(touched)


def _patch_spi_symbol_rows(workbook: Workbook, pins: tuple[ChipPin, ...]) -> int:
    """SPI 页只更新符号对得上的行，不清空其余模板行。"""
    sheet = _spi_sheet(workbook)
    if sheet is None or not pins:
        return 0
    header_row = symbol_col = function_col = direction_col = 0
    for row in range(1, 8):
        for col in range(1, 12):
            text = _text(sheet.cell(row, col).value).casefold()
            if text == "pin" and not symbol_col:
                header_row, symbol_col = row, col
            elif text.startswith("pin f") and not function_col:
                function_col = col
            elif text in {"i/o", "io"} and not direction_col:
                direction_col = col
    if not header_row or not symbol_col:
        return 0
    by_symbol: dict[str, int] = {}
    last = header_row
    for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
        symbol = _text(sheet.cell(row, symbol_col).value)
        if not symbol:
            continue
        last = row
        for key in split_symbol_parts(symbol):
            by_symbol.setdefault(key, row)
    updated = 0
    left = Alignment(horizontal="left", vertical="center", wrap_text=False)
    wrapped = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for pin in pins:
        items = _spi_functions(pin)
        if not items:
            continue
        row = 0
        for key in split_symbol_parts(pin.symbol):
            if key in by_symbol:
                row = by_symbol[key]
                break
        if not row:
            last += 1
            row = last
            sheet.cell(row, 1, last - header_row)
            sheet.cell(row, symbol_col, pin.symbol).alignment = left
            for key in split_symbol_parts(pin.symbol):
                by_symbol.setdefault(key, row)
        if function_col:
            sheet.cell(row, function_col, "\n".join(token for token, _io in items)).alignment = wrapped
        directions = [io for _token, io in items]
        if direction_col and any(directions):
            sheet.cell(row, direction_col, "\n".join(directions)).alignment = wrapped
        _grow_row(sheet, row, max(len(items), 1))
        updated += 1
    return updated


def _apply_drawing_chip(sheet, mcu: str, header_row: int) -> None:
    """型号来自原理图上的芯片文字，盖过模板清掉之后的空表头。"""
    if not mcu:
        return
    title = _text(sheet.cell(1, 1).value)
    if "port assignment" in title.casefold() or not title:
        bracket = title[title.index("[") :] if "[" in title else "[Main Table]"
        sheet.cell(1, 1, f"{mcu} Port Assignment {bracket}")
    if not _text(sheet.cell(2, 2).value):
        sheet.cell(2, 2, f"MCU_{mcu}")


def _pin_definition_column(layout: _PortLayout) -> int:
    """网络名写进 Pin Definition。星驱原理图网络这一列不再用。"""
    return layout.name or layout.net


def _rename_function_description(sheet, layout: _PortLayout) -> None:
    """两列都叫 Pin Definition 时，后一列是功能描述。"""
    if not layout.desc or layout.desc == layout.name:
        return
    current = _text(sheet.cell(layout.header, layout.desc).value)
    if current.startswith("Pin Definition"):
        sheet.cell(layout.header, layout.desc, "Pin Function Description")


def _retire_schematic_net_column(sheet) -> None:
    """星驱原理图网络不再作为一列。表头清掉，列藏起来。"""
    layout = _port_layout(sheet)
    if not layout.net:
        return
    header = sheet.cell(layout.header, layout.net)
    header.value = None
    for row in range(layout.data_start, (sheet.max_row or layout.data_start) + 1):
        sheet.cell(row, layout.net).value = None
    sheet.column_dimensions[get_column_letter(layout.net)].hidden = True


def _reset_row_heights(sheet, first: int) -> None:
    """清掉模板留在数据行上的行高。52 和 15 夹在一起时，通道名会叠到下一行。"""
    for key in list(sheet.row_dimensions):
        if isinstance(key, int) and key >= first:
            del sheet.row_dimensions[key]


def _grow_row(sheet, row: int, lines: int) -> None:
    needed = 16 * max(lines, 1) + 6
    current = sheet.row_dimensions[row].height or 0
    if needed > current:
        sheet.row_dimensions[row].height = min(needed, 96)


def _adc_channel_names(pin: ChipPin) -> list[str]:
    found: list[str] = []
    for item in present_mux(pin.mux).split("\n"):
        token = item.split()[0] if item.strip() else ""
        if token and re.search(r"ADC", token, re.I) and token not in found:
            found.append(token)
    return found


_ADC_CONVERTER = re.compile(r"(?:ADC_)?(TMADC\d+)CH\d+|EVADC_(G\d+)CH\d+", re.I)
# 模板 Gr 列：同一组合并，Accent 1 浅色 60%。
_ADC_GROUP_FILL = PatternFill("solid", fgColor="BDD7EE")
_ADC_GROUP_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _adc_group(channels: list[str]) -> str:
    """组号取唯一的 EVADC 组或 TMADC。EDSADC、FC 不另算一组。两路 EVADC 留空。"""
    groups: list[str] = []
    for token in channels:
        matched = _ADC_CONVERTER.search(token)
        if not matched:
            continue
        group = matched.group(1) or matched.group(2) or ""
        if group and group not in groups:
            groups.append(group)
    if len(groups) == 1:
        return groups[0]
    return ""


def _adc_channel_index(channels: list[str], group: str) -> int:
    if not group:
        return 10**6
    for token in channels:
        matched = re.search(rf"{re.escape(group)}CH(\d+)", token, re.I)
        if matched:
            return int(matched.group(1))
    return 10**6


def _merge_adc_groups(sheet, first: int, last: int, group_col: int) -> None:
    """同一组的 Gr 合成一块，组名居中，只给这一列浅蓝。"""
    if not group_col or last < first:
        return
    row = first
    while row <= last:
        label = _text(sheet.cell(row, group_col).value)
        if not label:
            row += 1
            continue
        end = row
        while end + 1 <= last and _text(sheet.cell(end + 1, group_col).value) == label:
            sheet.cell(end + 1, group_col).value = None
            end += 1
        cell = sheet.cell(row, group_col, label)
        cell.fill = _ADC_GROUP_FILL
        cell.alignment = _ADC_GROUP_ALIGN
        thin = Side(style="thin")
        for current in range(row, end + 1):
            sheet.cell(current, group_col).border = Border(
                left=thin,
                right=thin,
                top=thin if current == row else None,
                bottom=thin if current == end else None,
            )
        if end > row:
            sheet.merge_cells(start_row=row, start_column=group_col, end_row=end, end_column=group_col)
        row = end + 1


def _adc_row_order(pin: ChipPin) -> tuple[int, int, int, int, str]:
    channels = _adc_channel_names(pin)
    group = _adc_group(channels)
    if not group:
        return (1, 0, 0, 0, pin.symbol)
    number = int(re.search(r"\d+", group).group(0))
    kind = 0 if group.upper().startswith("G") else 1
    return (0, kind, number, _adc_channel_index(channels, group), pin.symbol)


def _chips_from_schematic(pins: list[SchematicSymbolPin]) -> tuple[ChipPin, ...]:
    """符号上的功能当作这一脚的复用，后面的 ADC、SPI、CAN 表只认这些名字。"""
    return tuple(
        ChipPin("", pin.ball, pin.symbol, "", "", pin.function, pin.function, pin.sheet, "")
        for pin in pins
    )


_MANUAL_PAGES: dict[tuple[str, int], list[tuple[int, str]]] = {}
_MANUAL_PACKAGE: dict[tuple[str, int, str], dict[str, ChipPin]] = {}


def _manual_candidates(mcu: str) -> list[Path]:
    """同一型号的芯片手册 PDF。没有这一本时，ADC 组号保持空白。"""
    token = re.sub(r"[^A-Za-z0-9]", "", mcu or "").lower()
    if not token.startswith("tc") or len(token) < 5:
        return []
    folder = Path(__file__).resolve().parents[2] / "资料" / "MCU 芯片手册"
    if not folder.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(folder.glob("*.pdf")):
        folded = re.sub(r"[^a-z0-9]", "", path.name.lower())
        if token in folded:
            found.append(path)
    return found


def _adc_mux_lines(mux: str) -> list[str]:
    lines: list[str] = []
    for item in present_mux(mux).split("\n"):
        token = item.split()[0] if item.strip() else ""
        if token and re.search(r"ADC", token, re.I) and item not in lines:
            lines.append(item)
    return lines


def _manual_pins_by_ball(mcu: str, balls: set[str]) -> dict[str, ChipPin]:
    """手册引脚按球号索引。封装取和这批球号对上最多的那一个。"""
    wanted = {ball.upper() for ball in balls if ball}
    if not wanted:
        return {}
    best: dict[str, ChipPin] = {}
    best_hits = 0
    for path in _manual_candidates(mcu):
        stamp = path.stat().st_mtime_ns
        key = (str(path), stamp)
        pages = _MANUAL_PAGES.get(key)
        if pages is None:
            pages = read_pdf_pages(path)
            _MANUAL_PAGES[key] = pages
        packages = parse_pin_pages(pages) or ("BGA436",)
        for package in packages:
            cache_key = (str(path), stamp, package)
            rows = _MANUAL_PACKAGE.get(cache_key)
            if rows is None:
                rows = {pin.ball.upper(): pin for pin in parse_pins(pages, package) if pin.ball}
                _MANUAL_PACKAGE[cache_key] = rows
            hits = sum(1 for ball in wanted if ball in rows)
            if hits > best_hits:
                best = rows
                best_hits = hits
            if hits == len(wanted):
                return rows
    return best if best_hits else {}


def _merge_manual_adc(
    pins: list[SchematicSymbolPin],
    chips: tuple[ChipPin, ...],
    by_ball: dict[str, ChipPin],
) -> tuple[ChipPin, ...]:
    """原理图符号上没有转换器名时，把手册里这个球号的 ADC 复用补进通道。"""
    if not by_ball:
        return chips
    by_symbol = {pin.symbol.upper(): pin for pin in by_ball.values() if pin.symbol}
    merged: list[ChipPin] = []
    for pin, chip in zip(pins, chips):
        manual = by_ball.get(pin.ball.upper()) if pin.ball else None
        if manual is None and not pin.ball:
            manual = by_symbol.get(pin.symbol.upper())
        extra = _adc_mux_lines(manual.mux) if manual is not None else []
        if not extra:
            merged.append(chip)
            continue
        text = chip.mux
        seen = set(present_mux(text).split("\n"))
        for line in extra:
            if line not in seen:
                text = f"{text}；{line}" if text else line
                seen.add(line)
        merged.append(replace(chip, mux=text))
    return tuple(merged)


def _chips_with_manual_adc(pins: list[SchematicSymbolPin], mcu: str) -> tuple[ChipPin, ...]:
    chips = _chips_from_schematic(pins)
    return _merge_manual_adc(pins, chips, _manual_pins_by_ball(mcu, {pin.ball for pin in pins}))


def _fill_adc_from_manual(workbook: Workbook, pins: tuple[ChipPin, ...]) -> None:
    """ADC 表只列手册标明有 ADC 的脚，球号和引脚符号与端口表相同。"""
    sheet = _sheet(workbook, "3_ADC Table")
    if sheet is None or not pins:
        return
    header_row = ball_col = channel_col = group_col = 0
    for row in range(1, 8):
        for col in range(1, 16):
            text = _text(sheet.cell(row, col).value).casefold()
            if text.startswith("ball"):
                header_row, ball_col = row, col
            elif text == "channel":
                channel_col = col
            elif text == "gr" and not group_col:
                group_col = col
    if not header_row or not ball_col:
        return
    _clear_adc_group_allocation(sheet)
    _clear_adc_template_constants(sheet, header_row)
    symbol_col = ball_col - 1
    if not _text(sheet.cell(header_row, symbol_col).value):
        sheet.cell(header_row, symbol_col, "PIN")
    signal_cols = [
        col
        for col in range(1, min(sheet.max_column or 1, 40) + 1)
        if _text(sheet.cell(header_row, col).value).replace(" ", "").casefold().startswith("signalname")
    ]
    _reset_row_heights(sheet, header_row + 1)
    _unmerge_from(sheet, header_row + 1)
    left = Alignment(horizontal="left", vertical="center", wrap_text=False)
    wrapped = Alignment(horizontal="left", vertical="center", wrap_text=True)
    adc_pins = sorted((pin for pin in pins if pin_class(pin) == "ADC"), key=_adc_row_order)
    for index, pin in enumerate(adc_pins, start=1):
        row = header_row + index
        number = sheet.cell(row, 1, index)
        number.alignment = Alignment(horizontal="center", vertical="center")
        channels = _adc_channel_names(pin)
        group = _adc_group(channels)
        if group_col and group:
            sheet.cell(row, group_col, group)
        if channel_col and channels:
            channel = sheet.cell(row, channel_col, "\n".join(channels))
            channel.alignment = wrapped
        pin_cell = sheet.cell(row, symbol_col, pin.symbol)
        pin_cell.alignment = left
        ball = sheet.cell(row, ball_col, pin.ball)
        ball.alignment = left
        for col in signal_cols:
            sheet.cell(row, col).alignment = wrapped
        _grow_row(sheet, row, max(len(channels), 1))
    if adc_pins and group_col:
        _merge_adc_groups(sheet, header_row + 1, header_row + len(adc_pins), group_col)


def _spi_sheet(workbook: Workbook):
    for name in workbook.sheetnames:
        if "SPI" in name.upper():
            return workbook[name]
    return None


def _spi_io(text: str) -> str:
    """SPI 功能自己的输入或输出。引脚垫是双向的，不拿来填这一列。"""
    folded = text.casefold()
    has_in = re.search(r"\binputs?\b", folded) is not None
    has_out = re.search(r"\boutputs?\b", folded) is not None
    if has_in and has_out:
        return "Input/Output"
    if has_out:
        return "Output"
    if has_in:
        return "Input"
    return ""


def _spi_functions(pin: ChipPin) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in present_mux(pin.mux).split("\n"):
        token = item.split()[0] if item.strip() else ""
        if not token or not re.match(r"(?:QSPI|SPI)\d", token, re.I) or token in seen:
            continue
        seen.add(token)
        found.append((token, _spi_io(item)))
    return found


def _spi_tokens(pin: ChipPin) -> list[str]:
    return [token for token, _direction in _spi_functions(pin)]


_CAN_TOKEN = re.compile(r"^(?:CANXL|CAN)\d+_(?:TXD|RXD)", re.I)


def _can_functions(pin: ChipPin) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in present_mux(pin.mux).split("\n"):
        token = item.split()[0] if item.strip() else ""
        if not token or not _CAN_TOKEN.match(token) or token in seen:
            continue
        seen.add(token)
        found.append((token, _spi_io(item)))
    return found


def _fill_spi_from_manual(workbook: Workbook, pins: tuple[ChipPin, ...]) -> None:
    """SPI 表只列手册复用里有 QSPI 或 SPI 的脚。项目网络名和波特率留空。"""
    sheet = _spi_sheet(workbook)
    if sheet is None or not pins:
        return
    header_row = symbol_col = function_col = direction_col = 0
    for row in range(1, 8):
        for col in range(1, 12):
            text = _text(sheet.cell(row, col).value).casefold()
            if text == "pin" and not symbol_col:
                header_row, symbol_col = row, col
            elif text.startswith("pin f") and not function_col:
                function_col = col
            elif text in {"i/o", "io"} and not direction_col:
                direction_col = col
    if not header_row or not symbol_col:
        return
    plain = Border()
    for row in range(1, header_row):
        for column in range(1, 6):
            cell = sheet.cell(row, column)
            if "SPI总线" in _text(cell.value):
                cell.value = None
                cell.border = plain
    spi_pins = [pin for pin in pins if _spi_tokens(pin)]
    _reset_row_heights(sheet, header_row + 1)
    left = Alignment(horizontal="left", vertical="center", wrap_text=False)
    wrapped = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for index, pin in enumerate(spi_pins, start=1):
        row = header_row + index
        number = sheet.cell(row, 1, index)
        number.alignment = Alignment(horizontal="center", vertical="center")
        pin_cell = sheet.cell(row, symbol_col, pin.symbol)
        pin_cell.alignment = left
        items = _spi_functions(pin)
        if function_col and items:
            function = sheet.cell(row, function_col, "\n".join(token for token, _io in items))
            function.alignment = wrapped
        directions = [io for _token, io in items]
        if direction_col and any(directions):
            direction = sheet.cell(row, direction_col, "\n".join(directions))
            direction.alignment = wrapped
        _grow_row(sheet, row, max(len(items), 1))


def _fill_can_from_manual(workbook: Workbook, pins: tuple[ChipPin, ...]) -> None:
    """CAN 表只列手册复用里的 TXD/RXD。项目网络名和中文说明留空。"""
    sheet = _sheet(workbook, "6_CAN")
    if sheet is None or not pins:
        return
    rows = [(pin, _can_functions(pin)) for pin in pins]
    rows = [(pin, items) for pin, items in rows if items]
    if not rows:
        return
    for ref in [str(merged) for merged in sheet.merged_cells.ranges]:
        sheet.unmerge_cells(ref)
    for row in range(1, 3):
        for col in range(1, 8):
            sheet.cell(row, col).value = None
    sheet.cell(1, 1, "CAN TXD/RXD")
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    sheet.cell(1, 1).alignment = Alignment(horizontal="left", vertical="center")
    for col, title in enumerate(("PIN", "PIN Fuction", "I/O", "Net Name", "Fuction Des"), start=2):
        sheet.cell(2, col, title)
    for letter, width in (("A", 8), ("B", 14), ("C", 22), ("D", 16), ("E", 22), ("F", 28)):
        sheet.column_dimensions[letter].width = width
    for row in range(3, (sheet.max_row or 2) + 1):
        for col in range(1, 8):
            cell = sheet.cell(row, col)
            if cell.value not in (None, ""):
                cell.value = None
    _reset_row_heights(sheet, 3)
    left = Alignment(horizontal="left", vertical="center", wrap_text=False)
    wrapped = Alignment(horizontal="left", vertical="center", wrap_text=True)
    for index, (pin, items) in enumerate(rows, start=1):
        row = 2 + index
        number = sheet.cell(row, 1, index)
        number.alignment = Alignment(horizontal="center", vertical="center")
        pin_cell = sheet.cell(row, 2, pin.symbol)
        pin_cell.alignment = left
        function = sheet.cell(row, 3, "\n".join(token for token, _io in items))
        function.alignment = wrapped
        directions = [io for _token, io in items]
        if any(directions):
            direction = sheet.cell(row, 4, "\n".join(directions))
            direction.alignment = wrapped
        _grow_row(sheet, row, max(len(items), 1))


def _clear_adc_group_allocation(sheet) -> None:
    """组号、项目通道、信号名和组×通道对照是上一份项目的分配，确认前清掉。"""
    from openpyxl.cell.cell import MergedCell

    header_row = gr_col = channel_col = 0
    signal_cols: list[int] = []
    width = min(sheet.max_column or 1, 40)
    for row in range(1, 8):
        for col in range(1, width + 1):
            compact = _text(sheet.cell(row, col).value).replace(" ", "").casefold()
            if compact == "gr" and not gr_col:
                header_row, gr_col = row, col
            elif compact == "channel" and not channel_col:
                channel_col = col
            elif compact.startswith("signalname") and col not in signal_cols:
                signal_cols.append(col)
    plain = Border()

    def wipe(cell) -> None:
        if isinstance(cell, MergedCell) or cell.value in (None, ""):
            return
        if _text(cell.value).startswith("="):
            return
        cell.value = None
        cell.border = plain

    last_row = sheet.max_row or 1
    if header_row and gr_col:
        for row in range(header_row + 1, last_row + 1):
            wipe(sheet.cell(row, gr_col))
    if header_row and channel_col:
        for row in range(header_row + 1, last_row + 1):
            cell = sheet.cell(row, channel_col)
            if isinstance(cell, MergedCell):
                continue
            if re.fullmatch(r"Ch\d+", _text(cell.value), re.I):
                wipe(cell)
    for col in signal_cols:
        if not header_row:
            break
        for row in range(header_row + 1, last_row + 1):
            wipe(sheet.cell(row, col))
    for row in range(1, last_row + 1):
        label = _text(sheet.cell(row, 1).value)
        if label.casefold() == "group" or re.fullmatch(r"Gr\d+", label, re.I):
            for col in range(1, width + 1):
                wipe(sheet.cell(row, col))
            continue
        for col in range(1, width + 1):
            cell = sheet.cell(row, col)
            if isinstance(cell, MergedCell):
                continue
            text = _text(cell.value)
            if "current sense" in text.casefold() or text.startswith("不可用通道"):
                wipe(cell)


def _clear_adc_template_constants(sheet, header_row: int) -> None:
    """阻容、时间常数是模板示例，手册里没有，数据行清掉，表头留下。"""
    from openpyxl.cell.cell import MergedCell

    columns: list[int] = []
    for column in range(1, min(sheet.max_column or 1, 40) + 1):
        text = _text(sheet.cell(header_row, column).value).replace(" ", "").casefold()
        if text.startswith(("r1(", "c1(", "r2(", "c2(", "r3(", "τ", "tau")):
            columns.append(column)
    if not columns:
        return
    plain = Border()
    for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
        for column in columns:
            cell = sheet.cell(row, column)
            if isinstance(cell, MergedCell):
                continue
            cell.value = None
            cell.border = plain


_HSI_KEYWORDS = ("水温", "CAN", "LIN")


def hsi_keyword_hits(text: str) -> list[str]:
    """水温、CAN、LIN 这些固定词出现在当份文字里时，这条信号要进入 HSI。"""
    raw = text or ""
    folded = raw.upper()
    found: list[str] = []
    for word in _HSI_KEYWORDS:
        if word.isascii():
            if re.search(rf"(?<![A-Z]){word}(?![A-Z])", folded) and word not in found:
                found.append(word)
        elif word in raw and word not in found:
            found.append(word)
    return found


def _adc_signal_name_columns(sheet) -> tuple[int, list[int]]:
    header_row = 0
    columns: list[int] = []
    width = min(sheet.max_column or 1, 40)
    for row in range(1, 8):
        for col in range(1, width + 1):
            compact = _text(sheet.cell(row, col).value).replace(" ", "").casefold()
            if compact.startswith("signalname"):
                header_row = row
                if col not in columns:
                    columns.append(col)
    return header_row, columns


def _hide_adc_signal_names(workbook: Workbook) -> None:
    """手册出表不显示 ADC 信号名。这一列要等原理图才能填写。"""
    sheet = _sheet(workbook, "3_ADC Table")
    if sheet is None:
        return
    header_row, columns = _adc_signal_name_columns(sheet)
    if not header_row:
        return
    for col in columns:
        for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
            cell = sheet.cell(row, col)
            if cell.value not in (None, ""):
                cell.value = None
        sheet.column_dimensions[get_column_letter(col)].hidden = True


def _fill_adc_signal_names_from_port(workbook: Workbook) -> None:
    """有原理图时，把端口表上对上的网络名写入 ADC 信号名。没对上的格子留空。"""
    sheet = _sheet(workbook, "3_ADC Table")
    port = _port_sheet(workbook)
    if sheet is None or port is None:
        return
    header_row, columns = _adc_signal_name_columns(sheet)
    if not header_row or not columns:
        return
    layout = _port_layout(port)
    symbol_col, _ball_col = _placed_symbol_ball(port, layout)
    net_col = layout.net or layout.name
    names: dict[str, str] = {}
    if net_col:
        for row in range(layout.data_start, (port.max_row or layout.data_start) + 1):
            symbol = _text(port.cell(row, symbol_col).value)
            net = _text(port.cell(row, net_col).value)
            if not symbol or not net:
                continue
            for key in split_symbol_parts(symbol):
                names.setdefault(key, net)
    pin_col = 0
    for col in range(1, min(sheet.max_column or 1, 12) + 1):
        compact = _text(sheet.cell(header_row, col).value).replace(" ", "").casefold()
        if compact in {"pin", "pin_symbol"} or compact.startswith("ball"):
            if compact.startswith("ball"):
                pin_col = pin_col or col - 1
            elif not pin_col:
                pin_col = col
    if not pin_col:
        pin_col = 4
    for col in columns:
        sheet.column_dimensions[get_column_letter(col)].hidden = False
        for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
            symbol = _text(sheet.cell(row, pin_col).value)
            if not symbol:
                continue
            net = ""
            for key in split_symbol_parts(symbol):
                if key in names:
                    net = names[key]
                    break
            if net:
                sheet.cell(row, col, net)
            elif sheet.cell(row, col).value not in (None, ""):
                sheet.cell(row, col).value = None


def _hide_adc_spare_columns(workbook: Workbook) -> None:
    """ADC 表里这版不参与复核的 R1、R3 列隐藏。模板里的阻容数值另清。"""
    sheet = _sheet(workbook, "3_ADC Table")
    if sheet is None:
        return
    for row in range(1, 8):
        for column in range(1, min(sheet.max_column or 1, 40) + 1):
            compact = _text(sheet.cell(row, column).value).replace(" ", "")
            if compact.startswith("R1(") or compact.startswith("R3("):
                sheet.column_dimensions[get_column_letter(column)].hidden = True


_EXAMPLE_TEXT = re.compile(
    r"P\d{1,2}\.\d|HSR_|SIC_TYPE|士兰微|底盘CAN|驱动芯片均使用|真值表|上桥FW|MBit|HW\d|如下示意图|600uA|内部电流源|待更新NTC|TEMP_|AN\d+|SCHEMATIC|原理图|正常工作|详见|油温",
    re.I,
)
_KEEP_BESIDE_EXAMPLE = frozenset({"死区时间", "μs", "µs", "us"})


def _example_cell(value: object) -> bool:
    """表头区里的模板示例：句子、公式、日期、数值和上一份项目的信号。"""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, datetime)):
        return True
    text = _text(value)
    if not text:
        return False
    if text.startswith("="):
        return True
    if "。" in text or "；" in text or len(text) > 40:
        return True
    return _EXAMPLE_TEXT.search(text) is not None


def _strip_header_examples(sheet) -> None:
    """前几行只留列名和表名。模板写在表头区的示例行、公式和说明清掉。"""
    stale = [
        str(merged)
        for merged in sheet.merged_cells.ranges
        if merged.min_row <= 8 and _example_cell(sheet.cell(merged.min_row, merged.min_col).value)
    ]
    for ref in stale:
        sheet.unmerge_cells(ref)
    plain_fill = PatternFill(fill_type=None)
    plain_border = Border()
    width = min(sheet.max_column or 1, 80)
    for row in range(1, min(sheet.max_row or 1, 8) + 1):
        cells = [sheet.cell(row, col) for col in range(1, width + 1) if sheet.cell(row, col).value not in (None, "")]
        if not any(_example_cell(cell.value) for cell in cells):
            continue
        for cell in cells:
            if _text(cell.value) in _KEEP_BESIDE_EXAMPLE:
                continue
            cell.value = None
            if cell.hyperlink is not None:
                cell.hyperlink = None
            if _painted_cell(cell):
                cell.fill = plain_fill
                cell.border = plain_border
    from openpyxl.cell.cell import MergedCell

    for row in range(1, min(sheet.max_row or 1, 8) + 1):
        for col in range(1, width + 1):
            cell = sheet.cell(row, col)
            if isinstance(cell, MergedCell):
                continue
            if _text(cell.value) == "c":
                cell.value = None


def _painted_cell(cell) -> bool:
    fill = cell.fill
    if fill is not None and fill.patternType not in (None, "none"):
        return True
    border = cell.border
    return any(getattr(getattr(border, side), "style", None) for side in ("left", "right", "top", "bottom"))


def _drop_detail_chrome(sheet, header: int) -> None:
    """模板嵌图和空表的底色、边框不是这次网表读出来的。"""
    sheet._images.clear()
    sheet.conditional_formatting._cf_rules.clear()
    _drop_column_fills(sheet)
    plain_fill = PatternFill(fill_type=None)
    plain_border = Border()
    if (sheet.max_row or header) > header:
        for row in sheet.iter_rows(
            min_row=header + 1,
            max_row=sheet.max_row,
            max_col=sheet.max_column or 1,
        ):
            for cell in row:
                if _painted_cell(cell):
                    cell.fill = plain_fill
                    cell.border = plain_border
    for key, dim in list(sheet.row_dimensions.items()):
        if not isinstance(key, int) or key <= header:
            continue
        if dim.fill is not None and dim.fill.patternType not in (None, "none"):
            dim.fill = plain_fill
    view = sheet.sheet_view
    view.view = "normal"
    view.topLeftCell = "A1"


def _clear_template_detail_rows(workbook: Workbook, *, drop_template_chrome: bool = False) -> None:
    """模板各页只留表头。上一份项目的信号名、公式和最大最小值不再显示。"""
    if not _keeps_template_body(workbook):
        return
    skip = {
        SHEET_COVER,
        "Cover",
        "0_Cover",
        SHEET_HISTORY,
        "1_Chang History",
        SHEET_EVIDENCE,
        SHEET_CONSTRAINT,
        SHEET_REVISION,
        SHEET_ACCEPT,
        _JUMP_INDEX,
    }
    port = _port_sheet(workbook)
    for name in workbook.sheetnames:
        if name in skip or name.startswith("WpsReserved") or name.startswith("2_Port"):
            continue
        sheet = workbook[name]
        if port is not None and sheet is port:
            continue
        if drop_template_chrome:
            _strip_header_examples(sheet)
            header = 8
        else:
            header = 1
            best = 0
            limit = min(sheet.max_row or 1, 8)
            width = min(sheet.max_column or 1, 40)
            for row in range(1, limit + 1):
                count = sum(1 for col in range(1, width + 1) if _text(sheet.cell(row, col).value))
                if count > best:
                    header, best = row, count
        stale = [str(merged) for merged in sheet.merged_cells.ranges if merged.min_row > header]
        for ref in stale:
            sheet.unmerge_cells(ref)
        if drop_template_chrome:
            _drop_detail_chrome(sheet, header)
        if (sheet.max_row or header) > header:
            for row in sheet.iter_rows(
                min_row=header + 1,
                max_row=sheet.max_row,
                max_col=sheet.max_column or 1,
            ):
                for cell in row:
                    if cell.value not in (None, ""):
                        cell.value = None
                    if cell.hyperlink is not None:
                        cell.hyperlink = None
        if drop_template_chrome:
            _drop_empty_boxes(sheet)
        if name.startswith("3_ADC"):
            _clear_adc_group_allocation(sheet)


def _drop_empty_boxes(sheet) -> None:
    """没有字的合并区域和黑框清掉。有字的表头边框留下。"""
    from openpyxl.cell.cell import MergedCell

    stale = [
        str(merged)
        for merged in sheet.merged_cells.ranges
        if sheet.cell(merged.min_row, merged.min_col).value in (None, "")
    ]
    for ref in stale:
        sheet.unmerge_cells(ref)
    plain = Border()
    width = min(sheet.max_column or 1, 80)
    for row in sheet.iter_rows(max_row=sheet.max_row or 1, max_col=width):
        for cell in row:
            if isinstance(cell, MergedCell) or cell.value not in (None, ""):
                continue
            border = cell.border
            if any(getattr(getattr(border, side), "style", None) for side in ("left", "right", "top", "bottom")):
                cell.border = plain


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


def _clear_project_banner(sheet, header_row: int) -> None:
    """表头里的项目名不是这次的端口名。Pin Definition 列名留下。"""
    for row in range(1, header_row + 1):
        for col in range(1, 20):
            text = _text(sheet.cell(row, col).value)
            if "superevo" in text.casefold():
                sheet.cell(row, col).value = None


def _stamp_port_names(sheet, mcu: str, package: str, header_row: int) -> None:
    """表头上的型号和封装跟这次选择走，不留模板里的 TC499、BGA436。"""
    if not mcu and not package:
        return
    title = _text(sheet.cell(1, 1).value)
    if mcu and "port assignment" in title.casefold():
        bracket = title[title.index("[") :] if "[" in title else "[Main Table]"
        sheet.cell(1, 1, f"{mcu} Port Assignment {bracket}")
    for row in range(1, header_row + 1):
        for col in range(1, 12):
            text = _text(sheet.cell(row, col).value)
            if mcu and text.upper().startswith("MCU_"):
                sheet.cell(row, col, f"MCU_{mcu}")
            elif package and "\\" in text and "ball" in text.casefold():
                suffix = text.split("\\", 1)[1]
                sheet.cell(row, col, f"{package}\\{suffix}")


def _stamp_adc_mcu(workbook: Workbook, mcu: str) -> None:
    if not mcu:
        return
    sheet = _sheet(workbook, "3_ADC Table")
    if sheet is None:
        return
    for row in range(1, 4):
        for col in range(1, 6):
            text = _text(sheet.cell(row, col).value)
            if text.upper().startswith("MCU_"):
                sheet.cell(row, col, f"MCU_{mcu}")


def _write_ports_v13(
    sheet,
    layout: _PortLayout,
    mcu: str,
    package: str,
    drafts: list[tuple[_PortRow, str, str]],
    pins: tuple[ChipPin, ...],
    human: dict[str, object],
    usages: dict[str, str] | None = None,
) -> None:
    """DHTE400：格子写手册上的符号、球号、缓冲、方向和复用。功能列写对得上的模板用法。"""
    _clear_project_banner(sheet, layout.header)
    _stamp_port_names(sheet, mcu, package, layout.header)
    sheet.cell(layout.header, layout.mux, "复用")
    _rename_function_description(sheet, layout)
    sheet.cell(layout.header, layout.page, "页码")
    sheet.cell(layout.header, layout.excerpt, "原文摘录")
    sheet.cell(layout.header, layout.status, "核对状态")
    sheet.cell(layout.header, layout.mark, "标记说明")
    sheet.cell(layout.header, layout.human, "人工修改")
    _unmerge_from(sheet, layout.data_start)
    _clear_below(sheet, layout.header)
    _plain_port_sheet(sheet, layout.header)
    excerpts = {pin.symbol: pin.excerpt for pin in pins}
    by_symbol = {pin.symbol: pin for pin in pins}
    placed = _header_symbol_ball(sheet, layout.header)
    symbol_col, ball_col = placed if placed else (2, 3)
    wrap = {layout.mux: 56, layout.excerpt: 56, layout.status: 18, layout.mark: 36}
    for index, (row, status, note) in enumerate(drafts, start=1):
        excel_row = layout.header + index
        sheet.cell(excel_row, 1, index)
        sheet.cell(excel_row, ball_col, row.ball)
        sheet.cell(excel_row, symbol_col, row.symbol)
        sheet.cell(excel_row, 4, row.buffer or None)
        sheet.cell(excel_row, 5, row.pull or None)
        sheet.cell(excel_row, 6, row.supply or None)
        if layout.direction and row.direction:
            sheet.cell(excel_row, layout.direction, row.direction)
        usage = (usages or {}).get(row.symbol, "")
        if layout.function and usage:
            sheet.cell(excel_row, layout.function, usage)
        name = _project_name(row.project)
        if layout.name and name:
            sheet.cell(excel_row, layout.name, name)
        desc = _field(row.project, 1)
        if layout.desc and desc:
            sheet.cell(excel_row, layout.desc, desc)
        sheet.cell(excel_row, layout.mux, present_mux(row.mux))
        sheet.cell(excel_row, layout.page, row.page)
        sheet.cell(excel_row, layout.excerpt, present_excerpt(excerpts.get(row.symbol, "")))
        sheet.cell(excel_row, layout.status, status)
        if note:
            sheet.cell(excel_row, layout.mark, note)
        if row.symbol in human:
            sheet.cell(excel_row, layout.human, human[row.symbol])
        _write_port_match(
            sheet,
            layout.header,
            excel_row,
            layout.human,
            _match_text([
                ("球号", bool(row.ball)),
                ("符号", bool(row.symbol)),
                ("复用", bool(present_mux(row.mux))),
                ("方向", bool(row.direction)),
            ]),
        )
        if pin_supply_kind(row.symbol):
            sheet.row_dimensions[excel_row].hidden = True
        _wrap_port_row(sheet, excel_row, wrap)
    for column, width in wrap.items():
        sheet.column_dimensions[get_column_letter(column)].width = width
    last = layout.header + len(drafts)
    end_col = (layout.human or 1) + 1
    sheet.auto_filter.ref = f"A{layout.header}:{get_column_letter(end_col)}{max(last, layout.header)}"
    _plain_port_sheet(sheet, layout.header, keep_heights=True)


def _write_ports(
    sheet,
    mcu: str,
    package: str,
    drafts: list[tuple[_PortRow, str, str]],
    pins: tuple[ChipPin, ...],
    human: dict[str, object],
    usages: dict[str, str] | None = None,
) -> None:
    layout = _port_layout(sheet)
    if not layout.legacy:
        _write_ports_v13(sheet, layout, mcu, package, drafts, pins, human, usages)
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
    _plain_port_sheet(sheet, 4)
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
        )
        for column, value in enumerate(values, start=1):
            sheet.cell(excel_row, column, value)
        if row.direction:
            sheet.cell(excel_row, 8, row.direction)
        name = _project_name(row.project)
        if name:
            sheet.cell(excel_row, 10, name)
        sheet.cell(excel_row, 14, present_mux(row.mux))
        sheet.cell(excel_row, 20, row.page)
        sheet.cell(excel_row, 21, present_excerpt(excerpts.get(row.symbol, "")))
        sheet.cell(excel_row, COL_STATUS, status)
        if note:
            sheet.cell(excel_row, COL_MARK, note)
        if row.symbol in human:
            sheet.cell(excel_row, COL_HUMAN, human[row.symbol])
        if pin_supply_kind(row.symbol):
            sheet.row_dimensions[excel_row].hidden = True
        _wrap_port_row(sheet, excel_row)
    sheet.column_dimensions["N"].width = 56
    sheet.column_dimensions["U"].width = 56
    sheet.column_dimensions["V"].width = 18
    sheet.column_dimensions["W"].width = 36
    last = 4 + len(drafts)
    sheet.auto_filter.ref = f"A4:{get_column_letter(COL_HUMAN)}{max(last, 4)}"
    _plain_port_sheet(sheet, 4, keep_heights=True)


def _class_summary(pins: tuple[ChipPin, ...]) -> str:
    counts: dict[str, int] = {}
    for pin in pins:
        kind = pin_class(pin) or "未分类"
        counts[kind] = counts.get(kind, 0) + 1
    order = ("电源", "地", "ADC", "SPI", "CAN", "GPIO", "IO", "Timer")
    parts = [f"{name} {counts[name]}" for name in order if name in counts]
    parts.extend(f"{name} {counts[name]}" for name in sorted(counts) if name not in order)
    return "、".join(parts)


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
            pin_class(pin),
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
    # 模板上的组和信号名还没经当份需求确认，不据此写分配结论。
    allocation: dict[str, list[str]] = {}
    tick(88, "write", "")

    drafts: list[tuple[_PortRow, str, str]] = []
    current_rows: dict[str, _PortRow] = {}
    usages: dict[str, str] = {}
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
        # 上一版这一列已被改过时，不再把模板端口名写回去；只记球号等差异。
        sheet_project = project
        if previous_rows:
            prev = previous_rows.get(pin.symbol)
            if prev is not None and _project_name(prev.project) != _project_name(project):
                sheet_project = ()
        row = _pin_row(pin, sheet_project)
        usage = _template_function(matches)
        if usage:
            usages[pin.symbol] = usage
        drafts.append((row, status, note))
        current_rows[pin.symbol] = row
    changes = _diff(previous_rows, current_rows) if previous_rows else []
    version = _next_version(mcu, package, previous_version)
    today = date.today().strftime("%Y%m%d")
    classes = _class_summary(pins)
    if previous_rows:
        summary = f"相对上一版 {len(changes)} 处端口差异；总脚数 {len(pins)}"
    else:
        summary = f"首次按手册生成端口表；总脚数 {len(pins)}"
    if classes:
        summary = f"{summary}；{classes}"
    remark = _COVER_REMARK
    cover = _cover_sheet(template_book)
    history = _history_sheet(template_book)
    port = _port_sheet(template_book)
    if cover is None or history is None or port is None:
        raise ValueError("HSI 模板缺少封面、变更记录或端口表。")
    _write_cover(cover, today, summary, version, remark)
    _write_history(history, today, changes)
    _write_ports(port, mcu, package, drafts, pins, human, usages)
    _stamp_adc_mcu(template_book, mcu)
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
    _clear_template_detail_rows(template_book, drop_template_chrome=True)
    _fill_adc_from_manual(template_book, pins)
    if schematic is not None:
        _fill_adc_signal_names_from_port(template_book)
    else:
        _hide_adc_signal_names(template_book)
    _fill_spi_from_manual(template_book, pins)
    _fill_can_from_manual(template_book, pins)
    _link_detail_sheets(template_book)
    _hide_adc_spare_columns(template_book)
    if port is not None:
        _rename_function_description(port, _port_layout(port))
        _retire_schematic_net_column(port)
    template_book.active = port
    _stamp_issue(template_book, "按芯片手册重出")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tick(97, "write", "")
    combos = list(getattr(template_book, "_hsi_jump_combos", []) or [])
    template_book.save(dest)
    template_book.close()
    apply_dead_time_sheet(dest)
    _install_jump_combos(dest, combos)
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


_MCU_BANNER = re.compile(r"^MCU_[A-Za-z]*\d+[A-Za-z0-9]*$")


def _drop_chip_package(text: str) -> str:
    if _MCU_BANNER.fullmatch(text):
        return ""
    if "BGA436" in text:
        return text.replace("BGA436", "").strip(" \\/_-")
    if text.startswith("TC499"):
        return text[len("TC499"):].lstrip(" \\/_-")
    return text


def _clear_cover_column(cover, header: str, *, include_header: bool = False) -> None:
    column = next(
        (
            col
            for col in range(1, min(cover.max_column or 1, 12) + 1)
            if _text(cover.cell(1, col).value) == header
        ),
        None,
    )
    if column is None:
        return
    start = 1 if include_header else 2
    for row in range(start, (cover.max_row or 1) + 1):
        cell = cover.cell(row, column)
        if cell.value not in (None, ""):
            cell.value = None


def _strip_schematic_template_identity(workbook: Workbook) -> None:
    """原理图出表不把模板上的芯片、封装、修改说明和变更记录显示成这次的结果。"""
    cover = _cover_sheet(workbook)
    if cover is not None:
        _clear_cover_column(cover, "修改人")
        _clear_cover_column(cover, "需要修改内容", include_header=True)
    history = _history_sheet(workbook)
    if history is not None:
        header = None
        for row in range(1, min(history.max_row or 1, 8) + 1):
            labels = {
                _text(history.cell(row, col).value)
                for col in range(1, min(history.max_column or 1, 8) + 1)
            }
            if "版本" in labels:
                header = row
                break
        if header is not None and (history.max_row or header) > header:
            for row in history.iter_rows(
                min_row=header + 1,
                max_row=history.max_row,
                max_col=history.max_column or 1,
            ):
                for cell in row:
                    if cell.value not in (None, ""):
                        cell.value = None
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(
            min_row=1,
            max_row=min(sheet.max_row or 1, 4),
            max_col=sheet.max_column or 1,
        ):
            for cell in row:
                text = _text(cell.value)
                if not text or text.startswith("="):
                    continue
                revised = _drop_chip_package(text)
                if revised != text:
                    cell.value = revised or None
    for sheet in workbook.worksheets:
        _drop_empty_boxes(sheet)


def revise_hsi_from_schematic(
    base: Path,
    dest: Path,
    schematic: Path,
    *,
    on_progress=None,
) -> HsiResult:
    """有原理图时保留模板。PDF 按符号更新对上的行；EDIF 只改对上的网络名和外部电阻。"""
    suffix = schematic.suffix.lower()
    if suffix not in {".edf", ".pdf"}:
        raise ValueError("按原理图生成请用 EDIF（.edf）网表或原理图 PDF。")
    if on_progress is not None:
        on_progress(15, "read", schematic.name)
    drawing_mcu = ""
    symbol_pins: list[SchematicSymbolPin] = []
    if suffix == ".pdf":
        symbol_pins, drawing_mcu = read_schematic_pdf(schematic)
        if not symbol_pins:
            raise ValueError("这份原理图 PDF 里没有认出 MCU 引脚。")
    else:
        board_pins = read_board_pins(schematic)
        if not board_pins:
            raise ValueError("这份网表里没有接插件脚，未修改端口表。")
    book = load_workbook(base)
    try:
        if suffix == ".pdf":
            updated = _write_schematic_symbol_pins(book, symbol_pins)
            if updated == 0:
                raise ValueError("这份原理图 PDF 里没有认出 MCU 引脚。")
            _patch_spi_symbol_rows(book, _chips_from_schematic(symbol_pins))
            _fill_adc_signal_names_from_port(book)
            port = _port_sheet(book)
            if port is not None:
                _apply_drawing_chip(port, drawing_mcu, _port_layout(port).header)
            _stamp_issue(book, "按原理图归档更新")
        else:
            updated = _archive_edif_onto_template(book, schematic)
            port = _port_sheet(book)
            if updated:
                _stamp_issue(book, "按原理图归档更新")
            else:
                _stamp_issue(book, "按原理图归档；网络未对上模板端口，格子未改")
            _fill_adc_signal_names_from_port(book)
        mcu = drawing_mcu
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
    finally:
        book.close()
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
    report(40, "mcu", "")
    detected = mcu_name(datasheet.name, pages)
    mcu = mcu.strip() or detected
    if not mcu:
        raise ValueError("认不出 MCU 型号，未填写端口表。")
    report(42, "mcu", mcu)
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
    report(46, "pins", str(len(pins)) if pins else "")
    report(48, "classify", _class_summary(pins))

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
