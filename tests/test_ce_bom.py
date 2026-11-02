"""CE BOM 只抄当份手册。单位不换算，多规格和缺项留空。"""
from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from electrical_krow.ce_bom import build_ce_bom
from electrical_krow.config import load_settings
from electrical_krow.gateway import create_app
from electrical_krow.login import AuthSession
from electrical_krow.mock_server import DEMO_USER


def _xlsx(path: Path, rows: list[list[str]], title: str = "Sheet1") -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    book.save(path)
    book.close()


class CeBomTests(unittest.TestCase):
    def test_copies_handbook_values_and_leaves_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "template.xlsx"
            manual = folder / "manual.xlsx"
            _xlsx(template, [["物料", "规格", "长(mm)", "宽(mm)", "高(mm)", "重量(g)"]])
            _xlsx(manual, [
                ["物料名称", "型号", "长度", "宽度", "高度", "重量"],
                ["电阻", "0805", "10mm", "5mm", "2mm", ""],
                ["电容", "0603", "1.2cm", "3mm", "1mm", "0.2g"],
            ])
            dest = folder / "out.xlsx"
            result = build_ce_bom([manual], template, dest)
            book = load_workbook(dest)
            rows = list(book["CE BOM"].iter_rows(values_only=True))
            self.assertEqual(list(rows[0]), ["物料", "规格", "长(mm)", "宽(mm)", "高(mm)", "重量(g)"])
            resistor = rows[1]
            self.assertEqual(resistor[0], "电阻")
            self.assertEqual(resistor[2], "10mm")
            self.assertEqual(resistor[5], None)
            capacitor = rows[2]
            self.assertIsNone(capacitor[2])
            self.assertNotEqual(capacitor[2], 12)
            notes = "\n".join("" if item is None else str(item) for row in book["核验记录"].iter_rows(values_only=True) for item in row)
            self.assertIn("单位不一致", notes)
            self.assertIn("信息缺失", notes)
            self.assertIn("未规定完整度或一致性的通过阈值", notes)
            self.assertGreater(result.blank, 0)
            book.close()

    def test_multiple_specs_are_not_chosen(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "template.xlsx"
            manual = folder / "manual.xlsx"
            _xlsx(template, [["物料", "规格", "长(mm)"]])
            _xlsx(manual, [
                ["物料", "规格", "长度(mm)"],
                ["电感", "A", "8"],
                ["电感", "A", "9"],
            ])
            dest = folder / "out.xlsx"
            result = build_ce_bom([manual], template, dest)
            book = load_workbook(dest)
            body = list(book["CE BOM"].iter_rows(min_row=2, values_only=True))
            book.close()
            self.assertEqual(len(body), 1)
            self.assertEqual(body[0][0], "电感")
            self.assertIsNone(body[0][2])
            self.assertEqual(result.conflicts, 1)

    def test_gateway_requires_template_and_returns_workbook(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        client = TestClient(create_app(load_settings(server_url="http://127.0.0.1:18766"), output_dir=Path(folder.name)))
        session = AuthSession(access_token="tok", username=DEMO_USER, source="password")
        with patch("electrical_krow.gateway.login_with_password", return_value=session):
            login = client.post("/api/login", json={"username": DEMO_USER, "password": "demo"})
        self.assertEqual(login.status_code, 200)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            template = root / "template.xlsx"
            manual = root / "manual.xlsx"
            _xlsx(template, [["物料", "长(mm)"]])
            _xlsx(manual, [["物料名称", "长度"], ["磁芯", "4mm"]])
            with patch("electrical_krow.gateway.open_locally"):
                resp = client.post(
                    "/api/ce-bom",
                    files=[
                        ("manuals", ("manual.xlsx", manual.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                        ("template", ("template.xlsx", template.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
                    ],
                )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["rows"], 1)
        self.assertTrue(data["name"].startswith("CEBOM-"))
        got = client.get(data["download"])
        book = load_workbook(BytesIO(got.content))
        self.assertEqual(set(book.sheetnames), {"CE BOM", "字段映射", "核验记录"})
        self.assertEqual(book["CE BOM"]["A2"].value, "磁芯")
        self.assertEqual(book["CE BOM"]["B2"].value, "4mm")
        book.close()
        bad = client.post("/api/ce-bom", files=[("manuals", ("a.pdf", b"%PDF", "application/pdf")), ("template", ("a.pdf", b"%PDF", "application/pdf"))])
        self.assertEqual(bad.status_code, 400)
        self.assertIn("Excel", bad.json()["detail"])
