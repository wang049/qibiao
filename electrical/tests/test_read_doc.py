"""PDF 数字稿：结构化表按页嵌回，盖掉表格区内乱序文字。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrical.read_doc import (
    _PdfLoad,
    _docx_markdown_in_order,
    _expand_markdown_tables,
    _finish_pdf,
    _line_covered,
    _load_pdf,
    load_document,
)


def _drawn_table_pdf(path: Path, *, caption: str = "Inverter SR Parameter table") -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), caption)
    xs = [72, 300, 520]
    ys = [100, 140, 180, 220]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    cells = [
        ((80, 110), "Item"),
        ((310, 110), "Value"),
        ((80, 150), "HVDC bus voltage"),
        ((310, 150), "380 Vdc"),
        ((80, 190), "Peak power"),
        ((310, 190), "80 kW"),
    ]
    for pos, text in cells:
        page.insert_text(pos, text, fontsize=11)
    doc.save(str(path))
    doc.close()


def _page_number_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    top = doc.new_page()
    top.insert_text((420, 24), "Page No 5 (10)", fontsize=9)
    top.insert_text((72, 200), "weight of the XCM shall be less than 20.2kg")
    bottom = doc.new_page()
    bottom.insert_text((72, 200), "The XCM shall be able to boost the HV input voltage")
    bottom.insert_text((430, 800), "6 (10)", fontsize=9)
    doc.save(str(path))
    doc.close()


def _tall_header_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((380, 168), "Page No 页码", fontsize=9)
    page.insert_text((410, 186), "78 (116)", fontsize=9)
    page.insert_text((72, 320), "控制器高压回路与地之间（外壳）绝缘电阻")
    doc.save(str(path))
    doc.close()


def _mixed_page_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 80), "This paragraph should remain.")
    xs = [300, 450, 560]
    ys = [70, 110, 150, 190]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.8)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.8)
    for pos, text in [
        ((310, 80), "Name"),
        ((460, 80), "Val"),
        ((310, 120), "Voltage"),
        ((460, 120), "350 V"),
        ((310, 160), "Current"),
        ((460, 160), "200 A"),
    ]:
        page.insert_text(pos, text, fontsize=10)
    doc.save(str(path))
    doc.close()


class LineCoverTests(unittest.TestCase):
    def test_center_inside_table_is_covered(self) -> None:
        table = (300.0, 70.0, 560.0, 190.0)
        self.assertTrue(_line_covered((310.0, 109.0, 344.0, 123.0), [table]))
        self.assertFalse(_line_covered((72.0, 68.0, 221.0, 83.0), [table]))


class PdfTableLayoutTests(unittest.TestCase):
    def test_table_is_under_page_heading_not_appendix(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "inverter.pdf"
            _drawn_table_pdf(path)
            loaded = _load_pdf(path)
        self.assertIn("## 第 1 页", loaded.markdown)
        self.assertIn("| HVDC bus voltage | 380 Vdc |", loaded.markdown)
        self.assertIn("| Peak power | 80 kW |", loaded.markdown)
        self.assertNotIn("## 表格", loaded.markdown)
        self.assertEqual(loaded.table_pages, {1})
        heading_at = loaded.markdown.find("## 第 1 页")
        table_at = loaded.markdown.find("| HVDC bus voltage | 380 Vdc |")
        self.assertGreater(table_at, heading_at)

    def test_covers_stream_text_inside_table_keeps_caption(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "mixed.pdf"
            _mixed_page_pdf(path)
            loaded = _load_pdf(path)
            src = fitz.open(str(path))
            try:
                raw_text = src[0].get_text()
            finally:
                src.close()
        self.assertIn("This paragraph should remain.", loaded.markdown)
        self.assertIn("| Voltage | 350 V |", loaded.markdown)
        self.assertEqual(loaded.markdown.count("350 V"), 1)
        self.assertIn("Voltage", raw_text)
        self.assertTrue(loaded.native_chars > 20)

    def test_uses_printed_page_from_header_or_footer(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "printed.pdf"
            _page_number_pdf(path)
            loaded = _load_pdf(path)
        self.assertIn("## 第 5 页", loaded.markdown)
        self.assertIn("## 第 6 页", loaded.markdown)
        self.assertNotIn("## 第 1 页", loaded.markdown)
        self.assertIn("20.2kg", loaded.markdown.split("## 第 5 页", 1)[1].split("## 第", 1)[0])
        self.assertIn("boost the HV input voltage", loaded.markdown.split("## 第 6 页", 1)[1])

    def test_reads_page_no_from_lower_header_band(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("need pymupdf")
        from electrical.read_doc import _pdf_page_labels, _printed_page_from_chrome

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "header.pdf"
            _tall_header_pdf(path)
            doc = fitz.open(str(path))
            try:
                labels = _pdf_page_labels(doc, require_chrome=True)
                chrome = doc[0].get_text("text") or ""
            finally:
                doc.close()
        self.assertEqual(
            _printed_page_from_chrome("Page No 页码\n78 (116)", 1, 116),
            78,
        )
        self.assertIn("78 (116)", chrome)
        self.assertEqual(labels, [78])

    def test_load_document_uses_page_tables(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "sr.pdf"
            _drawn_table_pdf(path)
            with patch("electrical.read_doc.ocr_available", return_value=False):
                doc = load_document(path)
        self.assertFalse(doc.likely_scan)
        self.assertIn("| HVDC bus voltage | 380 Vdc |", doc.markdown)
        self.assertEqual(doc.ocr_pages, 0)

    def test_pages_with_native_tables_skip_sparse_ocr(self) -> None:
        pdf = _PdfLoad(
            markdown="## 第 3 页\n| Item | Value |\n| --- | --- |\n| Voltage | 350 V |\n",
            page_count=8,
            native_chars=4000,
            table_pages={3},
        )
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "dummy.pdf"
            path.write_bytes(b"%PDF-1.4\n")
            with patch("electrical.read_doc.ocr_available", return_value=True):
                with patch(
                    "electrical.read_doc.sparse_pdf_pages",
                    return_value=[3, 4],
                ):
                    with patch("electrical.read_doc.ocr_pdf_pages") as ocr:
                        ocr.return_value = {}
                        _finish_pdf(path, pdf, deadline=None)
        ocr.assert_called_once()
        self.assertEqual(ocr.call_args[0][1], [4])


class DocxTableTests(unittest.TestCase):
    def test_keeps_long_cell_text(self) -> None:
        from docx import Document

        long = (
            "The inverter HVDC bus voltage shall remain 380 Vdc during "
            "continuous operation and overload."
        )
        self.assertGreater(len(long), 50)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "long.docx"
            doc = Document()
            table = doc.add_table(2, 2)
            table.cell(0, 0).text = "Item"
            table.cell(0, 1).text = "Requirement"
            table.cell(1, 0).text = "HVDC bus voltage"
            table.cell(1, 1).text = long
            doc.save(str(path))
            md = _docx_markdown_in_order(path)
        self.assertIn(long, md)
        self.assertNotIn(long[:47] + "...", md)

    def test_horizontal_merge_is_not_duplicated(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "hmerge.docx"
            doc = Document()
            table = doc.add_table(2, 2)
            table.cell(0, 0).text = "Item"
            table.cell(0, 1).text = "Value"
            table.cell(1, 0).text = "HVDC"
            table.cell(1, 1).text = "380 Vdc"
            table.cell(1, 0).merge(table.cell(1, 1))
            doc.save(str(path))
            md = _docx_markdown_in_order(path)
        self.assertEqual(md.count("HVDC"), 1)
        self.assertEqual(md.count("380 Vdc"), 1)

    def test_vertical_merge_is_not_duplicated(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "vmerge.docx"
            doc = Document()
            table = doc.add_table(3, 2)
            table.cell(0, 0).text = "Voltage"
            table.cell(0, 1).text = "380 Vdc"
            table.cell(1, 0).text = "below"
            table.cell(1, 1).text = "same col"
            table.cell(2, 0).text = "Peak"
            table.cell(2, 1).text = "80 kW"
            table.cell(0, 0).merge(table.cell(1, 0))
            doc.save(str(path))
            md = _docx_markdown_in_order(path)
        self.assertEqual(md.count("Voltage"), 1)
        self.assertIn("380 Vdc", md)
        self.assertIn("same col", md)
        self.assertIn("80 kW", md)

    def test_nested_table_keeps_grid(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "nested.docx"
            doc = Document()
            outer = doc.add_table(2, 1)
            outer.cell(0, 0).text = "Parameters"
            inner = outer.cell(1, 0).add_table(2, 2)
            inner.cell(0, 0).text = "HVDC bus voltage"
            inner.cell(0, 1).text = "380 Vdc"
            inner.cell(1, 0).text = "Peak power"
            inner.cell(1, 1).text = "80 kW"
            doc.save(str(path))
            md = _docx_markdown_in_order(path)
        self.assertIn("Parameters", md)
        self.assertIn("| HVDC bus voltage | 380 Vdc |", md)
        self.assertIn("| Peak power | 80 kW |", md)

    def test_textbox_table_is_read(self) -> None:
        from docx import Document
        from docx.oxml import parse_xml

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "txbx.docx"
            doc = Document()
            para = doc.add_paragraph("Caption outside box")
            para._p.append(
                parse_xml(
                    '<w:txbxContent xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    "<w:tbl>"
                    "<w:tr>"
                    "<w:tc><w:p><w:r><w:t>Item</w:t></w:r></w:p></w:tc>"
                    "<w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc>"
                    "</w:tr>"
                    "<w:tr>"
                    "<w:tc><w:p><w:r><w:t>Current</w:t></w:r></w:p></w:tc>"
                    "<w:tc><w:p><w:r><w:t>200 A</w:t></w:r></w:p></w:tc>"
                    "</w:tr>"
                    "</w:tbl>"
                    "</w:txbxContent>"
                )
            )
            doc.save(str(path))
            md = _docx_markdown_in_order(path)
        self.assertIn("Caption outside box", md)
        self.assertIn("| Current | 200 A |", md)


class TableExpandTests(unittest.TestCase):
    def test_flattens_cells_for_rules(self) -> None:
        md = (
            "## 第 1 页\n\n"
            "| Item | Value |\n"
            "| --- | --- |\n"
            "| HVDC bus voltage | 380 Vdc |\n"
            "| Peak power | 80 kW |\n"
        )
        expanded = _expand_markdown_tables(md)
        self.assertIn("| HVDC bus voltage | 380 Vdc |", expanded)
        self.assertIn("HVDC bus voltage  380 Vdc", expanded)
        self.assertIn("Peak power  80 kW", expanded)

    def test_load_document_appends_word_image_ocr(self) -> None:
        from docx import Document

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "mix.docx"
            doc = Document()
            doc.add_paragraph("Native cover paragraph")
            doc.save(str(path))
            with patch(
                "electrical.read_doc._ocr_docx_images",
                return_value=["HVDC bus voltage 380 Vdc peak power 80 kW asil D"],
            ):
                loaded = load_document(path)
        self.assertIn("Native cover paragraph", loaded.markdown)
        self.assertIn("[本页为本机 OCR]", loaded.markdown)
        self.assertIn("380 Vdc", loaded.markdown)
        self.assertEqual(loaded.ocr_pages, 1)
        self.assertFalse(loaded.likely_scan)


class DocxOutlineTests(unittest.TestCase):
    def test_prefix_skips_typed_clause(self) -> None:
        from electrical.read_doc import _prefix_printed_number

        self.assertEqual(
            _prefix_printed_number("6.2.3.2 High Voltage DC connection", "6.2.3.1"),
            "6.2.3.2 High Voltage DC connection",
        )
        self.assertEqual(
            _prefix_printed_number("HVDC Voltage Range 高压范围", "6.5.3"),
            "6.5.3 HVDC Voltage Range 高压范围",
        )
        self.assertEqual(
            _prefix_printed_number("6.5.3 HVDC Voltage Range", "6.5.3"),
            "6.5.3 HVDC Voltage Range",
        )

    def test_page_key_strips_clause_not_decimal_kg(self) -> None:
        from electrical.read_doc import _norm_page_key

        self.assertEqual(
            _norm_page_key("6.5.3 HVDC Voltage Range 高压范围 extra"),
            _norm_page_key("HVDC Voltage Range 高压范围 extra"),
        )
        self.assertIn("20.2", _norm_page_key("20.2kg including coolant fluid extra"))
