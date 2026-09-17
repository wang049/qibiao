"""「关于」页数据与本机打开文件。

版本号全部取自已安装的发行元数据；取不到的留空字符串，前端显示「—」。
本机打开只允许核对表目录下的文件，由网关校验路径后调用。
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from electrical_krow.knowledge import knowledge_version

_DISTS = {
    "client": ("electrical-krow", "electrical_krow"),
    "sdk": ("krow-agent-sdk",),
    "runtime": ("krow-agent-sdk-runtime",),
}


def _dist_version(*names: str) -> str:
    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return ""


def versions() -> dict[str, str]:
    out = {key: _dist_version(*names) for key, names in _DISTS.items()}
    if not out["client"]:
        from electrical_krow import __version__

        out["client"] = __version__
    out["knowledge"] = knowledge_version() or ""
    out["python"] = platform.python_version()
    out["platform"] = f"{platform.system()} {platform.release()}".strip()
    return out


class OpenError(RuntimeError):
    """本机打不开文件（系统没有关联程序、命令不存在等）。"""


def open_locally(path: Path) -> None:
    """用系统默认程序打开文件。不等待、不解析输出。"""
    target = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
        elif os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", target])
    except OSError as exc:
        raise OpenError(f"无法在本机打开文件：{exc}") from exc
