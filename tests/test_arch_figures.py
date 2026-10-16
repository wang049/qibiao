from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import SHEET_FIGURES, SourceDoc, read_pdf_pages, split_document, write_contrast
from electrical_krow.arch_figures import Figure, cluster_boxes, find_figures


def _chart_pdf(path: Path) -> None:
    """两页：第 1 页一张坐标图（斜线、曲线、短标签）加一段正文和一张文字框表；第 2 页只有正文。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    # 页眉框（页顶，不算图）
    page.draw_rect(pymupdf.Rect(35, 39, 553, 82))
    page.insert_text((50, 110), "2.5.1 Performance requirements", fontsize=13)
    page.insert_text((50, 130), "1) LDC Output map (TBD) : Refer to specific HW requirements for the output map.", fontsize=9)
    # 坐标图：两条轴、三条斜线、一条曲线、刻度标签
    shape = page.new_shape()
    shape.draw_line((150, 400), (150, 160))
    shape.draw_line((150, 400), (450, 400))
    for k in range(7):
        shape.draw_line((150, 400 - 20 * k), (450, 260 - 10 * k))
    for k in range(4):
        shape.draw_bezier((150, 380 - 10 * k), (250, 180), (350, 380), (450, 220 + 10 * k))
    shape.finish(color=(1, 0, 0), width=1.5)
    shape.commit()
    for y, label in ((200, "2.72kW"), (260, "2.50kW"), (330, "1.26kW")):
        page.insert_text((112, y + 3), label, fontsize=8)
    page.insert_text((110, 160), "Po (kW)", fontsize=8)
    page.insert_text((455, 404), "Vo", fontsize=8)
    page.insert_text((145, 415), "7V", fontsize=8)
    page.insert_text((430, 415), "16V", fontsize=8)
    # 文字框表：横竖线加满格文字，不算图
    for r in range(4):
        page.draw_rect(pymupdf.Rect(60, 520 + 40 * r, 540, 560 + 40 * r))
        page.insert_text((70, 545 + 40 * r), f"• Requirement sentence number {r} shall be satisfied by the supplier in all cases.", fontsize=9)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 110), "3 Other requirements", fontsize=13)
    page2.insert_text((50, 130), "1) The supplier shall confirm every change with the customer before release.", fontsize=9)
    doc.save(str(path))


class ArchFiguresTests(unittest.TestCase):
    def test_cluster_boxes_groups_nearby_strokes(self) -> None:
        boxes = [(10.0, 10.0, 50.0, 50.0), (55.0, 10.0, 90.0, 50.0), (300.0, 300.0, 320.0, 320.0)]
        clusters = cluster_boxes(boxes, gap=10)
        self.assertEqual(sorted(len(m) for _, m in clusters), [1, 2])
        self.assertIn(((10.0, 10.0, 90.0, 50.0), [1, 0]), clusters)

    def test_find_figures_takes_chart_but_not_text_boxes_or_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "chart.pdf"
            _chart_pdf(pdf)
            figures = find_figures(pdf)
            self.assertEqual(list(figures), [1])
            self.assertEqual(len(figures[1]), 1)
            figure = figures[1][0]
            self.assertEqual(figure.kind, "矢量图")
            self.assertTrue(figure.png.startswith(b"\x89PNG"))
            for label in ("Po (kW)", "2.72kW", "7V", "16V", "Vo"):
                self.assertIn(label, figure.labels)
            self.assertNotIn("Performance requirements", figure.labels)  # 标题不往图里拉
            self.assertNotIn("Requirement sentence", figure.labels)
            self.assertLess(figure.box[3], 520)  # 没把下面的文字框圈进来

            doc = read_pdf_pages(pdf)
            self.assertIsInstance(doc, SourceDoc)
            self.assertEqual(list(doc.figures), [1])
            rows, _ = split_document(doc)
            texts = [str(r[8]) for r in rows if r[3] == 1]
            self.assertTrue(any(t.startswith("本页图表（矢量图）：Po (kW)") for t in texts))
            self.assertTrue(any("LDC Output map" in t for t in texts))  # 正文条目还在
            self.assertFalse(any(t.strip() in {"7V", "16V", "2.72kW"} for t in texts))  # 标签不再单独成条
            index_row = next(r for r in rows if str(r[8]).startswith("本页图表"))
            self.assertEqual(index_row[9], "")  # 不取数
            self.assertIn("图表", index_row[15])

    def test_write_contrast_embeds_figures_and_skips_cover(self) -> None:
        from tests.test_arch_contrast import _PAGES  # 第 1 页是封面

        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(200)
        blob = pix.tobytes("png")
        figs = {1: [Figure(1, (0, 0, 40, 30), "logo", blob, "位图")], 5: [Figure(5, (0, 0, 40, 30), "Po (kW) 7V", blob, "矢量图")]}
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            result = write_contrast([SourceDoc("260605_LDC_SR.pdf", _PAGES, {}, {}, figs)], [], dest)
            self.assertEqual(result.figures, 1)  # 封面上的图不算
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                at = next(r for r in range(2, sheet.max_row + 1) if "本页图表（矢量图）" in str(sheet.cell(r, 5).value or ""))
                self.assertEqual((sheet.cell(at, 14).value, sheet.cell(at, 5).value), (5, "本页图表（矢量图）：Po (kW) 7V"))
                self.assertEqual(len(sheet._images), 1)
                self.assertGreater(sheet.row_dimensions[at].height, 20)
            finally:
                book.close()


if __name__ == "__main__":
    unittest.main()
