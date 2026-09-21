"""配置：识别服务地址、登录页端口。地址来自 config.ini / KROW_SERVER_URL。"""
from __future__ import annotations

import configparser
import ipaddress
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from electrical_krow.errors import ConfigError
from electrical_krow.paths import PROJECT_ROOT, data_root


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


def suggest_site_api_url(url: str) -> str | None:
    """门户 / 控制台 / 误猜的 api.rdagents 换成识别 API（仪表盘 Base URL 去掉 /v1）。"""
    host = hostname_of(url)
    if not host:
        return None
    for prefix in ("rdweb.", "rdagents.", "api.rdagents."):
        if host.startswith(prefix):
            return f"https://rdapi.{host[len(prefix):]}"
    return None


def require_private_endpoint(url: str) -> str:
    """归一化识别服务根地址（不要带 /v1）。允许本机、内网和 api.krow.cn。"""
    return origin_of(url)


def is_cloud_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h == "krow.cn" or h.endswith(".krow.cn")


def allows_page_images(url: str) -> bool:
    """扫描页图只许打指定场所识别服务，禁止 *.krow.cn。"""
    try:
        host = hostname_of(origin_of(url))
    except ConfigError:
        return False
    return not is_cloud_host(host)


def normalize_delivery(value: str) -> str:
    raw = (value or "client").strip().lower()
    if raw in {"client", "desktop", "loopback", "local"}:
        return "client"
    if raw in {"site", "lan", "web", "intranet"}:
        return "site"
    raise ConfigError(f"delivery 只能是 client 或 site，当前为 {value!r}。")


CLOUD_API_URL = "https://api.krow.cn"
SITE_API_URL = "https://rdapi.aurobaytech-t.com"


@dataclass(frozen=True)
class ServerEnvironment:
    id: str
    label: str
    server_url: str


SERVER_ENVIRONMENTS: tuple[ServerEnvironment, ...] = (
    ServerEnvironment("cloud", "公网联调", CLOUD_API_URL),
    ServerEnvironment("site", "现场识别", SITE_API_URL),
)
SERVER_ENV_BY_ID = {item.id: item for item in SERVER_ENVIRONMENTS}


def match_server_environment(url: str) -> ServerEnvironment | None:
    try:
        origin = origin_of(url)
    except ConfigError:
        return None
    for item in SERVER_ENVIRONMENTS:
        if origin_of(item.server_url) == origin:
            return item
    return None


def packaged_environment_lock() -> ServerEnvironment | None:
    """现场地址打的包锁在现场，不能再切回公网联调。"""
    ini = _ini_values()
    env = match_server_environment(ini.get("server_url") or "")
    forced = (ini.get("lock_environment") or "").strip().lower()
    if forced in {"1", "true", "yes", "on", "site"}:
        return SERVER_ENV_BY_ID["site"]
    if env is not None and env.id == "site":
        return env
    return None


def available_server_environments() -> tuple[ServerEnvironment, ...]:
    lock = packaged_environment_lock()
    if lock is not None:
        return (lock,)
    return SERVER_ENVIRONMENTS


def server_env_path() -> Path:
    return data_root() / "server_env.json"


def read_server_env_id() -> str | None:
    path = server_env_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    env_id = str((payload or {}).get("id") or "").strip()
    if env_id in SERVER_ENV_BY_ID:
        return env_id
    return None


def write_server_env_id(env_id: str) -> ServerEnvironment:
    env = SERVER_ENV_BY_ID.get((env_id or "").strip())
    if env is None:
        raise ConfigError("请选择公网联调或现场识别。")
    path = server_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {"id": env.id, "server_url": env.server_url},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return env


def apply_server_environment(settings: Settings, env_id: str) -> Settings:
    lock = packaged_environment_lock()
    want = (env_id or "").strip()
    if lock is not None and want != lock.id:
        raise ConfigError("本包为现场识别，不能切换到公网联调。")
    env = write_server_env_id(want)
    os.environ["KROW_SERVER_URL"] = env.server_url
    return replace(settings, server_url=env.server_url)


def apply_macos_client_server() -> None:
    """本机 Mac 启动时丢掉 Cursor/现场漏进进程的 KROW_SERVER_URL。

    设置里点过的环境写在 data_root/server_env.json，load_settings 会盖过这里的强制。
    """
    if sys.platform != "darwin":
        return
    raw = os.environ.get("KROW_DELIVERY") or "client"
    try:
        delivery = normalize_delivery(raw)
    except ConfigError:
        delivery = "client"
    if delivery == "site":
        return
    os.environ["KROW_SERVER_URL"] = CLOUD_API_URL


def is_all_interfaces(host: str) -> bool:
    return (host or "").strip().lower() in {"0.0.0.0", "::", "*"}


