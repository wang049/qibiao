from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from electrical_krow.config import load_settings
from electrical_krow.login import AuthSession
from electrical_krow.ocr import (
    decode_image_payload,
    ocr_endpoint_available,
    prepare_page_ocr,
    recognize_page,
)
from electrical_krow.session import StoredSession


class DecodeImageTests(unittest.TestCase):
    def test_data_url_and_raw_b64(self) -> None:
        raw = decode_image_payload("data:image/jpeg;base64,aGVsbG8=")
        self.assertEqual(raw, b"hello")
        self.assertEqual(decode_image_payload("aGVsbG8="), b"hello")
        with self.assertRaises(ValueError):
            decode_image_payload("")


class PreparePageOcrTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("SPEC_SHEET_PAGE_OCR", None)
        os.environ.pop("SPEC_SHEET_OCR_TASK", None)

    def test_cloud_enables_when_endpoint_exists(self) -> None:
        settings = load_settings(server_url="https://api.krow.cn")
        stored = StoredSession(
            sid="sid",
            auth=AuthSession(access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa", username="demo"),
        )
        with patch("electrical_krow.ocr.ocr_endpoint_available", return_value=True):
            self.assertTrue(prepare_page_ocr(settings, stored))
        self.assertEqual(os.environ.get("SPEC_SHEET_PAGE_OCR"), "1")
        self.assertEqual(os.environ.get("SPEC_SHEET_OCR_TASK"), "table")

    def test_missing_endpoint_disables(self) -> None:
        settings = load_settings(server_url="https://rdapi.aurobaytech-t.com")
        stored = StoredSession(
            sid="sid",
            auth=AuthSession(access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa", username="demo"),
        )
        with patch("electrical_krow.ocr.ocr_endpoint_available", return_value=False):
            self.assertFalse(prepare_page_ocr(settings, stored))
        self.assertEqual(os.environ.get("SPEC_SHEET_PAGE_OCR"), "0")


class OcrEndpointProbeTests(unittest.TestCase):
    def test_404_means_unavailable(self) -> None:
        session = AuthSession(access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa", username="demo")

        class FakeResp:
            status_code = 404
            text = "no"

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def post(self, *_a, **_k):
                return FakeResp()

        with patch("httpx.Client", FakeClient):
            self.assertFalse(
                ocr_endpoint_available("https://rdapi.aurobaytech-t.com", session)
            )

    def test_400_means_route_exists(self) -> None:
        session = AuthSession(access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa", username="demo")

        class FakeResp:
            status_code = 400
            text = "need image"

        class FakeClient:
            def __init__(self, **_kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

            def post(self, *_a, **_k):
                return FakeResp()

        with patch("httpx.Client", FakeClient):
            self.assertTrue(ocr_endpoint_available("https://api.krow.cn", session))


class RecognizePageTests(unittest.TestCase):
    def test_http_fallback_posts_data_url(self) -> None:
        session = AuthSession(access_token="sk-user-aaaaaaaaaaaaaaaaaaaaaaaa", username="demo")
        captured: dict[str, object] = {}

        class FakeResp:
            status_code = 200

            def json(self) -> dict:
                return {"success": True, "text": "HVDC 380"}

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

        with patch("electrical_krow.ocr._recognize_via_sdk", side_effect=ImportError):
            with patch("httpx.Client", FakeClient):
                out = recognize_page(
                    "https://api.krow.cn",
                    session,
                    b"jpeg-bytes",
                    task="table",
                )
        self.assertTrue(out["success"])
        self.assertIn("380", out["text"])
        self.assertEqual(captured["url"], "https://api.krow.cn/v1/ocr")
        payload = captured["json"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["task"], "table")
        self.assertTrue(str(payload["image"]).startswith("data:image/jpeg;base64,"))


if __name__ == "__main__":
    unittest.main()
