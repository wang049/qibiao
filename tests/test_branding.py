from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from electrical_krow.branding import (
    DOCK_APP_NAME,
    TITLE,
    handoff_macos_app,
    icon_arg,
    icon_file,
    install_macos_app_bundle,
    runtime_python,
    should_handoff_macos_app,
)


class BrandingTests(unittest.TestCase):
    def test_tests_do_not_handoff_to_app_bundle(self) -> None:
        self.assertFalse(should_handoff_macos_app())
        self.assertFalse(handoff_macos_app([]))

    def test_macos_handoff_reuses_one_app_instance(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))

            class Result:
                returncode = 0

            return Result()

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch("electrical_krow.branding.runtime_python", return_value=sys.executable):
                with patch("electrical_krow.branding.should_handoff_macos_app", return_value=True):
                    with patch("electrical_krow.branding.macos_app_dir", return_value=root / f"{DOCK_APP_NAME}.app"):
                        with patch("electrical_krow.branding.macos_client_app_paths", return_value=[]):
                            with patch("electrical_krow.branding.subprocess.run", side_effect=fake_run):
                                self.assertTrue(handoff_macos_app(["--port", "18765"]))
        open_calls = [cmd for cmd in calls if cmd and cmd[0] == "open"]
        self.assertEqual(len(open_calls), 1)
        self.assertEqual(open_calls[0][0], "open")
        self.assertTrue(str(open_calls[0][1]).endswith(f"{DOCK_APP_NAME}.app"))
        self.assertNotIn("-n", open_calls[0])

    def test_window_title_is_agent_name(self) -> None:
        self.assertEqual(TITLE, "电子电器智能体")
        self.assertEqual(DOCK_APP_NAME, "电子电器智能体")

    def test_icon_files_exist(self) -> None:
        path = icon_file()
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertIsNotNone(icon_arg())

    def test_runtime_python_respects_override(self) -> None:
        with patch.dict(os.environ, {"ELECTRICAL_KROW_PYTHON": "/tmp/custom-python"}):
            self.assertEqual(runtime_python(), "/tmp/custom-python")

    def test_installs_macos_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch("electrical_krow.branding.runtime_python", return_value=sys.executable):
                app = install_macos_app_bundle(argv=["--port", "18765"], root=root)
            self.assertEqual(app.name, f"{DOCK_APP_NAME}.app")
            plist = (app / "Contents" / "Info.plist").read_text(encoding="utf-8")
            self.assertIn(TITLE, plist)
            self.assertIn("cn.electrical.krow.sorfill", plist)
            exe = app / "Contents" / "MacOS" / "ElectricalKrow"
            self.assertTrue(os.access(exe, os.X_OK))
            payload = json.loads(
                (app / "Contents" / "Resources" / "launch.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["argv"], ["--port", "18765"])
            self.assertEqual(payload["env"]["ELECTRICAL_KROW_BUNDLED"], "1")
            self.assertIn("site-packages", payload["env"]["PYTHONPATH"])
            self.assertEqual(payload["python"], os.path.abspath(sys.executable))
            self.assertTrue((app / "Contents" / "Resources" / "launch.py").is_file())
            copied = list((app / "Contents" / "Resources").glob("AppIcon.*"))
            self.assertTrue(copied, "bundle should include the app icon")

    def test_macos_client_launch_uses_cloud_api(self) -> None:
        extra = {
            "KROW_SERVER_URL": "https://rdapi.aurobaytech-t.com",
            "KROW_DELIVERY": "client",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.dict(os.environ, extra, clear=False):
                with patch(
                    "electrical_krow.branding.runtime_python",
                    return_value=sys.executable,
                ):
                    with patch("electrical_krow.branding.sys.platform", "darwin"):
                        app = install_macos_app_bundle(root=root)
            payload = json.loads(
                (app / "Contents" / "Resources" / "launch.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(payload["env"]["KROW_SERVER_URL"], "https://api.krow.cn")


if __name__ == "__main__":
    unittest.main()
