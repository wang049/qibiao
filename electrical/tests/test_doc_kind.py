"""文档分流与 OCR 选页：ESOW / 变速器 / 目录页不得按 120 项电控清单硬抽。"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

from electrical.doc_kind import classify_document, page_text_kind
from electrical.extract import _rule_cells


class PageKindTests(unittest.TestCase):
    def test_toc_page_not_param(self) -> None:
        text = """
        目 录
        1 范围 ................ 1
        2 规范性引用文件 .......... 2
        3 术语和定义 .............. 3
        引用标准清单
        GB/T 18488
        """
        self.assertEqual(page_text_kind(text), "toc")

    def test_param_page_chinese(self) -> None:
        text = "直流工作电压 350 Vdc，峰值功率 120 kW，额定扭矩 280 N·m，主动放电 2 s。"
        self.assertEqual(page_text_kind(text), "param")


class ClassifyTests(unittest.TestCase):
    def test_esow_skips_extract(self) -> None:
        kind = classify_document(
            Path("ESOW_controller.docx"),
            "Engineering Statement of Work\nThis ESOW defines supplier scope of work and deliverables.",
        )
        self.assertEqual(kind.code, "esow")
        self.assertFalse(kind.extract)
        self.assertEqual(kind.family, "none")

    def test_esow_upload_filename_not_transmission(self) -> None:
        kind = classify_document(
            Path("ed1c4c96_DHTS160_ESOW.docx"),
            "Commodity Information\nPTO Plant Location GEELY Changxing transmission CO.\n"
            "Description & Scope of Supplier Responsibility",
        )
        self.assertEqual(kind.code, "esow")
        self.assertFalse(kind.extract)

    def test_transmission_item_skips_extract(self) -> None:
        kind = classify_document(
            Path("Inverter_SR_from_Outside-2.pdf"),
            "Item\n6 Speed Transmission\nGear ratio 1st 4.5\nWarranty life target: 15 years - 300,000 km\nMAX. 12 LPM",
        )
        self.assertEqual(kind.code, "transmission_sr")
        self.assertFalse(kind.extract)

    def test_inverter_item_extracts(self) -> None:
        kind = classify_document(
            Path("Inverter_SR_from_Outside.pdf"),
            "Item\nDHT Inverter\nDC-link 400 Vdc\npeak power 80 kW\nactive discharge 1 s\nMAX. 12 LPM",
        )
        self.assertEqual(kind.code, "inverter_sr")
        self.assertTrue(kind.extract)
        self.assertEqual(kind.family, "inverter")

    def test_dpr_family(self) -> None:
        kind = classify_document(
            Path("DHTS160_DPR.pdf"),
            "DHTS160 Design Prerequisites\nXCM控制器\n冷启动 210V PCM母线 350 Vdc P1逆变器 120 kW P3逆变器 80 kW 额定扭矩 200 N·m",
        )
        self.assertEqual(kind.code, "xcm_dpr")
        self.assertTrue(kind.extract)
        self.assertEqual(kind.family, "dpr")

    def test_scanned_4ldht_filename_is_still_dpr(self) -> None:
        kind = classify_document(Path("4LDHT260_DPR(扫描件).pdf"), "")
        self.assertEqual(kind.code, "xcm_dpr")
        self.assertTrue(kind.extract)
        self.assertEqual(kind.label, "电控 DPR")
        self.assertNotIn("非电控", kind.label)
        self.assertNotIn("不按", kind.note)

    def test_scan_toc_skips_extract(self) -> None:
        kind = classify_document(
            Path("scan.pdf"),
            "目录\n规范性引用文件\n修订记录\n标准清单\n适用标准\n第 1 章 …… 1\n第 2 章 …… 5",
        )
        self.assertEqual(kind.code, "scan_toc")
        self.assertFalse(kind.extract)


class FamilyRuleTests(unittest.TestCase):
    def test_hyundai_lpm_not_applied_to_dpr(self) -> None:
        chunk = "Coolant MAX. 12 LPM EWP forced circulation"
        dpr = _rule_cells(chunk, family="dpr")
        self.assertFalse(any(c.name == "额定流量" for c in dpr))
        inv = _rule_cells(chunk, family="inverter")
        self.assertTrue(any(c.name == "额定流量" and "12 LPM" in c.value for c in inv))


    def test_dpr_emc_and_p1_asc_alias(self) -> None:
        chunk = (
            "主动短路期间，P1电磁最大允许稳态电流为250Arms有效值。"
            "该要求适用于全工作速度范围。P1逆变器应能在此条件下工作3.5秒。"
            "控制器应满足Q/JLY J7110922D-2024的要求。"
            "发电工况(负扭矩): -40到-50nm在5000~7000rpm@340V的转速范围内。"
        )
        found = {c.name: c.value for c in _rule_cells(chunk, family="dpr")}
        self.assertIn("P1 ASC电流能力", found)
        self.assertIn("250Arms", found["P1 ASC电流能力"])
        self.assertEqual(found.get("EMC等级"), "Q/JLY J7110922D-2024")
        self.assertIn("P1馈电要求", found)
        self.assertIn("-40", found["P1馈电要求"])


class TocPageTests(unittest.TestCase):
    def test_printed_labels_override_physical(self) -> None:
        from electrical.read_doc import _HEADER_PAGE_PAIR, _printed_from_physical

        pages = _printed_from_physical([1, 0, 3], labels=[5, 6, 7])
        self.assertEqual(pages, [5, 0, 7])
        match = _HEADER_PAGE_PAIR.search("Page No 页码\n3 (116)")
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), 3)
        self.assertEqual(int(match.group(2)), 116)

    def test_printed_page_from_header_or_footer_chrome(self) -> None:
        from electrical.read_doc import _printed_page_from_chrome

        self.assertEqual(
            _printed_page_from_chrome("Page No 页码\n60 (116)", 58, 116),
            60,
        )
        self.assertEqual(
            _printed_page_from_chrome("Page No 78 (116)", 80, 116),
            78,
        )
        self.assertEqual(
            _printed_page_from_chrome("第 78 页", 76, 116),
            78,
        )
        self.assertEqual(
            _printed_page_from_chrome("60 / 116", 58, 116),
            60,
        )
        self.assertIsNone(_printed_page_from_chrome("18 (21)", 60, 110))

    def test_toc_like_page_needs_trailing_page_numbers(self) -> None:
        from electrical.read_doc import _is_mupdf_toc_page

        toc = "\n".join(
            [
                "Contents",
                "1. General information概述信息 4",
                "2.3 Attributes requirements 属性要求 21",
                "2.4 Service and spare parts 29",
                "6.5 PEI requirements逆变器要求 52",
                "6.6 Generic generation 60",
                "11.2 Logistics物流 102",
            ]
        )
        mixed = (
            "6.13 ELECTRICAL SAFETY电气安全 82\n"
            "11.2 Logistics物流 102\n"
            "General information概述信息\n"
            "This document defines the technical parameters of the electronic "
            "control system DHT160S used in the dedicated transmission for "
            "passenger vehicle hybridization (DHT).\n"
            "本文档定义了乘用车混动专用变速箱（DHT）使用的电控系统DHT160S的技术参数。"
        )
        body = (
            "The XCM shall be able to boost the HV input voltage to a higher "
            "voltage in order to improve the TM performance when HVDC input "
            "voltage is low.\n"
            "当高压直流输入电压较低时，控制器应能够将直流输入的电压提升到更高电压。"
        )
        self.assertTrue(_is_mupdf_toc_page(toc))
        self.assertFalse(_is_mupdf_toc_page(mixed))
        self.assertFalse(_is_mupdf_toc_page(body))

    def test_dhts_boost_and_weight_match_header_pages(self) -> None:
        from electrical.read_doc import _docx_markdown_in_order

        root = Path(__file__).resolve().parents[2]
        candidates = [
            root
            / "资料"
            / "电控开发部Agent开发第一阶段需求-2.7z"
            / "DHTS160 DPR.docx",
            root
            / "electrical-krow"
            / "output"
            / "uploads"
            / "35d69798_DHTS160_DPR.docx",
        ]
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            self.skipTest("DHTS160 DPR is not in the local uploads folder")
        md = _docx_markdown_in_order(path)
        self.assertIn("weight of the XCM shall be less than 20.2kg", md)
        self.assertIn("The XCM shall be able to boost the HV input voltage", md)
        self.assertIn("控制器高压回路与地之间（外壳）绝缘电阻", md)
        self.assertIn("2.3.1 Weight", md)
        self.assertIn("6.5.3 HVDC Voltage Range", md)
        self.assertIn("6.5.4 HV Booster", md)
        if "## 第 " not in md:
            return

        def page_of(needle: str) -> int:
            at = md.find(needle)
            self.assertGreaterEqual(at, 0, needle)
            markers = list(re.finditer(r"## 第 (\d+) 页", md[: at + 1]))
            self.assertTrue(markers, needle)
            return int(markers[-1].group(1))

        self.assertGreaterEqual(page_of("weight of the XCM shall be less than 20.2kg"), 21)
        self.assertLessEqual(page_of("weight of the XCM shall be less than 20.2kg"), 25)
        self.assertGreaterEqual(page_of("The XCM shall be able to boost the HV input voltage"), 52)
        self.assertLessEqual(page_of("The XCM shall be able to boost the HV input voltage"), 56)
        insulation = page_of("控制器高压回路与地之间（外壳）绝缘电阻")
        self.assertGreaterEqual(insulation, 64)
        self.assertLessEqual(insulation, 70)

    def test_docx_without_word_does_not_use_toc_as_printed_page(self) -> None:
        from unittest.mock import patch

        from electrical.read_doc import _pages_from_printed_docx

        events = [("heading", "6.5 PEI requirements逆变器要求 extra", 2, None)]
        with (
            patch("electrical.read_doc._pages_from_word_app", return_value=None),
            patch("electrical.read_doc._sidecar_pdf", return_value=None),
        ):
            self.assertIsNone(_pages_from_printed_docx(Path("dummy.docx"), events))

    def test_docx_skips_pages_without_word_or_pdf(self) -> None:
        from unittest.mock import patch

        from electrical.read_doc import _pages_from_printed_docx

        events = [("para", "hello world " * 20, 0, None)]
        with patch("electrical.read_doc._pages_from_word_app", return_value=None):
            self.assertIsNone(_pages_from_printed_docx(Path("missing.docx"), events))

    def test_carry_printed_pages_does_not_interpolate(self) -> None:
        from electrical.read_doc import _carry_printed_pages

        self.assertEqual(_carry_printed_pages([23, 0, 60, 78]), [23, 23, 60, 78])
        self.assertEqual(_carry_printed_pages([0, 0, 78, 0]), [78, 78, 78, 78])

    def test_align_events_to_word_pages_reads_printed_page(self) -> None:
        from unittest.mock import patch

        from electrical.read_doc import (
            _align_events_to_word_pages,
            _pages_from_word_app,
        )

        events = [
            (
                "para",
                "weight of the XCM shall be less than 20.2kg including coolant fluid.",
                0,
                None,
            ),
            ("table", ["| a | b |\n| 1 | 2 |"], 2, None),
            (
                "para",
                "The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve.",
                0,
                None,
            ),
            (
                "para",
                "控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧，测试电压1000VDC。",
                0,
                None,
            ),
        ]
        paras = [
            ("cover sheet text that is long enough to keep", 1),
            ("weight of the XCM shall be less than 20.2kg including coolant fluid", 23),
            *[(f"table cell value {index:03d} padding text", 40) for index in range(80)],
            (
                "The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve the TM",
                60,
            ),
            ("控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧，测试电压1000VDC", 78),
        ]
        self.assertEqual(_align_events_to_word_pages(events, paras), [23, 0, 60, 78])
        self.assertEqual(
            _align_events_to_word_pages(events, paras, fill_unmatched=True),
            [23, 40, 60, 78],
        )
        with patch("electrical.read_doc._office_paragraph_pages", return_value=paras):
            pages = _pages_from_word_app(Path("dummy.docx"), events)
        self.assertEqual(pages, [23, 40, 60, 78])

    def test_align_word_pages_ignores_restored_outline_prefix(self) -> None:
        from electrical.read_doc import _align_events_to_word_pages

        events = [
            (
                "heading",
                "2.3.1 Weight重量 The weight of the XCM shall be less than 20.2kg including coolant.",
                3,
                None,
            ),
            (
                "heading",
                "6.5.3 HVDC Voltage Range 高压范围 Min level during cold ICE start 160",
                3,
                None,
            ),
            (
                "para",
                "The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve.",
                0,
                None,
            ),
            (
                "para",
                "控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧，测试电压1000VDC。",
                0,
                None,
            ),
        ]
        paras = [
            (
                "Weight重量 The weight of the XCM shall be less than 20.2kg including coolant.",
                23,
            ),
            (
                "HVDC Voltage Range 高压范围 Min level during cold ICE start 160",
                53,
            ),
            (
                "The XCM shall be able to boost the HV input voltage to a higher voltage in order to improve the TM",
                54,
            ),
            ("控制器高压回路与地之间（外壳）绝缘电阻应当不小于48兆欧，测试电压1000VDC", 67),
        ]
        self.assertEqual(_align_events_to_word_pages(events, paras), [23, 53, 54, 67])

    def test_docx_uses_sidecar_pdf(self) -> None:
        import tempfile
        from unittest.mock import patch

        from electrical.read_doc import _pages_from_printed_docx

        events = [("para", "hello world " * 20, 0, None)]
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "spec.docx"
            src.write_bytes(b"fake-docx-bytes")
            (src.with_suffix(".pdf")).write_bytes(b"%PDF-1.4\n" + b"x" * 2000)
            with (
                patch("electrical.read_doc._pages_from_pdf_file", return_value=[23]) as from_pdf,
                patch("electrical.read_doc._pages_from_word_app", return_value=None),
            ):
                pages = _pages_from_printed_docx(src, events)
        self.assertEqual(pages, [23])
        from_pdf.assert_called_once()

    def test_prefers_word_app_over_sidecar_pdf(self) -> None:
        from unittest.mock import patch

        from electrical.read_doc import _pages_from_printed_docx

        events = [("para", "hello world " * 20, 0, None)]
        with (
            patch("electrical.read_doc._pages_from_word_app", return_value=[23, 60, 78]) as word,
            patch("electrical.read_doc._pages_from_pdf_file") as from_pdf,
        ):
            pages = _pages_from_printed_docx(Path("missing.docx"), events)
        self.assertEqual(pages, [23, 60, 78])
        word.assert_called_once()
        from_pdf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
