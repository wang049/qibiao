"""接到本仓库里的 electrical 出表流水线。

填表仍走 electrical（读文件 → 分流 → 规则 + 分段识别 → Excel）。
识别请求打回本登录页的 /v1/chat/completions（Bearer local）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from electrical_krow.config import Settings
from electrical_krow.paths import PROJECT_ROOT


def electrical_root() -> Path:
    """出表工程在本仓库 electrical/。ELECTRICAL_ROOT 只用于换一份本地副本。"""
    override = (os.environ.get("ELECTRICAL_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    bundled = PROJECT_ROOT / "electrical"
    if (bundled / "electrical").is_dir():
        return bundled.resolve()
    return (PROJECT_ROOT.parent / "electrical").resolve()


def ensure_electrical() -> Path:
    lexicon = PROJECT_ROOT / "docs" / "clause_lexicon.json"
    if lexicon.is_file():
        os.environ.setdefault("SPEC_SHEET_CLAUSE_LEXICON", str(lexicon))
    manifest = PROJECT_ROOT / "docs" / "knowledge" / "published" / "manifest.json"
    if manifest.is_file():
        os.environ.setdefault("SPEC_SHEET_KB_MANIFEST", str(manifest))
    root = electrical_root()
    pkg = root / "electrical"
    if not pkg.is_dir():
        raise FileNotFoundError(
            f"找不到 electrical 出表工程: {root}。"
            "本仓库应自带 electrical/。若要改用别的副本，设置 ELECTRICAL_ROOT。"
        )
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    return root


def wire_extract_endpoint(settings: Settings, *, origin: str | None = None) -> str:
    """出表抽取打到本登录页，沿用 electrical 的 Bearer local 约定。"""
    url = (origin or f"http://{settings.gateway_host}:{settings.gateway_port}").rstrip(
        "/"
    )
    os.environ["SPEC_SHEET_LLM_URL"] = url
    os.environ["SPEC_SHEET_LLM_MODEL"] = settings.chat_model
    os.environ["SPEC_SHEET_LLM_TIMEOUT"] = str(int(settings.timeout_sec))
    try:
        ensure_electrical()
        import electrical.extract as extract

        extract.DEFAULT_BASE_URL = url
        extract.DEFAULT_MODEL = settings.chat_model
        extract.DEFAULT_TIMEOUT = float(settings.timeout_sec)
    except Exception:
        pass
    return url