def is_site_bind_host(host: str) -> bool:
    """场所网页允许回环、全接口或 RFC1918 内网地址，禁止公网单播地址。"""
    h = (host or "").strip().lower()
    if is_loopback_host(h) or is_all_interfaces(h):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_link_local)


def require_gateway_bind(host: str, delivery: str) -> str:
    """客户端必须回环；场所网页默认同绑 127.0.0.1（nginx 转发），禁止公网地址。"""
    mode = normalize_delivery(delivery)
    h = (host or "").strip() or "127.0.0.1"
    if mode == "client":
        if not is_loopback_host(h):
            raise ConfigError(
                "客户端模式只允许绑本机回环（127.0.0.1）。"
                "场所网页请设 delivery = site，并由内网 nginx 转发。"
            )
        return h
    if is_site_bind_host(h):
        return h
    raise ConfigError(
        "场所网页不得绑公网地址。请绑 127.0.0.1 并由内网 nginx 转发，或绑内网地址。"
    )


@dataclass(frozen=True)
class Settings:
    server_url: str
    chat_model: str
    vision_model: str
    username: str
    password: str
    api_key: str
    gateway_host: str
    gateway_port: int
    mock_port: int
    electrical_backend_url: str
    timeout_sec: float
    delivery: str

    def server_origin(self) -> str:
        return origin_of(self.server_url)

    def has_password_login(self) -> bool:
        return bool(self.username and self.password)

    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def is_site(self) -> bool:
        return self.delivery == "site"


def _ini_values() -> dict[str, str]:
    paths: list[Path] = []
    env_path = (os.environ.get("ELECTRICAL_KROW_CONFIG") or "").strip()
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(PROJECT_ROOT / "config.ini")
    parser = configparser.ConfigParser()
    for path in paths:
        if not path.is_file():
            continue
        parser.read(path, encoding="utf-8-sig")
        if parser.has_section("krow"):
            return {k: v.strip() for k, v in parser.items("krow") if v.strip()}
        if parser.has_section("DEFAULT") or parser.defaults():
            return {k: v.strip() for k, v in parser.defaults().items() if v.strip()}
    return {}


def _pick(
    overrides: dict[str, object],
    key: str,
    env_name: str,
    ini: dict[str, str],
    default: str,
    ini_key: str = "",
) -> str:
    if key in overrides and overrides[key] is not None:
        return str(overrides[key])
    env = os.environ.get(env_name)
    if env is not None and str(env).strip() != "":
        return str(env)
    found = ini.get(ini_key or key)
    if found:
        return found
    return default


def load_settings(**overrides: object) -> Settings:
    ini = _ini_values()
    picked = dict(overrides)
    lock = packaged_environment_lock()
    if picked.get("server_url") is None and lock is not None:
        picked["server_url"] = lock.server_url
    elif picked.get("server_url") is None:
        overlay_id = read_server_env_id()
        if overlay_id:
            picked["server_url"] = SERVER_ENV_BY_ID[overlay_id].server_url
    data = {
        "server_url": _pick(
            picked, "server_url", "KROW_SERVER_URL", ini, "https://api.krow.cn"
        ),
        "chat_model": _pick(
            picked, "chat_model", "KROW_CHAT_MODEL", ini, "deepseek-v4-pro"
        ),
        "vision_model": _pick(
            picked, "vision_model", "KROW_VISION_MODEL", ini, ""
        ),
        "username": _pick(picked, "username", "KROW_USERNAME", ini, ""),
        "password": _pick(picked, "password", "KROW_PASSWORD", ini, ""),
        "api_key": _pick(picked, "api_key", "KROW_API_KEY", ini, ""),
        "gateway_host": _pick(
            picked, "gateway_host", "KROW_GATEWAY_HOST", ini, "127.0.0.1"
        ),
        "gateway_port": int(
            _pick(picked, "gateway_port", "KROW_GATEWAY_PORT", ini, "18765")
        ),
        "mock_port": int(_pick(picked, "mock_port", "KROW_MOCK_PORT", ini, "18766")),
        "electrical_backend_url": _pick(
            picked,
            "electrical_backend_url",
            "ELECTRICAL_BACKEND_URL",
            ini,
            "http://127.0.0.1:8765",
        ),
        "timeout_sec": float(
            _pick(
                picked,
                "timeout_sec",
                "KROW_LLM_TIMEOUT",
                ini,
                "180",
                ini_key="timeout_sec",
            )
        ),
        "delivery": normalize_delivery(
            _pick(picked, "delivery", "KROW_DELIVERY", ini, "client")
        ),
    }
    return Settings(**data)  # type: ignore[arg-type]
