"""识别服务返回里有没有「算力/额度用尽」。

krow 没有单独的算力字段，只能从 HTTP 状态和正文里认。命中时打 [算力] 日志，
并写到 data 目录的 quota.log，方便对照门户「今日 0 CP」。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Any

from electrical_krow.paths import data_root

LOG_PREFIX = "[算力]"

# 正文里这些词才算额度/算力用尽；不要用单独的 credit，会误伤 credential。
_QUOTA_MARKERS = (
    "算力不足",
    "算力用尽",
    "算力已用尽",
    "没有算力",
    "无算力",
    "算力不够",
    "额度不足",
    "额度已用尽",
    "额度用尽",
    "余额不足",
    "配额不足",
    "配额已用尽",
    "点数不足",
    "用量已尽",
    "insufficient_quota",
    "quota_exceeded",
    "quota exceeded",
    "exceeded your current quota",
    "out of credits",
    "out of credit",
    "no credits",
    "credit exhausted",
    "insufficient credits",
    "insufficient balance",
    "insufficient funds",
    "payment required",
    "billing_hard_limit",
    "billing hard limit",
)
_QUOTA_RE = re.compile(
    r"(?:算力|额度|配额|点数|余额).{0,8}(?:不足|用尽|已尽|不够|用完|耗尽)"
    r"|(?:insufficient[_\s-]?quota)|(?:quota[_\s-]?exceeded)",
    re.IGNORECASE,
)

_lock = threading.Lock()


def classify_remote(
    status: int,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """quota / rate_limit / auth / other / ok。"""
    text = _haystack(status, body, payload)
    if _looks_like_quota(status, text):
        return "quota"
    if status == 429 or "rate limit" in text or "too many requests" in text or "限流" in text:
        return "rate_limit"
    if status == 401:
        return "auth"
    if status >= 400:
        return "other"
    error = _error_blob(payload)
    if error:
        return "other"
    return "ok"


def looks_like_quota(
    status: int,
    body: str = "",
    payload: dict[str, Any] | None = None,
) -> bool:
    return classify_remote(status, body, payload) == "quota"


def note_remote(
    kind: str,
    status: int,
    body: str = "",
    *,
    model: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    """写一条 [算力] 日志，返回判定结果。"""
    verdict = classify_remote(status, body, payload)
    if verdict == "ok" and kind != "chat":
        return verdict
    line = format_log_line(
        kind,
        status,
        verdict,
        body=body,
        model=model,
        payload=payload,
    )
    emit(line)
    return verdict


def quota_error_message(status: int, body: str, *, fallback: str) -> str:
    clipped = _clip(body)
    if looks_like_quota(status, body):
        if clipped:
            return f"识别服务提示算力不足（HTTP {status}）：{clipped}"
        return f"识别服务提示算力不足（HTTP {status}）。"
    return fallback


def format_log_line(
    kind: str,
    status: int,
    verdict: str,
    *,
    body: str = "",
    model: str = "",
    payload: dict[str, Any] | None = None,
) -> str:
    label = {
        "quota": "算力不足",
        "rate_limit": "限流",
        "auth": "未授权",
        "other": "其他错误",
        "ok": "未提示不足",
    }.get(verdict, verdict)
    parts = [
        LOG_PREFIX,
        kind,
        f"HTTP {status}",
        f"判定={label}",
    ]
    if model:
        parts.append(f"model={model}")
    usage = usage_brief(payload)
    if usage:
        parts.append(f"usage={usage}")
    if verdict != "ok":
        clipped = _clip(body, 240)
        if clipped:
            parts.append(f"body={clipped}")
    return " ".join(parts)


def usage_brief(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    usage = payload.get("usage")
    chunks: list[str] = []
    if isinstance(usage, dict):
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "credits",
            "credit",
            "cp",
            "points",
        ):
            if usage.get(key) is not None:
                chunks.append(f"{key}={usage[key]}")
        if not chunks:
            extra = {k: v for k, v in usage.items() if v is not None}
            if extra:
                chunks.append(_clip(json.dumps(extra, ensure_ascii=False), 80))
    for key in ("credits", "credit", "cp", "points"):
        if payload.get(key) is not None and f"{key}=" not in " ".join(chunks):
            chunks.append(f"{key}={payload[key]}")
    return " ".join(chunks)


def emit(line: str) -> None:
    text = (line or "").strip()
    if not text:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = f"{stamp} {text}"
    print(row, flush=True)
    try:
        path = data_root() / "quota.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(row + "\n")
    except OSError:
        pass


def json_payload(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw.startswith("{") and not raw.startswith("["):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _looks_like_quota(status: int, text: str) -> bool:
    if status == 402:
        return True
    if _QUOTA_RE.search(text):
        return True
    folded = text.lower()
    return any(marker.lower() in folded for marker in _QUOTA_MARKERS)


def _haystack(
    status: int,
    body: str,
    payload: dict[str, Any] | None,
) -> str:
    parts = [str(status), body or ""]
    error = _error_blob(payload)
    if error:
        parts.append(error)
    if isinstance(payload, dict):
        for key in ("code", "error_code", "type", "message", "error_message"):
            value = payload.get(key)
            if value:
                parts.append(str(value))
    return " ".join(parts)


def _error_blob(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        bits = [
            str(error.get("message") or ""),
            str(error.get("type") or ""),
            str(error.get("code") or ""),
        ]
        return " ".join(bit for bit in bits if bit)
    return ""


def _clip(text: str, n: int = 240) -> str:
    return (text or "").strip().replace("\n", " ")[:n]
