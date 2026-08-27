from __future__ import annotations

import unittest

from electrical_krow.config import load_settings, require_private_endpoint
from electrical_krow.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_loopback_ok(self) -> None:
        self.assertEqual(
            require_private_endpoint("http://127.0.0.1:18766/v1"),
            "http://127.0.0.1:18766",
        )

    def test_public_cloud_blocked(self) -> None:
        with self.assertRaises(ConfigError):
            require_private_endpoint("https://api.krow.cn")
        with self.assertRaises(ConfigError):
            require_private_endpoint("https://api-staging.krow.cn")

    def test_load_defaults(self) -> None:
        s = load_settings()
        self.assertEqual(s.gateway_host, "127.0.0.1")
        self.assertEqual(s.gateway_port, 18765)


if __name__ == "__main__":
    unittest.main()
