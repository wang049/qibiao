"""登录指定场所的识别服务。

两种方式：
1. 用户名 + 密码 → POST /api/auth/login
2. API key → krow_agent_sdk.auth 校验格式后作为 Bearer

不走公网识别。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from krow_agent_sdk.auth import validate_api_key_format
from krow_agent_sdk.errors import InvalidKrowAPIKeyError

from electrical_krow.config import require_private_endpoint
from electrical_krow.errors import LoginError

LOGIN_PATHS = ("/api/auth/login", "/api/login", "/login")


@dataclass(frozen=True)
class AuthSession:
    access_token: str
    username: str
    token_type: str = "Bearer"
    source: str = "password"
    raw: dict[str, Any] | None = None

    def authorization(self) -> str:
        kind = self.token_type or "Bearer"
        return f"{kind} {self.access_token}"


def login_with_api_key(api_key: str, *, username: str = "") -> AuthSession:
    try:
        key = validate_api_key_format(api_key)
    except InvalidKrowAPIKeyError as exc:
        raise LoginError("API key 格式不正确。需要 sk- 或 pk-pilot- 前缀。") from exc
    return AuthSession(
        access_token=key,
        username=username or "api-key",
        source="api_key",
    )


def login_with_password(
    base_url: str,
    username: str,
    password: str,
    *,
    timeout: float = 30.0,
    remember_me: bool = True,
    device_id: str = "electrical-krow",
) -> AuthSession:
    if not (username or "").strip() or not (password or ""):
        raise LoginError("用户名和密码都不能为空。")
    origin = require_private_endpoint(base_url)
    payload = {
        "username": username.strip(),
        "password": password,
        "remember_me": remember_me,
        "device_id": device_id,
    }
    last_error = ""
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for path in LOGIN_PATHS:
            try:
                resp = client.post(f"{origin}{path}", json=payload)
            except httpx.HTTPError as exc:
                raise LoginError(f"连不上登录服务：{exc}") from exc
            if resp.status_code == 404:
                last_error = f"{path} 不存在"
                continue
            if resp.status_code >= 400:
                raise LoginError(
                    f"登录失败 HTTP {resp.status_code}: {_clip(resp.text)}"
                )
            token, uname = _token_from_body(resp)
            if not token:
                raise LoginError("登录成功但响应里没有 access_token。")
            return AuthSession(
                access_token=token,
                username=uname or username.strip(),
                source="password",
                raw=_json_or_empty(resp),
            )
    raise LoginError(f"没有可用的登录接口（{last_error or '均 404'}）。")


def _json_or_empty(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _token_from_body(resp: httpx.Response) -> tuple[str, str]:
    data = _json_or_empty(resp)
    if not data:
        return "", ""
    credential = data.get("credential") if isinstance(data.get("credential"), dict) else {}
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    token = (
        data.get("access_token")
        or data.get("token")
        or credential.get("token")
        or nested.get("access_token")
        or nested.get("token")
        or ""
    )
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    username = (
        data.get("username")
        or user.get("username")
        or credential.get("username")
        or ""
    )
    if data.get("success") is False:
        msg = data.get("error_message") or data.get("message") or "登录被拒绝"
        raise LoginError(str(msg))
    return str(token).strip(), str(username).strip()


def _clip(text: str, n: int = 240) -> str:
    raw = (text or "").strip().replace("\n", " ")
    return raw[:n]
