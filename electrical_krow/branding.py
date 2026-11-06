"""窗口/Dock/任务栏的产品名和图标。不把出表改成 agent.run()。"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from electrical_krow.paths import FRONTEND_DIR, PACKAGE_DIR

TITLE = "电子电器智能体"
DOCK_APP_NAME = "电子电器智能体"
BUNDLE_ID = "cn.electrical.krow.sorfill"
LAUNCHER_NAME = "ElectricalKrow"


def icon_file(*, platform: str | None = None) -> Path | None:
    plat = sys.platform if platform is None else platform
    names: tuple[str, ...]
    if plat == "win32":
        names = ("app-icon.ico", "app-icon.png")
    elif plat == "darwin":
        names = ("app-icon.icns", "app-icon.png")
    else:
        names = ("app-icon.png",)
    for folder in (FRONTEND_DIR, PACKAGE_DIR / "frontend"):
        for name in names:
            path = folder / name
            if path.is_file():
                return path
    return None


def icon_arg(*, platform: str | None = None) -> str | None:
    path = icon_file(platform=platform)
    return str(path) if path is not None else None


def runtime_python() -> str:
    override = (os.environ.get("ELECTRICAL_KROW_PYTHON") or "").strip()
    if override:
        return override
    return sys.executable


def should_handoff_macos_app() -> bool:
    if sys.platform != "darwin":
        return False
    flag = (os.environ.get("ELECTRICAL_KROW_BUNDLED") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return False
    skip = (os.environ.get("ELECTRICAL_KROW_NO_BUNDLE") or "").strip().lower()
    if skip in {"1", "true", "yes"}:
        return False
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    return True


def macos_app_dir(root: Path | None = None) -> Path:
    base = root if root is not None else Path.home() / "Library" / "Application Support" / "electrical-krow"
    return base / f"{DOCK_APP_NAME}.app"


def _plist(icon_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleExecutable</key>
  <string>{LAUNCHER_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>{icon_name}</string>
  <key>CFBundleIdentifier</key>
  <string>{BUNDLE_ID}</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>{DOCK_APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>{TITLE}</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.1</string>
  <key>CFBundleVersion</key>
  <string>0.1.1</string>
  <key>LSMinimumSystemVersion</key>
  <string>11.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
"""


def _venv_site_packages() -> Path | None:
    major, minor = sys.version_info[:2]
    for site in (
        Path(sys.prefix) / "lib" / f"python{major}.{minor}" / "site-packages",
        Path(sys.prefix) / "Lib" / "site-packages",
    ):
        if site.is_dir():
            return site
    return None


def _pythonpath() -> str:
    parts: list[str] = []
    cwd = str(Path.cwd().resolve())
    raw = os.environ.get("PYTHONPATH") or ""
    for item in raw.split(os.pathsep):
        text = item.strip()
        if not text:
            continue
        if text in {".", "./"}:
            parts.append(cwd)
            continue
        parts.append(str(Path(text).expanduser().resolve()))
    if cwd not in parts:
        parts.insert(0, cwd)
    site = _venv_site_packages()
    if site is not None:
        text = str(site)
        if text not in parts:
            parts.append(text)
    return os.pathsep.join(parts)


def _launch_python() -> str:
    """Keep the venv entry path. Resolving the symlink drops site-packages."""
    return os.path.abspath(runtime_python())


def _launch_env() -> dict[str, str]:
    env = {str(k): str(v) for k, v in os.environ.items()}
    env["ELECTRICAL_KROW_BUNDLED"] = "1"
    env["ELECTRICAL_KROW_PYTHON"] = _launch_python()
    env["PYTHONPATH"] = _pythonpath()
    if (Path(sys.prefix) / "pyvenv.cfg").is_file():
        env.setdefault("VIRTUAL_ENV", str(sys.prefix))
    # Mac 桌面调试不要把 Cursor/现场的 KROW_SERVER_URL 带进 .app。
    if sys.platform == "darwin":
        delivery = (env.get("KROW_DELIVERY") or "client").strip().lower()
        if delivery not in {"site", "lan", "web", "intranet"}:
            env["KROW_SERVER_URL"] = "https://api.krow.cn"
    return env


def install_macos_app_bundle(
    *,
    argv: list[str] | None = None,
    root: Path | None = None,
) -> Path:
    app = macos_app_dir(root)
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    icon_name = "AppIcon"
    src_icon = icon_file(platform="darwin")
    if src_icon is not None:
        dest = resources / ("AppIcon" + src_icon.suffix.lower())
        dest.write_bytes(src_icon.read_bytes())
        if dest.suffix.lower() == ".icns":
            icon_name = "AppIcon"

    (app / "Contents" / "Info.plist").write_text(_plist(icon_name), encoding="utf-8")

    python = _launch_python()
    payload = {
        "python": python,
        "cwd": str(Path.cwd().resolve()),
        "argv": list(argv or []),
        "env": _launch_env(),
    }
    (resources / "launch.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    launcher_py = resources / "launch.py"
    launcher_py.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path(__file__).with_name('launch.json').read_text(encoding='utf-8'))\n"
        "os.chdir(payload['cwd'])\n"
        "os.environ.update(payload.get('env') or {})\n"
        "os.environ['ELECTRICAL_KROW_BUNDLED'] = '1'\n"
        "log_dir = Path.home() / 'Library' / 'Application Support' / 'electrical-krow'\n"
        "log_dir.mkdir(parents=True, exist_ok=True)\n"
        "log = open(log_dir / 'desktop.log', 'a', encoding='utf-8', buffering=1)\n"
        "os.dup2(log.fileno(), 1)\n"
        "os.dup2(log.fileno(), 2)\n"
        "python = payload['python']\n"
        "argv = payload.get('argv') or []\n"
        "os.execv(python, [python, '-m', 'electrical_krow', 'desktop', *argv, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    quoted = "'" + python.replace("'", "'\"'\"'") + "'"
    exe = macos / LAUNCHER_NAME
    exe.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        f"exec {quoted} \"$DIR/../Resources/launch.py\" \"$@\"\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return app


def handoff_macos_app(argv: list[str] | None = None) -> bool:
    """用 .app 身份打开窗口，避免 Dock 显示 python3.12。父进程随即退出。"""
    if not should_handoff_macos_app():
        return False
    app = install_macos_app_bundle(argv=argv)
    started = subprocess.run(["open", "-n", str(app)], check=False)
    return started.returncode == 0


def apply_native_identity() -> None:
    """菜单栏/任务栏显示产品名，而不是 python / pythonw。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(BUNDLE_ID)
        except Exception:
            pass
        return
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle, NSProcessInfo

        bundle = NSBundle.mainBundle()
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = TITLE
            info["CFBundleDisplayName"] = TITLE
            info["CFBundleIdentifier"] = BUNDLE_ID
        NSProcessInfo.processInfo().setProcessName_(DOCK_APP_NAME)
        icon = icon_file(platform="darwin")
        if icon is not None:
            image = NSImage.alloc().initByReferencingFile_(str(icon))
            if image:
                NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass
