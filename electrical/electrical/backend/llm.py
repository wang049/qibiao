"""本机大模型是否就绪。"""
from __future__ import annotations

import httpx

from electrical.extract import DEFAULT_BASE_URL, DEFAULT_MODEL, ExtractError, require_workstation_endpoint


def check_local_llm() -> tuple[bool, str, str]:
    try:
        origin = require_workstation_endpoint(DEFAULT_BASE_URL)
    except ExtractError as exc:
        return False, DEFAULT_MODEL, str(exc)
    try:
        with httpx.Client(timeout=3.0, follow_redirects=False, trust_env=False) as client:
            resp = client.get(f"{origin}/api/tags")
        if resp.status_code >= 400:
            return False, DEFAULT_MODEL, f"本机模型 HTTP {resp.status_code}"
        names = [str(m.get("name") or "") for m in (resp.json().get("models") or [])]
        if names and not any(n == DEFAULT_MODEL or n.startswith(DEFAULT_MODEL + "-") for n in names):
            return False, DEFAULT_MODEL, f"未找到模型 {DEFAULT_MODEL}，请执行 ollama pull {DEFAULT_MODEL}"
        return True, DEFAULT_MODEL, origin
    except httpx.HTTPError as exc:
        return False, DEFAULT_MODEL, f"连不上本机模型：{exc}"
