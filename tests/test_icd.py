"""接插件 ICD 只抄当份表。空脚待确认，有上一版才写差异。"""
from __future__ import annotations

import base64
import re
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from electrical_krow.hsi_book import hsi_keyword_hits
from openpyxl.cell.rich_text import CellRichText, TextBlock

from electrical_krow.icd_book import _icd_status, _note_plain, build_icd, read_icd


def _shown(value: object) -> str:
    if isinstance(value, CellRichText):
        return "".join(getattr(part, "text", str(part)) for part in value)
    return str(value or "")


def _png(width: int, height: int) -> bytes:
    """只含 IHDR 的 PNG，够读出像素尺寸。"""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)


def _rename_picture(path: Path, filename: str) -> None:
    """把唯一一张图改成客户文件那种编号，例如 image17.png。"""
    import zipfile
    from io import BytesIO
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(path) as source:
        payload = {item.filename: source.read(item.filename) for item in source.infolist()}
        infos = {item.filename: item for item in source.infolist()}
    old = next(name for name in payload if name.startswith("xl/media/"))
    blob = payload.pop(old)
    new = f"xl/media/{filename}"
    payload[new] = blob
    for name in list(payload):
        if "/drawings/_rels/" not in name:
            continue
        root = ET.fromstring(payload[name])
        for item in root:
            if item.attrib.get("Type", "").endswith("/image"):
                item.attrib["Target"] = f"../media/{filename}"
        payload[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:
        for filename_in, data in payload.items():
            info = infos.get(filename_in)
            if info is None:
                info = zipfile.ZipInfo(filename_in)
                info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, data)
    path.write_bytes(buffer.getvalue())


def _book(path: Path, *, signal: str = "SIG_A", extra_pin: str = "") -> None:
    book = Workbook()
    low = book.active
    low.title = "4-整车低压连接器"
    low.append(["接插件信息"])
    low.append(["电器端", "", "", "", "线束端", "", "", "", "", "引脚号", "信号定义", "信号名称", "信号类型", "电流", "备注1"])
    low.append(["厂家", "型号", "供应商料号", "镀层", "厂家", "型号", "供应商料号", "镀层", "", "PIN1", signal, "名称A", "通讯信号", "0.1A", "备注A"])
    low.append(["Molex", "MX1", "P1", "银", "molex", "H1", "P2", "锡", "", "PIN2", "空", "", "", "", ""])
    if extra_pin:
        low.append(["", "", "", "", "", "", "", "", "", extra_pin, "SIG_X", "名称X", "开关量", "1A", ""])
    hv = book.create_sheet("2-高压接口定义")
    hv.append(["连接器", "用途", "电流要求", "型号", "供应商料号", "引脚数", "引脚定义", "供应商", "备注1"])
    hv.append(["HVDC", "高压母线供电", "32A", "M1", "PN1", "2", "1-负极；2-正极", "天海", ""])
    power = book.create_sheet("3-整车12V连接器")
    power.append(["接插件信息"])
    power.append(["XCM端", "", "", "", "线束端"])
    power.append(["厂家", "型号", "供应商料号", "镀层", "厂家", "型号", "供应商料号", "镀层"])
    power.append(["天海", "暂不在系统中", "TES1", "银", "天海", "PP2", "TES2", "锡"])
    book.save(path)
    book.close()


def _sheet_change_rows(sheet) -> list[tuple]:
    """本表小结的数据行：差异、对象、字段、上一版、当版。"""
    header = None
    for row in range(1, (sheet.max_row or 1) + 1):
        for col in range(1, (sheet.max_column or 1) + 1):
            if sheet.cell(row, col).value == "差异" and sheet.cell(row, col + 1).value == "对象":
                header = (row, col)
                break
        if header:
            break
    if header is None:
        return []
    start, col = header
    rows = []
    for row in range(start + 1, (sheet.max_row or 1) + 1):
        values = tuple(sheet.cell(row, col + offset).value for offset in range(5))
        if all(item in (None, "") for item in values):
            break
        rows.append(values)
    return rows


def _column_text(sheet, column: int = 1) -> str:
    return " ".join(str(sheet.cell(row, column).value or "") for row in range(1, (sheet.max_row or 1) + 1))


