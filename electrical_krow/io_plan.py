"""第3项 IO 口初始配置表。

手册未到时只出空表和作业步骤。引脚只接受当份手册已经抽出的行。
命名规则未确认时，端口名留空。人工修改列只保留表上已有内容，不由这里写入。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook

SHEET_NOTE = "说明"
SHEET_TABLE = "IO口初始配置表"

JOB_STEPS: tuple[str, ...] = (
    "读取芯片数据手册",
    "提取引脚、复用及约束",
    "按已确认命名规则生成端口名；规则未确认则该列留空",
    "保留人工修改列，已填内容不得覆盖",
)

HEADERS: tuple[str, ...] = (
    "手册引脚号",
    "手册功能名",
    "复用",
    "电气或工作模式",
    "页码",
    "原文摘录",
    "端口名",
    "人工修改",
)

_PIN = 1
_FUNCTION = 2
_MUX = 3
_CONSTRAINT = 4
_PAGE = 5
_EXCERPT = 6
_PORT = 7
_HUMAN = 8

_NOTE_UNCONFIRMED = "命名规则未经甲方确认，端口名留空。本表确认前不得作为接口控制依据。"
_NOTE_CONFIRMED = "命名规则已确认。端口名只采用调用方给出的名称，这里不自拟名称。"


@dataclass(frozen=True)
class ManualPin:
    """当份手册中的一行。页码和原文必须来自该手册。"""

    pin: str
    function: str
    page: str
    excerpt: str
    mux: str = ""
    constraint: str = ""
    port_name: str = ""


def _text(value: str) -> str:
    return str(value or "").strip()


def _checked(row: ManualPin) -> ManualPin:
    pin = _text(row.pin)
    function = _text(row.function)
    page = _text(row.page)
    excerpt = _text(row.excerpt)
    missing = [
        name
        for name, value in (
            ("手册引脚号", pin),
            ("手册功能名", function),
            ("页码", page),
            ("原文摘录", excerpt),
        )
        if not value
    ]
    if missing:
        raise ValueError("引脚行缺少" + "、".join(missing) + "，不能写入初始表。")
    return ManualPin(
        pin=pin,
        function=function,
        page=page,
        excerpt=excerpt,
        mux=_text(row.mux),
        constraint=_text(row.constraint),
        port_name=_text(row.port_name),
    )


def _row_key(pin: str, function: str, excerpt: str) -> tuple[str, str, str]:
    return (_text(pin), _text(function), _text(excerpt))


def _existing_human(path: Path) -> dict[tuple[str, str, str], str]:
    if not path.is_file():
        return {}
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_TABLE not in workbook.sheetnames:
            return {}
        sheet = workbook[SHEET_TABLE]
        found: dict[tuple[str, str, str], str] = {}
        for cells in sheet.iter_rows(min_row=2, values_only=True):
            if not cells or all(cell is None or str(cell).strip() == "" for cell in cells):
                continue
            padded = list(cells) + [None] * _HUMAN
            human = _text(padded[_HUMAN - 1] if padded[_HUMAN - 1] is not None else "")
            if not human:
                continue
            found[_row_key(padded[0], padded[1], padded[5])] = human
        return found
    finally:
        workbook.close()


def write_io_sheet(
    path: Path,
    rows: tuple[ManualPin, ...] | list[ManualPin] = (),
    *,
    naming_confirmed: bool = False,
) -> Path:
    """写出初始表。无手册行时只有表头。人工修改列沿用原表已填内容。"""
    dest = Path(path)
    kept = _existing_human(dest)
    checked = [_checked(row) for row in rows]

    workbook = Workbook()
    note = workbook.active
    note.title = SHEET_NOTE
    note["A1"] = "步骤"
    note["B1"] = "内容"
    for index, step in enumerate(JOB_STEPS, start=2):
        note.cell(index, 1, index - 1)
        note.cell(index, 2, step)
    note.cell(len(JOB_STEPS) + 3, 1, "端口名")
    note.cell(
        len(JOB_STEPS) + 3,
        2,
        _NOTE_CONFIRMED if naming_confirmed else _NOTE_UNCONFIRMED,
    )

    sheet = workbook.create_sheet(SHEET_TABLE)
    for column, header in enumerate(HEADERS, start=1):
        sheet.cell(1, column, header)
    for offset, row in enumerate(checked):
        excel_row = offset + 2
        port = row.port_name if naming_confirmed else ""
        human = kept.get(_row_key(row.pin, row.function, row.excerpt), "")
        values = (
            row.pin,
            row.function,
            row.mux,
            row.constraint,
            row.page,
            row.excerpt,
            port,
            human,
        )
        for column, value in enumerate(values, start=1):
            sheet.cell(excel_row, column, value)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{max(1, 1 + len(checked))}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(dest)
    workbook.close()
    return dest
