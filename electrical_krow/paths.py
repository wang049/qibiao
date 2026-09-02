"""本机出表的目录与限额。"""
from __future__ import annotations

import os
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18765
MAX_BYTES = 80 * 1024 * 1024
MAX_MB = MAX_BYTES // (1024 * 1024)

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
FRONTEND_DIR = PACKAGE_DIR / "frontend"
SUPPORTED = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}


def data_root() -> Path:
    """核对表和上传缓存。安装包通过 ELECTRICAL_KROW_DATA 指到用户目录。"""
    override = (os.environ.get("ELECTRICAL_KROW_DATA") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return PROJECT_ROOT / "output"


OUTPUT_DIR = data_root()
UPLOAD_DIR = OUTPUT_DIR / "uploads"
