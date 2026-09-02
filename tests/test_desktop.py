from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from electrical_krow.config import load_settings
from electrical_krow.desktop import (
    DesktopApi,
    bind_show_when_ready,
    gateway_command,
    gateway_in_thread,
    http_ok,
    main as desktop_main,
    picked_save_path,
    port_is_open,
    reap_stale_gateway,
    sheet_file,
    start_gateway,
    wait_until_open,
    wait_until_ready,
    _prepare_webview_runtime,
)


class DesktopTests(unittest.TestCase):
    def test_native_identity_helper_is_safe(self) -> None:
        from electrical_krow.desktop import _set_native_app_identity

        _set_native_app_identity()

    def test_port_is_open_false_for_unused(self) -> None:
        self.assertFalse(port_is_open("127.0.0.1", 1))

    def test_wait_until_open_times_out(self) -> None:
        self.assertFalse(wait_until_open("127.0.0.1", 1, seconds=0.05))

    def test_already_running_does_not_open_window(self) -> None:
        settings = load_settings(server_url="http://127.0.0.1:18766")
        args = SimpleNamespace(host=None, port=None, site=False, no_browser=True)
        with patch("electrical_krow.desktop.parse_gateway_argv", return_value=args):
            with patch(
                "electrical_krow.desktop.listen_from_args",
                return_value=(settings, "127.0.0.1", 18765, "http://127.0.0.1:18765"),
            ):
                with patch("electrical_krow.desktop.reap_stale_gateway"):
                    with patch("electrical_krow.desktop.port_is_open", return_value=True):
                        with patch("electrical_krow.desktop._alert") as alert:
                            with patch("electrical_krow.desktop.open_window") as window:
                                with patch("electrical_krow.desktop.start_gateway") as serve:
                                    code = desktop_main([])
        self.assertEqual(code, 0)
        alert.assert_called()
        window.assert_not_called()
        serve.assert_not_called()

    def test_site_mode_refuses_desktop_window(self) -> None:
        settings = load_settings(
            server_url="http://127.0.0.1:18766", delivery="site"
        )
        args = SimpleNamespace(host=None, port=None, site=True, no_browser=True)
        with patch("electrical_krow.desktop.parse_gateway_argv", return_value=args):
            with patch(
                "electrical_krow.desktop.listen_from_args",
                return_value=(settings, "127.0.0.1", 18765, "http://127.0.0.1:18765"),
            ):
                with patch("electrical_krow.desktop._alert") as alert:
                    with patch("electrical_krow.desktop.open_window") as window:
                        code = desktop_main([])
        self.assertEqual(code, 1)
        alert.assert_called()
        window.assert_not_called()

    def test_missing_webview_returns_error(self) -> None:
        settings = load_settings(server_url="http://127.0.0.1:18766")
        args = SimpleNamespace(host=None, port=None, site=False, no_browser=True)
        with patch("electrical_krow.desktop.parse_gateway_argv", return_value=args):
            with patch(
                "electrical_krow.desktop.listen_from_args",
                return_value=(settings, "127.0.0.1", 18765, "http://127.0.0.1:18765"),
            ):
                with patch("electrical_krow.desktop.port_is_open", return_value=False):
                    with patch("electrical_krow.desktop.reap_stale_gateway"):
                        with patch(
                            "electrical_krow.desktop.webview_installed",
                            return_value=False,
                        ):
                            with patch("electrical_krow.desktop._alert") as alert:
                                with patch("electrical_krow.desktop.start_gateway") as serve:
                                    code = desktop_main([])
        self.assertEqual(code, 1)
        alert.assert_called()
        serve.assert_not_called()

    def test_sheet_file_rejects_traversal(self) -> None:
        self.assertIsNone(sheet_file("../secret.xlsx"))
        self.assertIsNone(sheet_file("not-excel.txt"))
        self.assertIsNone(sheet_file(""))

    def test_picked_save_path_accepts_macos_string(self) -> None:
        dest = picked_save_path(
            "/Users/wwj/Desktop/demo_核对表.xlsx",
            default_name="demo_核对表.xlsx",
        )
        self.assertEqual(dest, Path("/Users/wwj/Desktop/demo_核对表.xlsx"))
        listed = picked_save_path(
            ["/tmp/out.xlsx"], default_name="demo_核对表.xlsx"
        )
        self.assertEqual(listed, Path("/tmp/out.xlsx"))
        self.assertIsNone(picked_save_path("/", default_name="demo_核对表.xlsx"))
        self.assertIsNone(picked_save_path(None, default_name="demo_核对表.xlsx"))

    def test_save_sheet_copies_and_can_cancel(self) -> None:
        api = DesktopApi()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            src = root / "demo_核对表.xlsx"
            src.write_bytes(b"xlsx")
            dest = root / "saved.xlsx"
            mac = root / "mac.xlsx"
            with patch("electrical_krow.desktop.OUTPUT_DIR", root):
                self.assertEqual(sheet_file("demo_核对表.xlsx"), src.resolve())
                api.window = None
                missed = api.save_sheet("demo_核对表.xlsx")
                self.assertFalse(missed["ok"])
                api.window = SimpleNamespace(create_file_dialog=lambda *a, **k: None)
                canceled = api.save_sheet("demo_核对表.xlsx")
                self.assertTrue(canceled["canceled"])
                api.window = SimpleNamespace(
                    create_file_dialog=lambda *a, **k: [str(dest)]
                )
                with patch("electrical_krow.desktop._load_webview") as load:
                    load.return_value = SimpleNamespace(FileDialog=SimpleNamespace(SAVE=30))
                    with patch("electrical_krow.desktop.reveal_file"):
                        out = api.save_sheet("demo_核对表.xlsx")
                self.assertTrue(out["ok"])
                self.assertTrue(dest.is_file())
                self.assertEqual(dest.read_bytes(), b"xlsx")
                api.window = SimpleNamespace(
                    create_file_dialog=lambda *a, **k: str(mac)
                )
                with patch("electrical_krow.desktop._load_webview") as load:
                    load.return_value = SimpleNamespace(FileDialog=SimpleNamespace(SAVE=30))
                    with patch("electrical_krow.desktop.reveal_file"):
                        mac_out = api.save_sheet("demo_核对表.xlsx")
                self.assertTrue(mac_out["ok"], mac_out)
                self.assertTrue(mac.is_file())

    def test_wait_until_ready_needs_http(self) -> None:
        with patch("electrical_krow.desktop.http_ok", return_value=True):
            self.assertTrue(
                wait_until_ready("127.0.0.1", 1, "http://127.0.0.1:1", seconds=0.2)
            )
        with patch("electrical_krow.desktop.http_ok", return_value=False):
            self.assertFalse(
                wait_until_ready("127.0.0.1", 1, "http://127.0.0.1:1", seconds=0.05)
            )

    def test_http_ok_reads_status(self) -> None:
        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("urllib.request.urlopen", return_value=Resp()):
            self.assertTrue(http_ok("http://127.0.0.1/health"))

    def test_bind_show_when_ready_shows_once(self) -> None:
        class Hook:
            def __init__(self) -> None:
                self.cbs: list = []

            def __iadd__(self, cb):
                self.cbs.append(cb)
                return self

        class FakeWin:
            def __init__(self) -> None:
                self.events = SimpleNamespace(initialized=Hook(), loaded=Hook())
                self.shown = 0

            def show(self) -> None:
                self.shown += 1

        window = FakeWin()
        bind_show_when_ready(window, fallback_sec=0)
        self.assertEqual(len(window.events.initialized.cbs), 1)
        window.events.initialized.cbs[0]()
        window.events.loaded.cbs[0]()
        self.assertEqual(window.shown, 1)

    def test_window_does_not_start_hidden(self) -> None:
        from electrical_krow.desktop import window_starts_hidden

        with patch("electrical_krow.desktop.sys.platform", "darwin"):
            self.assertFalse(window_starts_hidden())
        with patch("electrical_krow.desktop.sys.platform", "win32"):
            self.assertFalse(window_starts_hidden())

    def test_gateway_in_thread_defaults_on_windows(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "ELECTRICAL_KROW_GW_THREAD"}
        with patch.dict(os.environ, env, clear=True):
            with patch("electrical_krow.desktop.sys.platform", "win32"):
                self.assertTrue(gateway_in_thread())
            with patch("electrical_krow.desktop.sys.platform", "darwin"):
                self.assertFalse(gateway_in_thread())
        with patch.dict(os.environ, {"ELECTRICAL_KROW_GW_THREAD": "0"}):
            with patch("electrical_krow.desktop.sys.platform", "win32"):
                self.assertFalse(gateway_in_thread())

    def test_gateway_command_uses_run_py_flag(self) -> None:
        fake = Path(tempfile.gettempdir()) / "run.py"
        with patch.object(sys, "argv", [str(fake)]):
            cmd = gateway_command("127.0.0.1", 18765)
        self.assertEqual(Path(cmd[1]).name, "run.py")
        self.assertIn("--gateway", cmd)
        self.assertEqual(cmd[-1], "18765")

    def test_gateway_command_uses_module_outside_packaged_entry(self) -> None:
        with patch.object(sys, "argv", ["electrical_krow"]):
            cmd = gateway_command("127.0.0.1", 18765)
        self.assertEqual(cmd[1:5], ["-m", "electrical_krow", "gateway", "--no-browser"])

    def test_gateway_command_uses_runtime_python_override(self) -> None:
        with patch.object(sys, "argv", ["electrical_krow"]):
            with patch.dict(os.environ, {"ELECTRICAL_KROW_PYTHON": "/tmp/krow-python"}):
                cmd = gateway_command("127.0.0.1", 18765)
        self.assertEqual(cmd[0], "/tmp/krow-python")

    def test_reap_stale_gateway_removes_dead_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            pid_file = root / "desktop-gateway.pid"
            pid_file.write_text("99999999", encoding="utf-8")
            with patch("electrical_krow.desktop.data_root", return_value=root):
                reap_stale_gateway("127.0.0.1", 1)
            self.assertFalse(pid_file.is_file())

    def test_start_gateway_spawns_process_and_writes_pid(self) -> None:
        class FakeProc:
            def __init__(self) -> None:
                self.pid = 4242
                self._handle = None
                self.stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self) -> None:
                self.stopped = True

            def kill(self) -> None:
                self.stopped = True

            def wait(self, timeout=None):
                return 0

        proc = FakeProc()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch("electrical_krow.desktop.data_root", return_value=root):
                with patch("electrical_krow.desktop.gateway_in_thread", return_value=False):
                    with patch("electrical_krow.desktop.subprocess.Popen", return_value=proc):
                        handle = start_gateway(
                            None, "127.0.0.1", 18765, "http://127.0.0.1:18765"
                        )
                pid_file = root / "desktop-gateway.pid"
                self.assertEqual(pid_file.read_text(encoding="utf-8"), "4242")
                handle.stop()
                self.assertTrue(proc.stopped)
                self.assertFalse(pid_file.is_file())

    def test_prepare_webview_runtime_sets_occlusion_flag(self) -> None:
        key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
        old = os.environ.get(key)
        try:
            os.environ.pop(key, None)
            with patch("electrical_krow.desktop.sys.platform", "win32"):
                _prepare_webview_runtime()
            self.assertIn("CalculateNativeWinOcclusion", os.environ.get(key, ""))
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


if __name__ == "__main__":
    unittest.main()
