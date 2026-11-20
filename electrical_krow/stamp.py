"""本机服务的版本印记。启动时算一次，避免更新后还连着旧进程。"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_FILES = (
    _ROOT / "gateway.py",
    _ROOT / "enterprise_dialogue.py",
    _ROOT / "frontend" / "app.js",
)


def compute_source_stamp() -> str:
    """按当前这几份源文件的内容算出印记。"""
    digest = hashlib.sha256()
    for path in _FILES:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:16]


# 进程启动时固定。健康检查不能再读磁盘，否则旧进程会读到刚覆盖的新文件。
STAMP = compute_source_stamp()


def listening_stamp(origin: str, *, timeout: float = 1.5) -> str:
    """读端口上那个服务启动时的印记。没有、超时或不是这一版接口，都返回空。"""
    url = origin.rstrip("/") + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("stamp") or "")


def same_gateway(origin: str, *, timeout: float = 1.5) -> bool:
    """端口上的服务就是当前这份代码时才继续用。"""
    found = listening_stamp(origin, timeout=timeout)
    return bool(found) and found == STAMP
