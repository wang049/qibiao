from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from electrical_krow.config import load_settings
from electrical_krow.gateway import prepare_page_vision
from electrical_krow.login import AuthSession
from electrical_krow.session import StoredSession
from electrical_krow.vision import (
    image_chat_messages,
    is_text_chat_model,
    message_has_image,
    pick_vision_model,
    sample_probe_png,
)


class VisionPickTests(unittest.TestCase):
    def test_text_chat_models(self) -> None:
        self.assertTrue(is_text_chat_model("deepseek-v4-pro"))
        self.assertTrue(is_text_chat_model("ZHIPU/GLM-5.2"))
        self.assertTrue(is_text_chat_model("glm-5.2"))
        self.assertFalse(is_text_chat_model("krow-ocr-table"))
        self.assertFalse(is_text_chat_model("qwen2.5-vl"))

    def test_skips_text_chat_and_prefers_ocr_table(self) -> None:
        names = ["deepseek-v4-pro", "ZHIPU/GLM-5.2", "krow-ocr-table", "qwen2.5-vl"]
        self.assertEqual(pick_vision_model(names), "krow-ocr-table")
        self.assertEqual(
            pick_vision_model(names, preferred="deepseek-v4-pro"),
            "krow-ocr-table",
        )
        self.assertEqual(pick_vision_model(["qwen2.5-vl", "foo-ocr"]), "qwen2.5-vl")

    def test_preferred_vision_used_when_listed(self) -> None:
        self.assertEqual(
            pick_vision_model(["krow-ocr-table", "qwen2.5-vl"], preferred="qwen2.5-vl"),
            "qwen2.5-vl",
        )

    def test_empty_when_only_text_chat(self) -> None:
        self.assertEqual(pick_vision_model(["deepseek-v4-pro", "GLM-5.2"]), "")

    def test_image_payload_shape(self) -> None:
        messages = image_chat_messages(b"png-bytes", "image/png", "读图")
        content = messages[0]["content"]
        self.assertTrue(message_has_image(content))
        self.assertTrue(message_has_image(messages))
        url = content[1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))

    def test_sample_probe_png_decodes(self) -> None:
        raw = sample_probe_png()
        self.assertGreater(len(raw), 32)
        self.assertTrue(raw.startswith(b"\x89PNG"))


class PreparePageVisionTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("SPEC_SHEET_PAGE_VISION", None)
        os.environ.pop("SPEC_SHEET_VISION_MODEL", None)

    def test_cloud_disables_page_vision(self) -> None:
        settings = load_settings(
            server_url="https://api.krow.cn",
            vision_model="krow-ocr-table",
        )
        session = AuthSession(access_token="tok", username="demo", source="password")
        stored = StoredSession(sid="sid", auth=session)
        with patch(
            "electrical_krow.gateway.list_models",
            return_value=["deepseek-v4-pro", "krow-ocr-table"],
        ) as listed:
            vision = prepare_page_vision(settings, stored)
        listed.assert_not_called()
        self.assertEqual(vision, "")
        self.assertEqual(os.environ.get("SPEC_SHEET_PAGE_VISION"), "0")
        self.assertIsNone(os.environ.get("SPEC_SHEET_VISION_MODEL"))

    def test_site_picks_ocr_table(self) -> None:
        settings = load_settings(
            server_url="https://rdapi.aurobaytech-t.com",
            chat_model="deepseek-v4-pro",
            vision_model="",
        )
        session = AuthSession(access_token="tok", username="demo", source="password")
        stored = StoredSession(sid="sid", auth=session)
        with patch(
            "electrical_krow.gateway.list_models",
            return_value=["deepseek-v4-pro", "ZHIPU/GLM-5.2", "krow-ocr-table"],
        ):
            vision = prepare_page_vision(settings, stored)
        self.assertEqual(vision, "krow-ocr-table")
        self.assertEqual(os.environ.get("SPEC_SHEET_PAGE_VISION"), "1")
        self.assertEqual(os.environ.get("SPEC_SHEET_VISION_MODEL"), "krow-ocr-table")


if __name__ == "__main__":
    unittest.main()
