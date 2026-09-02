"""由 site 在启动时加载。嵌入式 Python 的 ._pth 会丢掉应用目录。"""
from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[3]
_site = Path(__file__).resolve().parent
_app = _root / "app"
for _p in (_site, _app, _app / "electrical"):
    _s = str(_p)
    if _p.is_dir() and _s not in sys.path:
        sys.path.insert(0, _s)
