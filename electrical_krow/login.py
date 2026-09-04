"""登录 Krow 云端（或本机 mock）。

按 KAD 指南：邮箱密码 POST /auth/login 拿 JWT，再 POST /api-keys
创建 sk-user- Key，交给后续 /v1/chat/completions（与 SDK 同一套凭据）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from krow_agent_sdk.auth import validate_api_key_format
from krow_agent_sdk.errors import InvalidKrowAPIKeyError

from electrical_krow.config import origin_of, suggest_site_api_url
from electrical_krow.errors import LoginError
from electrical_krow.paths import data_root
from electrical_krow.quota import json_payload, looks_like_quota, note_remote

# 云端契约在前；后面几条兼容旧 mock / 场所服务。
_LOGIN_ATTEMPTS: tuple[tuple[str, str], ...] = (
    ("/auth/login", "email"),
    ("/api/auth/login", "username"),
    ("/api/login", "username"),
    ("/login", "username"),
)
_KEY_PATHS = ("/api-keys", "/api/api-keys")
_KEY_NAME = "electrical-krow"
_MOBILE = re.compile(r"^1\d{10}$")


def _looks_like_mobile(value: str) -> bool:
    return bool(_MOBILE.fullmatch((value or "").strip()))


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
        raise LoginError("账号和密码都不能为空。")
    origin = origin_of(base_url)
    email = username.strip()
    if _looks_like_mobile(email):
        raise LoginError("请填写登录邮箱，不要填手机号。")
    last_error = ""
    seen: list[str] = []
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for path, kind in _LOGIN_ATTEMPTS:
            payload = (
                {"email": email, "password": password, "device_code": None}
                if kind == "email"
                else {
                    "username": email,
                    "password": password,
                    "remember_me": remember_me,
                    "device_id": device_id,
                }
            )
            try:
                resp = client.post(f"{origin}{path}", json=payload)
            except httpx.HTTPError as exc:
                raise LoginError(_connect_error(origin, exc)) from exc
            if resp.status_code in {404, 405}:
                data = _json_or_empty(resp)
                if data:
                    _note_quota_response("login", resp)
                    raise LoginError(_error_message(resp, f"登录失败 HTTP {resp.status_code}"))
                last_error = f"{path} HTTP {resp.status_code}"
                seen.append(last_error)
                continue
            if resp.status_code >= 400:
                _note_quota_response("login", resp)
                raise LoginError(_error_message(resp, f"登录失败 HTTP {resp.status_code}"))
            token, uname = _token_from_body(resp)
            if not token:
                raise LoginError("登录成功但响应里没有 access_token。")
            session = AuthSession(
                access_token=token,
                username=uname or email,
                source="password",
                raw=_json_or_empty(resp),
            )
            return _with_sdk_key(client, origin, session)
    raise LoginError(_login_unavailable(origin, seen, last_error))


def revoke_sdk_key(base_url: str, session: AuthSession, *, timeout: float = 15.0) -> None:
    """登出时吊销本机这把 Key，避免门户里堆 electrical-krow。"""
    raw = dict(session.raw or {})
    key_id = str(raw.get("api_key_id") or "").strip()
    jwt = str(raw.get("jwt") or "").strip()
    if not key_id:
        return
    origin = origin_of(base_url)
    token = jwt or session.access_token
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        _delete_key(client, origin, headers, key_id)
    cached = _read_key_cache()
    if cached.get("id") == key_id:
        _write_key_cache({})


def refresh_sdk_key(
    base_url: str, session: AuthSession, *, timeout: float = 30.0
) -> AuthSession:
    """chat 401 时作废缓存的 sk-user-，用登录 JWT 再发一把。"""
    raw = dict(session.raw or {})
    jwt = str(raw.get("jwt") or "").strip()
    if not jwt:
        raise LoginError("识别未授权，请重新登录。")
    origin = origin_of(base_url)
    jwt_session = AuthSession(
        access_token=jwt,
        username=session.username,
        source="password",
        raw=raw,
    )
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        refreshed = _with_sdk_key(client, origin, jwt_session, force_new=True)
    token = refreshed.access_token
    if not (token.startswith("sk-") or token.startswith("pk-pilot-")):
        raise LoginError("识别密钥已失效，请重新登录。")
    return refreshed


def _with_sdk_key(
    client: httpx.Client,
    origin: str,
    session: AuthSession,
    *,
    force_new: bool = False,
) -> AuthSession:
    """JWT 不能给 SDK / 长期抽取用。复用已落盘的 sk-user-，没有再创建。"""
    if session.access_token.startswith("sk-") or session.access_token.startswith(
        "pk-pilot-"
    ):
        return session
    headers = {
        "Authorization": session.authorization(),
        "Content-Type": "application/json",
    }
    listed = _list_keys(client, origin, headers)
    cached = _read_key_cache()
    cached_ok = (
        not force_new
        and cached.get("origin") == origin
        and cached.get("username") == session.username
        and str(cached.get("id") or "") in {str(item.get("id") or "") for item in listed}
    )
    if cached_ok:
        try:
            key = validate_api_key_format(str(cached.get("key") or ""))
        except InvalidKrowAPIKeyError:
            key = ""
        if key:
            _delete_named_keys(
                client, origin, headers, listed, keep_id=str(cached.get("id") or "")
            )
            return _session_with_key(session, key, str(cached.get("id") or ""))
    _delete_named_keys(client, origin, headers, listed, keep_id="")
    created, last = _create_key(client, origin, headers)
    if created is None and "最多" in last:
        leftover = _list_keys(client, origin, headers)
        _delete_named_keys(client, origin, headers, leftover, keep_id="")
        created, last = _create_key(client, origin, headers)
    if created is None:
        raw = dict(session.raw or {})
        if last:
            raw["api_key_error"] = last
        return AuthSession(
            access_token=session.access_token,
            username=session.username,
            source=session.source,
            raw=raw,
        )
    _write_key_cache(
        {
            "origin": origin,
            "username": session.username,
            "id": created["id"],
            "key": created["key"],
        }
    )
    return _session_with_key(session, created["key"], created["id"])


def _session_with_key(session: AuthSession, key: str, key_id: str) -> AuthSession:
    raw = dict(session.raw or {})
    raw["jwt"] = session.access_token
    raw["api_key_id"] = key_id
    return AuthSession(
        access_token=key,
        username=session.username,
        source="password",
        raw=raw,
    )


def _list_keys(
    client: httpx.Client, origin: str, headers: dict[str, str]
) -> list[dict[str, Any]]:
    for path in _KEY_PATHS:
        try:
            resp = client.get(f"{origin}{path}", headers=headers)
        except httpx.HTTPError:
            continue
        if resp.status_code in {404, 405}:
            continue
        if resp.status_code >= 400:
            continue
        data = _json_or_empty(resp)
        rows = data.get("keys")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
        raw_list = data.get("data")
        if isinstance(raw_list, list):
            return [item for item in raw_list if isinstance(item, dict)]
    return []


def _create_key(
    client: httpx.Client, origin: str, headers: dict[str, str]
) -> tuple[dict[str, str] | None, str]:
    last = ""
    payload = {"name": _KEY_NAME}
    for path in _KEY_PATHS:
        try:
            resp = client.post(f"{origin}{path}", headers=headers, json=payload)
        except httpx.HTTPError as exc:
            last = str(exc)
            continue
        if resp.status_code in {404, 405}:
            last = f"{path} 不存在"
            continue
        if resp.status_code >= 400:
            last = _error_message(resp, f"创建 API Key HTTP {resp.status_code}")
            _note_quota_response("api-keys", resp)
            continue
        data = _json_or_empty(resp)
        key = str(data.get("key") or data.get("api_key") or "").strip()
        key_id = str(data.get("id") or "").strip()
        if not key:
            last = "创建 API Key 成功但响应里没有 key"
            continue
        try:
            key = validate_api_key_format(key)
        except InvalidKrowAPIKeyError:
            last = "服务端返回的 API Key 格式不正确"
            continue
        return {"key": key, "id": key_id}, ""
    return None, last


def _delete_named_keys(
    client: httpx.Client,
    origin: str,
    headers: dict[str, str],
    listed: list[dict[str, Any]],
    *,
    keep_id: str,
) -> None:
    for item in listed:
        name = str(item.get("name") or "")
        key_id = str(item.get("id") or "")
        if name != _KEY_NAME or not key_id or key_id == keep_id:
            continue
        _delete_key(client, origin, headers, key_id)


def _delete_key(
    client: httpx.Client, origin: str, headers: dict[str, str], key_id: str
) -> None:
    for path in _KEY_PATHS:
        try:
            resp = client.delete(f"{origin}{path}/{key_id}", headers=headers)
        except httpx.HTTPError:
            continue
        if resp.status_code not in {404, 405}:
            return


def _key_cache_path() -> Path:
    return data_root() / "krow-sdk-key.json"


def _read_key_cache() -> dict[str, str]:
    path = _key_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def _write_key_cache(data: dict[str, str]) -> None:
    path = _key_cache_path()
    try:
        if not data:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
    except OSError:
        pass


def _json_or_empty(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_message(resp: httpx.Response, fallback: str) -> str:
    data = _json_or_empty(resp)
    msg = data.get("error") or data.get("error_message") or data.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    clipped = _clip(resp.text)
    return f"{fallback}: {clipped}" if clipped else fallback


def _note_quota_response(kind: str, resp: httpx.Response) -> None:
    payload = json_payload(resp.text)
    if looks_like_quota(resp.status_code, resp.text, payload):
        note_remote(kind, resp.status_code, resp.text, payload=payload)


def _token_from_body(resp: httpx.Response) -> tuple[str, str]:
    data = _json_or_empty(resp)
    if not data:
        return "", ""
    if data.get("success") is False:
        msg = data.get("error") or data.get("error_message") or data.get("message") or "登录被拒绝"
        raise LoginError(str(msg))
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
        or data.get("email")
        or user.get("email")
        or user.get("username")
        or user.get("nickname")
        or credential.get("username")
        or ""
    )
    return str(token).strip(), str(username).strip()


def _login_unavailable(origin: str, seen: list[str], last_error: str) -> str:
    """全是 404/405 空响应时，多半把门户网页当成了识别 API。"""
    detail = "；".join(seen) if seen else (last_error or "均 404")
    msg = (
        f"没有可用的登录接口（{detail}）。"
        "当前地址更像门户或控制台网页（可以打开页面，但不接受登录 POST），不是识别 API。"
    )
    hinted = suggest_site_api_url(origin)
    if hinted:
        msg += (
            f" 请把 config.ini 的 server_url 改成 {hinted}"
            "（仪表盘「快速开始」Base URL 去掉 /v1），不要填门户或控制台。"
        )
    else:
        msg += (
            " 请改成现场识别 API 根地址（仪表盘 Base URL 去掉 /v1，"
            "例如 https://rdapi.aurobaytech-t.com）。"
        )
    return msg


def _connect_error(origin: str, exc: BaseException) -> str:
    text = str(exc)
    dns = (
        "nodename nor servname" in text
        or "Name or service not known" in text
        or "getaddrinfo failed" in text
        or "11001" in text
    )
    if dns:
        hinted = suggest_site_api_url(origin)
        extra = f" 现场识别 API 是 {hinted}。" if hinted else ""
        return (
            f"解析不到登录服务 {origin}。"
            "请检查网络和 DNS，以及 config.ini 里的 server_url。"
            + extra
        )
    return f"连不上登录服务：{exc}"


def _clip(text: str, n: int = 240) -> str:
    raw = (text or "").strip().replace("\n", " ")
    return raw[:n]
