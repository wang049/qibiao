"""识别请求：OpenAI 兼容 /v1/chat/completions，形态对齐出表分段抽取。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from electrical_krow.config import require_private_endpoint
from electrical_krow.errors import LLMError
from electrical_krow.login import AuthSession

try:
    from modules.ai.krow.provider import KrowLLMProvider

    CHAT_PATH = getattr(KrowLLMProvider, "CHAT_ENDPOINT", "/v1/chat/completions")
    MODELS_PATH = getattr(KrowLLMProvider, "MODELS_ENDPOINT", "/v1/models")
except Exception:
    CHAT_PATH = "/v1/chat/completions"
    MODELS_PATH = "/v1/models"


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
    raw: dict[str, Any]
    finish_reason: str = "stop"


def complete(
    base_url: str,
    session: AuthSession,
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float = 0.0,
    timeout: float = 90.0,
) -> ChatResult:
    origin = require_private_endpoint(base_url)
    url = f"{origin}{CHAT_PATH}"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    headers = {
        "Authorization": session.authorization(),
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise LLMError(f"连不上识别服务：{exc}") from exc
    if 300 <= resp.status_code < 400:
        raise LLMError("识别服务返回了重定向，已拒绝。")
    if resp.status_code == 401:
        raise LLMError("识别未授权（401）。请重新登录。")
    if resp.status_code >= 400:
        raise LLMError(f"识别服务 HTTP {resp.status_code}: {_clip(resp.text)}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise LLMError(f"识别响应不是 JSON: {_clip(resp.text)}") from exc
    if not isinstance(body, dict):
        raise LLMError("识别响应格式异常。")
    try:
        content = body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"识别响应缺少 choices: {_clip(str(body))}") from exc
    return ChatResult(
        content=str(content),
        model=str(body.get("model") or model),
        raw=body,
        finish_reason=str(
            (body.get("choices") or [{}])[0].get("finish_reason") or "stop"
        ),
    )


def list_models(
    base_url: str,
    session: AuthSession,
    *,
    timeout: float = 15.0,
) -> list[str]:
    origin = require_private_endpoint(base_url)
    headers = {"Authorization": session.authorization()}
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            resp = client.get(f"{origin}{MODELS_PATH}", headers=headers)
    except httpx.HTTPError as exc:
        raise LLMError(f"连不上识别服务模型列表：{exc}") from exc
    if resp.status_code >= 400:
        raise LLMError(f"模型列表 HTTP {resp.status_code}: {_clip(resp.text)}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise LLMError("模型列表不是 JSON。") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            names.append(str(item["id"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _clip(text: str, n: int = 300) -> str:
    return (text or "").strip().replace("\n", " ")[:n]
