"""登录页：先登录，再把识别请求转到指定场所的模型服务。

只监听 127.0.0.1。出表程序可把 SPEC_SHEET_LLM_URL 指到这里。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from electrical_krow.config import Settings, is_loopback_host, load_settings
from electrical_krow.errors import ConfigError, LLMError, LoginError
from electrical_krow.llm import complete
from electrical_krow.login import login_with_api_key, login_with_password
from electrical_krow.session import SessionStore, StoredSession

COOKIE = "electrical_krow_sid"
FRONTEND = Path(__file__).resolve().parent / "frontend"


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""
    api_key: str = ""


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatIn(BaseModel):
    model: str = ""
    messages: list[ChatMessageIn] = Field(default_factory=list)
    temperature: float = 0.0


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    app = FastAPI(title="电子电器 · SOR填表", docs_url=None, redoc_url=None)
    app.state.settings = cfg
    app.state.store = SessionStore()

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        path = FRONTEND / "index.html"
        if not path.is_file():
            return HTMLResponse("<p>找不到界面文件。</p>", status_code=500)
        return HTMLResponse(
            path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        logged = app.state.store.default() is not None
        try:
            origin = cfg.server_origin()
            server_error = ""
        except ConfigError as exc:
            origin = ""
            server_error = str(exc)
        return {
            "ok": not server_error,
            "logged_in": logged,
            "server": origin,
            "model": cfg.chat_model,
            "detail": server_error,
        }

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, object]:
        try:
            if (body.api_key or "").strip():
                auth = login_with_api_key(body.api_key.strip(), username=body.username)
            else:
                auth = login_with_password(
                    cfg.server_url,
                    body.username,
                    body.password,
                    timeout=min(cfg.timeout_sec, 30.0),
                )
        except (LoginError, ConfigError) as exc:
            raise HTTPException(401, str(exc)) from exc
        stored = request.app.state.store.put(auth)
        response.set_cookie(
            COOKIE,
            stored.sid,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return {
            "ok": True,
            "username": auth.username,
            "source": auth.source,
        }

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        request.app.state.store.drop(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request) -> dict[str, object]:
        item = _session_from(request, None)
        if item is None:
            return {"ok": False, "logged_in": False}
        return {
            "ok": True,
            "logged_in": True,
            "username": item.auth.username,
            "source": item.auth.source,
        }

    @app.post("/v1/chat/completions")
    def chat_completions(
        body: ChatIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _session_from(request, authorization)
        if item is None:
            raise HTTPException(401, "请先登录")
        model = (body.model or cfg.chat_model).strip() or cfg.chat_model
        messages = [{"role": m.role, "content": m.content} for m in body.messages]
        try:
            result = complete(
                cfg.server_url,
                item.auth,
                messages,
                model=model,
                temperature=body.temperature,
                timeout=cfg.timeout_sec,
            )
        except (LLMError, ConfigError) as exc:
            raise HTTPException(502, str(exc)) from exc
        return result.raw

    if FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")
    return app


def _bearer(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return ""


def _session_from(request: Request, authorization: str | None) -> StoredSession | None:
    sessions = request.app.state.store
    token = _bearer(authorization)
    if token:
        found = sessions.by_token(token)
        if found is not None:
            return found
        if token == "local":
            return sessions.default()
    sid = request.cookies.get(COOKIE)
    found = sessions.get(sid)
    if found is not None:
        return found
    return None


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电子电器 · SOR填表")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    settings = load_settings()
    host = args.host or settings.gateway_host
    port = args.port or settings.gateway_port
    if not is_loopback_host(host):
        raise SystemExit("只允许绑本机回环（127.0.0.1 / localhost）。")
    print(f"电子电器 · SOR填表：http://{host}:{port}/", flush=True)
    print(f"识别服务：{settings.server_url}", flush=True)
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
