"""配置：识别服务地址、登录页端口，禁止公网 Cloud。"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlparse

from electrical_krow.errors import ConfigError

_BLOCKED_HOST_SUFFIXES = (".krow.cn",)
_BLOCKED_HOSTS = {"krow.cn", "api.krow.cn", "www.krow.cn", "api-staging.krow.cn"}


def hostname_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    return ((parsed.hostname or "").strip().lower()).strip("[]")


def is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def origin_of(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        raise ConfigError("未配置识别服务地址。请设置 KROW_SERVER_URL。")
    if raw.endswith("/v1"):
        raw = raw[:-3]
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError(f"识别服务地址不合法: {url}")
    host = hostname_of(raw)
    if not host:
        raise ConfigError(f"识别服务地址不合法: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def require_private_endpoint(url: str) -> str:
    """允许本机或指定场所内网地址，拒绝公网 *.krow.cn。"""
    origin = origin_of(url)
    host = hostname_of(origin)
    if host in _BLOCKED_HOSTS or any(host.endswith(s) for s in _BLOCKED_HOST_SUFFIXES):
        raise ConfigError(
            "规格书不得发往公网识别服务。"
            "请改用指定场所内网地址，或本机联调地址。"
        )
    return origin


@dataclass(frozen=True)
class Settings:
    server_url: str
    chat_model: str
    username: str
    password: str
    api_key: str
    gateway_host: str
    gateway_port: int
    mock_port: int
    electrical_backend_url: str
    timeout_sec: float

    def server_origin(self) -> str:
        return require_private_endpoint(self.server_url)

    def has_password_login(self) -> bool:
        return bool(self.username and self.password)

    def has_api_key(self) -> bool:
        return bool(self.api_key)


def load_settings(**overrides: object) -> Settings:
    server = str(
        overrides.get(
            "server_url",
            os.environ.get("KROW_SERVER_URL", "http://127.0.0.1:18766"),
        )
    )
    data = {
        "server_url": server,
        "chat_model": str(
            overrides.get(
                "chat_model",
                os.environ.get("KROW_CHAT_MODEL", "qwen2.5:7b"),
            )
        ),
        "username": str(overrides.get("username", os.environ.get("KROW_USERNAME", ""))),
        "password": str(overrides.get("password", os.environ.get("KROW_PASSWORD", ""))),
        "api_key": str(overrides.get("api_key", os.environ.get("KROW_API_KEY", ""))),
        "gateway_host": str(
            overrides.get(
                "gateway_host",
                os.environ.get("KROW_GATEWAY_HOST", "127.0.0.1"),
            )
        ),
        "gateway_port": int(
            overrides.get(
                "gateway_port",
                os.environ.get("KROW_GATEWAY_PORT", "18765"),
            )
        ),
        "mock_port": int(
            overrides.get("mock_port", os.environ.get("KROW_MOCK_PORT", "18766"))
        ),
        "electrical_backend_url": str(
            overrides.get(
                "electrical_backend_url",
                os.environ.get("ELECTRICAL_BACKEND_URL", "http://127.0.0.1:8765"),
            )
        ),
        "timeout_sec": float(
            overrides.get(
                "timeout_sec",
                os.environ.get("KROW_LLM_TIMEOUT", "90"),
            )
        ),
    }
    return Settings(**data)  # type: ignore[arg-type]
