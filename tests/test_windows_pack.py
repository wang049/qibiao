from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from electrical_krow.branding import icon_file

ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "packaging" / "windows"


class WindowsPackIconTests(unittest.TestCase):
    def test_shortcut_sets_icon_location(self) -> None:
        app_c = (WIN / "app.c").read_text(encoding="utf-8")
        self.assertIn("SetIconLocation", app_c)
        self.assertIn("app-icon.ico", app_c)
        self.assertIn("电子电器智能体.lnk", app_c)
        self.assertIn("SHORTCUT_NAME_OLD", app_c)
        self.assertIn("电子电器SOR填表.lnk", app_c)
        self.assertIn("正在打开电子电器智能体", app_c)
        self.assertIn("正在启动电子电器智能体", app_c)
        self.assertIn("请把这个窗口截图发给我们", app_c)
        self.assertNotIn("请查看 gateway.log", app_c)
        console = (WIN / "console.bat").read_text(encoding="utf-8")
        start = (WIN / "start.bat").read_text(encoding="utf-8")
        self.assertIn('"!PYW!" "!ROOT!\\run.py"', console)
        self.assertNotIn('"!PY!" "!ROOT!\\run.py"', console)
        self.assertIn('"!PYW!" "!ROOT!\\run.py" --wait-gateway', start)
        self.assertNotIn('"!PY!" "!ROOT!\\run.py"', start)
        self.assertNotIn("%LOCALAPPDATA%\\electrical-krow\\gateway.log", app_c)
        self.assertNotIn("正在打开出表窗口", app_c)

    def test_pack_script_embeds_frontend_icon(self) -> None:
        script = (WIN / "build_zip.sh").read_text(encoding="utf-8")
        self.assertIn("app-icon.ico", script)
        self.assertIn("embed_icon.py", script)
        self.assertIn("lock_environment = true", script)
        self.assertIn("https://rdapi.aurobaytech-t.com", script)
        self.assertIn("site pack missing lock_environment", script)
        readme = (WIN / "使用说明.txt").read_text(encoding="utf-8")
        self.assertIn("本包默认 https://api.krow.cn。", readme)
        self.assertIn("锁定现场识别", readme)
        ico = icon_file(platform="win32")
        self.assertIsNotNone(ico)
        self.assertEqual(ico.name, "app-icon.ico")
        self.assertGreater(ico.stat().st_size, 100)

    def test_embed_icon_writes_pe_resource(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("embed_icon", WIN / "embed_icon.py")
        self.assertIsNotNone(spec)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ico = ROOT / "electrical_krow" / "frontend" / "app-icon.ico"
        group, images = mod.parse_ico(ico.read_bytes())
        self.assertGreaterEqual(len(images), 4)
        self.assertGreater(len(group), 6)
        with tempfile.TemporaryDirectory() as raw:
            exe = Path(raw) / "blank.exe"
            exe.write_bytes(mod.make_blank_pe32plus())
            self.assertFalse(mod.has_icon_resource(exe.read_bytes()))
            mod.embed_icon(exe, ico)
            patched = exe.read_bytes()
            self.assertTrue(mod.has_icon_resource(patched))
            self.assertIn(b".rsrc", patched)
            self.assertIn(images[0][:16], patched)
            mod.embed_icon(exe, ico)
            again = exe.read_bytes()
            self.assertTrue(mod.has_icon_resource(again))
            self.assertEqual(again.count(b".rsrc"), 1)


if __name__ == "__main__":
    unittest.main()
