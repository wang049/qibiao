"""本机联调用的识别服务：登录 + /v1/chat/completions。

设 KROW_MOCK_UPSTREAM（如 http://127.0.0.1:11434）时，chat 转到本机 Ollama。
未设则回固定 JSON，供单测和连通检查。
"""
from __future__ import annotations

import argparse
import os
import time
import uuid
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

DEMO_USER = "demo"
DEMO_PASSWORD = "demo"
DEMO_TOKEN = "mock-token-electrical-krow"


def _upstream() -> str:
    return (os.environ.get("KROW_MOCK_UPSTREAM") or "").strip().rstrip("/")


class LoginBody(BaseModel):
    username: str
    password: str
    remember_me: bool = True
    device_id: str = ""


class CloudLoginBody(BaseModel):
    email: str = ""
    username: str = ""
    password: str
    device_code: str | None = None


class KeyCreateBody(BaseModel):
    name: str = "electrical-krow"


class ChatMessage(BaseModel):
    role: str
    content: Any = ""


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "qwen2.5:7b"
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.0


class OcrBody(BaseModel):
    image: str = ""
    task: str = "table"


def create_app() -> FastAPI:
    app = FastAPI(title="电子电器 · SOR填表（联调）", docs_url=None, redoc_url=None)
    app.state.api_keys = []

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "kind": "local-dev",
            "upstream": _upstream(),
        }

    @app.post("/api/auth/login")
    def login(body: LoginBody) -> dict[str, object]:
        if body.username != DEMO_USER or body.password != DEMO_PASSWORD:
            raise HTTPException(401, "用户名或密码不对（mock 账号是 demo / demo）")
        return {
            "success": True,
            "access_token": DEMO_TOKEN,
            "token_type": "Bearer",
            "username": DEMO_USER,
            "user": {"username": DEMO_USER, "user_id": "mock-demo"},
        }

    @app.post("/auth/login")
    def cloud_login(body: CloudLoginBody) -> dict[str, object]:
        account = (body.email or body.username or "").strip()
        if account not in {DEMO_USER, "demo@krow.cn"} or body.password != DEMO_PASSWORD:
            raise HTTPException(401, "用户名或密码错误")
        return {
            "access_token": "eyJmock." + DEMO_TOKEN,
            "refresh_token": "rt-mock-electrical-krow",
            "token_type": "Bearer",
            "expires_in": 604800,
            "refresh_expires_in": 604800,
            "user": {
                "id": "mock-demo",
                "email": "demo@krow.cn",
                "tier": "free",
            },
        }

    @app.post("/api-keys")
    def create_key(
        body: KeyCreateBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_auth(authorization)
        ident = uuid.uuid4().hex[:8]
        secret = uuid.uuid4().hex[:32]
        full = f"sk-user-{ident}{secret}"
        info = {
            "id": str(uuid.uuid4()),
            "name": body.name,
            "key": full,
            "key_prefix": f"sk-user-{ident[:4]}...{secret[-4:]}",
        }
        stored = {k: v for k, v in info.items() if k != "key"}
        app.state.api_keys.append(stored)
        return info

    @app.get("/api-keys")
    def list_keys(authorization: str | None = Header(default=None)) -> dict[str, object]:
        _require_auth(authorization)
        return {"keys": list(getattr(app.state, "api_keys", []))}

    @app.delete("/api-keys/{key_id}")
    def delete_key(
        key_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_auth(authorization)
        keys = getattr(app.state, "api_keys", [])
        app.state.api_keys = [item for item in keys if str(item.get("id")) != key_id]
        return {"success": True}

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> dict[str, object]:
        _require_auth(authorization)
        return {
            "object": "list",
            "data": [
                {"id": "qwen2.5:7b", "object": "model"},
                {"id": "krow-ocr-table", "object": "model"},
            ],
        }

    @app.post("/v1/ocr")
    def ocr(
        body: OcrBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_auth(authorization)
        if not (body.image or "").strip():
            raise HTTPException(400, "需要 image")
        task = body.task or "table"
        text = (
            "HVDC bus voltage 380 V\n"
            "Min level for limited performance 性能限制时的最低电压 380"
        )
        return {
            "success": True,
            "text": text,
            "pages": [{"page_number": 1, "text": text, "confidence": 1.0}],
            "task": task,
            "error": None,
            "model": "krow-ocr-table" if task == "table" else "krow-ocr",
        }

    @app.post("/v1/chat/completions")
    def chat(
        body: ChatBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_auth(authorization)
        forwarded = _forward_chat(body.model_dump())
        if forwarded is not None:
            return forwarded
        text = _reply(body.messages)
        return {
            "id": f"chatcmpl-mock-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": text},
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    return app


def _forward_chat(payload: dict[str, Any]) -> dict[str, Any] | None:
    origin = _upstream()
    if not origin:
        return None
    timeout = float(os.environ.get("KROW_LLM_TIMEOUT", "90"))
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            resp = client.post(f"{origin}/v1/chat/completions", json=payload)
    except httpx.HTTPError:
        return None
    if resp.status_code >= 400:
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not body.get("choices"):
        return None
    return body


def _require_auth(authorization: str | None) -> None:
    raw = (authorization or "").strip()
    if raw.startswith("Bearer "):
        token = raw[7:].strip()
    else:
        token = raw
    if (
        token == DEMO_TOKEN
        or token.endswith(DEMO_TOKEN)
        or token.startswith("sk-")
        or token.startswith("pk-pilot-")
        or token.startswith("eyJ")
    ):
        return
    raise HTTPException(401, "需要登录")


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item.get("type") in {"image_url", "image"} or "image_url" in item:
                parts.append("[image]")
        return "\n".join(parts)
    return str(content or "")


def _reply(messages: list[ChatMessage]) -> str:
    blob = "\n".join(_content_text(m.content) for m in messages)
    if "[image]" in blob:
        return (
            "HVDC bus voltage 380 V\n"
            "Min level for limited performance 性能限制时的最低电压 380"
        )
    if "只输出 JSON" in blob or "第一个字符是 {" in blob:
        return '{"ok":true,"source":"local-dev","rows":[]}'
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    preview = _content_text(last).replace("\n", " ").strip()[:40]
    return f"连接成功。{(' 问：' + preview) if preview else ''}"


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本机联调识别服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args(argv)
    print(f"联调识别：http://{args.host}:{args.port}/  账号 demo / demo", flush=True)
    upstream = _upstream()
    if upstream:
        print(f"chat 转到 {upstream}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