class IcdBookTests(unittest.TestCase):
    def test_pins_parts_and_hv_come_from_the_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "icd.xlsx"
            _book(source)
            found = read_icd(source)
            pins = {pin.pin: pin for pin in found.pins}
            self.assertEqual(set(pins), {"PIN1", "PIN2"})
            self.assertEqual(pins["PIN1"].signal, "SIG_A")
            self.assertEqual(pins["PIN1"].device_model, "MX1")
            self.assertEqual(pins["PIN1"].harness_model, "H1")
            self.assertEqual(pins["PIN1"].status, "待人工确认")
            self.assertEqual(pins["PIN2"].status, "待确认")
            self.assertEqual(pins["PIN2"].name, "")
            marked = pins["PIN1"].__class__(
                pins["PIN1"].sheet, pins["PIN1"].pin, "CAN1_H", "水温采样", pins["PIN1"].kind,
                pins["PIN1"].current, pins["PIN1"].note, pins["PIN1"].device_maker,
                pins["PIN1"].device_model, pins["PIN1"].device_part, pins["PIN1"].harness_maker,
                pins["PIN1"].harness_model, pins["PIN1"].harness_part, pins["PIN1"].vehicles,
                pins["PIN1"].module, pins["PIN1"].status,
            )
            self.assertEqual(hsi_keyword_hits("CAN1_H 水温采样"), ["水温", "CAN"])
            self.assertIn("须进入HSI：水温、CAN", _icd_status(marked))
            self.assertEqual(found.hv[0].connector, "HVDC")
            self.assertEqual(found.hv[0].pin_def, "1-负极；2-正极")
            sides = {(item.sheet, item.side, item.model, item.status) for item in found.parts}
            self.assertIn(("3-整车12V连接器", "XCM端", "暂不在系统中", "待确认"), sides)
            self.assertIn(("3-整车12V连接器", "线束端", "PP2", "待人工确认"), sides)

    def test_previous_file_marks_add_remove_and_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"
            _book(previous, signal="SIG_OLD", extra_pin="PIN3")
            _book(current, signal="SIG_A", extra_pin="PIN4")
            dest = folder / "out.xlsx"
            result = build_icd(current, dest, previous)
            self.assertGreater(result.changes, 0)
            book = load_workbook(dest, data_only=False)
            summary = book["差异总结"]
            self.assertNotIn("引脚清单", book.sheetnames)
            self.assertNotIn("版本差异", book.sheetnames)
            self.assertIn("差异总结", book.sheetnames)
            brief = _column_text(summary)
            self.assertIn("关键变化", brief)
            self.assertIn("引脚有变动，见本表小结", brief)
            self.assertNotIn("PIN4", brief)
            self.assertNotIn("PIN3", brief)
            self.assertFalse(any(
                summary.cell(row, col).value == "对象"
                for row in range(1, summary.max_row + 1)
                for col in range(1, (summary.max_column or 1) + 1)
            ))
            self.assertTrue(str(summary.cell(3, 1).fill.fgColor.rgb or "").endswith("C6EFCE"))
            self.assertTrue(str(summary.cell(3, 3).fill.fgColor.rgb or "").endswith("FFE699"))
            self.assertTrue(str(summary.cell(3, 5).fill.fgColor.rgb or "").endswith("FFC7CE"))
            low = book["4-整车低压连接器"]
            kinds = {(row[1], row[0], row[2]) for row in _sheet_change_rows(low)}
            self.assertIn(("PIN1", "修改", "信号定义"), kinds)
            self.assertIn(("PIN4", "新增", "引脚"), kinds)
            self.assertIn(("PIN3", "删除", "引脚"), kinds)
            self.assertIn("本次出表", str(summary.cell(2, 1).value))
            flat_low = [
                str(low.cell(row, col).value or "")
                for row in range(1, low.max_row + 1)
                for col in range(1, (low.max_column or 1) + 1)
            ]
            self.assertNotIn("匹配", flat_low)
            self.assertNotIn("修改：信号定义", flat_low)
            self.assertLessEqual(summary.column_dimensions["B"].width, 20)
            book.close()

    def test_match_column_avoids_merged_cells(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            current = folder / "new.xlsx"
            _book(current)
            draft = load_workbook(current)
            draft.active.merge_cells("P3:R5")
            draft.save(current)
            draft.close()
            dest = folder / "out.xlsx"
            build_icd(current, dest)
            book = load_workbook(dest)
            try:
                low = book["4-整车低压连接器"]
                flat_low = [
                    str(low.cell(row, col).value or "")
                    for row in range(1, low.max_row + 1)
                    for col in range(1, (low.max_column or 1) + 1)
                ]
                self.assertNotIn("匹配", flat_low)
                self.assertNotIn("已从当版读出", flat_low)
                self.assertIsNone(low.cell(3, 16).value)
            finally:
                book.close()

    def test_different_sheet_name_and_plain_pin_still_compare(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, title: str, pin: str, signal: str, version: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = title
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append([pin, signal, "名称A"])
                log = book.create_sheet("变更记录")
                log.append(["序号", "版本号", "更改内容"])
                log.append(["1", version, "发布"])
                book.save(path)
                book.close()

            write(previous, "整车低压连接器", "1", "SIG_OLD", "V3.11")
            write(current, "4-整车低压连接器", "PIN1", "SIG_A", "V3.12")
            draft = load_workbook(current)
            cover = draft.create_sheet("0-封面", 0)
            cover["A1"] = "封面"
            sheet = draft["4-整车低压连接器"]
            sheet.column_dimensions["A"].width = 14
            sheet.column_dimensions["D"].width = 9
            sheet.print_area = "A1:C2"
            draft.save(current)
            draft.close()
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                self.assertEqual(book.sheetnames, ["0-封面", "4-整车低压连接器", "差异总结"])
                self.assertNotIn("变更记录", book.sheetnames)
                self.assertNotIn("版本差异", book.sheetnames)
                self.assertEqual(book.active.title, "0-封面")
                source = book["4-整车低压连接器"]
                self.assertIn(str(source.max_row), str(source.print_area).replace("$", ""))
                self.assertGreater(source.max_row, 2)
                self.assertTrue(str(source.cell(2, 2).fill.fgColor.rgb or "").endswith("FFE699"))
                flat = [
                    str(source.cell(row, col).value or "")
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                ]
                self.assertTrue(any(item.startswith("本表小结") for item in flat))
                self.assertTrue(any("绿色为新增，黄色为修改，红色为删除" in item for item in flat))
                summary_cell = next(
                    source.cell(row, col)
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                    if str(source.cell(row, col).value or "").startswith("本表小结")
                )
                self.assertEqual(summary_cell.row, 2)
                self.assertGreater(summary_cell.column, 3)
                self.assertEqual(summary_cell.alignment.horizontal, "left")
                self.assertEqual(source.cell(summary_cell.row + 1, summary_cell.column).value, "差异")
                self.assertEqual(_shown(source.cell(1, summary_cell.column).value), _note_plain())
                self.assertIn("上一版", flat)
                self.assertIn("当版", flat)
                overall = book["差异总结"]
                self.assertIn("绿色：新增", str(overall.cell(3, 1).value))
                self.assertTrue(str(overall.cell(3, 1).fill.fgColor.rgb or "").endswith("C6EFCE"))
                self.assertIn("黄色：修改", str(overall.cell(3, 3).value))
                self.assertTrue(str(overall.cell(3, 3).fill.fgColor.rgb or "").endswith("FFE699"))
                self.assertIn("红色：删除", str(overall.cell(3, 5).value))
                self.assertTrue(str(overall.cell(3, 5).fill.fgColor.rgb or "").endswith("FFC7CE"))
                self.assertIn("old.xlsx", str(overall.cell(1, 1).value))
                self.assertIn("V3.11", str(overall.cell(1, 1).value))
                self.assertIn("new.xlsx", str(overall.cell(2, 1).value))
                self.assertIn("V3.12", str(overall.cell(2, 1).value))
                self.assertLessEqual(overall.column_dimensions["B"].width, 20)
                self.assertEqual(source.column_dimensions["A"].width, 14)
                self.assertEqual(source.column_dimensions["D"].width, 9)
                summary_width = source.column_dimensions[get_column_letter(summary_cell.column + 3)].width
                self.assertGreaterEqual(summary_width, 16)
                brief = _column_text(overall)
                self.assertIn("关键变化", brief)
                self.assertIn("引脚有变动，见本表小结", brief)
                self.assertFalse(any(
                    overall.cell(row, col).value == "对象"
                    for row in range(1, overall.max_row + 1)
                    for col in range(1, (overall.max_column or 1) + 1)
                ))
                kinds = {(row[1], row[0]) for row in _sheet_change_rows(source)}
                self.assertIn(("PIN1", "修改"), kinds)
                self.assertNotIn(("PIN1", "新增"), kinds)
                painted = ""
                for row in range(1, source.max_row + 1):
                    for col in range(1, (source.max_column or 1) + 1):
                        if source.cell(row, col).value == "修改" and source.cell(row, col + 1).value == "PIN1":
                            painted = str(source.cell(row, col).fill.fgColor.rgb or "")
                self.assertTrue(painted.endswith("FFE699"))
                self.assertGreaterEqual(overall.column_dimensions["A"].width, 18)
            finally:
                book.close()

    def test_new_pin_does_not_paint_connector_info(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, part_no: str, extra: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["接插件信息"])
                sheet.append(["电器端", "", "", "", "线束端", "", "", "", "", "引脚号", "信号定义", "信号名称"])
                sheet.append(["厂家", "型号", "供应商料号", "镀层", "厂家", "型号", "供应商料号", "镀层", "", "PIN1", "SIG_A", "名称A"])
                sheet.append(["Molex", "MX1", part_no, "银", "molex", "H1", "P2", "锡", "", extra, "NEW_SIG" if extra else "", "新信号" if extra else ""])
                book.save(path)
                book.close()

            write(previous, "P1", "")
            write(current, "P9", "PIN30")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]

                def paint(row: int, col: int) -> str:
                    return str(source.cell(row, col).fill.fgColor.rgb or "")

                self.assertFalse(paint(4, 1).endswith("C6EFCE"))
                self.assertFalse(paint(4, 1).endswith("FFE699"))
                self.assertFalse(paint(4, 5).endswith("C6EFCE"))
                self.assertFalse(paint(3, 1).endswith("C6EFCE"))
                self.assertTrue(paint(4, 3).endswith("FFE699"))
                self.assertTrue(paint(4, 10).endswith("C6EFCE"))
                self.assertTrue(paint(4, 11).endswith("C6EFCE"))
                self.assertFalse(paint(3, 10).endswith("C6EFCE"))
            finally:
                book.close()

    def test_same_signal_without_pin_number_is_not_a_new_pin(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, pin: str, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append([pin, signal, "底盘通讯"])
                book.save(path)
                book.close()

            write(previous, "", "Chassis_CAN1_H")
            write(current, "PIN30", "Chassis_ CAN1_H")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                overall = book["差异总结"]
                brief = _column_text(overall)
                self.assertIn("关键变化", brief)
                self.assertIn("引脚有变动，见本表小结", brief)
                self.assertNotIn("Chassis", brief)
                source = book["4-整车低压连接器"]
                kinds = {(row[1], row[0], row[2]) for row in _sheet_change_rows(source)}
                self.assertIn(("PIN30", "修改", "引脚号"), kinds)
                self.assertNotIn(("PIN30", "新增", "引脚"), kinds)
                self.assertNotIn("版本差异", book.sheetnames)
                flat = [
                    str(source.cell(row, col).value or "")
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                ]
                self.assertTrue(any(item.startswith("本表小结") for item in flat))
                self.assertTrue(any(item == "修改" for item in flat))
                self.assertTrue(any(item == "引脚号" for item in flat))
                self.assertTrue(any("Chassis" in item for item in flat))
            finally:
                book.close()

    def test_many_new_pins_share_one_list(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, rows: tuple[tuple[str, str], ...]) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                for pin, signal in rows:
                    sheet.append([pin, signal, "名称"])
                book.save(path)
                book.close()

            write(previous, (("PIN1", "SIG_A"),))
            write(current, (
                ("PIN1", "SIG_A"),
                ("PIN30", "Chassis_CAN1_H"),
                ("PIN40", "Chassis_CAN1_L"),
                ("PIN29", "Chassis_CANFD2_H"),
                ("高压压缩机", "不用主动唤醒"),
            ))
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]
                rows = _sheet_change_rows(source)
                lists = [str(row[4] or "") for row in rows if row[1] == "3只" and row[0] == "新增"]
                self.assertEqual(len(lists), 1)
                self.assertIn("PIN30  Chassis_CAN1_H", lists[0])
                self.assertIn("PIN40  Chassis_CAN1_L", lists[0])
                self.assertIn("PIN29  Chassis_CANFD2_H", lists[0])
                self.assertNotIn("高压压缩机", lists[0])
                self.assertTrue(any(row[1] == "高压压缩机" for row in rows))
                brief = _column_text(book["差异总结"])
                self.assertIn("关键变化", brief)
                self.assertIn("引脚有变动，见本表小结", brief)
                self.assertNotIn("CAN", brief)
                self.assertNotIn("PIN30  Chassis_CAN1_H", brief)
            finally:
                book.close()

            write(previous, (("", "XCP_CAN_H"), ("", "XCP_CAN_L")))
            write(current, (("PIN49", "XCP_CAN_H"), ("PIN50", "XCP_CAN_L")))
            dest2 = folder / "out2.xlsx"
            build_icd(current, dest2, previous)
            book = load_workbook(dest2)
            try:
                source = book["4-整车低压连接器"]
                filled = [
                    str(row[4] or "")
                    for row in _sheet_change_rows(source)
                    if row[1] == "2只" and row[2] == "引脚号"
                ]
                self.assertEqual(filled, ["PIN49（XCP_CAN_H）\nPIN50（XCP_CAN_L）"])
                brief = _column_text(book["差异总结"])
                self.assertIn("引脚有变动，见本表小结", brief)
                self.assertNotIn("PIN49（XCP_CAN_H）\nPIN50（XCP_CAN_L）", brief)
            finally:
                book.close()

    def test_same_current_and_prose_pin_stay_readable(self) -> None:
        sentence = "4路LIN总线，具体每一个LIN挂在哪个总线暂不考虑"
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, rows: tuple[tuple[str, str, str], ...]) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称", "电流"])
                for pin, signal, amp in rows:
                    sheet.append([pin, signal, "名称", amp])
                book.save(path)
                book.close()

            write(previous, (
                ("PIN4", "SIG_A", ""),
                ("PIN53", "SIG_B", ""),
                ("PIN54", "SIG_C", ""),
                ("PIN1", "Chassis_CAN_H", "0.1A"),
            ))
            write(current, (
                ("PIN4", "SIG_A", "0.1A"),
                ("PIN53", "SIG_B", "0.1A"),
                ("PIN54", "SIG_C", "0.1A"),
                ("PIN1", "Chassis_CAN_H", "0.1A"),
                ("", sentence, ""),
            ))
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]
                rows = _sheet_change_rows(source)
                currents = [
                    (str(row[1] or ""), str(row[4] or ""))
                    for row in rows
                    if row[2] == "电流" and row[0] == "修改"
                ]
                self.assertEqual(len(currents), 1)
                self.assertEqual(currents[0][0], "3处")
                self.assertIn("0.1A", currents[0][1])
                self.assertIn("PIN4", currents[0][1])
                self.assertIn("PIN53", currents[0][1])
                self.assertIn("PIN54", currents[0][1])
                notes = [str(row[4] or "") for row in rows if row[1] == "说明"]
                self.assertEqual(notes, [sentence])
                self.assertFalse(any(row[2] == "信号名称" for row in rows))
                brief = _column_text(book["差异总结"])
                self.assertIn(sentence, brief)
                self.assertNotIn("0.1A", brief)
                self.assertNotIn("PIN53", brief)
            finally:
                book.close()

    def test_llm_marks_wording_and_drops_invented_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, note: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称", "备注"])
                sheet.append(["PIN1", "SIG_A", "名称", note])
                book.save(path)
                book.close()

            write(previous, "量产后取消")
            write(current, "量产取消，仅开发使用")

            def ask(messages: list[dict[str, str]]) -> str:
                return (
                    '{"summary":"低压连接器备注有措辞差异，另有 PIN99 电流 9A",'
                    '"wording":[0],"notes":[]}'
                )

            dest = folder / "out.xlsx"
            build_icd(current, dest, previous, ask)
            book = load_workbook(dest)
            try:
                overall = book["差异总结"]
                brief = _column_text(overall)
                self.assertNotIn("PIN99", brief)
                self.assertNotIn("9A", brief)
                self.assertIn("4-整车低压连接器", brief)
                self.assertIn("关键变化", brief)
                source = book["4-整车低压连接器"]
                fields = [str(row[2] or "") for row in _sheet_change_rows(source)]
                currents = [str(row[4] or "") for row in _sheet_change_rows(source)]
                self.assertTrue(any("措辞，请看" in item for item in fields))
                self.assertTrue(any("量产取消，仅开发使用" in item for item in currents))
            finally:
                book.close()

    def test_long_note_row_is_tall_enough_to_show_the_text(self) -> None:
        long = "4路LIN总线，具体每一个LIN挂在哪个总线暂不考虑"
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "底盘通讯"])
                book.save(path)
                book.close()

            write(previous, "短信号")
            write(current, long)
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]
                self.assertEqual(source.cell(2, 2).value, long)
                self.assertNotIn("版本差异", book.sheetnames)
                overall = book["差异总结"]
                brief_row = next(
                    row for row in range(1, overall.max_row + 1) if long in str(overall.cell(row, 1).value or "")
                )
                self.assertGreaterEqual(overall.row_dimensions[brief_row].height or 0, 22)
                self.assertNotIn("信号类别", _column_text(overall))
                self.assertFalse(any(overall.cell(row, col).value == "对象" for row in range(1, overall.max_row + 1) for col in range(1, (overall.max_column or 1) + 1)))
                summary_rows = [
                    row
                    for row in range(1, source.max_row + 1)
                    if any(source.cell(row, col).value == long for col in range(1, source.max_column + 1))
                    and (source.row_dimensions[row].height or 0) >= 40
                ]
                self.assertTrue(summary_rows)
            finally:
                book.close()

    def test_repeated_note_collapses_and_blank_pin_delete_is_hidden(self) -> None:
        old_note = "4路LIN总线，具体每一个LIN挂在哪个总线暂不考虑"
        new_note = "4路LIN总线，具体每一个LIN挂在哪个总线按顺序分配"
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, note: str, *, orphan: bool, compressor: bool) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称", "备注"])
                for pin, signal in (("PIN1", "SIG_A"), ("PIN2", "SIG_B"), ("PIN3", "SIG_C")):
                    sheet.append([pin, signal, "名称", note])
                sheet.append(["PIN4", "SIG_D", "名称", "线束 备注" if orphan else "线束备注"])
                if orphan:
                    sheet.append(["", "Chassis_CAN1_H", "底盘", ""])
                    sheet.append(["", old_note, "", ""])
                hv = book.create_sheet("2-高压接口定义")
                hv.append(["连接器", "用途", "电流要求", "型号", "供应商料号", "引脚数", "引脚定义", "供应商", "备注"])
                hv.append(["HVDC", "高压母线供电", "32A", "M1", "PN1", "2", "1-负极；2-正极", "天海", ""])
                if compressor:
                    hv.append(["高压压缩机", "配电", "16A", "M2", "PN2", "2", "1-正极；2-负极", "天海", ""])
                book.save(path)
                book.close()

            write(previous, old_note, orphan=True, compressor=False)
            write(current, new_note, orphan=False, compressor=True)
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                low = book["4-整车低压连接器"]
                hv = book["2-高压接口定义"]
                rows = [
                    (row[1], row[0], row[2], row[3], row[4])
                    for sheet in (low, hv)
                    for row in _sheet_change_rows(sheet)
                ]
                remarks = [row for row in rows if row[2] == "备注"]
                self.assertEqual(len(remarks), 1)
                self.assertEqual(remarks[0][0], "本表备注")
                self.assertEqual(remarks[0][3], old_note)
                self.assertEqual(remarks[0][4], new_note)
                self.assertTrue(any(row[1] == "删除" and row[3] == "Chassis_CAN1_H" for row in rows))
                self.assertFalse(any(row[1] == "删除" and row[3] == old_note for row in rows))
                self.assertTrue(any(row[0] == "高压压缩机" and row[1] == "新增" for row in rows))
                self.assertFalse(any(row[0] == "PIN4" and row[2] == "备注" for row in rows))
                brief = _column_text(book["差异总结"])
                self.assertIn("关键变化", brief)
                self.assertIn("高压压缩机", brief)
                self.assertFalse(any(
                    book["差异总结"].cell(row, col).value == "对象"
                    for row in range(1, book["差异总结"].max_row + 1)
                    for col in range(1, (book["差异总结"].max_column or 1) + 1)
                ))
            finally:
                book.close()

    def test_pinless_signal_deletes_share_one_list(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, extra: list[tuple[str, str]]) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", "SIG_A", "名称"])
                for pin, signal in extra:
                    sheet.append([pin, signal, ""])
                book.save(path)
                book.close()

            write(previous, [("", "Chassis1_CAN_H"), ("", "Chassis1_CAN_L"), ("", "THM1_LIN"), ("PIN9", "KEEP_ME")])
            write(current, [])
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]
                flat = [
                    str(source.cell(row, col).value or "")
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                ]
                self.assertIn("删除 4", " ".join(flat))
                lists = [item for item in flat if "Chassis1_CAN_H" in item and "Chassis1_CAN_L" in item]
                self.assertEqual(len(lists), 1)
                self.assertIn("THM1_LIN", lists[0])
                self.assertIn("3只", flat)
                self.assertIn("PIN9", flat)
                self.assertEqual(flat.count("无引脚号"), 0)
            finally:
                book.close()

    def test_key_change_prefers_the_connector_over_pins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, part_no: str, extra: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["接插件信息"])
                sheet.append(["电器端", "", "", "", "线束端", "", "", "", "", "引脚号", "信号定义", "信号名称"])
                sheet.append(["厂家", "型号", "供应商料号", "镀层", "厂家", "型号", "供应商料号", "镀层", "", "PIN1", "SIG_A", "名称A"])
                sheet.append(["Molex", "MX1", part_no, "银", "molex", "H1", "P2", "锡", "", extra, "NEW_SIG" if extra else "", "新信号" if extra else ""])
                book.save(path)
                book.close()

            write(previous, "P1", "")
            write(current, "P9", "PIN30")

            def ask(messages: list[dict[str, str]]) -> str:
                self.assertIn("接插件", messages[0]["content"])
                return (
                    '{"points":[{"sheet":"4-整车低压连接器","lines":["新增1只引脚，信号类别为NEW_SIG"]}],'
                    '"wording":[],"notes":[]}'
                )

            dest = folder / "out.xlsx"
            build_icd(current, dest, previous, ask)
            book = load_workbook(dest)
            try:
                brief = _column_text(book["差异总结"])
                self.assertIn("供应商料号", brief)
                self.assertIn("P9", brief)
                self.assertNotIn("信号类别", brief)
                self.assertNotIn("只引脚", brief)
            finally:
                book.close()

    def test_key_change_writes_from_and_to_for_the_connector(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, maker: str, plate: str, purpose: str, pin_def: str) -> None:
                book = Workbook()
                low = book.active
                low.title = "5-变速器连接器"
                low.append(["接插件信息"])
                low.append(["电器端", "", "", "", "线束端", "", "", "", "", "引脚号", "信号定义", "信号名称"])
                low.append(["厂家", "型号", "供应商料号", "镀层", "厂家", "型号", "供应商料号", "镀层", "", "PIN1", "SIG_A", "名称"])
                low.append([maker, "MX1", "P1", plate, maker, "H1", "P2", plate, "", "PIN2", "SIG_B", "名称"])
                hv = book.create_sheet("2-高压接口定义")
                hv.append(["连接器", "用途", "电流要求", "型号", "供应商料号", "引脚数", "引脚定义", "供应商", "备注"])
                hv.append(["AC", purpose, "16A", "M1", "PN1", "4", pin_def, "天海", ""])
                book.save(path)
                book.close()

            write(previous, "Molex", "银", "充电", "1 N IN / 2 L IN")
            write(current, "TE", "金", "慢充", "1 N OUT / 2 L OUT")

            def ask(messages: list[dict[str, str]]) -> str:
                return (
                    '{"points":[{"sheet":"5-变速器连接器","lines":["修改2处厂家","修改2处镀层"]},'
                    '{"sheet":"2-高压接口定义","lines":["AC的引脚定义由1 N IN改为1 N OUT"]}],'
                    '"wording":[],"notes":[]}'
                )

            dest = folder / "out.xlsx"
            build_icd(current, dest, previous, ask)
            book = load_workbook(dest)
            try:
                brief = _column_text(book["差异总结"])
                self.assertIn("厂家由Molex改为TE", brief)
                self.assertIn("镀层由银改为金", brief)
                self.assertIn("用途由充电改为慢充", brief)
                self.assertNotIn("修改2处厂家", brief)
                self.assertNotIn("修改2处镀层", brief)
                self.assertIn("引脚定义有改动，见本表小结", brief)
                self.assertNotIn("1 N OUT / 2 L OUT", brief)
            finally:
                book.close()

    def test_model_brief_replaces_the_pin_list(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")

            def ask(messages: list[dict[str, str]]) -> str:
                self.assertIn("关键数据", messages[0]["content"])
                self.assertIn("points", messages[0]["content"])
                return (
                    '{"points":[{"sheet":"4-整车低压连接器","lines":["信号定义改为 SIG_A","没有新增引脚"]}],'
                    '"wording":[],"notes":[]}'
                )

            dest = folder / "out.xlsx"
            build_icd(current, dest, previous, ask)
            book = load_workbook(dest)
            try:
                overall = book["差异总结"]
                brief = _column_text(overall)
                self.assertIn("信号定义改为 SIG_A", brief)
                self.assertNotIn("由SIG_OLD改为", brief)
                titles = [
                    (row, col)
                    for row in range(1, overall.max_row + 1)
                    for col in range(1, (overall.max_column or 1) + 1)
                    if overall.cell(row, col).value == "4-整车低压连接器"
                    and str(overall.cell(row, col).fill.fgColor.rgb or "").endswith("D6E3F0")
                ]
                self.assertEqual(len(titles), 1)
                bullets = [
                    row
                    for row in range(1, overall.max_row + 1)
                    if str(overall.cell(row, 1).value or "").startswith("· ")
                ]
                self.assertEqual(len(bullets), 2)
                self.assertEqual(overall.cell(bullets[0], 1).value, "· 信号定义改为 SIG_A")
                self.assertEqual(overall.cell(bullets[1], 1).value, "· 没有新增引脚")
                self.assertNotEqual(bullets[0], bullets[1])
                self.assertFalse(any("；" in str(overall.cell(row, 1).value or "") for row in bullets))
                self.assertFalse(any(
                    book["差异总结"].cell(row, col).value == "上一版"
                    for row in range(1, book["差异总结"].max_row + 1)
                    for col in range(1, (book["差异总结"].max_column or 1) + 1)
                ))
                rows = _sheet_change_rows(book["4-整车低压连接器"])
                self.assertTrue(any(row[1] == "PIN1" and row[3] == "SIG_OLD" and row[4] == "SIG_A" for row in rows))
            finally:
                book.close()

    def test_short_sheet_summary_stays_under_the_table(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, title: str, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = title
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                book.save(path)
                book.close()

            write(previous, "高压接口", "SIG_OLD")
            write(current, "高压接口", "SIG_A")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["高压接口"]
                summary = next(
                    source.cell(row, col)
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                    if str(source.cell(row, col).value or "").startswith("本表小结")
                )
                self.assertEqual(summary.column, 1)
                self.assertGreater(summary.row, 2)
                self.assertEqual(source.cell(summary.row + 1, 1).value, "差异")
            finally:
                book.close()

            write(previous, "5-变速器连接器", "SIG_OLD")
            write(current, "5-变速器连接器", "SIG_A")
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["5-变速器连接器"]
                summary = next(
                    source.cell(row, col)
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                    if str(source.cell(row, col).value or "").startswith("本表小结")
                )
                self.assertEqual(summary.row, 2)
                self.assertGreater(summary.column, 3)
                self.assertEqual(_shown(source.cell(1, summary.column).value), _note_plain())
                self.assertEqual(source.cell(1, 1).value, "引脚号")
            finally:
                book.close()

    def test_long_sheet_legend_is_on_the_left(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "5-变速器连接器"
                sheet["A1"] = "接插件信息"
                sheet.merge_cells("A1:H1")
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                if signal == "SIG_A":
                    import base64
                    from io import BytesIO

                    from openpyxl.drawing.image import Image
                    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

                    png = base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
                    )
                    image = Image(BytesIO(png))
                    anchor = TwoCellAnchor(editAs="oneCell")
                    anchor._from = AnchorMarker(col=1, colOff=841168, row=6, rowOff=51132)
                    anchor.to = AnchorMarker(col=2, colOff=658089, row=10, rowOff=138035)
                    image.anchor = anchor
                    sheet.add_image(image)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest, rich_text=True)
            try:
                source = book["5-变速器连接器"]
                from openpyxl.cell.rich_text import CellRichText, TextBlock

                from electrical_krow.icd_book import _note_rules

                note = _note_rules()
                shown = "".join(str(part) for part in note)
                self.assertIn("绿色：新增", shown)
                self.assertIn("黄色：修改", shown)
                self.assertIn("红色：删除", shown)
                self.assertIn("只涂改过的那一项", shown)
                self.assertIn("写在表格右侧，逐条列出新增、修改、删除", shown)
                self.assertNotIn("空一列", shown)
                self.assertNotIn("先看接插件", shown)
                self.assertNotIn("匹配栏", shown)
                note = source.cell(1, 1).value
                self.assertEqual(_shown(note), _note_plain())
                self.assertTrue(any(
                    isinstance(part, TextBlock) and part.text.startswith("绿色") and part.font.b
                    for part in note
                ))
                self.assertTrue(any(
                    isinstance(part, TextBlock) and part.text.startswith("黄色") and part.font.b
                    for part in note
                ))
                self.assertTrue(any(
                    isinstance(part, TextBlock) and part.text.startswith("红色") and part.font.b
                    for part in note
                ))
                self.assertIn("不把整行涂黄", _shown(note))
                self.assertEqual(source.cell(2, 1).value, "接插件信息")
                self.assertEqual(source.cell(3, 1).value, "引脚号")
                placed = source._images[0].anchor
                self.assertEqual(placed._from.col, 1)
                self.assertEqual(placed._from.row, 7)
                self.assertEqual(placed._from.colOff, 841168)
                self.assertEqual(placed._from.rowOff, 51132)
                self.assertEqual(placed.to.col, 2)
                self.assertEqual(placed.to.row, 11)
                self.assertEqual(placed.to.rowOff, 138035)
                summary = next(
                    source.cell(row, col)
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                    if str(source.cell(row, col).value or "").startswith("本表小结")
                )
                self.assertGreater(summary.column, 2)
                self.assertFalse(str(source.cell(1, summary.column).value or "").startswith("备注："))
                self.assertNotEqual(source.cell(1, summary.column).value, "绿色：新增")
                gap = source.cell(summary.row, summary.column - 1)
                self.assertIn(gap.value, (None, ""))
                self.assertNotEqual(gap.fill.patternType, "solid")
            finally:
                book.close()

    def test_picture_sheet_keeps_the_customer_drawing(self) -> None:
        import zipfile
        from xml.etree import ElementTree as ET

        from openpyxl.drawing.image import Image
        from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
        from openpyxl.worksheet.dimensions import ColumnDimension
        from PIL import Image as PILImage

        png = BytesIO()
        PILImage.new("RGB", (8, 6), "white").save(png, format="PNG")
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str, *, picture: bool) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet["A1"] = "接插件信息"
                sheet.merge_cells("A1:H1")
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                view = sheet.views.sheetView[0]
                view.view = "pageBreakPreview"
                view.topLeftCell = "I49"
                sheet.column_dimensions["G"] = ColumnDimension(
                    sheet, index="G", min=7, max=8, width=18.4
                )
                if picture:
                    image = Image(BytesIO(png.getvalue()))
                    anchor = TwoCellAnchor(editAs="oneCell")
                    anchor._from = AnchorMarker(col=1, colOff=10, row=3, rowOff=0)
                    anchor.to = AnchorMarker(col=6, colOff=20, row=22, rowOff=0)
                    image.anchor = anchor
                    sheet.add_image(image)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD", picture=False)
            write(current, "SIG_A", picture=True)

            def drawing_of(path: Path) -> bytes:
                with zipfile.ZipFile(path) as book:
                    root = ET.fromstring(book.read("xl/workbook.xml"))
                    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
                    targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
                    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
                    for sheet in root.findall(f"{ns}sheets/{ns}sheet"):
                        if sheet.attrib["name"] != "4-整车低压连接器":
                            continue
                        target = targets[sheet.attrib[f"{rel_ns}id"]].lstrip("/")
                        if not target.startswith("xl/"):
                            target = "xl/" + target
                        rel_path = str(Path(target).parent / "_rels" / (Path(target).name + ".rels"))
                        for item in ET.fromstring(book.read(rel_path)):
                            if not item.attrib.get("Type", "").endswith("/drawing"):
                                continue
                            drawing = item.attrib["Target"]
                            if drawing.startswith("/"):
                                drawing = drawing.lstrip("/")
                            elif drawing.startswith("../"):
                                drawing = "xl/" + drawing.replace("../", "")
                            elif not drawing.startswith("xl/"):
                                drawing = str(Path(target).parent / drawing)
                            return book.read(drawing)
                raise AssertionError("no drawing")

            source_drawing = drawing_of(current)
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            from electrical_krow.icd_book import _shift_drawing_rows

            self.assertEqual(drawing_of(dest), _shift_drawing_rows(source_drawing))
            with zipfile.ZipFile(dest) as saved:
                root = ET.fromstring(saved.read("xl/workbook.xml"))
                rels = ET.fromstring(saved.read("xl/_rels/workbook.xml.rels"))
                targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
                ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
                for sheet in root.findall(f"{ns}sheets/{ns}sheet"):
                    if sheet.attrib["name"] != "4-整车低压连接器":
                        continue
                    target = targets[sheet.attrib[f"{rel_ns}id"]].lstrip("/")
                    if not target.startswith("xl/"):
                        target = "xl/" + target
                    xml = saved.read(target).decode("utf-8")
            self.assertIn('view="normal"', xml)
            self.assertNotIn('view="pageBreakPreview"', xml)
            self.assertIn('topLeftCell="A1"', xml)
            self.assertNotIn('topLeftCell="I49"', xml)
            grouped = next(
                col
                for col in re.findall(r"<col\b[^>]*/>", xml)
                if 'min="7"' in col and 'max="8"' in col
            )
            self.assertIn('width="18.4"', grouped)

    def test_shifted_drawing_keeps_the_original_picture_file(self) -> None:
        import zipfile
        from io import BytesIO
        from xml.etree import ElementTree as ET

        from electrical_krow.icd_book import _shift_drawing_xml

        shifted = _shift_drawing_xml(
            b'<xdr:col>1</xdr:col><xdr:colOff>5</xdr:colOff><a:off x="100"/>',
            10,
        )
        self.assertIn(b"<xdr:col>2</xdr:col>", shifted)
        self.assertIn(b"<xdr:colOff>5</xdr:colOff>", shifted)
        self.assertIn(b'x="110"', shifted)
        from electrical_krow.icd_book import _seat_blown_pictures

        blown = (
            '<xdr:twoCellAnchor editAs="oneCell">'
            '<xdr:from><xdr:col>2</xdr:col><xdr:colOff>803068</xdr:colOff>'
            '<xdr:row>3</xdr:row><xdr:rowOff>171782</xdr:rowOff></xdr:from>'
            '<xdr:to><xdr:col>7</xdr:col><xdr:colOff>939800</xdr:colOff>'
            '<xdr:row>22</xdr:row><xdr:rowOff>157434</xdr:rowOff></xdr:to>'
            '<xdr:pic><a:blip r:embed="rId2"/>'
            '<a:off x="3425618" y="889332"/>'
            '<a:ext cx="5559632" cy="3967102"/></xdr:pic>'
            '</xdr:twoCellAnchor>'
            '<xdr:twoCellAnchor><xdr:from><xdr:col>5</xdr:col><xdr:row>6</xdr:row></xdr:from>'
            '<xdr:to><xdr:col>6</xdr:col><xdr:row>10</xdr:row></xdr:to>'
            '<xdr:pic><a:blip r:embed="rId3"/>'
            '<a:off x="1" y="1"/><a:ext cx="1443764" cy="941161"/></xdr:pic></xdr:twoCellAnchor>'
        )
        # 图片格是 B7:E11。列宽、行高取均匀值，只核对图落在格子里且不变形。
        seated = _seat_blown_pictures(
            blown.encode(),
            {"rId2": _png(535, 375), "rId3": _png(799, 277)},
            [1_000_000] * 12,
            [200_000] * 30,
            [(1, 6, 4, 10)],
        ).decode()
        pic = seated.split("</xdr:twoCellAnchor>", 1)[0]
        cols = [int(item) for item in re.findall(r"<xdr:col>(\d+)</xdr:col>", pic)]
        rows = [int(item) for item in re.findall(r"<xdr:row>(\d+)</xdr:row>", pic)]
        ext = re.search(r'cx="(\d+)" cy="(\d+)"', pic)
        self.assertGreaterEqual(cols[0], 1)
        self.assertLessEqual(cols[1], 5)
        self.assertGreaterEqual(rows[0], 6)
        self.assertLessEqual(rows[1], 11)
        self.assertLess(int(ext.group(2)), 2_000_000)
        self.assertAlmostEqual(int(ext.group(1)) / int(ext.group(2)), 535 / 375, delta=0.05)
        self.assertIn('<a:ext cx="1443764" cy="941161"', seated)

        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "5-变速器连接器"
                sheet["A1"] = "接插件信息"
                sheet.merge_cells("A1:H1")
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                if signal == "SIG_A":
                    from openpyxl.drawing.image import Image
                    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

                    image = Image(BytesIO(png))
                    anchor = TwoCellAnchor(editAs="oneCell")
                    anchor._from = AnchorMarker(col=1, colOff=841168, row=6, rowOff=51132)
                    anchor.to = AnchorMarker(col=2, colOff=658089, row=10, rowOff=138035)
                    image.anchor = anchor
                    sheet.add_image(image)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")
            _rename_picture(current, "image17.png")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            with zipfile.ZipFile(dest) as saved:
                rels_name = next(
                    name for name in saved.namelist() if name.startswith("xl/drawings/_rels/")
                )
                root = ET.fromstring(saved.read(rels_name))
                targets = [
                    item.attrib["Target"]
                    for item in root
                    if item.attrib.get("Type", "").endswith("/image")
                ]
                self.assertTrue(targets)
                for target in targets:
                    if target.startswith("/"):
                        packed = target.lstrip("/")
                    else:
                        packed = "xl/" + target.replace("../", "")
                    self.assertIn(packed, saved.namelist(), target)
                    self.assertTrue(saved.read(packed).startswith(b"\x89PNG"))
            book = load_workbook(dest)
            try:
                placed = book["5-变速器连接器"]._images[0].anchor
                self.assertEqual(placed._from.col, 1)
                self.assertEqual(placed._from.row, 7)
                self.assertEqual(placed._from.colOff, 841168)
                self.assertEqual(placed.to.col, 2)
                self.assertEqual(placed.to.row, 11)
            finally:
                book.close()

    def test_note_column_shifts_the_picture_with_its_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            current = folder / "new.xlsx"
            previous = folder / "old.xlsx"
            def base(signal: str) -> Workbook:
                made = Workbook()
                grid = made.active
                grid.title = "4-整车低压连接器"
                grid["A1"] = "接插件信息"
                grid.merge_cells("A1:H1")
                grid.append(["引脚号", "信号定义", "信号名称"])
                grid.append(["PIN1", signal, "名称"])
                grid.merge_cells("A7:D11")
                grid.merge_cells("E7:H11")
                return made

            book = base("SIG_OLD")
            book.save(previous)
            book.close()
            book = base("SIG_A")
            sheet = book.active
            from PIL import Image as PILImage
            from openpyxl.drawing.image import Image
            from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

            blob = BytesIO()
            PILImage.new("RGB", (20, 14), "white").save(blob, format="PNG")
            blob.seek(0)
            image = Image(blob)
            anchor = TwoCellAnchor(editAs="oneCell")
            anchor._from = AnchorMarker(col=1, colOff=0, row=3, rowOff=0)
            anchor.to = AnchorMarker(col=6, colOff=0, row=22, rowOff=0)
            image.anchor = anchor
            sheet.add_image(image)
            book.save(current)
            book.close()
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            saved = load_workbook(dest, rich_text=True)
            try:
                sheet = saved["4-整车低压连接器"]
                self.assertEqual(_shown(sheet.cell(1, 1).value), _note_plain())
                self.assertEqual(sheet.cell(2, 1).value, "接插件信息")
                placed = sheet._images[0].anchor
                self.assertEqual(placed._from.col, 1)
                self.assertEqual(placed._from.row, 4)
                self.assertEqual(placed.to.col, 6)
                self.assertEqual(placed.to.row, 23)
                self.assertEqual(sheet._images[0]._data()[:8], b"\x89PNG\r\n\x1a\n")
            finally:
                saved.close()

    def test_tall_connector_picture_sits_in_the_view_cell(self) -> None:
        import zipfile

        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str, *, picture: bool) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet["A1"] = "接插件信息"
                sheet.merge_cells("A1:H1")
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                sheet.merge_cells("A7:D11")
                sheet.merge_cells("E7:H11")
                if picture:
                    from openpyxl.drawing.image import Image
                    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

                    blob = BytesIO()
                    PILImage.new("RGB", (20, 14), "white").save(blob, format="PNG")
                    blob.seek(0)
                    image = Image(blob)
                    anchor = TwoCellAnchor(editAs="oneCell")
                    anchor._from = AnchorMarker(col=1, colOff=0, row=3, rowOff=0)
                    anchor.to = AnchorMarker(col=6, colOff=0, row=22, rowOff=0)
                    image.anchor = anchor
                    sheet.add_image(image)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD", picture=False)
            write(current, "SIG_A", picture=True)
            with zipfile.ZipFile(current) as source:
                payload = {item.filename: source.read(item.filename) for item in source.infolist()}
                infos = {item.filename: item for item in source.infolist()}
            drawing = next(name for name in payload if name.startswith("xl/drawings/drawing"))
            text = payload[drawing].decode("utf-8")
            text = text.replace(
                "<a:prstGeom",
                '<a:xfrm xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:off x="1000" y="1000"/>'
                f'<a:ext cx="{20 * 9525}" cy="{14 * 9525}"/></a:xfrm><a:prstGeom',
                1,
            )
            payload[drawing] = text.encode("utf-8")
            with zipfile.ZipFile(current, "w") as target:
                for filename, data in payload.items():
                    target.writestr(infos[filename], data)
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            with zipfile.ZipFile(dest) as saved:
                drawing = next(name for name in saved.namelist() if name.startswith("xl/drawings/drawing"))
                text = saved.read(drawing).decode("utf-8")
            rows = [int(item) for item in re.findall(r"<(?:xdr:)?row>(\d+)</(?:xdr:)?row>", text)]
            self.assertIn("twoCellAnchor", text)
            self.assertNotIn("oneCellAnchor", text)
            self.assertEqual(rows, [4, 23])
            self.assertIn(f'cx="{20 * 9525}"', text)
            self.assertIn(f'cy="{14 * 9525}"', text)

    def test_note_column_opens_in_normal_view_and_moves_the_page_break(self) -> None:
        from openpyxl.worksheet.pagebreak import Break

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet["A1"] = "接插件信息"
                sheet.merge_cells("A1:H1")
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                view = sheet.views.sheetView[0]
                view.view = "pageBreakPreview"
                view.topLeftCell = "I49"
                sheet.col_breaks.append(Break(id=8, min=0, max=142, man=True))
                sheet.row_breaks.append(Break(id=83, min=0, max=16383, man=True))
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            saved = load_workbook(dest)
            try:
                sheet = saved["4-整车低压连接器"]
                view = sheet.views.sheetView[0]
                self.assertEqual(view.view, "normal")
                self.assertEqual(view.topLeftCell, "A1")
                self.assertEqual([brk.id for brk in sheet.col_breaks.brk], [8])
                self.assertEqual([brk.id for brk in sheet.row_breaks.brk], [84])
            finally:
                saved.close()

    def test_each_sheet_keeps_its_own_picture(self) -> None:
        from PIL import Image as PILImage
        from openpyxl.drawing.image import Image
        from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor

        colors = {
            "2-高压接口定义": ("red", 6),
            "3-整车12V连接器": ("blue", 0),
            "4-整车低压连接器": ("green", 1),
        }

        def png(color: str) -> bytes:
            blob = BytesIO()
            PILImage.new("RGB", (8, 6), color).save(blob, format="PNG")
            return blob.getvalue()

        blobs = {name: png(color) for name, (color, _col) in colors.items()}
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                for index, (name, (_color, col)) in enumerate(colors.items()):
                    sheet = book.active if index == 0 else book.create_sheet()
                    sheet.title = name
                    if "低压" in name:
                        sheet["A1"] = "接插件信息"
                        sheet.merge_cells("A1:H1")
                    sheet.append(["引脚号", "信号定义", "信号名称"])
                    sheet.append(["PIN1", signal if "低压" in name else "SIG", "名称"])
                    image = Image(BytesIO(blobs[name]))
                    anchor = TwoCellAnchor(editAs="oneCell")
                    anchor._from = AnchorMarker(col=col, colOff=10, row=2, rowOff=0)
                    anchor.to = AnchorMarker(col=col + 1, colOff=20, row=4, rowOff=0)
                    image.anchor = anchor
                    sheet.add_image(image)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            saved = load_workbook(dest, rich_text=True)
            try:
                low = saved["4-整车低压连接器"]
                self.assertTrue(_shown(low.cell(1, 1).value).startswith("备注"))
                self.assertEqual(low.cell(2, 1).value, "接插件信息")
                self.assertEqual(low._images[0].anchor._from.col, 1)
                self.assertEqual(saved["2-高压接口定义"]._images[0].anchor._from.col, 6)
                self.assertEqual(saved["3-整车12V连接器"]._images[0].anchor._from.col, 0)
                for name, blob in blobs.items():
                    self.assertEqual(saved[name]._images[0]._data(), blob)
                    self.assertEqual(len(saved[name]._images), 1)
            finally:
                saved.close()

    def test_grouped_column_width_stays_out_of_the_default(self) -> None:
        import zipfile
        from xml.etree import ElementTree as ET

        from openpyxl.worksheet.dimensions import ColumnDimension

        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str) -> None:
                book = Workbook()
                low = book.active
                low.title = "4-整车低压连接器"
                low["A1"] = "接插件信息"
                low.merge_cells("A1:H1")
                low.append(["引脚号", "信号定义", "信号名称"])
                low.append(["PIN1", signal, "名称"])
                low.column_dimensions["G"] = ColumnDimension(low, index="G", min=7, max=8, width=18.4)
                hv = book.create_sheet("2-高压接口定义")
                hv.append(["引脚号", "信号定义", "信号名称"])
                hv.append(["PIN1", signal, "名称"])
                hv.column_dimensions["G"] = ColumnDimension(hv, index="G", min=7, max=8, width=18.4)
                from openpyxl.drawing.image import Image

                low.add_image(Image(BytesIO(png)), "B2")
                hv.add_image(Image(BytesIO(png)), "B2")
                book.save(path)
                book.close()

            write(previous, "SIG_OLD")
            write(current, "SIG_A")
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)

            def width_at(sheet_name: str, col: int) -> float | None:
                with zipfile.ZipFile(dest) as book:
                    root = ET.fromstring(book.read("xl/workbook.xml"))
                    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
                    targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels}
                    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
                    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
                    chosen = None
                    for sheet in root.findall(f"{ns}sheets/{ns}sheet"):
                        if sheet.attrib["name"] == sheet_name:
                            target = targets[sheet.attrib[f"{rel_ns}id"]].lstrip("/")
                            chosen = target if target.startswith("xl/") else "xl/" + target
                    xml = ET.fromstring(book.read(chosen))
                found = None
                for item in xml.findall(f"{ns}cols/{ns}col"):
                    if int(item.attrib["min"]) <= col <= int(item.attrib["max"]):
                        found = float(item.attrib["width"])
                return found

            self.assertEqual(width_at("2-高压接口定义", 7), 18.4)
            self.assertEqual(width_at("2-高压接口定义", 8), 18.4)
            self.assertEqual(width_at("4-整车低压连接器", 7), 18.4)
            self.assertEqual(width_at("4-整车低压连接器", 8), 18.4)

    def test_original_row_marks_come_back(self) -> None:
        from electrical_krow.icd_book import _restore_row_heights, _row_height_attrs

        original = '<sheetFormatPr defaultRowHeight="16.5"/><row r="5" spans="1:19" x14ac:dyDescent="0.45"/>'
        saved = _restore_row_heights(
            '<row r="5"/>',
            _row_height_attrs(original),
            16.5,
        )
        self.assertIn('spans="1:19"', saved)
        self.assertIn('x14ac:dyDescent="0.45"', saved)
        self.assertIn('ht="16.5"', saved)
        self.assertIn('customHeight="1"', saved)

    def test_side_summary_keeps_picture_row_height(self) -> None:
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            previous = folder / "old.xlsx"
            current = folder / "new.xlsx"

            def write(path: Path, signal: str, *, picture: bool) -> None:
                book = Workbook()
                sheet = book.active
                sheet.title = "4-整车低压连接器"
                sheet.append(["引脚号", "信号定义", "信号名称"])
                sheet.append(["PIN1", signal, "名称"])
                sheet.row_dimensions[1].height = 18
                sheet.row_dimensions[2].height = 30
                sheet.column_dimensions["A"].width = 8
                sheet.column_dimensions["E"].width = 9
                if picture:
                    from openpyxl.drawing.image import Image

                    image = Image(BytesIO(png))
                    image.anchor = "B2"
                    sheet.add_image(image)
                    hv = book.create_sheet("高压接口")
                    hv.append(["引脚号", "信号定义", "信号名称"])
                    hv.append(["PIN1", signal, "名称"])
                    hv.column_dimensions["A"].width = 7.5
                    hv.column_dimensions["E"].width = 9
                    hv.row_dimensions[2].height = 20
                    photo = Image(BytesIO(png))
                    photo.anchor = "A2"
                    hv.add_image(photo)
                book.save(path)
                book.close()

            write(previous, "SIG_OLD", picture=False)
            write(current, "SIG_A", picture=True)
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                source = book["4-整车低压连接器"]
                self.assertEqual(source.row_dimensions[1].height, 18)
                self.assertEqual(source.row_dimensions[2].height, 30)
                import zipfile
                with zipfile.ZipFile(dest) as packed:
                    sheet_xml = packed.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn('r="2"', sheet_xml)
                self.assertRegex(sheet_xml, r'<row[^>]*r="2"[^>]*ht="30"')
                self.assertTrue(source._images)
                self.assertEqual(source.column_dimensions["A"].width, 8)
                self.assertEqual(source.column_dimensions["E"].width, 9)
                hv = book["高压接口"]
                self.assertEqual(hv.column_dimensions["A"].width, 7.5)
                self.assertEqual(hv.column_dimensions["E"].width, 9)
                self.assertEqual(hv.row_dimensions[2].height, 20)
                legend = next(
                    source.cell(1, col)
                    for col in range(1, (source.max_column or 1) + 1)
                    if _shown(source.cell(1, col).value).startswith("备注")
                )
                self.assertIn("不把整行涂黄", _shown(legend.value))
            finally:
                book.close()

            path = Path(raw) / "empty.xlsx"
            book = Workbook()
            book.active.title = "封面"
            book.active["A1"] = "不是接插件表"
            book.save(path)
            book.close()
            with self.assertRaises(ValueError):
                read_icd(path)

    def test_gateway_returns_the_pin_workbook(self) -> None:
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from electrical_krow.config import load_settings
        from electrical_krow.gateway import create_app
        from electrical_krow.login import AuthSession
        from electrical_krow.mock_server import DEMO_USER

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        client = TestClient(create_app(load_settings(server_url="http://127.0.0.1:18766"), output_dir=Path(folder.name)))
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        self.assertEqual(login.status_code, 200)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "icd.xlsx"
            _book(path)
            payload = path.read_bytes()
        with patch("electrical_krow.gateway.open_locally"):
            resp = client.post(
                "/api/icd",
                files={"file": ("接插件ICD.xlsx", payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["pins"], 2)
        self.assertEqual(data["hv"], 1)
        self.assertEqual(data["changes"], 0)
        got = client.get(data["download"])
        self.assertEqual(got.status_code, 200)
        book = load_workbook(BytesIO(got.content))
        self.assertIn("4-整车低压连接器", book.sheetnames)
        self.assertIn("2-高压接口定义", book.sheetnames)
        self.assertNotIn("引脚清单", book.sheetnames)
        self.assertNotIn("版本差异", book.sheetnames)
        self.assertNotIn("差异总结", book.sheetnames)
        book.close()
        bad = client.post("/api/icd", files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Excel", bad.json()["detail"])
