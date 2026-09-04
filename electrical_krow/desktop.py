"""客户端原生窗口：嵌入 Python 网关，界面仍是现有登录/出表页。

不对齐 KAD 的 agent.run() 或设备码登录。关掉窗口即停止本机服务。
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from electrical_krow.branding import (
    TITLE,
    apply_native_identity,
    handoff_macos_app,
    icon_arg,
    runtime_python,
)
from electrical_krow.config import apply_macos_client_server
from electrical_krow.errors import ConfigError
from electrical_krow.gateway import (
    announce,
    apply_windows_event_loop_policy,
    listen_from_args,
    parse_gateway_argv,
)
from electrical_krow.paths import OUTPUT_DIR, data_root

EDGE_HINT = (
    "找不到 Microsoft Edge，无法打开工位窗口。\n"
    "请安装 Microsoft Edge 后再打开（不是 Chrome）。"
)


def port_is_open(host: str, port: int, *, timeout: float = 0.4) -> bool:
    targets = [host]
    if host in {"localhost", "127.0.0.1", "::1"}:
        targets = ["127.0.0.1"]
    for target in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            if sock.connect_ex((target, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            sock.close()
    return False


def wait_until_open(host: str, port: int, *, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_is_open(host, port):
            return True
        time.sleep(0.05)
    return False


def http_ok(url: str, *, timeout: float = 0.4) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 500
    except (OSError, ValueError):
        return False


def wait_until_ready(_host: str, _port: int, origin: str, *, seconds: float = 20.0) -> bool:
    """等本机页真能打开，避免窗口先出来却卡在首屏请求上。"""
    deadline = time.time() + seconds
    root = origin.rstrip("/")
    health = f"{root}/api/health"
    home = f"{root}/"
    while time.time() < deadline:
        if http_ok(health) or http_ok(home):
            return True
        time.sleep(0.05)
    return False


def webview_installed() -> bool:
    return importlib.util.find_spec("webview") is not None


def edge_app_profile() -> Path:
    return data_root() / "edge-app"


def msedge_path() -> str | None:
    override = (os.environ.get("ELECTRICAL_KROW_EDGE") or "").strip()
    if override:
        return override if Path(override).is_file() else None
    homes: list[Path] = []
    for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = (os.environ.get(key) or "").strip()
        if root:
            homes.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    homes.append(
        Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    )
    for path in homes:
        if path.is_file():
            return str(path)
    found = shutil.which("msedge")
    return found


def edge_profile_busy(profile: Path) -> bool:
    """只看真正的实例锁。SingletonCookie 关掉窗口后仍会留在目录里。"""
    for name in ("SingletonLock", "lockfile"):
        if (profile / name).exists():
            return True
    return False


def _msedge_cmd_uses_profile(profile: Path) -> bool:
    if sys.platform != "win32":
        return False
    needle = str(profile).replace("/", "\\").lower()
    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='msedge.exe'", "get", "CommandLine"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (out.stdout or "").replace("/", "\\").lower()
    return needle in text


def edge_app_running(profile: Path, *, probe_process: bool = True) -> bool:
    if edge_profile_busy(profile):
        return True
    if probe_process:
        return _msedge_cmd_uses_profile(profile)
    return False


def wait_edge_app_closed(
    proc: subprocess.Popen, profile: Path, *, seconds: float | None = None
) -> None:
    """Edge --app 常把窗口交给独立进程，Popen 的 stub 可能马上退出。

    seconds 只给测试用。生产环境一直等到窗口退出；若检测不到锁文件，
    也不提前停网关，避免窗口刚出来页面就断。
    """
    appear = 60.0 if seconds is None else max(0.05, float(seconds))
    close_budget = None if seconds is None else max(0.05, float(seconds))
    seen = False
    deadline = time.time() + appear
    last_probe = 0.0
    while time.time() < deadline:
        now = time.time()
        probe = now - last_probe >= 1.0
        if probe:
            last_probe = now
        if edge_app_running(profile, probe_process=probe):
            seen = True
            break
        if proc.poll() not in (None, 0):
            raise RuntimeError(EDGE_HINT)
        time.sleep(0.1)
    if proc.poll() is None:
        if close_budget is None:
            proc.wait()
        else:
            try:
                proc.wait(timeout=close_budget)
            except subprocess.TimeoutExpired:
                pass
    if proc.poll() not in (None, 0) and not edge_app_running(
        profile, probe_process=True
    ):
        raise RuntimeError(EDGE_HINT)
    if close_budget is not None:
        stop = time.time() + close_budget
        while time.time() < stop and edge_app_running(profile, probe_process=False):
            time.sleep(0.05)
        return
    if not seen:
        extra = time.time() + 30.0
        while time.time() < extra:
            if edge_app_running(profile, probe_process=True):
                seen = True
                break
            time.sleep(0.2)
    last_probe = 0.0
    while True:
        now = time.time()
        probe = now - last_probe >= 1.0
        if probe:
            last_probe = now
        running = edge_app_running(profile, probe_process=probe)
        if running:
            seen = True
        elif seen:
            return
        time.sleep(0.8)


def open_edge_app_window(url: str) -> None:
    """Windows 用工位专用 Edge 应用窗口，不再走 pywebview/pythonnet。"""
    edge = msedge_path()
    if not edge:
        raise RuntimeError(EDGE_HINT)
    profile = edge_app_profile()
    profile.mkdir(parents=True, exist_ok=True)
    profile = profile.resolve()
    args = [
        edge,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--window-size=1180,840",
        "--disable-features=TranslateUI,MediaRouter",
    ]
    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 1))
        info.wShowWindow = 1
        kwargs["startupinfo"] = info
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    proc = subprocess.Popen(args, **kwargs)
    wait_edge_app_closed(proc, profile)


def gateway_in_thread() -> bool:
    """默认独立进程。和 WebView2 同进程会把窗口拖成「未响应」。"""
    raw = os.environ.get("ELECTRICAL_KROW_GW_THREAD", "").strip().lower()
    return raw in {"1", "true", "yes"}


def gateway_python() -> str:
    """子进程用 python.exe，避免再开一个 pythonw 和窗口抢消息泵。"""
    exe = Path(runtime_python())
    if sys.platform == "win32" and exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return str(console)
    return str(exe)


def gateway_pid_path() -> Path:
    return data_root() / "desktop-gateway.pid"


def gateway_command(host: str, port: int) -> list[str]:
    extra = ["--host", str(host), "--port", str(port)]
    argv0 = Path(sys.argv[0]).resolve()
    python = gateway_python()
    if argv0.name.lower() == "run.py":
        return [python, str(argv0), "--gateway", *extra]
    return [
        python,
        "-m",
        "electrical_krow",
        "gateway",
        "--no-browser",
        *extra,
    ]


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            return
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def reap_stale_gateway(host: str, port: int) -> None:
    """上次窗口被强制结束后，清掉残留的本机网关，避免端口占死。"""
    path = gateway_pid_path()
    if not path.is_file():
        return
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return
    if pid == os.getpid():
        path.unlink(missing_ok=True)
        return
    if _pid_running(pid):
        _kill_pid(pid)
    path.unlink(missing_ok=True)
    deadline = time.time() + 2.0
    while time.time() < deadline and port_is_open(host, port):
        time.sleep(0.05)


def _kill_port_listener(port: int) -> None:
    """端口被占但页面打不开时，清掉监听进程。"""
    if sys.platform != "win32":
        return
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
    except OSError:
        return
    needle = f":{int(port)}"
    seen: set[int] = set()
    for line in (out.stdout or "").splitlines():
        if "LISTENING" not in line.upper() or needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid in seen or pid <= 0:
            continue
        seen.add(pid)
        _kill_pid(pid)


class WinJob:
    """父进程退出时一并结束子进程，避免任务管理器只杀掉窗口。"""

    def __init__(self) -> None:
        self.handle = None
        self._kernel32 = None
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_uint64),
                    ("WriteOperationCount", ctypes.c_uint64),
                    ("OtherOperationCount", ctypes.c_uint64),
                    ("ReadTransferCount", ctypes.c_uint64),
                    ("WriteTransferCount", ctypes.c_uint64),
                    ("OtherTransferCount", ctypes.c_uint64),
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x2000
            ok = kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            )
            if not ok:
                kernel32.CloseHandle(handle)
                return
            self._kernel32 = kernel32
            self.handle = handle
        except Exception:
            self.handle = None
            self._kernel32 = None

    def assign(self, process_handle: int) -> None:
        if not self.handle or not process_handle or self._kernel32 is None:
            return
        try:
            self._kernel32.AssignProcessToJobObject(self.handle, process_handle)
        except Exception:
            pass

    def close(self) -> None:
        if not self.handle or self._kernel32 is None:
            self.handle = None
            return
        try:
            self._kernel32.CloseHandle(self.handle)
        except Exception:
            pass
        self.handle = None


class GatewayHandle:
    def stop(self) -> None:
        return


def _alert(message: str) -> None:
    print(message, flush=True)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, TITLE, 0x40)
            return
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showinfo(TITLE, message)
        root.destroy()
    except Exception:
        pass


def _load_webview():
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "未安装窗口组件 pywebview。开发机可执行：pip install pywebview"
        ) from exc
    return webview


def sheet_file(name: str) -> Path | None:
    safe = Path(str(name or "")).name
    if not safe or Path(safe).suffix.lower() != ".xlsx":
        return None
    path = (OUTPUT_DIR / safe).resolve()
    if path.parent != OUTPUT_DIR.resolve() or not path.is_file():
        return None
    return path


def reveal_file(path: Path) -> None:
    text = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", text])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", text])
    except OSError:
        pass


def picked_save_path(dests: object, *, default_name: str) -> Path | None:
    """macOS 保存框返回字符串，Windows 返回路径列表。取第一个字符会变成 Path('/')。"""
    if dests is None or dests is False:
        return None
    if isinstance(dests, (str, Path)):
        text = str(dests).strip()
    elif isinstance(dests, (list, tuple)) and dests:
        text = str(dests[0]).strip()
    else:
        return None
    if not text:
        return None
    dest = Path(text)
    if dest.is_dir():
        if dest == dest.parent:
            return None
        dest = dest / default_name
    elif not dest.name:
        return None
    if dest.suffix.lower() != ".xlsx":
        dest = dest.with_suffix(".xlsx")
    return dest


class DesktopApi:
    """给窗口页调用：核对表在本机已生成，弹保存框拷一份，不走 WebView 下载。"""

    def __init__(self) -> None:
        self.window = None

    def save_sheet(self, name: str) -> dict[str, object]:
        src = sheet_file(name)
        if src is None:
            return {"ok": False, "canceled": False, "error": "找不到核对表"}
        if self.window is None:
            return {"ok": False, "canceled": False, "error": "窗口未就绪"}
        try:
            webview = _load_webview()
            dests = self.window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(Path.home() / "Desktop"),
                save_filename=src.name,
                file_types=("Excel 核对表 (*.xlsx)",),
            )
            dest = picked_save_path(dests, default_name=src.name)
            if dest is None:
                return {"ok": False, "canceled": True, "error": ""}
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            reveal_file(dest)
            return {"ok": True, "canceled": False, "path": str(dest)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "canceled": False, "error": str(exc)}


def _gui_name() -> str | None:
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform == "darwin":
        return "cocoa"
    return None


def _set_native_app_identity() -> None:
    apply_native_identity()


def serve_in_thread(settings, host: str, port: int, origin: str) -> GatewayHandle:
    import uvicorn
    from electrical_krow.gateway import create_app

    apply_windows_event_loop_policy()
    app = create_app(settings, extract_url=origin)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("KROW_UVICORN_LOG", "warning"),
        lifespan="on",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = False
    worker = threading.Thread(target=server.run, name="electrical-krow-gw", daemon=True)
    worker.start()

    class Handle(GatewayHandle):
        def stop(self) -> None:
            server.should_exit = True
            worker.join(timeout=2.0)

    return Handle()


def spawn_gateway(host: str, port: int) -> GatewayHandle:
    cmd = gateway_command(host, port)
    kwargs: dict[str, object] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    env = os.environ.copy()
    env["ELECTRICAL_KROW_NESTED"] = "1"
    env["ELECTRICAL_KROW_GW_THREAD"] = "0"
    proc = subprocess.Popen(cmd, env=env, **kwargs)
    job = WinJob()
    raw = getattr(proc, "_handle", None)
    if raw:
        job.assign(int(raw))
    pid_path = gateway_pid_path()
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pid_path = None

    class Handle(GatewayHandle):
        def stop(self) -> None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
            if pid_path is not None:
                try:
                    pid_path.unlink(missing_ok=True)
                except OSError:
                    pass
            job.close()

    return Handle()


def start_gateway(settings, host: str, port: int, origin: str) -> GatewayHandle:
    if gateway_in_thread():
        return serve_in_thread(settings, host, port, origin)
    return spawn_gateway(host, port)


def _prepare_webview_runtime() -> None:
    storage = data_root() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        return
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(storage))
    extra = (
        "--disable-features=CalculateNativeWinOcclusion "
        "--disable-backgrounding-occluded-windows"
    )
    prev = (os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") or "").strip()
    if "CalculateNativeWinOcclusion" not in prev:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            f"{prev} {extra}".strip() if prev else extra
        )


def window_starts_hidden() -> bool:
    """默认不要藏窗口。hidden=True 时 WebView2 的 show() 常不在 UI 线程，双击会像没反应。"""
    raw = os.environ.get("ELECTRICAL_KROW_HIDE_UNTIL_READY", "").strip().lower()
    return raw in {"1", "true", "yes"}


def bind_show_when_ready(window, *, fallback_sec: float = 6.0) -> None:
    """WebView2 冷启动完成前先藏着窗口，避免任务栏先出现「未响应」。"""
    shown = {"done": False}

    def show() -> None:
        if shown["done"]:
            return
        shown["done"] = True
        try:
            window.show()
        except Exception:
            pass

    events = getattr(window, "events", None)
    if events is not None:
        for name in ("initialized", "loaded"):
            hook = getattr(events, name, None)
            if hook is None:
                continue
            try:
                hook += show
            except Exception:
                pass
    if fallback_sec > 0:
        threading.Thread(
            target=lambda: (time.sleep(fallback_sec), show()),
            name="electrical-krow-show",
            daemon=True,
        ).start()


def open_window(url: str) -> None:
    if sys.platform == "win32":
        open_edge_app_window(url)
        return
    _prepare_webview_runtime()
    _set_native_app_identity()
    webview = _load_webview()
    webview.settings["ALLOW_DOWNLOADS"] = True
    storage = data_root() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    api = DesktopApi()
    hidden = window_starts_hidden()
    window = webview.create_window(
        TITLE,
        url,
        width=1180,
        height=840,
        min_size=(760, 600),
        text_select=True,
        confirm_close=False,
        hidden=hidden,
        easy_drag=False,
        background_color="#F4F1EA",
        js_api=api,
    )
    api.window = window
    if hidden:
        bind_show_when_ready(window)
    kwargs: dict[str, object] = {
        "private_mode": False,
        "storage_path": str(storage),
        "debug": False,
        "http_server": False,
    }
    gui = _gui_name()
    if gui:
        kwargs["gui"] = gui
    icon = icon_arg()
    if icon:
        kwargs["icon"] = icon
    try:
        webview.start(**kwargs)
    except Exception as exc:
        raise RuntimeError("无法打开窗口。\n\n" + str(exc)) from exc


def main(argv: list[str] | None = None) -> int:
    apply_macos_client_server()
    args = parse_gateway_argv(argv)
    try:
        settings, host, port, origin = listen_from_args(args)
    except ConfigError as exc:
        _alert(str(exc))
        return 1
    if settings.delivery == "site":
        _alert("场所网页请用浏览器打开内网地址，不要用桌面窗口。")
        return 1
    if handoff_macos_app(list(argv or [])):
        announce(settings, host, origin)
        print("客户端窗口已用应用身份打开，Dock 不再显示 python3.12。", flush=True)
        if wait_until_ready(host, port, origin):
            return 0
        _alert("本机服务没有启动成功。请查看 gateway.log。")
        return 1
    announce(settings, host, origin)
    print("客户端窗口：登录和出表都在本窗口完成，不再打开系统浏览器。", flush=True)
    if sys.platform == "win32":
        _set_native_app_identity()
        if not msedge_path():
            _alert(EDGE_HINT)
            return 1
    else:
        if not webview_installed():
            _alert("未安装窗口组件 pywebview。开发机可执行：pip install pywebview")
            return 1
        _prepare_webview_runtime()
        _set_native_app_identity()
        try:
            _load_webview()
        except RuntimeError as exc:
            _alert(str(exc))
            return 1
    page = f"{origin}/"

    def _open() -> int:
        try:
            open_window(page)
            return 0
        except RuntimeError as exc:
            _alert(str(exc))
            return 1
        except Exception as exc:
            _alert(f"无法打开窗口：{exc}")
            return 1

    if wait_until_ready(host, port, origin, seconds=1.2):
        print("本机服务已在运行，重新打开窗口。", flush=True)
        return _open()
    reap_stale_gateway(host, port)
    if port_is_open(host, port) and not wait_until_ready(host, port, origin, seconds=0.6):
        _kill_port_listener(port)
    handle = start_gateway(settings, host, port, origin)
    try:
        ready_sec = 45.0 if sys.platform == "win32" else 20.0
        if not wait_until_ready(host, port, origin, seconds=ready_sec):
            _alert("本机服务没有启动成功。请查看 gateway.log。")
            return 1
        return _open()
    finally:
        handle.stop()


if __name__ == "__main__":
    raise SystemExit(main())
