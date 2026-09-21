"""识别请求：OpenAI 兼容 /v1/chat/completions，形态对齐出表分段抽取。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from electrical_krow.config import origin_of
from electrical_krow.errors import LLMError
from electrical_krow.login import AuthSession
from electrical_krow.quota import json_payload, note_remote, quota_error_message
from electrical_krow.vision import is_text_chat_model

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


def looks_like_model_unavailable(status: int = 0, body: str = "") -> bool:
    """现场/云端把已下线模型标成 400 unavailable，不能再按分段失败悄悄跳过。"""
    blob = f"{status} {body or ''}"
    low = blob.lower()
    if "try another model" in low:
        return True
    if "model" in low and "currently unavailable" in low:
        return True
    if "model_not_found" in low or "model not found" in low:
        return True
    if "模型" in blob and "不可用" in blob:
        return True
    return "没有该模型" in blob


def chat_model_candidates(names: list[str], preferred: str = "") -> list[str]:
    """出表只用 chat 模型。OCR / 看图模型不进候选。"""
    pref = (preferred or "").strip()
    listed = [(n or "").strip() for n in names if (n or "").strip()]

    def usable(name: str) -> bool:
        low = name.lower()
        if not name:
            return False
        if "ocr" in low or "-vl" in low or "vision" in low:
            return False
        return True

    out: list[str] = []
    if pref and usable(pref) and (not listed or pref in listed):
        out.append(pref)
    for name in listed:
        if name not in out and usable(name) and is_text_chat_model(name):
            out.append(name)
    for name in listed:
        if name not in out and usable(name):
            out.append(name)
    return out


def assistant_text(message: Any) -> str:
    """识别回包里的可解析正文。现场 deepseek 常把 JSON 放在 reasoning_content，content 为空。"""
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return ""
    for key in ("content", "reasoning_content", "reasoning"):
        blob = _flatten_text(message.get(key))
        if blob:
            return blob
    return ""


def _flatten_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts).strip()
    return ""


def _with_content(body: dict[str, Any], content: str) -> dict[str, Any]:
    choices = list(body.get("choices") or [])
    if not choices or not isinstance(choices[0], dict):
        return body
    message = dict(choices[0].get("message") or {})
    if (message.get("content") or "").strip():
        return body
    message["content"] = content
    first = dict(choices[0])
    first["message"] = message
    out = dict(body)
    out["choices"] = [first, *choices[1:]]
    return out


def complete(
    base_url: str,
    session: AuthSession,
    messages: list[dict[str, Any]],
    *,
    model: str,
    temperature: float = 0.0,
    timeout: float = 90.0,
    extra: dict[str, Any] | None = None,
) -> ChatResult:
    origin = origin_of(base_url)
    url = f"{origin}{CHAT_PATH}"
    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    # 只透传推理/长度控制字段；不让调用方随意改上游请求
    for key in ("thinking", "reasoning_effort", "max_tokens"):
        if extra and extra.get(key) is not None:
            payload[key] = extra[key]
    headers = {
        "Authorization": session.authorization(),
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            resp = client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise LLMError(f"连不上识别服务：{exc}") from exc
    if 300 <= resp.status_code < 400:
        note_remote("chat", resp.status_code, resp.text, model=model)
        raise LLMError("识别服务返回了重定向，已拒绝。")
    if resp.status_code >= 400:
        err_payload = json_payload(resp.text)
        note_remote(
            "chat",
            resp.status_code,
            resp.text,
            model=model,
            payload=err_payload,
        )
        if resp.status_code == 401:
            fallback = "识别未授权（401）。请重新登录。"
        else:
            fallback = f"识别服务 HTTP {resp.status_code}: {_clip(resp.text)}"
        raise LLMError(
            quota_error_message(resp.status_code, resp.text, fallback=fallback)
        )
    try:
        body = resp.json()
    except ValueError as exc:
        note_remote("chat", resp.status_code, resp.text, model=model)
        raise LLMError(f"识别响应不是 JSON: {_clip(resp.text)}") from exc
    if not isinstance(body, dict):
        note_remote("chat", resp.status_code, str(body), model=model)
        raise LLMError("识别响应格式异常。")
    error = body.get("error")
    if error and not body.get("choices"):
        blob = error if isinstance(error, str) else str(error)
        note_remote(
            "chat",
            resp.status_code,
            blob,
            model=model,
            payload=body,
        )
        raise LLMError(
            quota_error_message(
                resp.status_code,
                blob,
                fallback=f"识别响应错误: {_clip(blob)}",
            )
        )
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        note_remote("chat", resp.status_code, str(body), model=model, payload=body)
        raise LLMError(f"识别响应缺少 choices: {_clip(str(body))}") from exc
    content = assistant_text(message)
    if content:
        body = _with_content(body, content)
    note_remote("chat", resp.status_code, "", model=model, payload=body)
    return ChatResult(
        content=content,
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
    origin = origin_of(base_url)
    headers = {"Authorization": session.authorization()}
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            resp = client.get(f"{origin}{MODELS_PATH}", headers=headers)
            if resp.status_code == 401:
                resp = client.get(f"{origin}{MODELS_PATH}")
    except httpx.HTTPError as exc:
        raise LLMError(f"连不上识别服务模型列表：{exc}") from exc
    if resp.status_code >= 400:
        note_remote("models", resp.status_code, resp.text)
        raise LLMError(
            quota_error_message(
                resp.status_code,
                resp.text,
                fallback=f"模型列表 HTTP {resp.status_code}: {_clip(resp.text)}",
            )
        )
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
