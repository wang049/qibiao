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
    def test_previous_bom_marks_difference_and_does_not_invent_rows(self) -> None:
        from electrical_krow.ce_bom import _read_previous_bom, bom_field_check

        self.assertEqual(
            bom_field_check("电阻", "2", "10k", 4, {"电阻": ("1", "10k", 4)}),
            "不一致：用量",
        )
        self.assertEqual(
            bom_field_check("电阻", "2", "10k", 4, {"电阻": ("2", "10k", 4)}),
            "一致",
        )
        self.assertEqual(bom_field_check("新件", "1", "", 4, {"电阻": ("1", "", 0)}), "上一版没有")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "old.xlsx"
            _xlsx(path, [["零件中文名称", "用量", "规格型号"], ["电阻", "1", "10k"]])
            self.assertEqual(_read_previous_bom(path)["电阻"], ("1", "10k", 0))
            self.assertNotIn("电容", _read_previous_bom(path))
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
            sheet["A1"] = "PMXU件应该成本计算技术分解"
            sheet["A2"] = "项目"
            sheet["G2"] = "3DHT200"
            sheet["K2"] = 300
            sheet["Q2"] = 0
            sheet["X2"] = "无锡星驱科技有限公司"
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
            sheet.freeze_panes = "H105"
            sheet.auto_filter.ref = "A15:F40"
            book.save(template)
            book.close()
            _xlsx(manual, [["物料名称", "长度"], ["密封圈", "999mm"]])
            dest = folder / "out.xlsx"
            result = build_ce_bom([manual], template, dest)
            self.assertTrue(result.standard)
            self.assertEqual(result.filled, 0)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertIsNone(body["A1"].value)
            self.assertEqual(body["A2"].value, "项目")
            self.assertIsNone(body["G2"].value)
            self.assertIsNone(body["K2"].value)
            self.assertIsNone(body["Q2"].value)
            self.assertIsNone(body["X2"].value)
            self.assertIsNone(body["B16"].value)
            self.assertIsNone(body["C16"].value)
            self.assertIsNone(body["F16"].value)
            self.assertIsNone(body["B17"].value)
            self.assertEqual(body["C15"].value, "X")
            self.assertEqual(body.freeze_panes, "A16")
            self.assertEqual(body.views.sheetView[0].pane.topLeftCell, "A16")
            self.assertIsNone(body.auto_filter.ref)
            self.assertNotIn("999", " ".join("" if cell.value is None else str(cell.value) for row in body.iter_rows(min_row=16, max_row=17) for cell in row))
            self.assertNotIn("密封圈", " ".join("" if cell.value is None else str(cell.value) for row in body.iter_rows(min_row=16, max_row=20) for cell in row))
            self.assertEqual(saved.sheetnames, ["供应商", "字段匹配"])
            saved.close()
            self.assertEqual(result.blank, 0)

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
            self.assertIsNone(body["C16"].value)
            self.assertIsNone(body["C17"].value)
            body_text = " ".join("" if cell.value is None else str(cell.value) for row in body.iter_rows(min_row=16, max_row=20) for cell in row)
            self.assertNotIn("1.5", body_text)
            self.assertNotIn("上盖板", body_text)
            self.assertEqual(saved.sheetnames, ["供应商", "字段匹配"])
            saved.close()
            self.assertEqual(result.filled, 0)

    def test_edf_counts_same_part_and_does_not_fill_the_standard_sheet(self) -> None:
        edif = """(edif demo
  (Instance R1
    (Property Type (String "Res"))
    (Property Comment (String "470Ω"))
    (Property Footprint (String "R0402"))
    (Property (rename Design_Item_ID "Design Item ID") (String "Res, 470Ω, 0402"))
    (Property (rename Manufacture_PN "Manufacture PN") (String "MR04X4700FTL"))
  )
  (Instance R2
    (Property Type (String "Res"))
    (Property Comment (String "470Ω"))
    (Property Footprint (String "R0402"))
    (Property (rename Design_Item_ID "Design Item ID") (String "Res, 470Ω, 0402"))
    (Property (rename Manufacture_PN "Manufacture PN") (String "MR04X4700FTL"))
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
            for col, title in enumerate(("序号", "级别", "", "", "", "", "零件中文名称", "零件号", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料", "规格型号"), start=1):
                sheet.cell(14, col, title or None)
            for col, number in enumerate("12345", start=2):
                sheet.cell(15, col, number)
            sheet.merge_cells("J14:L14")
            sheet["J15"] = "X"
            sheet["K15"] = "Y"
            sheet["L15"] = "Z"
            sheet["A16"] = 1
            sheet["B16"] = "●"
            sheet["G16"] = "电阻"
            sheet["I16"] = 2
            book.save(template)
            book.close()
            edf = folder / "board.edf"
            edf.write_text(edif, encoding="utf-8")
            dest = folder / "out.xlsx"
            result = build_ce_bom([edf], template, dest)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertEqual(saved.sheetnames, ["供应商", "字段匹配"])
            self.assertEqual(body["A16"].value, 1)
            self.assertEqual(body["E16"].value, "●")
            self.assertIsNone(body["B16"].value)
            from electrical_krow.ce_bom import DEFAULT_CE_BOM_NAME_RULES, read_name_rules

            names = read_name_rules(DEFAULT_CE_BOM_NAME_RULES)
            self.assertEqual(body["G16"].value, names.get("res") or None)
            self.assertEqual(body["H16"].value, "MR04X4700FTL")
            self.assertEqual(body["I16"].value, 2)
            self.assertIsNone(body["J16"].value)
            self.assertEqual(body["P16"].value, "Res, 470Ω, 0402")
            self.assertEqual(body["A17"].value, 2)
            self.assertEqual(body["G17"].value, names.get("cap") or None)
            self.assertIsNone(body["H17"].value)
            self.assertEqual(body["I17"].value, 1)
            self.assertEqual(body["P17"].value, "100nF")
            self.assertIsNone(body["J17"].value)
            saved.close()
            self.assertEqual(result.filled, 0)

    def test_issue_version_skips_merged_title_cells(self) -> None:
        from openpyxl.cell.cell import MergedCell

        from electrical_krow.ce_bom import _place_issue_version

        book = Workbook()
        sheet = book.active
        sheet.merge_cells("A1:B3")
        sheet["A1"] = "标题"
        sheet.merge_cells("A4:B13")
        sheet["A14"] = "序号"
        _place_issue_version(sheet, 14)
        found = []
        for row in sheet.iter_rows(max_row=14, max_col=6):
            for cell in row:
                if isinstance(cell, MergedCell) or not cell.value:
                    continue
                if "出表版本" in str(cell.value):
                    found.append((cell.coordinate, str(cell.value)))
        self.assertTrue(found)
        book.close()

    def test_name_rules_read_type_from_every_sheet(self) -> None:
        from electrical_krow.ce_bom import read_name_rules

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "rules.xlsx"
            book = Workbook()
            res = book.active
            res.title = "01_Resistor"
            res.append(["Type", "类型"])
            res.append(["Res", "贴片电阻"])
            res.append(["Cap", None])
            ind = book.create_sheet("03_Inductor")
            ind.append(["Design Item ID", "Type", "类型"])
            ind.append(["IND, 1uH", "IND", "电感"])
            ind.append(["Bead, 2000Ω", "Bead", "磁珠"])
            other = book.create_sheet("10_Others")
            other.append(["Type", "类型"])
            other.append(["*", "（未定义）"])
            other.append(["Z", "稳压管/特殊器件"])
            other.append(["Z", "Mark点"])
            book.save(path)
            book.close()
            rules = read_name_rules(path)
            self.assertEqual(rules["res"], "贴片电阻")
            self.assertEqual(rules["ind"], "电感")
            self.assertEqual(rules["bead"], "磁珠")
            self.assertEqual(rules["z"], "稳压管/特殊器件")
            self.assertNotIn("*", rules)
            self.assertNotIn("cap", rules)

    def test_ad_bom_type_maps_to_chinese_name(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            for col, title in enumerate(("序号", "级别", "", "", "", "", "零件中文名称", "零件号", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料"), start=1):
                sheet.cell(14, col, title or None)
            for col, number in enumerate("12345", start=2):
                sheet.cell(15, col, number)
            sheet.merge_cells("J14:L14")
            sheet["J15"] = "X"
            sheet["K15"] = "Y"
            sheet["L15"] = "Z"
            sheet["A16"] = 3
            sheet["G16"] = "上盖板"
            book.save(template)
            book.close()
            rules = folder / "rules.xlsx"
            bom = folder / "bom.xlsx"
            _xlsx(rules, [["Type", "中文名称"], ["MCU", "微控制器"], ["Cap", "电容"]], title="06_IC")
            _xlsx(bom, [
                ["Comment", "Designator", "Quantity", "Manufacture PN", "Fitted", "Type"],
                ["0.1uF", "C1, C2", "2", "CL05B104KB54PNC", "Fitted", "Cap"],
                ["TC499", "U1", "1", "SAK-TC499", "Fitted", "MCU"],
                ["10k", "R1", "1", "RC0402", "Fitted", "Res"],
            ])
            dest = folder / "out.xlsx"
            with patch("electrical_krow.ce_bom.DEFAULT_CE_BOM_NAME_RULES", rules):
                result = build_ce_bom([bom], template, dest)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertEqual(body["E16"].value, "●")
            self.assertIsNone(body["B16"].value)
            self.assertEqual(body["A16"].value, 1)
            self.assertEqual(body["G16"].value, "电容")
            self.assertEqual(body["H16"].value, "CL05B104KB54PNC")
            self.assertEqual(body["I16"].value, 2)
            self.assertEqual(body["G17"].value, "微控制器")
            self.assertIsNone(body["G18"].value)
            self.assertEqual(body["I18"].value, 1)
            self.assertIsNone(body["J16"].value)
            self.assertNotIn("上盖板", " ".join("" if cell.value is None else str(cell.value) for row in body.iter_rows(min_row=16, max_row=20) for cell in row))
            self.assertEqual(saved.sheetnames, ["供应商", "字段匹配"])
            self.assertGreaterEqual(saved["字段匹配"].column_dimensions["D"].width, 17)
            match = saved["字段匹配"]
            results = {
                (match.cell(row, 2).value, match.cell(row, 3).value): match.cell(row, 5).value
                for row in range(2, match.max_row + 1)
            }
            self.assertEqual(results[("电容", "中文名称")], "已对上")
            self.assertEqual(results[("电容", "级别")], "已对上")
            self.assertEqual(results[("电容", "规格型号")], "已对上")
            self.assertEqual(results[("RC0402", "中文名称")], "未对上")
            saved.close()
            self.assertEqual(result.filled, 0)

    def test_structure_drawing_reads_title_and_detail_rows(self) -> None:
        from electrical_krow.ce_structure import _bom_rows, _title_row

        words = [
            (1483, 950, 1540, 962, "上级总成"),
            (1500, 972, 1560, 984, "5501801726"),
            (1534, 993, 1580, 1005, "图样代号"),
            (1526, 1008, 1580, 1020, "5501801798"),
            (1352, 950, 1410, 962, "材料标记"),
            (1375, 972, 1450, 984, "Al5052-O态"),
            (1408, 1025, 1440, 1037, "质量"),
            (1413, 1054, 1445, 1066, "31g"),
            (1555, 1029, 1610, 1041, "图样名称"),
            (1516, 1047, 1620, 1059, "保险盒接线盖板[3]"),
            (1700, 1100, 1760, 1112, "外形尺寸"),
            (1700, 1120, 1780, 1132, "120×80×15"),
            (1110, 400, 1400, 412, "板料厚度1.5±0.15mm"),
            (1466, 795, 1490, 807, "序号"),
            (1540, 795, 1580, 807, "零件名"),
            (1620, 795, 1650, 807, "材料"),
            (1697, 795, 1720, 807, "数量"),
            (1476, 815, 1488, 827, "1"),
            (1530, 815, 1600, 827, "PN-N铜排"),
            (1617, 815, 1660, 827, "T2HO2"),
            (1707, 815, 1720, 827, "1"),
        ]
        title = _title_row(words, "cover.pdf")
        self.assertIsNotNone(title)
        assert title is not None
        self.assertEqual(title.name, "保险盒接线盖板")
        self.assertEqual(title.part_no, "5501801798")
        self.assertEqual(title.material, "Al5052-O态")
        self.assertEqual(title.weight, "31g")
        self.assertEqual(title.thickness, "1.5±0.15mm")
        self.assertEqual(title.parent, "5501801726")
        self.assertEqual((title.size_x, title.size_y, title.size_z), ("120", "80", "15"))
        details = _bom_rows(words, "cover.pdf", title.part_no)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].size_x, "")
        self.assertEqual(details[0].name, "PN-N铜排")
        self.assertEqual(details[0].material, "T2HO2")
        self.assertEqual(details[0].quantity, "1")
        self.assertEqual(details[0].parent, "5501801798")
        self.assertEqual(title.quantity, "")

    def test_structure_drawing_fills_supplier_sheet_and_drops_template_rows(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            for col, title in enumerate(("序号", "级别", "", "", "", "", "零件中文名称", "零件号", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料"), start=1):
                sheet.cell(14, col, title or None)
            for col, number in enumerate("12345", start=2):
                sheet.cell(15, col, number)
            sheet.merge_cells("J14:L14")
            sheet["J15"] = "X"
            sheet["K15"] = "Y"
            sheet["L15"] = "Z"
            sheet["A16"] = 3
            sheet["G16"] = "密封圈"
            sheet["N16"] = "=1+1"
            book.save(template)
            book.close()
            drawing = folder / "cover.pdf"
            pdf = pymupdf.open()
            page = pdf.new_page(width=1800, height=1200)
            for x, y, text in (
                (1483, 962, "上级总成"),
                (1500, 984, "5501801726"),
                (1534, 1005, "图样代号"),
                (1526, 1020, "5501801798"),
                (1352, 962, "材料标记"),
                (1375, 984, "Al5052-O态"),
                (1408, 1037, "质量"),
                (1413, 1066, "31g"),
                (1555, 1041, "图样名称"),
                (1516, 1059, "保险盒接线盖板"),
                (1110, 412, "板料厚度1.5±0.15mm"),
            ):
                page.insert_text((x, y), text, fontsize=8, fontname="china-s")
            pdf.save(drawing)
            pdf.close()
            dest = folder / "out.xlsx"
            build_ce_bom([drawing], template, dest)
            saved = load_workbook(dest)
            body = saved["供应商"]
            self.assertEqual(body["A16"].value, 1)
            self.assertEqual(body["C16"].value, "●")
            self.assertIsNone(body["B16"].value)
            self.assertEqual(body["G16"].value, "保险盒接线盖板")
            self.assertEqual(body["H16"].value, "5501801798")
            self.assertIsNone(body["I16"].value)
            self.assertIsNone(body["J16"].value)
            self.assertEqual(body["M16"].value, "1.5±0.15mm")
            self.assertEqual(body["N16"].value, "31g")
            self.assertEqual(body["O16"].value, "Al5052-O态")
            self.assertEqual(saved.sheetnames, ["供应商", "字段匹配"])
            saved.close()

    def test_hardware_and_structure_stay_on_separate_supplier_sheets(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            template = folder / "standard.xlsx"
            book = Workbook()
            sheet = book.active
            sheet.title = "供应商"
            for col, title in enumerate(("序号", "级别", "", "", "", "", "零件中文名称", "零件号", "用量", "产品尺寸(mm)", "", "", "材料厚度(mm)", "产品净重（g）", "原材料"), start=1):
                sheet.cell(14, col, title or None)
            for col, number in enumerate("12345", start=2):
                sheet.cell(15, col, number)
            sheet.merge_cells("J14:L14")
            sheet["J15"] = "X"
            sheet["K15"] = "Y"
            sheet["L15"] = "Z"
            sheet["G16"] = "密封圈"
            book.save(template)
            book.close()
            rules = folder / "rules.xlsx"
            bom = folder / "bom.xlsx"
            _xlsx(rules, [["Type", "中文名称"], ["Cap", "电容"]], title="06_IC")
            _xlsx(bom, [
                ["Comment", "Quantity", "Manufacture PN", "Fitted", "Type"],
                ["0.1uF", "2", "CL05B104KB54PNC", "Fitted", "Cap"],
            ])
            drawing = folder / "cover.pdf"
            pdf = pymupdf.open()
            page = pdf.new_page(width=1800, height=1200)
            for x, y, text in (
                (1483, 962, "上级总成"),
                (1500, 984, "5501801726"),
                (1534, 1005, "图样代号"),
                (1526, 1020, "5501801798"),
                (1352, 962, "材料标记"),
                (1375, 984, "Al5052-O态"),
                (1408, 1037, "质量"),
                (1413, 1066, "31g"),
                (1555, 1041, "图样名称"),
                (1516, 1059, "保险盒接线盖板"),
                (1110, 412, "板料厚度1.5±0.15mm"),
            ):
                page.insert_text((x, y), text, fontsize=8, fontname="china-s")
            pdf.save(drawing)
            pdf.close()
            dest = folder / "out.xlsx"
            with patch("electrical_krow.ce_bom.DEFAULT_CE_BOM_NAME_RULES", rules):
                build_ce_bom([bom, drawing], template, dest)
            saved = load_workbook(dest)
            hardware = saved["供应商"]
            structure = saved["结构"]
            self.assertEqual(hardware["E16"].value, "●")
            self.assertEqual(hardware["G16"].value, "电容")
            self.assertEqual(structure["C16"].value, "●")
            self.assertEqual(structure["G16"].value, "保险盒接线盖板")
            self.assertNotIn("结构CEBOM", saved.sheetnames)
            saved.close()

    def test_required_fields_follow_electronic_and_structure(self) -> None:
        from electrical_krow.ce_bom import StandardLayout, SupplierFill, _write_supplier_lines

        book = Workbook()
        sheet = book.active
        layout = StandardLayout("供应商", 1, 2, 3, {"X": 5, "Y": 6, "Z": 7}, 10, 3)
        fields = {
            "序号": [0],
            "级别": [1],
            "名称": [2],
            "零件号": [3],
            "图片": [],
            "用量": [4],
            "厚度": [8],
            "原材料": [10],
        }
        _, electronic = _write_supplier_lines(
            sheet,
            layout,
            fields,
            [SupplierFill("电容", "CL05", "2")],
            structural=False,
        )
        _, structural = _write_supplier_lines(
            sheet,
            layout,
            fields,
            [
                SupplierFill("PN包塑件", "5501801801"),
                SupplierFill("保险盒接线盖板", "5501801798", "", "1.5±0.15mm", "31g", "Al5052-O态"),
            ],
            structural=True,
        )
        book.close()
        electronic_notes = "\n".join(item[4] for item in electronic)
        structural_notes = "\n".join(item[4] for item in structural)
        self.assertNotIn("缺产品尺寸", electronic_notes)
        self.assertNotIn("缺净重", electronic_notes)
        self.assertNotIn("缺原材料", electronic_notes)
        self.assertIn("PN包塑件 缺产品尺寸", structural_notes)
        self.assertIn("PN包塑件 缺净重", structural_notes)
        self.assertIn("体积或密度未给定，不计算", structural_notes)
        self.assertIn("PN包塑件 缺原材料", structural_notes)
        self.assertIn("保险盒接线盖板 缺产品尺寸", structural_notes)
        self.assertNotIn("保险盒接线盖板 缺净重", structural_notes)
        self.assertNotIn("保险盒接线盖板 缺原材料", structural_notes)
        self.assertNotIn("缺材料厚度", structural_notes)

    def test_structure_level_follows_the_detail_parent(self) -> None:
        from electrical_krow.ce_bom import StandardLayout, SupplierFill, _bom_levels, _write_supplier_lines
        from electrical_krow.ce_structure import StructureRow

        rows = [
            StructureRow("电机控制器壳体", "5501801758", "1", "", "", "ADC12", "5501801726", "housing.pdf", ""),
            StructureRow("摩擦焊板", "", "1", "", "", "ADC12", "5501801758", "housing.pdf", ""),
            StructureRow("固化密封胶", "", "1", "", "", "瓦克988", "5501801758", "housing.pdf", ""),
        ]
        self.assertEqual(_bom_levels(rows), [2, 3, 3])
        book = Workbook()
        sheet = book.active
        layout = StandardLayout("供应商", 1, 2, 3, {"X": 7, "Y": 8, "Z": 9}, 11, 6)
        fields = {
            "序号": [0],
            "级别": [1, 2, 3, 4, 5],
            "名称": [6],
            "零件号": [7],
            "图片": [],
            "用量": [8],
            "厚度": [],
            "原材料": [],
        }
        levels = _bom_levels(rows)
        _write_supplier_lines(
            sheet,
            layout,
            fields,
            [SupplierFill(row.name, level=level) for row, level in zip(rows, levels, strict=True)],
            structural=True,
            level_cols=[1, 2, 3, 4, 5],
        )
        self.assertIsNone(sheet["B3"].value)
        self.assertEqual(sheet["C3"].value, "●")
        self.assertIsNone(sheet["C4"].value)
        self.assertEqual(sheet["D4"].value, "●")
        self.assertEqual(sheet["D5"].value, "●")
        book.close()

    def test_structure_table_above_header_keeps_weight_blank_without_unit(self) -> None:
        from electrical_krow.ce_structure import _bom_rows, _title_row

        words = [
            (1483, 900, 1540, 912, "上级总成"),
            (1500, 922, 1560, 934, "5501801726"),
            (1534, 940, 1580, 952, "图样代号"),
            (1526, 960, 1580, 972, "5501801758"),
            (1352, 900, 1410, 912, "材料标记"),
            (1375, 922, 1420, 934, "ADC12"),
            (1259, 921, 1280, 933, "10"),
            (1408, 980, 1440, 992, "质量"),
            (1413, 1004, 1430, 1016, "3.8"),
            (1555, 1020, 1610, 1032, "图样名称"),
            (1516, 1040, 1620, 1052, "电机控制器壳体"),
            (2687, 1991, 2710, 2003, "序号"),
            (2742, 1990, 2780, 2002, "零件号"),
            (2858, 1990, 2910, 2002, "零件名称"),
            (3140, 1990, 3180, 2002, "材料标记"),
            (3230, 1990, 3260, 2002, "数量"),
            (2699, 1958, 2710, 1970, "1"),
            (2755, 1957, 2820, 1969, "5501801758"),
            (2853, 1949, 2960, 1961, "电机控制器壳体"),
            (2996, 1957, 3010, 1969, "/"),
            (3153, 1957, 3190, 1969, "ADC12"),
            (3230, 1958, 3242, 1970, "1"),
            (2699, 1907, 2710, 1919, "2"),
            (2755, 1907, 2770, 1919, "/"),
            (2853, 1907, 2920, 1919, "摩擦焊板"),
            (3153, 1907, 3190, 1919, "ADC12"),
            (3230, 1907, 3242, 1919, "1"),
        ]
        title = _title_row(words, "housing.pdf")
        self.assertIsNotNone(title)
        assert title is not None
        self.assertEqual(title.weight, "")
        self.assertIn("3.8", title.note)
        self.assertEqual(title.material, "ADC12")
        details = _bom_rows(words, "housing.pdf", title.part_no)
        self.assertEqual([row.name for row in details], ["电机控制器壳体", "摩擦焊板"])
        self.assertEqual(details[1].material, "ADC12")
        self.assertEqual(details[1].quantity, "1")
        self.assertNotIn("/", details[1].name)

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
