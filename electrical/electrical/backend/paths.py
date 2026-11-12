"""工位出表的目录与限额。"""
from __future__ import annotations

from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
MAX_BYTES = 80 * 1024 * 1024
MAX_MB = MAX_BYTES // (1024 * 1024)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_DIR.parent
FRONTEND_DIR = PACKAGE_DIR / "frontend"
UPLOAD_DIR = PROJECT_ROOT / "output" / "uploads"
OUTPUT_DIR = PROJECT_ROOT / "output"
