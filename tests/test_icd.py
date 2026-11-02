"""接插件 ICD 只抄当份表。空脚待确认，有上一版才写差异。"""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook

from electrical_krow.icd_book import build_icd, read_icd


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
            diff = list(book["版本差异"].iter_rows(min_row=2, values_only=True))
            book.close()
            kinds = {(row[1], row[2], row[3]) for row in diff}
            self.assertIn(("PIN1", "变更", "信号定义"), kinds)
            self.assertIn(("PIN4", "新增", "引脚"), kinds)
            self.assertIn(("PIN3", "删除", "引脚"), kinds)

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
        self.assertIn("引脚清单", book.sheetnames)
        self.assertNotIn("版本差异", book.sheetnames)
        book.close()
        bad = client.post("/api/icd", files={"file": ("notes.pdf", b"%PDF-1.4", "application/pdf")})
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Excel", bad.json()["detail"])
