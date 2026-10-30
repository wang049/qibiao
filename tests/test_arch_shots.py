from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import REQ_COLUMNS, SourceDoc, build_contrast, read_pdf_pages, suggest_category, write_contrast
from electrical_krow.arch_shots import Shot, clause_box, covered_by_stamp, render_shots, row_box


def _spec_pdf(path: Path) -> None:
    """一页：标题、两条正文、一张「Item | Spec」表。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "2 Spec", fontsize=13)
    page.insert_text((50, 130), "1) The supplier shall confirm every change with the customer before release.", fontsize=9)
    page.insert_text((50, 150), "2) Closed-loop feedback applies within 10 ms at all times for the loop.", fontsize=9)
    cells = [["Item", "Spec"], ["Ripple", "1.0 V"], ["Delay", "10 ms"]]
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            rect = pymupdf.Rect(60 + 200 * c, 300 + 30 * r, 260 + 200 * c, 330 + 30 * r)
            page.draw_rect(rect)
            page.insert_text((rect.x0 + 8, rect.y0 + 20), text, fontsize=9)
    doc.save(str(path))


class ArchShotsTests(unittest.TestCase):
    def test_stamp_overlap_drops_the_covered_clip_only(self) -> None:
        bands = [(266.0, 610.0)]
        self.assertTrue(covered_by_stamp((40.0, 280.0, 540.0, 310.0), bands))
        self.assertFalse(covered_by_stamp((40.0, 200.0, 540.0, 230.0), bands))
        self.assertFalse(covered_by_stamp((40.0, 200.0, 540.0, 230.0), []))

    def test_clause_box_unions_matching_lines_and_ignores_far_ones(self) -> None:
        lines = [
            ((50.0, 90.0, 120.0, 102.0), "2 Spec"),
            ((80.0, 105.0, 120.0, 115.0), "change"),  # 表头或图里的碎词，字数远少于正文整句
            ((80.0, 118.0, 120.0, 128.0), "release"),
            ((50.0, 220.0, 400.0, 232.0), "1) The supplier shall confirm every change"),
            ((60.0, 234.0, 300.0, 246.0), "with the customer before release."),
            ((50.0, 600.0, 300.0, 612.0), "the customer"),  # 远处的碎行，不并
        ]
        box = clause_box(lines, "1) The supplier shall confirm every change with the customer before release.")
        self.assertEqual(box, (50.0, 220.0, 400.0, 246.0))
        # pypdf 在「1)」与句首之间插进「Continued」时，也能命中原句首行
        box2 = clause_box(lines, "1) Continued The supplier shall confirm every change with the customer before release.")
        self.assertEqual(box2, (50.0, 220.0, 400.0, 246.0))
        self.assertIsNone(clause_box(lines, "nothing like this appears"))

    def test_row_box_skips_tall_merged_cells(self) -> None:
        cells = [(60.0, 300.0, 160.0, 420.0), (160.0, 330.0, 360.0, 360.0), None]  # 第一格纵向合并了四行
        self.assertEqual(row_box(cells, (60.0, 300.0, 460.0, 420.0)), (60.0, 330.0, 460.0, 360.0))
        # 六列表里四列纵向合并、两列是本行单格时，仍只取本行高度
        six_col = [
            (40.0, 138.0, 100.0, 254.0),
            (100.0, 138.0, 160.0, 208.0),
            (160.0, 138.0, 220.0, 161.0),
            (220.0, 138.0, 280.0, 161.0),
            (280.0, 138.0, 400.0, 208.0),
            (400.0, 138.0, 560.0, 254.0),
        ]
        self.assertEqual(row_box(six_col, (40.0, 100.0, 560.0, 254.0)), (40.0, 138.0, 560.0, 161.0))
        self.assertIsNone(row_box([None, None], (0.0, 0.0, 1.0, 1.0)))

    def test_scaled_xl_image_keeps_hidpi_bitmap_for_preview(self) -> None:
        from io import BytesIO
        from PIL import Image as PilImage
        from electrical_krow.arch_contrast import _scaled_xl_image

        buf = BytesIO()
        PilImage.new("RGB", (1500, 300), (255, 255, 255)).save(buf, format="PNG")
        img = _scaled_xl_image(buf.getvalue(), 530, 360)
        self.assertLessEqual(img.width, 530)
        self.assertLessEqual(img.height, 360)
        with PilImage.open(BytesIO(img._data())) as raw:
            self.assertGreaterEqual(raw.width, img.width * 2)
            self.assertGreaterEqual(raw.height, img.height * 2)

    def test_suggest_category_is_keyword_based(self) -> None:
        self.assertEqual(suggest_category("2.5.3 EMC", "CE (Conducted Emission)"), "Regulation")
        self.assertEqual(suggest_category("2.5.1 Performance requirements", "Output voltage ripple 1.0 V"), "Performance")
        self.assertEqual(suggest_category("2.6 Reliability", "Must meet durability"), "Quality")
        self.assertEqual(suggest_category("4 Deliverables", "Submit the DFMEA report"), "Technical document output")
        self.assertEqual(suggest_category("3.3 Control", "Wake-up by CAN"), "Function")

    def test_requirement_sheet_has_req_ids_and_shots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "spec.pdf"
            _spec_pdf(pdf)
            doc = read_pdf_pages(pdf)
            self.assertIsInstance(doc, SourceDoc)
            self.assertEqual(doc.path, str(pdf))
            self.assertIn(1, doc.lines)
            self.assertEqual(len(doc.table_rows[1][0]), 3)
            dest = Path(raw) / "out.xlsx"
            result = build_contrast([pdf], dest, now=datetime(2026, 10, 15))
            self.assertGreaterEqual(result.reqs, 4)  # 两条正文 + 两行表
            self.assertGreaterEqual(result.shots, 4)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                self.assertEqual(tuple(c.value for c in sheet[1]), REQ_COLUMNS)
                ids = [sheet.cell(r, 1).value for r in range(2, sheet.max_row + 1)]
                self.assertEqual(ids[:2], ["REQ-20261015-001", "REQ-20261015-002"])
                self.assertEqual(len(ids), len(set(ids)))
                statuses = {sheet.cell(r, REQ_COLUMNS.index("Currently status\n状态") + 1).value for r in range(2, sheet.max_row + 1)}
                self.assertEqual(statuses, {"To be confirmed"})
                self.assertEqual(len(sheet._images), result.shots)
                excerpts = [str(sheet.cell(r, 5).value) for r in range(2, sheet.max_row + 1)]
                self.assertTrue(any(e.startswith("Ripple：") for e in excerpts))
                qty = REQ_COLUMNS.index("数值与单位") + 1
                self.assertIn("1.0 V", [sheet.cell(r, qty).value for r in range(2, sheet.max_row + 1)])
                self.assertTrue(all(sheet.row_dimensions[r].height >= 30 for r in range(2, sheet.max_row + 1)))
                self.assertEqual(book.active.title, "需求清单")
            finally:
                book.close()

    def test_requirement_sheet_skips_cover_and_index_rows(self) -> None:
        from tests.test_arch_contrast import _PAGES

        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            result = write_contrast([SourceDoc("260605_LDC_SR.pdf", _PAGES)], [], dest, now=datetime(2026, 10, 15))
            self.assertEqual(result.shots, 0)  # 没有文件路径就不截图
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                sections = {sheet.cell(r, 3).value for r in range(2, sheet.max_row + 1)}
                self.assertNotIn("封面", sections)
                self.assertNotIn("目录", sections)
                excerpts = [str(sheet.cell(r, 5).value) for r in range(2, sheet.max_row + 1)]
                self.assertFalse(any(e.startswith("本页表格") or "（表格块，整块见" in e for e in excerpts))
                self.assertLess(sheet.max_row - 1, result.rows)
            finally:
                book.close()

    def test_conflicting_values_are_noted_and_highlighted_in_requirement_sheet(self) -> None:
        from unittest import mock

        import electrical_krow.arch_contrast as ac

        pages = (
            (1, "2.1 Power\nIntro text about the power supply requirements of this unit goes here.\n"),
            (2, "2.2 Power again\nMore text about the power supply requirements of this unit goes here.\n"),
        )
        grids = {
            1: [[["Item", "Requirement", "Remark"], ["Dark current", "1mA↓", "-"]]],
            2: [[["Item", "Requirement", "Remark"], ["Dark current", "2mA↓", "-"]]],
        }
        original = ac.split_document

        def with_section(doc):
            rows, tables = original(doc)
            for row in rows:
                row[5] = row[5] or "2.1 Power"
            return rows, tables

        with tempfile.TemporaryDirectory() as raw, mock.patch.object(ac, "split_document", with_section):
            dest = Path(raw) / "out.xlsx"
            result = ac.write_contrast([SourceDoc("x.pdf", pages, grids)], [], dest)
            self.assertEqual(result.conflicts, 2)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                remark = REQ_COLUMNS.index("Remark\n备注") + 1
                flagged = [r for r in range(2, sheet.max_row + 1) if str(sheet.cell(r, 1).fill.fgColor.rgb).endswith("FCE4E4")]
                self.assertEqual(len(flagged), 2)
                self.assertIn("「Dark current」此处 1mA↓，与别处不一致：第 2 页「Dark current」：2mA↓", str(sheet.cell(flagged[0], remark).value))
                self.assertNotIn("参数清单", book.sheetnames)
            finally:
                book.close()

    def test_render_shots_keeps_prerendered_png(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "spec.pdf"
            _spec_pdf(pdf)
            out = render_shots(pdf, [Shot(1, (50.0, 120.0, 400.0, 160.0)), Shot(1, None, b"\x89PNGfake"), Shot(1, (0.0, 0.0, 1.0, 1.0))])
            self.assertTrue(out[0].startswith(b"\x89PNG"))
            self.assertEqual(out[1], b"\x89PNGfake")
            self.assertEqual(out[2], b"")  # 太小的范围不渲染


if __name__ == "__main__":
    unittest.main()
