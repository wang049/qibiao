"""接插件 ICD 只抄当份表。空脚待确认，有上一版才写差异。"""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook

from electrical_krow.hsi_book import hsi_keyword_hits
from electrical_krow.icd_book import _icd_status, build_icd, read_icd


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
            colors = {}
            for row in range(1, summary.max_row + 1):
                kind = summary.cell(row, 3).value
                field = summary.cell(row, 4).value
                if kind not in {"新增", "修改", "删除"} or field in {None, "", "删除", "字段"}:
                    continue
                colors[kind] = str(summary.cell(row, 3).fill.fgColor.rgb or "")
            self.assertNotIn("引脚清单", book.sheetnames)
            self.assertNotIn("版本差异", book.sheetnames)
            self.assertIn("差异总结", book.sheetnames)
            kinds = {
                (summary.cell(row, 2).value, summary.cell(row, 3).value, summary.cell(row, 4).value)
                for row in range(1, summary.max_row + 1)
            }
            book.close()
            self.assertIn(("PIN1", "修改", "信号定义"), kinds)
            self.assertIn(("PIN4", "新增", "引脚"), kinds)
            self.assertIn(("PIN3", "删除", "引脚"), kinds)
            self.assertTrue(colors["新增"].endswith("C6EFCE"))
            self.assertTrue(colors["删除"].endswith("FFC7CE"))
            self.assertTrue(colors["修改"].endswith("FFE699"))

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
            draft.active.column_dimensions["A"].width = 14
            draft.active.column_dimensions["D"].width = 9
            draft.save(current)
            draft.close()
            dest = folder / "out.xlsx"
            build_icd(current, dest, previous)
            book = load_workbook(dest)
            try:
                self.assertEqual(book.sheetnames, ["差异总结", "4-整车低压连接器"])
                self.assertNotIn("变更记录", book.sheetnames)
                self.assertNotIn("版本差异", book.sheetnames)
                self.assertEqual(book.active.title, "差异总结")
                source = book["4-整车低压连接器"]
                self.assertGreater(source.max_row, 2)
                self.assertTrue(str(source.cell(2, 2).fill.fgColor.rgb or "").endswith("FFE699"))
                flat = [
                    str(source.cell(row, col).value or "")
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                ]
                self.assertTrue(any(item.startswith("本表小结") for item in flat))
                summary_cell = next(
                    source.cell(row, col)
                    for row in range(1, source.max_row + 1)
                    for col in range(1, (source.max_column or 1) + 1)
                    if str(source.cell(row, col).value or "").startswith("本表小结")
                )
                self.assertEqual(summary_cell.column, 1)
                self.assertEqual(summary_cell.alignment.horizontal, "left")
                self.assertEqual(source.cell(summary_cell.row + 1, 1).value, "差异")
                self.assertIn("上一版", flat)
                self.assertIn("当版", flat)
                overall = book["差异总结"]
                self.assertIn("old.xlsx", str(overall.cell(1, 1).value))
                self.assertIn("V3.11", str(overall.cell(1, 1).value))
                self.assertIn("new.xlsx", str(overall.cell(2, 1).value))
                self.assertIn("V3.12", str(overall.cell(2, 1).value))
                self.assertLessEqual(overall.column_dimensions["B"].width, 20)
                self.assertEqual(source.column_dimensions["A"].width, 14)
                self.assertEqual(source.column_dimensions["D"].width, 9)
                kinds = {
                    (overall.cell(row, 2).value, overall.cell(row, 3).value)
                    for row in range(1, overall.max_row + 1)
                }
                self.assertIn(("PIN1", "修改"), kinds)
                self.assertNotIn(("PIN1", "新增"), kinds)
                painted = ""
                for row in range(1, overall.max_row + 1):
                    if overall.cell(row, 2).value == "PIN1" and overall.cell(row, 3).value == "修改":
                        painted = str(overall.cell(row, 3).fill.fgColor.rgb or "")
                        break
                self.assertTrue(painted.endswith("FFE699"))
                self.assertGreaterEqual(overall.column_dimensions["A"].width, 18)
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
                kinds = {
                    (overall.cell(row, 2).value, overall.cell(row, 3).value, overall.cell(row, 4).value)
                    for row in range(1, overall.max_row + 1)
                }
                self.assertIn(("PIN30", "修改", "引脚号"), kinds)
                self.assertNotIn(("PIN30", "新增", "引脚"), kinds)
                source = book["4-整车低压连接器"]
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
                current_text = " ".join(
                    str(overall.cell(row, 6).value or "")
                    for row in range(1, overall.max_row + 1)
                    if overall.cell(row, 4).value == "引脚号"
                )
                self.assertIn("Chassis", current_text)
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
                overall_rows = [row for row in range(1, overall.max_row + 1) if overall.cell(row, 6).value == long]
                self.assertTrue(overall_rows)
                self.assertGreaterEqual(overall.row_dimensions[overall_rows[0]].height or 0, 40)
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
                overall = book["差异总结"]
                rows = [
                    tuple(overall.cell(row, col).value for col in range(2, 7))
                    for row in range(1, overall.max_row + 1)
                    if overall.cell(row, 3).value in {"新增", "修改", "删除"}
                    and overall.cell(row, 4).value not in {None, "", "删除", "字段"}
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
            finally:
                book.close()

    def test_workbook_without_icd_tables_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
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
