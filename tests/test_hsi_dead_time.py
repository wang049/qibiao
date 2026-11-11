"""死区页的时间要能改，图上的标注跟着这一格走。"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

from electrical_krow.hsi_book import DEFAULT_HSI_TEMPLATE
from electrical_krow.hsi_dead_time import apply_dead_time_sheet


class DeadTimeSheetTests(unittest.TestCase):
    def test_dead_time_value_drives_the_sentence_and_the_figure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "dead.xlsx"
            book = Workbook()
            sheet = book.active
            assert sheet is not None
            sheet.title = "7_Dead Time"
            sheet["C4"] = "Dead time of PWM-H and PWM-L shall be set 1.6μs；"
            sheet["C5"] = "Add Short Pulse Inhibition Time: 1.6μs；"
            book.save(dest)
            book.close()

            self.assertTrue(apply_dead_time_sheet(dest))
            saved = load_workbook(dest)
            try:
                page = saved["7_Dead Time"]
                self.assertEqual(page["J7"].value, 1.6)
                self.assertEqual(page["J8"].value, 1.6)
                self.assertEqual(page["I7"].value, "死区时间")
                self.assertEqual(page["I8"].value, "窄脉冲抑制")
                self.assertEqual(
                    page["C4"].value,
                    '="Dead time of PWM-H and PWM-L shall be set "&TEXT(J7,"0.0")&"μs；"',
                )
                self.assertEqual(
                    page["C5"].value,
                    '="Add Short Pulse Inhibition Time: "&TEXT(J8,"0.0")&"μs；"',
                )
                self.assertTrue(page.column_dimensions["AA"].hidden)
            finally:
                saved.close()
            drawing = _drawing_xml(dest)
            self.assertIn("PWM_H", drawing)
            self.assertIn("PWM_L", drawing)
            self.assertEqual(drawing.count('textlink="$AA$7"'), 2)
            self.assertIn("1.6μs", drawing)
            self.assertNotIn("custGeom", drawing)
            self.assertEqual(drawing.count("<xdr:colOff>"), 1)
            self.assertIn("<xdr:colOff>0</xdr:colOff>", drawing)

            saved = load_workbook(dest)
            saved["7_Dead Time"]["J7"] = 2.5
            saved.save(dest)
            saved.close()
            self.assertTrue(apply_dead_time_sheet(dest))
            saved = load_workbook(dest)
            try:
                self.assertEqual(saved["7_Dead Time"]["J7"].value, 2.5)
                self.assertIn("TEXT(J7", saved["7_Dead Time"]["C4"].value)
            finally:
                saved.close()
            self.assertIn("2.5μs", _drawing_xml(dest))

    def test_template_dead_time_keeps_cover_and_uses_the_sheet_value(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "template.xlsx"
            shutil.copy(DEFAULT_HSI_TEMPLATE, dest)
            self.assertTrue(apply_dead_time_sheet(dest))
            saved = load_workbook(dest)
            try:
                self.assertEqual(saved["Cover"].cell(2, 4).value, "殷桂来")
                page = saved["7_Dead Time"]
                self.assertEqual(page["J7"].value, 1.6)
                self.assertEqual(page["J8"].value, 1.6)
                self.assertIn("TEXT(J7", page["C4"].value)
                self.assertIn("PWM-H", page["C4"].value)
            finally:
                saved.close()
            self.assertIn("PWM_L", _drawing_xml(dest))

    def test_sheet_without_dead_time_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "plain.xlsx"
            book = Workbook()
            book.active.title = "7_Dead Time"
            book.save(dest)
            book.close()
            before = dest.read_bytes()
            self.assertFalse(apply_dead_time_sheet(dest))
            self.assertEqual(dest.read_bytes(), before)

    def test_schematic_archive_makes_dead_time_editable(self) -> None:
        from electrical_krow.hsi_book import revise_hsi_from_schematic

        edif = """(edif demo
          (library COMPONENT_LIB
            (cell DEMO (view NetlistView (contents
              (Instance J1 (viewRef NetlistView (cellRef CON2)) (Property Type (String "CON" )))
              (Net SIG (Joined (PortRef &1 (InstanceRef J1))))
            )))
          )
        )
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            base = root / "base.xlsx"
            dest = root / "out.xlsx"
            book = Workbook()
            book.active.title = "Cover"
            port = book.create_sheet("2_Port Assignment ")
            port.cell(3, 2, "Pin_Symbol")
            port.cell(3, 3, "Ball")
            port.cell(3, 9, "Direction")
            port.cell(3, 10, "Function")
            port.cell(3, 12, "Pin Definition")
            port.cell(4, 2, "P00.8")
            port.cell(4, 12, "CSN3")
            dead = book.create_sheet("7_Dead Time")
            dead["C4"] = "Dead time of PWM-H and PWM-L shall be set 1.6μs；"
            dead["C5"] = "Add Short Pulse Inhibition Time: 1.6μs；"
            book.save(base)
            book.close()
            (root / "board.edf").write_text(edif, encoding="utf-8")
            revise_hsi_from_schematic(base, dest, root / "board.edf")
            saved = load_workbook(dest)
            try:
                page = saved["7_Dead Time"]
                self.assertEqual(page["J7"].value, 1.6)
                self.assertEqual(page["K7"].value, "μs")
                self.assertIn("TEXT(J7", str(page["C4"].value))
                self.assertIn("TEXT(J8", str(page["C5"].value))
            finally:
                saved.close()
            self.assertIn("1.6μs", _drawing_xml(dest))


def _drawing_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as book:
        for name in book.namelist():
            if not name.startswith("xl/drawings/") or not name.endswith(".xml") or "/_rels/" in name:
                continue
            text = book.read(name).decode("utf-8")
            if "PWM_H" in text:
                return text
    return ""


if __name__ == "__main__":
    unittest.main()
