"""Windows 绿色包入口。不依赖 PYTHONPATH / python -m。

默认打开原生窗口（WebView2），不再跳系统浏览器。
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"


def _prepare() -> None:
    os.chdir(ROOT)
    site = ROOT / "python" / "Lib" / "site-packages"
    for path in (site, APP, APP / "electrical"):
        text = str(path)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    os.environ["ELECTRICAL_ROOT"] = str(APP / "electrical")
    os.environ["ELECTRICAL_KROW_CONFIG"] = str(ROOT / "config.ini")
    os.environ.setdefault(
        "ELECTRICAL_KROW_DATA",
        str(Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data"))) / "electrical-krow"),
    )
    os.environ.setdefault("KROW_UVICORN_LOG", "info")
    os.environ.setdefault("ELECTRICAL_KROW_GW_THREAD", "1")


def _missing_deps() -> list[str]:
    site = ROOT / "python" / "Lib" / "site-packages"
    need = ("httpx", "httpcore", "anyio", "certifi", "webview", "fastapi")
    return [name for name in need if not (site / name).exists()]


def _no_console() -> bool:
    name = Path(sys.executable).name.lower()
    if "pythonw" in name:
        return True
    out = sys.stdout
    if out is None:
        return True
    try:
        return not out.isatty()
    except Exception:
        return True


def _redirect_log() -> None:
    if not _no_console():
        return
    data = Path(os.environ["ELECTRICAL_KROW_DATA"])
    data.mkdir(parents=True, exist_ok=True)
    log = open(data / "gateway.log", "a", encoding="utf-8", errors="replace", buffering=1)
    log.write(f"\n---- {datetime.now().isoformat(timespec='seconds')} ----\n")
    log.flush()
    sys.stdout = log
    sys.stderr = log


def _win_error(message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message[:2500], "电子电器 SOR填表", 0x10)
    except Exception:
        pass


def _wait_gateway() -> int:
    _prepare()
    from electrical_krow.config import load_settings
    from electrical_krow.desktop import wait_until_ready

    settings = load_settings()
    host = settings.gateway_host
    if host in {"0.0.0.0", "::", "*"}:
        host = "127.0.0.1"
    origin = f"http://{host}:{settings.gateway_port}"
    return 0 if wait_until_ready(host, settings.gateway_port, origin, seconds=20) else 1


def _run_gateway() -> int:
    _prepare()
    _redirect_log()
    from electrical_krow.gateway import main as gateway_main

    return gateway_main(["--no-browser", *sys.argv[2:]])


def main() -> int:
    if sys.argv[1:] == ["--wait-gateway"]:
        return _wait_gateway()
    if sys.argv[1:2] == ["--gateway"]:
        return _run_gateway()
    _prepare()
    _redirect_log()
    pkg = APP / "electrical_krow" / "__init__.py"
    if not pkg.is_file():
        msg = f"找不到程序文件: {pkg}\n请重新解压完整 zip，不要只拷贝启动脚本。"
        print(msg, flush=True)
        _win_error(msg)
        return 1
    missing = _missing_deps()
    if missing:
        msg = (
            "安装不完整，缺少："
            + "、".join(missing)
            + "。\n请先关掉出表窗口，删掉 %LOCALAPPDATA%\\electrical-krow-app，再用新的 exe 安装。"
        )
        print(msg, flush=True)
        _win_error(msg)
        return 1
    try:
        from electrical_krow.desktop import main as desktop_main
    except Exception:
        traceback.print_exc()
        print("\nsys.path:", flush=True)
        for item in sys.path:
            print(f"  {item}", flush=True)
        print("\nFailed to import electrical_krow. Send this window text to us.", flush=True)
        _win_error(
            "无法启动出表窗口。请把 %LOCALAPPDATA%\\electrical-krow\\gateway.log 发给我们。\n\n"
            + traceback.format_exc()[-1200:]
        )
        return 1
    try:
        return desktop_main([])
    except Exception:
        traceback.print_exc()
        _win_error("出表窗口异常退出。\n\n" + traceback.format_exc()[-1200:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
