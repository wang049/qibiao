from __future__ import annotations

import unittest
from io import BytesIO
from zipfile import ZipFile

from electrical_krow.inspect_doc import _docx_probe, _pdf_probe, _xlsx_probe


def _pdf(pages: list[str]) -> bytes:
    import fitz

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _docx(body: str, header: str = "", footer: str = "") -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{ns}"><w:body>'
        f"{body}"
        "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"
        "<w:p><w:r><w:t>第二页</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    header_xml = (
        f'<?xml version="1.0"?><w:hdr xmlns:w="{ns}">'
        f"<w:p><w:r><w:t>{header}</w:t></w:r></w:p></w:hdr>"
    )
    footer_xml = (
        f'<?xml version="1.0"?><w:ftr xmlns:w="{ns}">'
        f"<w:p><w:r><w:t>{footer}</w:t></w:r></w:p></w:ftr>"
    )
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", document)
        if header:
            zf.writestr("word/header1.xml", header_xml)
        if footer:
            zf.writestr("word/footer1.xml", footer_xml)
    return buf.getvalue()


class PdfScanTests(unittest.TestCase):
    def test_front_matter_does_not_hide_scanned_back_half(self) -> None:
        pages = ["额定功率 120 kW " * 30] * 12 + ["12"] * 12
        _count, _head, likely = _pdf_probe(_pdf(pages))
        self.assertTrue(likely)

    def test_digital_document_is_not_a_scan(self) -> None:
        pages = ["额定功率 120 kW " * 20] * 6
        count, head, likely = _pdf_probe(_pdf(pages))
        self.assertEqual(count, 6)
        self.assertIn("120 kW", head)
        self.assertFalse(likely)


class DocxProbeTests(unittest.TestCase):
    def test_table_cells_and_header_are_kept(self) -> None:
        ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        table = (
            f'<w:tbl xmlns:w="{ns}"><w:tr>'
            "<w:tc><w:p><w:r><w:t>引脚</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>P1</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
        )
        pages, text = _docx_probe(_docx(table, header="印页 12", footer="机密"))
        self.assertEqual(pages, 2)
        self.assertIn("引脚 | P1", text)
        self.assertIn("【页眉】", text)
        self.assertIn("印页 12", text)
        self.assertIn("【页脚】", text)
        self.assertIn("机密", text)


class XlsxProbeTests(unittest.TestCase):
    def test_header_and_late_rows_stay_in_range(self) -> None:
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        assert sheet is not None
        sheet.title = "引脚表"
        sheet.append(["引脚", "功能"])
        for index in range(1, 201):
            sheet.append([index, f"行{index}"])
        buf = BytesIO()
        book.save(buf)
        count, text = _xlsx_probe(buf.getvalue())
        self.assertEqual(count, 1)
        self.assertIn("[引脚表] 范围", text)
        self.assertIn("引脚 | 功能", text)
        self.assertIn("行200", text)


if __name__ == "__main__":
    unittest.main()
