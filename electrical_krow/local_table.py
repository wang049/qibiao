"""本机直接读测试表。不经过浏览器的文件句柄。"""
from __future__ import annotations

import ctypes
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from electrical_krow.enterprise_dialogue import ManualItem, read_manual_table, search_queries, source_url
from electrical_krow.paths import MAX_BYTES, MAX_MB

_TABLE_SUFFIX = {".xlsx", ".xlsm", ".docx", ".txt", ".md"}
_INVALID_HANDLE = wintypes.HANDLE(-1).value if sys.platform == "win32" else None


def read_shared_bytes(path: Path) -> bytes:
    """按共享方式读。Excel 开着同一份表时也能读出内容。"""
    if sys.platform == "win32":
        return _read_shared_win(path)
    return path.read_bytes()


def _read_shared_win(path: Path) -> bytes:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel.ReadFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(
        str(path),
        0x80000000,
        0x1 | 0x2 | 0x4,
        None,
        3,
        0x80,
        None,
    )
    if handle == _INVALID_HANDLE:
        code = ctypes.get_last_error()
        raise OSError(code, f"本机读不出这个文件（Windows 错误 {code}）。请确认文件还在，且没有被独占。")
    chunks: list[bytes] = []
    total = 0
    try:
        buf = ctypes.create_string_buffer(1024 * 1024)
        got = wintypes.DWORD()
        while True:
            ok = kernel.ReadFile(handle, buf, len(buf), ctypes.byref(got), None)
            if not ok:
                code = ctypes.get_last_error()
                raise OSError(code, f"读到 {total} 字节后中断（Windows 错误 {code}）。")
            if got.value == 0:
                break
            chunks.append(buf.raw[: got.value])
            total += got.value
            if total > MAX_BYTES:
                raise ValueError(f"文件超过 {MAX_MB}MB")
    finally:
        kernel.CloseHandle(handle)
    return b"".join(chunks)


def pick_table_path() -> str:
    """弹出本机文件窗口。取消时返回空字符串。"""
    if sys.platform != "win32":
        raise OSError("当前系统没有本机文件窗口。")
    comdlg = ctypes.WinDLL("comdlg32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    class NMHDR(ctypes.Structure):
        _fields_ = [
            ("hwndFrom", wintypes.HWND),
            ("idFrom", ctypes.c_size_t),
            ("code", ctypes.c_long),
        ]

    def on_init(hwnd, msg, wparam, lparam):
        if msg == 0x004E and lparam:
            note = ctypes.cast(lparam, ctypes.POINTER(NMHDR)).contents
            if note.code in (-601, -601 & 0xFFFFFFFF):
                parent = user32.GetParent(hwnd) or hwnd
                user32.SetForegroundWindow(parent)
                user32.SetWindowPos(parent, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
                user32.SetWindowPos(parent, wintypes.HWND(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
        return 0

    hook_type = ctypes.WINFUNCTYPE(
        ctypes.c_size_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )
    hook = hook_type(on_init)
    pick_table_path._hook = hook
    file_buf = ctypes.create_unicode_buffer(32768)
    title_buf = ctypes.create_unicode_buffer("选择测试表")
    filt = "测试表 (*.xlsx;*.xlsm;*.docx;*.txt;*.md)\0*.xlsx;*.xlsm;*.docx;*.txt;*.md\0\0"
    filt_buf = ctypes.create_unicode_buffer(filt)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(ofn)
    ofn.hwndOwner = None
    ofn.lpstrFilter = ctypes.cast(filt_buf, wintypes.LPCWSTR)
    ofn.lpstrFile = ctypes.cast(file_buf, wintypes.LPWSTR)
    ofn.nMaxFile = len(file_buf)
    ofn.lpstrTitle = ctypes.cast(title_buf, wintypes.LPCWSTR)
    ofn.Flags = 0x00001000 | 0x00000800 | 0x00080000 | 0x00000008 | 0x00004000 | 0x00000020
    ofn.lpfnHook = ctypes.cast(hook, ctypes.c_void_p)
    comdlg.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
    comdlg.GetOpenFileNameW.restype = wintypes.BOOL
    if not comdlg.GetOpenFileNameW(ctypes.byref(ofn)):
        return ""
    return file_buf.value


def stage_table(path: Path) -> tuple[Path, Path, list[ManualItem], int]:
    """读入副本再解析。返回临时目录、副本、行、字节数。"""
    source = path.expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"找不到测试表：{source.name}")
    suffix = source.suffix.lower()
    if suffix not in _TABLE_SUFFIX:
        raise ValueError("测试表请用 Excel、Word 或文本。")
    data = read_shared_bytes(source)
    if not data:
        raise ValueError("文件是空的")
    if len(data) > MAX_BYTES:
        raise ValueError(f"文件超过 {MAX_MB}MB")
    folder = Path(tempfile.mkdtemp())
    dest = folder / f"table{suffix}"
    dest.write_bytes(data)
    try:
        manual = read_manual_table(dest)
    except Exception:
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder, dest, manual, len(data)


def intake_summary(name: str, manual: list[ManualItem], size: int) -> str:
    queries = search_queries(manual)
    shown = "、".join(queries[:6])
    extra = f" 等 {len(queries)} 个" if len(queries) > 6 else ""
    standards = f"标准号：{shown}{extra}。" if shown else "表里没有写出标准号。"
    return f"输入完成。{name}，{size} 字节，抽出 {len(manual)} 行。{standards}接下来打开 {source_url()}。"
