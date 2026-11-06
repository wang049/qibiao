from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from openpyxl import load_workbook

from electrical_krow.arch_contrast import SHEET_FIGURES, SourceDoc, read_pdf_pages, split_document, write_contrast
from electrical_krow.arch_contrast import REQ_COLUMNS
from electrical_krow.arch_figures import (
    Figure,
    _axis_scale_grid,
    cluster_boxes,
    find_figures,
    prose_beside,
    pull_orphan_column,
    text_layer_broken,
    transcript_kind,
)


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

    def test_chart_beside_a_data_table_keeps_the_table_in_the_picture_only(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "noise.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=595, height=842)
            shape = page.new_shape()
            shape.draw_line((80, 280), (80, 80))
            shape.draw_line((80, 280), (280, 280))
            for k in range(7):
                shape.draw_line((80, 260 - 24 * k), (280, 200 - 16 * k))
            for k in range(12):
                shape.draw_bezier((80, 250 - 8 * k), (140, 90 + 4 * k), (200, 260 - 6 * k), (280, 110 + 6 * k))
            shape.finish(color=(0, 0, 1), width=1.2)
            shape.commit()
            page.insert_text((40, 70), "dBA", fontsize=8)
            page.insert_text((290, 284), "rpm", fontsize=8)
            # 曲线右边的数据表，和坐标轴隔开一点
            for x in (300, 390, 480):
                page.draw_line((x, 90), (x, 250))
            for y in (90, 122, 154, 186, 218, 250):
                page.draw_line((300, y), (480, y))
            page.insert_text((312, 112), "rpm", fontsize=8)
            page.insert_text((400, 112), "Noise", fontsize=8)
            page.insert_text((312, 144), "2500", fontsize=8)
            page.insert_text((400, 144), "60", fontsize=8)
            doc.save(pdf)
            doc.close()
            figures = find_figures(pdf)
            self.assertEqual(len(figures.get(1, [])), 1)
            figure = figures[1][0]
            self.assertGreaterEqual(figure.box[2], 470)
            self.assertEqual(figure.grid, ())
            doc_read = SourceDoc(
                "noise.pdf",
                ((1, "1. Overview\nMotor noise is shown in the figure.\n"),),
                figures=figures,
            )
            rows, _ = split_document(doc_read)
            texts = [str(row[8]) for row in rows]
            self.assertTrue(any(text.startswith("本页图表（矢量图）") for text in texts))
            self.assertFalse(any(text.startswith("本页线框表格") for text in texts))
            self.assertFalse(any("2500" in text and "60" in text for text in texts))

    def test_curve_screenshot_keeps_the_whole_side_table(self) -> None:
        """曲线和旁边的数据表隔开一点、表线又被当成已读表格排除时，截图仍要含整张表，不能从半格切开。"""
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "sliced.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=842, height=595)
            shape = page.new_shape()
            shape.draw_line((310, 300), (310, 80))
            shape.draw_line((310, 300), (560, 300))
            for k in range(12):
                shape.draw_bezier((310, 260 - 6 * k), (380, 90 + 4 * k), (460, 280 - 4 * k), (560, 110 + 6 * k))
            shape.finish(color=(0, 0, 1), width=1.2)
            shape.commit()
            page.insert_text((292, 70), "dBA", fontsize=8)
            page.insert_text((540, 314), "rpm", fontsize=8)
            for x in (40, 150, 250):
                page.draw_line((x, 100), (x, 280))
            for y in (100, 145, 190, 235, 280):
                page.draw_line((40, y), (250, y))
            page.insert_text((55, 128), "rpm", fontsize=9)
            page.insert_text((165, 128), "Noise", fontsize=9)
            page.insert_text((55, 173), "2500", fontsize=9)
            page.insert_text((165, 173), "60", fontsize=9)
            doc.save(pdf)
            doc.close()
            table = (40.0, 100.0, 250.0, 280.0)
            figures = find_figures(pdf, table_boxes={1: [table]})
            self.assertEqual(len(figures.get(1, [])), 1)
            box = figures[1][0].box
            self.assertLessEqual(box[0], 42)
            self.assertLessEqual(box[1], 102)
            self.assertGreaterEqual(box[2], 540)
            self.assertGreaterEqual(box[3], 300)

    def test_spec_table_with_skewed_lines_is_still_excerpted(self) -> None:
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "spec.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=595, height=842)
            shape = page.new_shape()
            for k in range(12):
                shape.draw_line((80, 80 + 12 * k), (360, 88 + 12 * k))
            shape.finish(color=(0, 0, 0), width=0.6)
            shape.commit()
            page.insert_text((90, 100), "Table1. P3 Load & Speed rate", fontsize=9)
            page.insert_text((90, 130), "Load(Nm)", fontsize=9)
            page.insert_text((240, 130), "Speed rate", fontsize=9)
            page.insert_text((90, 160), "100Nm", fontsize=9)
            page.insert_text((240, 160), "200rpm/s", fontsize=9)
            doc.save(pdf)
            doc.close()
            doc_read = SourceDoc(
                "spec.pdf",
                ((1, "1. Overview\nTable1. P3 Load & Speed rate\nLoad(Nm) Speed rate\n100Nm 200rpm/s\n"),),
                figures=find_figures(pdf),
            )
            rows, _ = split_document(doc_read)
            texts = [str(row[8]) for row in rows]
            self.assertTrue(any("Table1" in text or "Load" in text for text in texts))
            self.assertFalse(all(text == "本页图表（矢量图）" for text in texts if text.startswith("本页图表") or "Table1" in text or "Load" in text))

    def test_spec_table_drawn_as_curves_is_still_excerpted(self) -> None:
        import pymupdf
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (520, 160), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for x in (0, 180, 360, 519):
            draw.line((x, 0, x, 159), fill="black", width=2)
        for y in (0, 40, 80, 120, 159):
            draw.line((0, y, 519, y), fill="black", width=2)
        draw.text((16, 12), "Table1 Load Speed", fill="black", font=font)
        draw.text((16, 52), "Load", fill="black", font=font)
        draw.text((200, 52), "Speed rate", fill="black", font=font)
        draw.text((16, 92), "100Nm", fill="black", font=font)
        draw.text((200, 92), "200rpm", fill="black", font=font)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            png = root / "spec.png"
            image.save(png)
            pdf = root / "spec.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=595, height=842)
            shape = page.new_shape()
            for k in range(8):
                shape.draw_bezier((40, 200 - 8 * k), (80, 80), (140, 220), (200, 100 + 6 * k))
            shape.finish(color=(0, 0, 1), width=1.2)
            shape.commit()
            page.insert_image(pymupdf.Rect(40, 80, 420, 240), filename=str(png))
            doc.save(pdf)
            doc.close()
            figures = find_figures(pdf)
            self.assertTrue(figures.get(1))
            figure = figures[1][0]
            blob = figure.transcript + " " + " ".join(" ".join(row) for row in figure.grid)
            self.assertTrue("Table1" in blob or "Load" in blob or "Speed" in blob)
            self.assertTrue(figure.grid or "Table1" in figure.transcript or "Load" in figure.transcript)

    def test_chart_title_and_caption_are_translated(self) -> None:
        from electrical_krow.arch_translate import _cell_bilingual

        self.assertIn("8阶", _cell_bilingual("8th Noise (dBA)/TBD"))
        self.assertIn("噪声", _cell_bilingual("8th Noise (dBA)/TBD"))
        over = _cell_bilingual("Over (±)50Nm~Max Tq Step: Every 10% of max Tq")
        zh = over.split(" / ", 1)[-1]
        self.assertIn("每10%", zh)
        self.assertIn("的最大", zh)
        self.assertNotIn("of max", zh)
        self.assertNotIn("每项", zh)
        self.assertIn("步进", over)
        self.assertIn("扭矩", over)
        self.assertIn("模式", _cell_bilingual("Table2. Parallel Mode test load"))
        self.assertNotIn("Mode", _cell_bilingual("Table2. Parallel Mode test load").split(" / ", 1)[-1])
        dyno = _cell_bilingual("Input-Dyno (Engine) Tq.")
        self.assertIn("输入测功机", dyno)
        self.assertIn("发动机", dyno)
        self.assertIn("扭矩", dyno)
        self.assertIn("扭矩", _cell_bilingual("P3 Motor Tq."))
        parallel = _cell_bilingual("(±)Max Tq@Parallel")
        self.assertIn("并联最大扭矩", parallel)
        self.assertIn("电机", _cell_bilingual("Motor 24th Noise"))
        self.assertIn("24阶", _cell_bilingual("Motor 24th Noise"))
        self.assertIn("分别", _cell_bilingual("[P1, P3 respectively]"))
        self.assertIn("P1", _cell_bilingual("[P1, P3 respectively]"))
        self.assertIn("1st Proto", _cell_bilingual("1st Proto type bench test"))

    def test_cell_translates_headers_and_keeps_names(self) -> None:
        from electrical_krow.arch_translate import _cell_bilingual

        self.assertIn("项目", _cell_bilingual("Item"))
        self.assertIn("部门", _cell_bilingual("Department"))
        self.assertIn("转速", _cell_bilingual("Speed rate"))
        self.assertEqual(_cell_bilingual("NVH"), "NVH")
        self.assertEqual(_cell_bilingual("Sanghun Han"), "Sanghun Han")
        self.assertEqual(_cell_bilingual("200rpm/s"), "200rpm/s")

    def test_picture_table_without_text_is_drawn(self) -> None:
        import pymupdf
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (640, 180), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        cols = [0, 160, 320, 480, 639]
        rows = [0, 40, 90, 140, 179]
        for x in cols:
            draw.line((x, 0, x, 179), fill="black", width=2)
        for y in rows:
            draw.line((0, y, 639, y), fill="black", width=2)
        cells = {
            (20, 20): "Item",
            (180, 20): "Unit",
            (340, 20): "Value",
            (20, 60): "Cooling",
            (180, 60): "LPM",
            (340, 60): "MAX12",
            (20, 110): "Temp",
            (180, 110): "C",
            (340, 110): "MIN65",
        }
        for (x, y), text in cells.items():
            draw.text((x, y), text, fill="black", font=font)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            png = root / "table.png"
            image.save(png)
            pdf = root / "table.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=595, height=842)
            page.insert_image(pymupdf.Rect(40, 120, 520, 280), filename=str(png))
            doc.save(pdf)
            doc.close()
            figures = find_figures(pdf)
            self.assertIn(1, figures)
            grids = [figure.grid for figure in figures[1] if figure.grid]
            self.assertTrue(grids)
            flat = " ".join(cell for row in grids[0] for cell in row)
            self.assertIn("Cooling", flat)
            self.assertIn("LPM", flat)

    def test_vector_text_and_table_are_excerpted(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(200)
        blob = pix.tobytes("png")
        sentence = "1) The supplier shall confirm every change with the customer before release."
        table = "\n".join([
            "Item | Unit | Value | Notes",
            "Water cooling | LPM | MAX. 12 | Use coolant that is forcibly circulated",
            "Coolant temperature | C | MIN. 65 | Based on inverter inlet temperature",
        ])
        self.assertEqual(transcript_kind(sentence), "prose")
        self.assertEqual(transcript_kind(table), "table")
        self.assertEqual(transcript_kind("7V | 16V\nPo (kW)"), "chart")
        figs = {
            1: [
                Figure(1, (40, 140, 500, 220), "Cooling", blob, "矢量图", sentence),
                Figure(1, (40, 240, 500, 400), "Item", blob, "矢量图", table),
            ]
        }
        pages = ((1, "1. Overview\n" + sentence + "\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("cool.pdf", pages, figures=figs)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                texts = [str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1)]
                prose = next(text for text in texts if "confirm every change" in text)
                self.assertIn("供应商", prose)
                self.assertNotIn("本页图表", prose)
                header = next(r for r in range(2, sheet.max_row + 1) if str(sheet.cell(r, 5).value or "").startswith("Item"))
                self.assertIn("项目", str(sheet.cell(header, 5).value or ""))
                self.assertIn("单位", str(sheet.cell(header, 6).value or ""))
                self.assertIn("数值", str(sheet.cell(header, 7).value or ""))
                self.assertIn("备注", str(sheet.cell(header, 8).value or ""))
                self.assertEqual(sheet.cell(header, 5).border.left.style, "thin")
                self.assertEqual(sheet.cell(header, 8).border.right.style, "thin")
                self.assertTrue(sheet.cell(header, 5).font.bold)
                data = header + 1
                self.assertIn("Water cooling", str(sheet.cell(data, 5).value or ""))
                self.assertIn("冷却", str(sheet.cell(data, 5).value or ""))
                self.assertIn("LPM", str(sheet.cell(data, 6).value or ""))
                self.assertIn("MAX. 12", str(sheet.cell(data, 7).value or ""))
                self.assertIn("forcibly circulated", str(sheet.cell(data, 8).value or ""))
                self.assertTrue(str(sheet.cell(header, 1).value or "").startswith("REQ-"))
            finally:
                book.close()

    def test_two_conditions_on_one_page_are_separate_rows(self) -> None:
        body = (
            "1) P1 Generating condition "
            "① Bench test sweep rate is 200rpm/s under rated rpm "
            "② Load condition steps up to 100Nm "
            "2. P3 Motor NVH TEST condition "
            "① Operating condition is acceleration and deceleration"
        )
        pages = ((1, "1. Overview\n" + body + "\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh-page.pdf", pages)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                texts = [str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1)]
                p1 = next(text for text in texts if text.startswith("1)") and "P1 Generating" in text)
                p3 = next(text for text in texts if "P3 Motor" in text)
                bench = next(text for text in texts if "Bench test" in text)
                self.assertNotIn("P3 Motor", p1)
                self.assertIn("电机", p3)
                self.assertIn("测试", bench)
                self.assertIn("/", bench)
            finally:
                book.close()

    def test_value_above_blank_cells_merges_down_the_column(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(200)
        blob = pix.tobytes("png")
        grid = (
            ("Table2. Parallel Mode test load", ""),
            ("Input-Dyno (Engine) Tq.", "P3 Motor Tq."),
            ("100Nm", "(±)Max Tq@Parallel"),
            ("", "(±)30Nm"),
            ("", "(±)20Nm"),
            ("", "(±)10Nm"),
        )
        figs = {1: [Figure(1, (40, 80, 400, 300), "", blob, "矢量图", "", grid)]}
        pages = ((1, "1. Overview\nParallel mode load is in the table.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("parallel.pdf", pages, figures=figs)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                anchor = next(
                    (cell.row, cell.column)
                    for row in sheet.iter_rows(min_row=2, max_col=8)
                    for cell in row
                    if str(cell.value or "").startswith("100Nm")
                )
                merged = [
                    area
                    for area in sheet.merged_cells.ranges
                    if area.min_row == anchor[0] and area.min_col == anchor[1]
                ]
                self.assertEqual(len(merged), 1)
                self.assertEqual(merged[0].max_row - merged[0].min_row, 3)
                self.assertEqual(merged[0].max_col, merged[0].min_col)
                title = next(
                    area
                    for area in sheet.merged_cells.ranges
                    if str(sheet.cell(area.min_row, area.min_col).value or "").startswith("Table2")
                )
                self.assertGreater(title.max_col, title.min_col)
            finally:
                book.close()

    def test_numbered_points_in_a_figure_are_separate_and_translated(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(200)
        blob = pix.tobytes("png")
        blob_text = (
            "1) P1 Generating condition ① Bench test sweep rate is 200rpm/s under rated rpm "
            "2. P3 Motor NVH TEST condition ① Operating condition is acceleration and deceleration"
        )
        grid = (
            (blob_text,),
            ("Table1. P1 Load and Speed rate", ""),
            ("Load", "Speed rate"),
            ("10", "200rpm/s"),
        )
        figs = {1: [Figure(1, (40, 80, 500, 400), "", blob, "矢量图", "", grid)]}
        pages = ((1, "1. Overview\nThe motor conditions are listed in the figure.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh.pdf", pages, figures=figs)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                texts = [str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1)]
                self.assertTrue(any("P1 Generating" in text for text in texts))
                self.assertTrue(any("P3 Motor" in text for text in texts))
                p1 = next(i for i, text in enumerate(texts) if "P1 Generating" in text)
                p3 = next(i for i, text in enumerate(texts) if "P3 Motor" in text)
                self.assertNotEqual(p1, p3)
                self.assertIn("电机", texts[p3])
                self.assertIn("/", texts[p3])
                speed = next(
                    str(sheet.cell(r, 6).value or "")
                    for r in range(2, sheet.max_row + 1)
                    if "Speed" in str(sheet.cell(r, 6).value or "")
                )
                self.assertIn("转速", speed)
            finally:
                book.close()

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

    def test_orphan_speed_moves_back_and_excerpt_stops_before_quantity(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(200)
        blob = pix.tobytes("png")
        self.assertTrue(text_layer_broken("1) P1 Generating condition u nd n rm d n m"))
        self.assertFalse(text_layer_broken("1) The supplier shall confirm every change before release."))
        pulled = pull_orphan_column((
            ("Table1. P3 Load & Speed rate", "", ""),
            ("Load(Nm)", "Speed rate", ""),
            ("(±)10,20,30", "", "200rpm/s"),
            ("(±)40,50", "", "400rpm/s"),
            ("Over (±)50Nm", "", "800rpm/s"),
            ("Input-Dyno (Engine) Tq.", "P3 Motor Tq.", ""),
            ("100Nm", "(±)Max Tq@Parallel", ""),
            ("", "(±)30Nm", ""),
            ("", "(±)20Nm", ""),
            ("", "(±)10Nm", ""),
        ))
        self.assertEqual(len(pulled[0]), 2)
        self.assertEqual(pulled[2][1], "200rpm/s")
        self.assertEqual(pulled[4][1], "800rpm/s")
        scrambled = pull_orphan_column((
            ("Table1. P3 Load & Speed rate", "", ""),
            ("Load(Nm)", "", "Speed rate"),
            ("(±)10,20,30", "", "200rpm/s"),
            ("(±)40,50", "", "400rpm/s"),
            ("0ver (±)50Nm~Max Tq", "", "800rpm/s"),
            ("Table2. Parallel Mode test load", "", ""),
            ("Input-Dyno (Engine) Tq.", "P3 Motor Tq.", ""),
            ("100Nm", "(±)Max Tq@Parallel", ""),
            ("", "(±)30Nm", ""),
            ("", "(±)20Nm", ""),
            ("", "(±)10Nm", ""),
        ))
        self.assertEqual(len(scrambled[0]), 2)
        self.assertEqual(scrambled[1], ("Load(Nm)", "Speed rate"))
        self.assertEqual(scrambled[2][1], "200rpm/s")
        self.assertTrue(scrambled[4][0].startswith("Over"))
        self.assertEqual(scrambled[4][1], "800rpm/s")
        self.assertEqual(scrambled[7][0], "100Nm")
        self.assertEqual(scrambled[8][1], "(±)30Nm")
        self.assertEqual(pulled[6][0], "100Nm")
        self.assertEqual(pulled[7][1], "(±)30Nm")
        prose = prose_beside(
            "1) P1 Generating condition\nLoad(Nm) | Speed rate\n(±)10,20,30 | 200rpm/s",
            (("Load(Nm)", "Speed rate"), ("(±)10,20,30", "200rpm/s")),
        )
        self.assertIn("P1 Generating", prose)
        self.assertNotIn("200rpm/s", prose)
        grid = scrambled
        figs = {1: [Figure(1, (40, 80, 500, 400), "", blob, "矢量图", "1) P1 Generating condition\n2. P3 Motor NVH TEST condition\n④ No noise", grid)]}
        pages = ((1, "1. Overview\nThe motor conditions are listed beside the table.\n"),)
        lines = {1: [((40, 40, 200, 55), "1. Overview")]}
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh.pdf", pages, figures=figs, lines=lines)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                qty_col = REQ_COLUMNS.index("数值与单位") + 2  # 表有两列，数值与单位右移一列
                self.assertEqual(sheet.cell(1, 5).value, "原文摘录")
                self.assertEqual(sheet.cell(1, qty_col).value, "数值与单位")
                speed = next(
                    (cell.row, cell.column)
                    for row in sheet.iter_rows(min_row=2, max_col=qty_col)
                    for cell in row
                    if "200rpm/s" in str(cell.value or "")
                )
                self.assertLess(speed[1], qty_col)
                self.assertIn("Speed rate", str(sheet.cell(speed[0] - 2, speed[1]).value or "") + str(sheet.cell(speed[0] - 1, speed[1]).value or ""))
                eight = next(
                    cell
                    for row in sheet.iter_rows(min_row=2, max_col=qty_col)
                    for cell in row
                    if str(cell.value or "").strip() == "800rpm/s"
                )
                self.assertEqual(eight.column, speed[1])
                covered = [
                    area
                    for area in sheet.merged_cells.ranges
                    if area.min_row <= eight.row <= area.max_row and area.min_col <= eight.column <= area.max_col
                ]
                self.assertTrue(all(
                    "Table2" not in str(sheet.cell(area.min_row, area.min_col).value or "")
                    and area.max_row == eight.row
                    for area in covered
                ))
                texts = [str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1)]
                self.assertTrue(any("P1 Generating" in text for text in texts))
                self.assertTrue(any("P3 Motor" in text for text in texts))
                self.assertTrue(any("No noise" in text for text in texts))
                self.assertFalse(any("200rpm/s" in str(sheet.cell(r, qty_col).value or "") for r in range(2, sheet.max_row + 1)))
            finally:
                book.close()

    def test_curve_axis_ticks_are_not_a_table(self) -> None:
        self.assertTrue(_axis_scale_grid((
            ("2500", "60", ""),
            ("7000", "75", ""),
            ("17000", "75", ""),
            ("0", "5000", "10000", "15000"),
        )))
        self.assertFalse(_axis_scale_grid((
            ("rpm", "8th Noise (dBA)/TBD"),
            ("0", "10"),
            ("2500", "60"),
            ("17000", "70"),
        )))

    def test_numbered_conditions_beside_a_table_stay_in_the_sheet(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(180)
        blob = pix.tobytes("png")
        transcript = "\n".join([
            "1) P1 Generating condition",
            "① Bench test sweep rate is 200rpm/s under rated rpm",
            "2. P3 Motor NVH TEST condition",
            "3. P3 Engine Driving condition",
        ])
        grid = (("Load(Nm)", "Speed rate"), ("(±)10,20,30", "200rpm/s"))
        figs = {1: [Figure(1, (40, 80, 400, 300), "", blob, "矢量图", transcript, grid)]}
        pages = ((1, "1. Overview\nThe conditions are beside the table.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh.pdf", pages, figures=figs, path="nvh.pdf")], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                texts = "\n".join(str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1))
                self.assertIn("P1 Generating", texts)
                self.assertIn("Bench test sweep rate", texts)
                self.assertIn("P3 Motor", texts)
                self.assertIn("Engine Driving", texts)
                self.assertIn("200rpm/s", texts)
            finally:
                book.close()

    def test_truncated_clause_keeps_the_longer_reading(self) -> None:
        from electrical_krow.arch_figures import order_clauses

        raw = "\n".join([
            "1) P1 Generating condition",
            "① Bench test sweep rate : Run up/down speed 200rpm/s under, engine min r",
            "① Bench test sweep rate : Run up/down speed 200rpm/s under, engine min rpm~ rated rpm",
        ])
        ordered = order_clauses(raw)
        self.assertIn("rated rpm", ordered)
        self.assertEqual(ordered.count("①"), 1)
        doubled = order_clauses("\n".join([
            "④No abnormal noise when 0 Torque control",
            "④ No abnormal noise when 0 Torque control",
            "Table1. P3 Load & Speed rate",
            "Load(Nm) Speed rate",
            "③ Battery condition : Battery system voltage(180V) up to 150Nm, 340V for over 150Nm",
            "(±)10,20,30 200rpm/s",
            "Ste",
            "Step: Every 10% of max Tq",
        ]))
        self.assertEqual(doubled.count("④"), 1)
        self.assertNotIn("Table1", doubled)
        self.assertNotIn("10,20,30", doubled)
        self.assertNotIn("Step:", doubled)
        doubled = order_clauses("\n".join([
            "④ No abnormal noise when 0 Torque control",
            "④ No abnormal noise when 0 Torque control Table1. P3 Load & Speed rate Load(Nm) Speed rate",
        ]))
        self.assertEqual(doubled.count("④"), 1)
        self.assertNotIn("Table1", doubled)
        self.assertIn("0 Torque control", doubled)

    def test_repeated_heading_does_not_drop_the_next_sweep_rate(self) -> None:
        from electrical_krow.arch_figures import order_clauses

        raw = "\n".join([
            "2. P3 Motor NVH TEST condition",
            "③ Battery condition : Battery system voltage(180V) up to 150Nm, 340V for over 150Nm 0ver",
            "3. P3 + Engine Driving condition Motor NVH TEST condition",
            "① Operating condition : Engine + P3 driving",
            "4. Engine Input Gear NVH TEST Condition",
            "① Operating condition : Engine + P3 driving Table2. Parallel Mode test load",
            "② Bench test sweep rate : Run up/down speed 120rpm/s under Input-Dyno P3 Motor Tq.",
            "4. Engine Input Gear NVH TEST Condition 100Nm",
            "① Operating condition : Engine driving condition(Clutch Engaged)",
            "② Bench test sweep rate : Run up/down speed 120rpm/s under, engine min rpm~ rated rpm",
            "③ Load condition : Engine max Torque 10%, 20%, 30%, 50%, 70%, Full Load",
        ])
        ordered = order_clauses(raw)
        self.assertIn("3. P3 + Engine Driving condition", ordered)
        self.assertNotIn("Motor NVH TEST condition\n", ordered.split("3. P3", 1)[-1].split("4. Engine", 1)[0])
        self.assertNotIn("0ver", ordered)
        self.assertNotIn("100Nm", ordered)
        self.assertNotIn("Input-Dyno", ordered)
        third = ordered.split("3. P3", 1)[-1].split("4. Engine", 1)[0]
        fourth = ordered.split("4. Engine", 1)[-1]
        self.assertIn("120rpm/s under", third)
        self.assertNotIn("rated rpm", third)
        self.assertIn("rated rpm", fourth)

    def test_axis_ticks_do_not_stick_to_the_footnote(self) -> None:
        from electrical_krow.arch_figures import axis_tick_dump

        self.assertFalse(axis_tick_dump("Po (kW)"))
        self.assertTrue(axis_tick_dump("80 60 dBA 0 5000 10000 15000 rpm"))
        body = "\n".join([
            "1. Specifications must be satisfied under all acceleration and deceleration conditions.",
            "*TBD : To be determined after T-car vehicle evaluation and bench test",
            "0",
            "5000",
            "10000",
            "dBA",
            "Motor 48th Noise",
            "Motor Noise 8th Oder",
        ])
        rows, _tables = split_document(SourceDoc("noise.pdf", ((1, body),)))
        joined = "\n".join(str(row[8]) for row in rows)
        self.assertIn("TBD", joined)
        self.assertIn("Specifications", joined)
        self.assertNotIn("5000", joined)
        self.assertNotIn("Motor 48th", joined)
        self.assertNotIn("8th Oder", joined)

    def test_table_inside_a_chart_shot_is_not_excerpted_again(self) -> None:
        grid = [["rpm", "8th Noise (dBA)"], ["2500", "60"], ["17000", "70"]]
        figure = Figure(2, (20, 180, 820, 580), "Motor 48th Noise 80 60 0 5000 10000 15000", b"", "矢量图", "")
        doc = SourceDoc(
            "noise.pdf",
            ((2, "1. Specifications must be satisfied under all acceleration and deceleration conditions.\n"),),
            tables={2: [grid]},
            figures={2: [figure]},
            table_rows={2: [[(40, 220, 210, 250), (40, 250, 210, 290), (40, 290, 210, 330)]]},
        )
        rows, _tables = split_document(doc)
        texts = [str(row[8]) for row in rows]
        chart = next(text for text in texts if text.startswith("本页图表"))
        self.assertNotIn("15000", chart)
        self.assertNotIn("dBA", chart)
        self.assertFalse(any("2500" in text for text in texts))

    def test_subitems_under_a_heading_stay_in_mark_order(self) -> None:
        from electrical_krow.arch_figures import order_clauses

        raw = "\n".join([
            "3. P3 + Engine Driving condition",
            "① Operating condition : Engine + P3 driving",
            "③ Load condition : P3 + Engine driving(refer to the table2)",
            "*TBD : To be determined after T-car vehicle evaluation",
            "② Bench test sweep rate : Run up/down speed 120rpm/s under Input-Dyno P3 Motor Tq.",
            "④ Battery condition : Battery system voltage(180V) up to 150Nm (±)Max Tq@Parallel",
            "(±)30Nm",
            "② Bench test sweep rate : Run up/down speed 120rpm/s under",
        ])
        ordered = order_clauses(raw).splitlines()
        self.assertEqual(ordered[0], "3. P3 + Engine Driving condition")
        self.assertTrue(ordered[1].startswith("①"))
        self.assertTrue(ordered[2].startswith("②"))
        self.assertIn("120rpm/s", ordered[2])
        self.assertNotIn("Input-Dyno", ordered[2])
        self.assertTrue(ordered[3].startswith("③"))
        self.assertTrue(ordered[4].startswith("④"))
        self.assertNotIn("Max Tq", ordered[4])
        self.assertEqual(sum(1 for line in ordered if line.startswith("②")), 1)
        self.assertLess(ordered.index(next(line for line in ordered if line.startswith("*TBD"))), len(ordered))
        self.assertGreater(next(i for i, line in enumerate(ordered) if line.startswith("*TBD")), 4)

    def test_excerpt_rules_hold_for_a_document_that_is_not_the_sample(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 30, 20), False)
        pix.clear_with(210)
        blob = pix.tobytes("png")
        transcript = "\n".join([
            "1) First operating condition",
            "① Bench sweep rate is 200rpm/s under rated rpm",
            "② Load steps every 10Nm up to 100Nm",
            "2. Second motor condition",
            "② Bench test refers to Table 1 for driving",
            "3. Third engine condition",
            "② Run up and down speed is 120rpm/s under",
        ])
        table = (("rpm", "Noise (dBA)"), ("2500", "60"), ("17000", "70"))
        axis = (("2500", "60", ""), ("0", "5000", "10000", "15000"))
        figs = {
            1: [Figure(1, (30, 40, 300, 200), "", blob, "矢量图", transcript, table)],
            2: [Figure(2, (30, 40, 300, 200), "rpm dBA", blob, "位图", "", axis)],
        }
        pages = (
            (1, "1. Overview\nThe operating conditions are listed beside the table.\n"),
            (2, "2. Noise\nThe curve is shown on this page.\n"),
        )
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("sample.pdf", pages, figures=figs, path="sample.pdf")], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                texts = [str(sheet.cell(r, 5).value or "") for r in range(2, sheet.max_row + 1)]
                joined = "\n".join(texts)
                block = next(text for text in texts if "10Nm" in text and "120rpm/s" in text)
                self.assertLess(block.find("10Nm"), block.find("Table 1"))
                self.assertLess(block.find("Table 1"), block.find("120rpm/s"))
                self.assertEqual(sum("10Nm" in text and "120rpm/s" in text for text in texts), 1)
                self.assertNotIn("15000", joined)
                self.assertFalse(
                    any(str(cell.value or "").strip() == "2500" for row in sheet.iter_rows(min_row=2) for cell in row)
                )
            finally:
                book.close()

    def test_two_column_table_is_drawn_beside_itself(self) -> None:
        grid = [
            ["rpm", "8th Noise (dBA)/TBD"],
            ["0", "10"],
            ["2500", "60"],
            ["17000", "70"],
        ]
        pages = ((1, "1. Overview\nThe noise limits are listed in the table.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("noise.pdf", pages, {1: [grid]})], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                rpm = next(
                    cell
                    for row in sheet.iter_rows(min_row=2)
                    for cell in row
                    if str(cell.value or "").strip() == "2500"
                )
                self.assertEqual(str(sheet.cell(rpm.row, rpm.column + 1).value or "").strip(), "60")
                self.assertIn("8th", str(sheet.cell(rpm.row - 2, rpm.column + 1).value or ""))
                self.assertNotIn("\n10", str(sheet.cell(rpm.row, rpm.column).value or ""))
            finally:
                book.close()

    def test_tall_shot_still_writes_the_status_list(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 420), False)
        pix.clear_with(180)
        blob = pix.tobytes("png")
        grid = (("Load(Nm)", "Speed rate"), ("(±)10,20,30", "200rpm/s"))
        figs = {1: [Figure(1, (40, 80, 400, 500), "", blob, "矢量图", "1) P1 Generating condition is a bench sweep.", grid)]}
        pages = ((1, "1. Overview\nThe load table is beside the text.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh.pdf", pages, figures=figs)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                headers = [sheet.cell(1, col).value for col in range(1, sheet.max_column + 1)]
                self.assertIn("Currently status\n状态", headers)
                formulas = [dv.formula1 for dv in sheet.data_validations.dataValidation]
                self.assertTrue(any("To be confirmed" in (formula or "") for formula in formulas))
            finally:
                book.close()

    def test_any_document_splits_each_chart_from_its_own_table(self) -> None:
        """不出现转速、噪声这两个词时，一页两张曲线仍各截一张、各摘自己的表。"""
        import pymupdf

        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "curves.pdf"
            doc = pymupdf.open()
            page = doc.new_page(width=842, height=520)

            def draw_table(x: float, y: float, headers: tuple[str, str], rows: list[tuple[str, str]]) -> None:
                col_w, row_h = 78, 22
                height = row_h * (1 + len(rows))
                for col in range(3):
                    page.draw_line((x + col * col_w, y), (x + col * col_w, y + height))
                for row in range(2 + len(rows)):
                    page.draw_line((x, y + row * row_h), (x + 2 * col_w, y + row * row_h))
                page.insert_text((x + 8, y + 16), headers[0], fontsize=9)
                page.insert_text((x + col_w + 8, y + 16), headers[1], fontsize=9)
                for index, row in enumerate(rows):
                    page.insert_text((x + 8, y + (index + 1) * row_h + 16), row[0], fontsize=9)
                    page.insert_text((x + col_w + 8, y + (index + 1) * row_h + 16), row[1], fontsize=9)

            draw_table(36, 60, ("kW", "Torque"), [("10", "21"), ("30", "41")])
            draw_table(36, 280, ("Speed", "Power"), [("80", "99"), ("90", "88")])
            shape = page.new_shape()
            for step in range(12):
                shape.draw_bezier((220, 80 + 6 * step), (300, 50), (380, 170), (500, 90 + 4 * step))
                shape.draw_bezier((220, 300 + 6 * step), (300, 270), (380, 390), (500, 310 + 4 * step))
            shape.finish(color=(0, 0, 1), width=1.2)
            shape.commit()
            doc.save(pdf)
            doc.close()
            figures = find_figures(pdf).get(1) or []
            self.assertEqual(len(figures), 2)
            self.assertTrue(all(not figure.grid for figure in figures))
            top, bottom = sorted(figures, key=lambda figure: figure.box[1])
            self.assertLess(top.box[1], 80)
            self.assertGreater(top.box[3], 120)
            self.assertLess(top.box[3], bottom.box[1] + 30)
            self.assertGreater(bottom.box[1], 200)
            self.assertGreater(bottom.box[3], 340)

    def test_attachment_title_above_the_body_is_its_own_row(self) -> None:
        from electrical_krow.arch_figures import apply_outlined_titles, outlined_titles

        path = next(Path("/Users/wwj/电子电器项目/资料").rglob("*Motor NVH*AB_Print.pdf"), None)
        if path is None:
            self.skipTest("样例 PDF 不在这台机器上")
        import pymupdf

        with pymupdf.open(path) as doc:
            title = outlined_titles(doc[1])
            page_text = doc[1].get_text("text")
        self.assertIn("Attachment2", title)
        self.assertIn("Bench test target", title)
        self.assertNotIn("Specifications", title)
        merged = apply_outlined_titles(path, ((2, page_text),), {})
        self.assertTrue(merged[0][1].lstrip().startswith("Attachment2"))
        rows, _tables = split_document(SourceDoc(path.name, merged))
        texts = [str(row[8]) for row in rows]
        heading = next(text for text in texts if "Attachment2" in text)
        self.assertNotIn("Specifications", heading)
        self.assertTrue(any("Specifications" in text for text in texts))
        self.assertEqual(sum("Attachment2" in text for text in texts), 1)

    def test_spec_table_rows_stay_as_tall_as_one_line(self) -> None:
        import pymupdf

        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 80, 700), False)
        pix.clear_with(180)
        blob = pix.tobytes("png")
        grid = (
            ("Load(Nm)", "Speed rate"),
            ("(±)10,20,30", "200rpm/s"),
            ("(±)40,50", "400rpm/s"),
            ("Over (±)50Nm~Max Tq Step: Every 10% of max Tq", "800rpm/s"),
        )
        transcript = "\n".join([
            "1) P1 Generating condition",
            "① Bench test sweep rate : Run up/down speed 200rpm/s under, engine min rpm~ rated rpm and the sentence keeps going so the column would otherwise stretch",
        ])
        figs = {1: [Figure(1, (40, 80, 400, 500), "", blob, "矢量图", transcript, grid)]}
        pages = ((1, "1. Overview\nThe load table is beside the text.\n"),)
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "out.xlsx"
            write_contrast([SourceDoc("nvh.pdf", pages, figures=figs)], [], dest)
            book = load_workbook(dest)
            try:
                sheet = book["需求清单"]
                speed = next(
                    cell
                    for row in sheet.iter_rows(min_row=2)
                    for cell in row
                    if "200rpm/s" in str(cell.value or "")
                )
                self.assertLess(sheet.row_dimensions[speed.row].height, 40)
                self.assertLess(sheet.column_dimensions["E"].width, 120)
                eight = next(
                    cell
                    for row in sheet.iter_rows(min_row=2)
                    for cell in row
                    if "800rpm/s" in str(cell.value or "")
                )
                self.assertLess(sheet.row_dimensions[eight.row].height, 40)
            finally:
                book.close()

    def test_condition_list_is_one_row_with_the_original_line_breaks(self) -> None:
        transcript = "\n".join([
            "Attachment1. Motor NVH bench test operating condition",
            "1. P1 Motor NVH TEST condition",
            "① Bench test sweep rate : Run up/down speed 200rpm/s under, engine min rpm~ rated rpm",
            "2. P3 Motor NVH TEST condition",
            "① Operating condition : Acceleration, Deceleration, 200~Max. rpm",
        ])
        figure = Figure(1, (20, 40, 400, 300), "", b"", "矢量图", transcript, ())
        rows, _tables = split_document(SourceDoc("nvh.pdf", ((1, "1. Overview\n"),), figures={1: [figure]}))
        blocks = [str(row[8]) for row in rows if "Attachment1" in str(row[8])]
        self.assertEqual(len(blocks), 1)
        lines = blocks[0].splitlines()
        self.assertEqual(lines[0], "Attachment1. Motor NVH bench test operating condition")
        self.assertEqual(lines[1], "1. P1 Motor NVH TEST condition")
        self.assertTrue(lines[2].startswith("① Bench test sweep rate"))
        self.assertLess(blocks[0].find("① Bench"), blocks[0].find("2. P3"))
        self.assertLess(blocks[0].find("2. P3"), blocks[0].find("Acceleration"))

    def test_page_title_stays_when_the_table_is_removed(self) -> None:
        from electrical_krow.arch_figures import prose_beside

        text = "\n".join([
            "Attachment1. Motor NVH bench test operating condition",
            "1. P1 Motor NVH TEST condition",
            "① Bench test sweep rate is 200rpm/s under",
        ])
        grid = (("Load(Nm)", "Speed rate"), ("10", "200rpm/s"), ("20", "200rpm/s"), ("30", "200rpm/s"))
        kept = prose_beside(text, grid)
        self.assertIn("Attachment1", kept)
        self.assertIn("1. P1 Motor NVH TEST", kept)
        self.assertIn("①", kept)

    def test_outlined_condition_page_excerpts_the_sentences_and_the_table(self) -> None:
        path = next(Path("/Users/wwj/电子电器项目/资料").rglob("*Motor NVH*AB_Print.pdf"), None)
        if path is None:
            self.skipTest("样例 PDF 不在这台机器上")
        found = find_figures(path)
        figures = found.get(1) or []
        self.assertEqual(len(figures), 1)
        text = figures[0].transcript
        self.assertIn("Bench test sweep rate", text)
        self.assertIn("rated rpm", text)
        self.assertIn("Load condition", text)
        second = text.split("2. P3", 1)[-1].split("3. P3", 1)[0]
        self.assertIn("③", second)
        self.assertIn("150Nm", second)
        self.assertIn("No abnormal noise", text)
        self.assertIn("Attachment1", text)
        self.assertIn("P1 Motor NVH TEST", text)
        self.assertNotIn("u nd n", text)
        flat = " ".join(cell for row in figures[0].grid for cell in row)
        self.assertIn("200rpm/s", flat)
        self.assertIn("100Nm", flat)
        noise = found.get(2) or []
        charts = [figure for figure in noise if "Noise" in figure.transcript]
        self.assertEqual(len(charts), 3)
        self.assertTrue(all(not figure.grid for figure in charts))
        eighth = next(figure for figure in charts if "8th" in figure.transcript)
        self.assertLessEqual(eighth.box[0], 40)
        self.assertLess(eighth.box[2], 520)
        self.assertLess(eighth.box[3], 350)
        forty = next(figure for figure in charts if "48th" in figure.transcript)
        self.assertGreater(forty.box[0], 360)
        self.assertTrue(any(figure.box[1] > 450 and "Noise" not in figure.transcript for figure in noise))
        twenty = next(figure for figure in charts if "24th" in figure.transcript)
        self.assertIn("respectively", twenty.transcript)
        self.assertNotIn("respectively", eighth.transcript)

    def test_chart_table_is_not_written_twice(self) -> None:
        grid = [("rpm", "8th Noise (dBA)/TBD"), ("0", "10"), ("2500", "60"), ("17000", "70")]
        figure = Figure(
            2, (20, 200, 500, 360), "", b"", "矢量图",
            "Motor Noise 8th Oder\nP1, P3 respectively",
            tuple(tuple(row) for row in grid),
        )
        doc = SourceDoc(
            "noise.pdf",
            ((2, "1. Specifications must be satisfied under all acceleration and deceleration conditions.\n"),),
            tables={2: [[list(row) for row in grid]]},
            figures={2: [figure]},
            table_rows={2: [[(40, 220, 200, 250), (40, 250, 200, 280), (40, 280, 200, 320), (40, 320, 200, 350)]]},
        )
        rows, _tables = split_document(doc)
        texts = [str(row[8]) for row in rows]
        self.assertEqual(sum("2500" in text for text in texts), 0)
        self.assertTrue(any("respectively" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
