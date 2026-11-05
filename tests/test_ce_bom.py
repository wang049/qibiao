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

    def test_standard_sheet_keeps_structure_formulas_and_existing_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            manual = folder / "manual.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            sheet["A14"] = "序号"
            sheet["B14"] = "零件中文名称"
            sheet["C14"] = "产品尺寸(mm)"
            sheet.merge_cells("C14:E14")
            sheet["C15"] = "X"
            sheet["D15"] = "Y"
            sheet["E15"] = "Z"
            sheet["F14"] = "产品净重（g）"
            sheet["B16"] = "密封圈"
            sheet["C16"] = 81.4
            sheet["F16"] = "=C16*2"
            sheet["B17"] = "铜排"
            sheet["C17"] = 10
            book.save(template)
            book.close()
            _xlsx(manual, [["物料名称", "长度"], ["密封圈", "999mm"]])
            dest = folder / "out.xlsx"
            result = build_ce_bom([manual], template, dest)
            self.assertTrue(result.standard)
            self.assertEqual(result.filled, 0)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertEqual(body["B16"].value, "密封圈")
            self.assertEqual(body["C16"].value, 81.4)
            self.assertEqual(body["F16"].value, "=C16*2")
            self.assertEqual(body["C15"].value, "X")
            self.assertNotIn("999", " ".join("" if cell.value is None else str(cell.value) for row in body.iter_rows(min_row=16, max_row=17) for cell in row))
            notes = "\n".join("" if item is None else str(item) for row in saved["核验记录"].iter_rows(values_only=True) for item in row)
            mapping = "\n".join("" if item is None else str(item) for row in saved["字段映射"].iter_rows(values_only=True) for item in row)
            saved.close()
            self.assertIn("尺寸X", mapping)
            self.assertIn("净重", mapping)
            self.assertIn("必填", mapping)
            self.assertIn("保持不动", notes)
            self.assertIn("不作为其他物料的填写依据", notes)
            self.assertIn("未写入标准表", notes)
            self.assertIn("第16行缺序号", notes)
            self.assertIn("密度未给定", notes)
            self.assertEqual(result.blank, 2)

    def test_cover_plate_missing_thickness_is_recorded_not_filled(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            for col, title in enumerate(("序号", "级别1", "零件中文名称", "零件号", "图片", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料"), start=1):
                sheet.cell(14, col, title or None)
            sheet.merge_cells("G14:I14")
            sheet["G15"] = "X"
            sheet["H15"] = "Y"
            sheet["I15"] = "Z"
            sheet["A16"] = 1
            sheet["B16"] = "●"
            sheet["C16"] = "上盖板"
            sheet["F16"] = 1
            sheet["A17"] = 2
            sheet["B17"] = "●"
            sheet["C17"] = "电阻"
            sheet["D17"] = "R100"
            sheet["F17"] = 4
            book.save(template)
            book.close()
            dest = folder / "out.xlsx"
            result = build_ce_bom([], template, dest)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertIsNone(body["J16"].value)
            self.assertEqual(body["C16"].value, "上盖板")
            notes = "\n".join("" if item is None else str(item) for row in saved["核验记录"].iter_rows(values_only=True) for item in row)
            mapping = "\n".join("" if item is None else str(item) for row in saved["字段映射"].iter_rows(values_only=True) for item in row)
            saved.close()
            self.assertIn("盖板缺材料厚度", notes)
            self.assertNotIn("电阻", notes.split("盖板")[0])
            self.assertIn("暂不处理", mapping)
            self.assertIn("有则填", mapping)
            self.assertEqual(result.filled, 0)

    def test_edf_counts_same_part_and_does_not_fill_the_standard_sheet(self) -> None:
        edif = """(edif demo
  (Instance R1
    (Property Type (String "Res"))
    (Property Comment (String "470Ω"))
    (Property Footprint (String "R0402"))
    (Property (rename Design_Item_ID "Design Item ID") (String "Res, 470Ω, 0402"))
  )
  (Instance R2
    (Property Type (String "Res"))
    (Property Comment (String "470Ω"))
    (Property Footprint (String "R0402"))
    (Property (rename Design_Item_ID "Design Item ID") (String "Res, 470Ω, 0402"))
  )
  (Instance C1
    (Property Type (String "Cap"))
    (Property Value (String "100nF"))
    (Property Footprint (String "C0402"))
  )
)"""
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            for col, title in enumerate(("序号", "级别1", "零件中文名称", "零件号", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料"), start=1):
                sheet.cell(14, col, title or None)
            sheet.merge_cells("F14:H14")
            sheet["F15"] = "X"
            sheet["G15"] = "Y"
            sheet["H15"] = "Z"
            sheet["A16"] = 1
            sheet["B16"] = "●"
            sheet["C16"] = "电阻"
            sheet["E16"] = 2
            book.save(template)
            book.close()
            edf = folder / "board.edf"
            edf.write_text(edif, encoding="utf-8")
            dest = folder / "out.xlsx"
            result = build_ce_bom([edf], template, dest)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertEqual(body["C16"].value, "电阻")
            self.assertIsNone(body["D16"].value)
            parts = list(saved["EDF器件"].iter_rows(min_row=2, values_only=True))
            notes = "\n".join("" if item is None else str(item) for row in saved["核验记录"].iter_rows(values_only=True) for item in row)
            saved.close()
            resistor = next(row for row in parts if row[0] == "Res")
            self.assertEqual(resistor[4], "2")
            self.assertEqual(resistor[3], "R0402")
            self.assertIn("R1", resistor[5])
            self.assertIn("不写入标准表", notes)
            self.assertIn("没有零件中文名称", notes)
            self.assertEqual(result.filled, 0)

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
