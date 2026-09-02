from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrical_krow.config import (
    load_settings,
    normalize_delivery,
    origin_of,
    require_gateway_bind,
    require_private_endpoint,
    suggest_site_api_url,
)
from electrical_krow.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_loopback_ok(self) -> None:
        self.assertEqual(
            require_private_endpoint("http://127.0.0.1:18766/v1"),
            "http://127.0.0.1:18766",
        )

    def test_cloud_ok(self) -> None:
        self.assertEqual(
            require_private_endpoint("https://api.krow.cn"),
            "https://api.krow.cn",
        )
        self.assertEqual(
            require_private_endpoint("https://api-staging.krow.cn/v1"),
            "https://api-staging.krow.cn",
        )

    def test_site_rdapi_strips_v1(self) -> None:
        self.assertEqual(
            origin_of("https://rdapi.aurobaytech-t.com/v1"),
            "https://rdapi.aurobaytech-t.com",
        )

    def test_allows_page_images_site_not_public(self) -> None:
        from electrical_krow.config import allows_page_images

        self.assertFalse(allows_page_images("https://api.krow.cn"))
        self.assertFalse(allows_page_images("https://api-staging.krow.cn/v1"))
        self.assertTrue(allows_page_images("https://rdapi.aurobaytech-t.com"))
        self.assertTrue(allows_page_images("http://127.0.0.1:18766"))
        self.assertTrue(allows_page_images("http://localhost:18766/v1"))

    def test_suggest_site_api_url(self) -> None:
        self.assertEqual(
            suggest_site_api_url("https://rdweb.aurobaytech-t.com"),
            "https://rdapi.aurobaytech-t.com",
        )
        self.assertEqual(
            suggest_site_api_url("https://rdagents.aurobaytech-t.com"),
            "https://rdapi.aurobaytech-t.com",
        )
        self.assertEqual(
            suggest_site_api_url("https://api.rdagents.aurobaytech-t.com"),
            "https://rdapi.aurobaytech-t.com",
        )
        self.assertIsNone(suggest_site_api_url("https://rdapi.aurobaytech-t.com"))

    def test_load_defaults(self) -> None:
        s = load_settings()
        self.assertEqual(s.gateway_host, "127.0.0.1")
        self.assertEqual(s.gateway_port, 18765)
        self.assertEqual(s.delivery, "client")
        self.assertEqual(s.vision_model, "")

    def test_load_from_ini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.ini"
            path.write_text(
                "[krow]\n"
                "server_url = https://example.krow.local\n"
                "chat_model = demo-model\n"
                "timeout_sec = 90\n"
                "delivery = site\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"ELECTRICAL_KROW_CONFIG": str(path)}):
                os.environ.pop("KROW_SERVER_URL", None)
                os.environ.pop("KROW_CHAT_MODEL", None)
                os.environ.pop("KROW_LLM_TIMEOUT", None)
                os.environ.pop("KROW_DELIVERY", None)
                s = load_settings()
            self.assertEqual(s.server_url, "https://example.krow.local")
            self.assertEqual(s.chat_model, "demo-model")
            self.assertEqual(s.timeout_sec, 90.0)
            self.assertEqual(s.delivery, "site")

    def test_load_from_ini_with_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.ini"
            path.write_bytes(
                b"\xef\xbb\xbf[krow]\n"
                b"server_url = https://bom.krow.local\n"
                b"chat_model = bom-model\n"
            )
            extra = {
                "ELECTRICAL_KROW_CONFIG": str(path),
                "KROW_SERVER_URL": "",
                "KROW_CHAT_MODEL": "",
            }
            with patch.dict(os.environ, extra, clear=False):
                os.environ.pop("KROW_SERVER_URL", None)
                os.environ.pop("KROW_CHAT_MODEL", None)
                s = load_settings()
            self.assertEqual(s.server_url, "https://bom.krow.local")
            self.assertEqual(s.chat_model, "bom-model")

    def test_delivery_aliases(self) -> None:
        self.assertEqual(normalize_delivery("web"), "site")
        self.assertEqual(normalize_delivery("desktop"), "client")
        with self.assertRaises(ConfigError):
            normalize_delivery("public")

    def test_gateway_bind_client_loopback_only(self) -> None:
        self.assertEqual(require_gateway_bind("127.0.0.1", "client"), "127.0.0.1")
        with self.assertRaises(ConfigError):
            require_gateway_bind("0.0.0.0", "client")
        with self.assertRaises(ConfigError):
            require_gateway_bind("192.168.1.10", "client")

    def test_gateway_bind_site_allows_loopback_and_lan(self) -> None:
        self.assertEqual(require_gateway_bind("127.0.0.1", "site"), "127.0.0.1")
        self.assertEqual(require_gateway_bind("0.0.0.0", "site"), "0.0.0.0")
        self.assertEqual(require_gateway_bind("10.0.0.8", "site"), "10.0.0.8")
        with self.assertRaises(ConfigError):
            require_gateway_bind("8.8.8.8", "site")

    def test_macos_client_forces_cloud_api(self) -> None:
        from electrical_krow.config import apply_macos_client_server

        extra = {
            "KROW_SERVER_URL": "https://rdapi.aurobaytech-t.com",
            "KROW_DELIVERY": "client",
        }
        with patch.dict(os.environ, extra, clear=False):
            with patch("electrical_krow.config.sys.platform", "darwin"):
                apply_macos_client_server()
                self.assertEqual(os.environ.get("KROW_SERVER_URL"), "https://api.krow.cn")


if __name__ == "__main__":
    unittest.main()
