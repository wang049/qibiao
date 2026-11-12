"""扫描件 OCR 选页、打分与 Tesseract 路径。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from electrical.doc_kind import page_text_kind
from electrical.ocr_local import (
    _boxes_to_layout_text,
    _keep_ocr_page,
    _llm_origin_loopback,
    _ocr_text_score,
    _page_zoom,
    _run_krow_ocr,
    _run_site_page_vision,
    _tesseract_bin,
    layout_ocr_text,
    ocr_image,
    ocr_pdf_pages,
    scan_image_pages,
)


class OcrScoreTests(unittest.TestCase):
    def test_param_page_scores_higher_than_garbage(self) -> None:
        good = "直流工作电压 350 Vdc，峰值功率 120 kW，额定扭矩 280 N·m"
        bad = "i# th#Hi#E&E I)#H#R#4E ####"
        self.assertGreater(_ocr_text_score(good), _ocr_text_score(bad))

    def test_keep_short_param_page(self) -> None:
        text = "峰值功率 120 kW 额定扭矩 280 N·m 主动放电 2 s"
        self.assertTrue(_keep_ocr_page(text))
        self.assertFalse(_keep_ocr_page(""))
        self.assertTrue(_keep_ocr_page("HVDC bus voltage 380 V inverter asil D coolant"))
        self.assertFalse(
            _keep_ocr_page(
                "目录\n规范性引用文件\n修订记录\n标准清单\n1 范围 ........ 1\n2 引用 ........ 2"
            )
        )

    def test_page_zoom_is_bounded(self) -> None:
        page = SimpleNamespace(rect=SimpleNamespace(width=595.0, height=842.0))
        zoom = _page_zoom(page)
        self.assertGreaterEqual(zoom, 1.8)
        self.assertLessEqual(zoom, 2.8)


class TesseractPathTests(unittest.TestCase):
    def test_windows_program_files_fallback(self) -> None:
        fake = Path("/tmp/Tesseract-OCR/tesseract.exe")
        with patch("electrical.ocr_local.sys.platform", "win32"):
            with patch("electrical.ocr_local.which", create=True):
                with patch("shutil.which", return_value=None):
                    with patch.dict(
                        os.environ,
                        {"PROGRAMFILES": str(fake.parent.parent)},
                        clear=False,
                    ):
                        with patch.object(Path, "is_file", return_value=True):
                            found = _tesseract_bin()
        self.assertTrue(found)
        self.assertTrue(str(found).endswith("tesseract.exe"))


class ScanPageSelectTests(unittest.TestCase):
    def test_sparse_text_without_xobject_still_selected(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "scan.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "4LDHT260 DPR")
            doc.save(str(path))
            doc.close()
            pages = scan_image_pages(path, 1)
        self.assertEqual(pages, [1])

    def test_does_not_drop_early_param_pages_when_capped(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "long-scan.pdf"
            doc = fitz.open()
            for i in range(15):
                page = doc.new_page()
                page.insert_text((72, 72), f"page {i + 1}")
            doc.save(str(path))
            doc.close()
            with patch("electrical.ocr_local.MAX_SCAN_OCR_PAGES", 6):
                pages = scan_image_pages(path, 15)
        self.assertEqual(pages[0], 2)
        self.assertIn(3, pages)
        self.assertIn(5, pages)
        self.assertNotIn(1, pages)


class ParallelOcrTests(unittest.TestCase):
    def test_ocr_pdf_pages_covers_all(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("need pymupdf")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "scan.pdf"
            doc = fitz.open()
            for i in range(3):
                page = doc.new_page()
                page.insert_text((72, 72), f"page {i + 1}")
            doc.save(str(path))
            doc.close()
            seen: list[str] = []

            def fake_ocr(image_path: Path) -> str:
                seen.append(str(image_path))
                return "HVDC bus voltage 380 Vdc peak 80 kW asil D coolant"

            with patch("electrical.ocr_local.ocr_image", side_effect=fake_ocr):
                with patch("electrical.ocr_local._ocr_workers", return_value=3):
                    out = ocr_pdf_pages(path, [1, 2, 3])
        self.assertEqual(set(out), {1, 2, 3})
        self.assertEqual(len(seen), 3)


class TocKindRegressionTests(unittest.TestCase):
    def test_native_toc_still_toc(self) -> None:
        text = """
        目 录
        1 范围 ................ 1
        2 规范性引用文件 .......... 2
        3 术语和定义 .............. 3
        引用标准清单
        GB/T 18488
        """
        self.assertEqual(page_text_kind(text), "toc")

    def test_ocr_param_page_not_toc_because_of_header(self) -> None:
        text = """
        [本页为本机 OCR]
        HORSE
        Document Name
        4LDHT260 PCM DESIGN PREREQUISITES
        63 (110)
        6.5.1 LVDC Voltage Range
        The PCM voltage range according to ISO 16750-2:CodeA(6~16V)
        HVDC bus voltage min 380 V full power 945 V
        fulfill ASIL D according to ISO 26262
        """
        self.assertEqual(page_text_kind(text), "param")

    def test_layout_ocr_joins_bilingual_row(self) -> None:
        raw = "\n".join(
            [
                "0.40\t0.08\t主动放电",
                "0.41\t0.52\tActive discharge shall be completed within 1s",
                "0.55\t0.08\t母线电压 945 V",
            ]
        )
        text = layout_ocr_text(raw)
        self.assertIn("主动放电", text)
        self.assertIn("Active discharge", text.split("主动放电", 1)[-1][:80])
        self.assertIn("母线电压 945 V", text)

    def test_layout_ocr_plain_text_fallback(self) -> None:
        self.assertIn("HVDC 400 V", layout_ocr_text("HVDC 400 V\nASIL D"))
        self.assertIn("Ω", layout_ocr_text("R Insulation ≥2.5₺"))

    def test_layout_ocr_strips_cyrillic_noise(self) -> None:
        cleaned = layout_ocr_text("HVDC 380 V  ###  ПРИВЕТ  满功率 640 V")
        self.assertIn("HVDC 380 V", cleaned)
        self.assertIn("640", cleaned)
        self.assertNotIn("ПРИВЕТ", cleaned)

    def test_boxes_layout_keeps_bilingual_row(self) -> None:
        boxes = [
            [[10, 10], [120, 10], [120, 24], [10, 24]],
            [[200, 10], [320, 10], [320, 24], [200, 24]],
            [[10, 40], [180, 40], [180, 54], [10, 54]],
            [[200, 40], [360, 40], [360, 54], [200, 54]],
            [[400, 40], [440, 40], [440, 54], [400, 54]],
        ]
        txts = [
            "HVDC Voltage Range",
            "高压范围",
            "Min level for limited performance",
            "性能限制时的最低电压",
            "380",
        ]
        text = _boxes_to_layout_text(boxes, txts)
        self.assertIn("HVDC Voltage Range", text)
        self.assertIn("高压范围", text)
        row = next(line for line in text.splitlines() if "limited" in line)
        self.assertIn("性能限制时的最低电压", row)
        self.assertIn("380", row)
        self.assertNotIn("Range高压", text)


class VisionHelperArchTests(unittest.TestCase):
    def test_x86_helper_rejected_on_apple_silicon(self) -> None:
        from electrical.ocr_local import _helper_usable

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"x" * 50_368)
            path = Path(handle.name)
        try:
            with patch("electrical.ocr_local._apple_silicon", return_value=True):
                with patch(
                    "electrical.ocr_local.subprocess.check_output",
                    return_value="Mach-O 64-bit executable x86_64\n",
                ):
                    self.assertFalse(_helper_usable(path))
                with patch(
                    "electrical.ocr_local.subprocess.check_output",
                    return_value="Mach-O 64-bit executable arm64\n",
                ):
                    self.assertTrue(_helper_usable(path))
        finally:
            path.unlink(missing_ok=True)


class SitePageVisionTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "SPEC_SHEET_PAGE_VISION",
            "SPEC_SHEET_VISION_MODEL",
            "SPEC_SHEET_LLM_URL",
        ):
            os.environ.pop(key, None)

    def test_rejects_non_loopback_llm_url(self) -> None:
        os.environ["SPEC_SHEET_LLM_URL"] = "https://rdapi.aurobaytech-t.com"
        self.assertEqual(_llm_origin_loopback(), "")
        os.environ["SPEC_SHEET_LLM_URL"] = "https://api.krow.cn"
        self.assertEqual(_llm_origin_loopback(), "")
        os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765/v1"
        self.assertEqual(_llm_origin_loopback(), "http://127.0.0.1:18765")

    def test_skips_when_flag_off(self) -> None:
        os.environ["SPEC_SHEET_PAGE_VISION"] = "0"
        os.environ["SPEC_SHEET_VISION_MODEL"] = "krow-ocr-table"
        os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
        self.assertEqual(_run_site_page_vision(Path("/tmp/missing.png")), "")

    def test_posts_image_url_to_loopback_gateway(self) -> None:
        captured: dict[str, object] = {}

        class FakeResp:
            status_code = 200

            def json(self) -> dict:
                return {
                    "choices": [
                        {"message": {"content": "HVDC bus voltage 380 V"}}
                    ]
                }

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return FakeResp()

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "page.png"
            try:
                from PIL import Image
            except ImportError:
                self.skipTest("need pillow")
            Image.new("RGB", (80, 40), "white").save(path)
            os.environ["SPEC_SHEET_PAGE_VISION"] = "1"
            os.environ["SPEC_SHEET_VISION_MODEL"] = "krow-ocr-table"
            os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
            with patch("httpx.Client", FakeClient):
                text = _run_site_page_vision(path)
        self.assertIn("380", text)
        self.assertEqual(captured["url"], "http://127.0.0.1:18765/v1/chat/completions")
        payload = captured["json"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["model"], "krow-ocr-table")
        content = payload["messages"][0]["content"]
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(
            str(content[1]["image_url"]["url"]).startswith("data:image/jpeg;base64,")
        )
        headers = captured["headers"]
        assert isinstance(headers, dict)
        self.assertEqual(headers.get("Authorization"), "Bearer local")

    def test_ocr_image_uses_site_when_local_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "page.png"
            path.write_bytes(b"not-an-image")
            with patch("electrical.ocr_local._run_rapidocr", return_value=""):
                with patch("electrical.ocr_local._vision_bin", return_value=None):
                    with patch("electrical.ocr_local._tesseract_bin", return_value=None):
                        with patch(
                            "electrical.ocr_local._run_site_page_vision",
                            return_value="HVDC bus voltage 380 V",
                        ) as site:
                            text = ocr_image(path)
        self.assertIn("380", text)
        site.assert_called_once()

    def test_ocr_image_skips_site_when_rapidocr_good(self) -> None:
        good = "直流工作电压 350 Vdc，峰值功率 120 kW，额定扭矩 280 N·m 主动放电 2 s"
        with patch("electrical.ocr_local._run_rapidocr", return_value=good):
            with patch("electrical.ocr_local._run_site_page_vision") as site:
                text = ocr_image(Path("/tmp/x.png"))
        self.assertEqual(text, good)
        site.assert_not_called()


class KrowSdkOcrTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "SPEC_SHEET_PAGE_OCR",
            "SPEC_SHEET_OCR_TASK",
            "SPEC_SHEET_LLM_URL",
            "SPEC_SHEET_PAGE_VISION",
            "SPEC_SHEET_VISION_MODEL",
        ):
            os.environ.pop(key, None)

    def test_skips_when_flag_off(self) -> None:
        os.environ["SPEC_SHEET_PAGE_OCR"] = "0"
        os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
        self.assertEqual(_run_krow_ocr(Path("/tmp/missing.png")), "")

    def test_posts_to_loopback_ocr(self) -> None:
        captured: dict[str, object] = {}

        class FakeResp:
            status_code = 200

            def json(self) -> dict:
                return {"success": True, "text": "HVDC bus voltage 380 V"}

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["json"] = json
                captured["headers"] = headers
                return FakeResp()

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "page.png"
            try:
                from PIL import Image
            except ImportError:
                self.skipTest("need pillow")
            Image.new("RGB", (80, 40), "white").save(path)
            os.environ["SPEC_SHEET_PAGE_OCR"] = "1"
            os.environ["SPEC_SHEET_OCR_TASK"] = "table"
            os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
            with patch("httpx.Client", FakeClient):
                text = _run_krow_ocr(path)
        self.assertIn("380", text)
        self.assertEqual(captured["url"], "http://127.0.0.1:18765/v1/ocr")
        payload = captured["json"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["task"], "table")
        self.assertTrue(str(payload["image"]).startswith("data:image/jpeg;base64,"))

    def test_ocr_image_skips_krow_when_rapidocr_good(self) -> None:
        good = "直流工作电压 350 Vdc，峰值功率 120 kW，额定扭矩 280 N·m 主动放电 2 s"
        os.environ["SPEC_SHEET_PAGE_OCR"] = "1"
        os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
        with patch("electrical.ocr_local._run_rapidocr", return_value=good):
            with patch("electrical.ocr_local._run_krow_ocr") as krow:
                text = ocr_image(Path("/tmp/x.png"))
        self.assertEqual(text, good)
        krow.assert_not_called()

    def test_ocr_image_uses_krow_when_rapidocr_weak(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "page.png"
            path.write_bytes(b"not-an-image")
            os.environ["SPEC_SHEET_PAGE_OCR"] = "1"
            os.environ["SPEC_SHEET_LLM_URL"] = "http://127.0.0.1:18765"
            with patch("electrical.ocr_local._run_rapidocr", return_value="###"):
                with patch(
                    "electrical.ocr_local._run_krow_ocr",
                    return_value="HVDC bus voltage 380 V inverter asil D coolant 350 Vdc",
                ) as krow:
                    with patch("electrical.ocr_local._vision_bin", return_value=None):
                        with patch("electrical.ocr_local._tesseract_bin", return_value=None):
                            text = ocr_image(path)
        self.assertIn("380", text)
        krow.assert_called_once()


if __name__ == "__main__":
    unittest.main()
