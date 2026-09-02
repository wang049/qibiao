"""扫描页 OCR：走 Krow SDK 的 /v1/ocr，基址用当前识别服务。

Mac 调试可指向 https://api.krow.cn；Windows 现场包指向本地 Krow Server。
出表进程只打本机网关，由网关带登录凭据转发。没有 /v1/ocr 则回退 RapidOCR。
认字结果当原文，不用 OCR 模型出 JSON 核对表。
"""
from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from electrical_krow.config import origin_of
from electrical_krow.errors import ConfigError, LLMError
from electrical_krow.login import AuthSession
from electrical_krow.quota import json_payload, looks_like_quota, note_remote, quota_error_message

OCR_PATH = "/v1/ocr"


def ocr_endpoint_available(
    base_url: str,
    session: AuthSession,
    *,
    timeout: float = 8.0,
) -> bool:
    """探测识别服务是否提供 /v1/ocr。404 视为没有，回退本机 RapidOCR。"""
    try:
        origin = origin_of(base_url)
    except ConfigError:
        return False
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            resp = client.post(
                f"{origin}{OCR_PATH}",
                headers={
                    "Authorization": session.authorization(),
                    "Content-Type": "application/json",
                },
                json={"task": "table"},
            )
    except httpx.HTTPError:
        return False
    if resp.status_code in {404, 405, 501}:
        return False
    if resp.status_code == 401:
        return False
    if looks_like_quota(resp.status_code, resp.text, json_payload(resp.text)):
        note_remote(
            "ocr-probe",
            resp.status_code,
            resp.text,
            payload=json_payload(resp.text),
        )
    return resp.status_code < 500


def decode_image_payload(raw: str) -> bytes:
    blob = (raw or "").strip()
    if not blob:
        raise ValueError("没有图")
    if blob.startswith("data:"):
        _, _, b64 = blob.partition(",")
        blob = b64
    try:
        data = base64.b64decode(blob, validate=False)
    except Exception as exc:
        raise ValueError("图片不是合法的 base64") from exc
    if not data:
        raise ValueError("图片是空的")
    return data


def recognize_page(
    base_url: str,
    session: AuthSession,
    image: bytes,
    *,
    task: str = "table",
) -> dict[str, Any]:
    """单页识别。优先 SDK；没有 runtime 时按同一路径直 POST。"""
    origin = origin_of(base_url)
    kind = (task or "table").strip().lower() or "table"
    try:
        result = _recognize_via_sdk(origin, session, image, kind)
    except ImportError:
        result = _recognize_via_http(origin, session, image, kind)
    except Exception as exc:
        if looks_like_quota(0, str(exc)):
            note_remote("ocr", 0, str(exc))
        raise
    text = _result_text(result)
    success = bool(result.get("success", True)) and bool(text.strip())
    if result.get("error") and not text.strip():
        success = False
        err = str(result.get("error") or "")
        if looks_like_quota(0, err):
            note_remote("ocr", 0, err, model=str(result.get("model") or ""), payload=result)
    return {
        "success": success,
        "text": text,
        "pages": result.get("pages") or [],
        "task": kind,
        "error": result.get("error"),
        "model": result.get("model") or ("krow-ocr-table" if kind == "table" else "krow-ocr"),
    }


def prepare_page_ocr(settings: Any, item: Any) -> bool:
    """出表前探测 /v1/ocr。可用则 electrical 走网关 OCR，否则 RapidOCR。"""
    if item is None or getattr(item, "auth", None) is None:
        os.environ["SPEC_SHEET_PAGE_OCR"] = "0"
        os.environ.pop("SPEC_SHEET_OCR_TASK", None)
        return False
    try:
        origin = origin_of(settings.server_url)
    except ConfigError:
        os.environ["SPEC_SHEET_PAGE_OCR"] = "0"
        os.environ.pop("SPEC_SHEET_OCR_TASK", None)
        return False
    if not ocr_endpoint_available(
        origin,
        item.auth,
        timeout=min(float(getattr(settings, "timeout_sec", 8) or 8), 8.0),
    ):
        os.environ["SPEC_SHEET_PAGE_OCR"] = "0"
        os.environ.pop("SPEC_SHEET_OCR_TASK", None)
        return False
    os.environ["SPEC_SHEET_PAGE_OCR"] = "1"
    os.environ["SPEC_SHEET_OCR_TASK"] = "table"
    return True


