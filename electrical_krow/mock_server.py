"""本机联调用的识别服务：登录 + /v1/chat/completions。"""
from __future__ import annotations

import argparse
import time
import uuid

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

DEMO_USER = "demo"
DEMO_PASSWORD = "demo"
DEMO_TOKEN = "mock-token-electrical-krow"


class LoginBody(BaseModel):
    username: str
    password: str
    remember_me: bool = True
    device_id: str = ""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatBody(BaseModel):
    model: str = "qwen2.5:7b"
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.0


def create_app() -> FastAPI:
    app = FastAPI(title="电子电器 · SOR填表（联调）", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "kind": "local-dev"}

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

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> dict[str, object]:
        _require_auth(authorization)
        return {
            "object": "list",
            "data": [{"id": "qwen2.5:7b", "object": "model"}],
        }

    @app.post("/v1/chat/completions")
    def chat(
        body: ChatBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_auth(authorization)
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


def _require_auth(authorization: str | None) -> None:
    raw = (authorization or "").strip()
    if raw.startswith("Bearer "):
        token = raw[7:].strip()
    else:
        token = raw
    if token == DEMO_TOKEN or token.startswith("sk-") or token.startswith("pk-pilot-"):
        return
    raise HTTPException(401, "需要登录")


def _reply(messages: list[ChatMessage]) -> str:
    blob = "\n".join(m.content for m in messages)
    if "只输出 JSON" in blob or "第一个字符是 {" in blob:
        return '{"ok":true,"source":"local-dev","rows":[]}'
    last = next((m.content for m in reversed(messages) if m.role == "user"), "")
    preview = last.replace("\n", " ").strip()[:40]
    return f"连接成功。{(' 问：' + preview) if preview else ''}"


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本机联调识别服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args(argv)
    print(f"联调识别：http://{args.host}:{args.port}/  账号 demo / demo", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