def _recognize_via_sdk(
    origin: str,
    session: AuthSession,
    image: bytes,
    task: str,
) -> dict[str, Any]:
    from modules.ai.krow.ocr import KrowOCRService, OCRTask
    from modules.auth.krow_auth import KrowAuthAdapter

    adapter = KrowAuthAdapter(api_base_url=origin)
    try:
        adapter.set_api_key(session.access_token)
    except ValueError as exc:
        raise LLMError("OCR 需要 sk-user 凭据，请重新登录。") from exc
    service = KrowOCRService(auth_adapter=adapter)
    service._api_base = origin
    ocr_task = OCRTask.TABLE if task == "table" else OCRTask.OCR
    if task == "table":
        raw = service.recognize_table(image)
    else:
        raw = service.recognize_image(image, task=ocr_task)
    return _sdk_result_to_dict(raw, task)


def _recognize_via_http(
    origin: str,
    session: AuthSession,
    image: bytes,
    task: str,
) -> dict[str, Any]:
    b64 = base64.b64encode(image).decode("ascii")
    payload = {
        "task": task,
        "image": f"data:image/jpeg;base64,{b64}",
    }
    try:
        with httpx.Client(timeout=90.0, follow_redirects=False, trust_env=False) as client:
            resp = client.post(
                f"{origin}{OCR_PATH}",
                headers={
                    "Authorization": session.authorization(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise LLMError(f"连不上 OCR 服务：{exc}") from exc
    if resp.status_code >= 400:
        err_payload = json_payload(resp.text)
        note_remote(
            "ocr",
            resp.status_code,
            resp.text,
            model="krow-ocr-table" if task == "table" else "krow-ocr",
            payload=err_payload,
        )
        if resp.status_code == 401:
            fallback = "OCR 未授权（401）。请重新登录。"
        elif resp.status_code == 404:
            fallback = "识别服务没有 /v1/ocr。"
        else:
            fallback = f"OCR HTTP {resp.status_code}: {(resp.text or '')[:200]}"
        raise LLMError(
            quota_error_message(resp.status_code, resp.text, fallback=fallback)
        )
    try:
        body = resp.json()
    except ValueError as exc:
        note_remote("ocr", resp.status_code, resp.text)
        raise LLMError("OCR 响应不是 JSON") from exc
    if not isinstance(body, dict):
        note_remote("ocr", resp.status_code, str(body))
        raise LLMError("OCR 响应格式异常")
    err = str(body.get("error") or "")
    if err and looks_like_quota(resp.status_code, err, body):
        note_remote("ocr", resp.status_code, err, payload=body)
    return body


def _sdk_result_to_dict(raw: Any, task: str) -> dict[str, Any]:
    pages_out: list[dict[str, Any]] = []
    for page in getattr(raw, "pages", None) or []:
        pages_out.append(
            {
                "page_number": int(getattr(page, "page_number", 0) or 0),
                "text": str(getattr(page, "text", "") or ""),
                "confidence": float(getattr(page, "confidence", 0) or 0),
            }
        )
    text = str(getattr(raw, "text", "") or "")
    if not text.strip() and pages_out:
        text = "\n".join(p["text"] for p in pages_out if p.get("text"))
    return {
        "success": bool(getattr(raw, "success", True)),
        "text": text,
        "pages": pages_out,
        "task": task,
        "error": getattr(raw, "error", None),
        "model": "krow-ocr-table" if task == "table" else "krow-ocr",
    }


def _result_text(result: dict[str, Any]) -> str:
    text = str(result.get("text") or "").strip()
    if text:
        return text
    pages = result.get("pages") or []
    parts: list[str] = []
    for page in pages:
        if isinstance(page, dict):
            blob = str(page.get("text") or "").strip()
        else:
            blob = str(getattr(page, "text", "") or "").strip()
        if blob:
            parts.append(blob)
    return "\n".join(parts)
