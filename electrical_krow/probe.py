"""联调：登录 → 识别 → 登录页 → 出表服务 8765。"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from typing import Any

import httpx
import uvicorn

from electrical_krow.config import load_settings, require_private_endpoint
from electrical_krow.errors import ConfigError, LLMError, LoginError
from electrical_krow.gateway import create_app as create_gateway
from electrical_krow.llm import complete, list_models
from electrical_krow.login import login_with_api_key, login_with_password
from electrical_krow.mock_server import DEMO_PASSWORD, DEMO_USER, create_app as create_mock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="登录与识别连通，再查出表服务")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args(argv)
    settings = load_settings()
    username = args.username or settings.username or DEMO_USER
    password = args.password or settings.password or DEMO_PASSWORD

    report: dict[str, Any] = {}
    ok = True
    started_mock = False
    server_url = settings.server_url

    if _reachable(f"{_origin_or_empty(server_url)}/health"):
        report["krow_server"] = {
            "ok": True,
            "url": _origin_or_empty(server_url),
            "mode": "live",
        }
    else:
        mock_url = f"http://127.0.0.1:{settings.mock_port}"
        _serve(create_mock(), "127.0.0.1", settings.mock_port)
        if not _wait(f"{mock_url}/health"):
            report["krow_server"] = {"ok": False, "error": "mock 没起来"}
            _print(report)
            return 1
        started_mock = True
        server_url = mock_url
        report["krow_server"] = {
            "ok": True,
            "url": mock_url,
            "mode": "mock",
            "note": "未连上 KROW_SERVER_URL，已在本机拉起 mock。",
        }

    try:
        if settings.has_api_key() and not started_mock:
            session = login_with_api_key(settings.api_key)
        else:
            session = login_with_password(server_url, username, password)
        report["login"] = {
            "ok": True,
            "username": session.username,
            "source": session.source,
        }
    except (LoginError, ConfigError) as exc:
        report["login"] = {"ok": False, "error": str(exc)}
        _print(report)
        return 1

    try:
        result = complete(
            server_url,
            session,
            [{"role": "user", "content": "用四个字回答：联调是否成功"}],
            model=settings.chat_model,
            timeout=min(settings.timeout_sec, 30.0),
        )
        try:
            models = list_models(server_url, session)
        except LLMError:
            models = []
        report["complete"] = {
            "ok": True,
            "preview": (result.content or "").replace("\n", " ")[:120],
            "models": models[:8],
        }
    except LLMError as exc:
        report["complete"] = {"ok": False, "error": str(exc)}
        ok = False

    gw_settings = load_settings(
        server_url=server_url,
        chat_model=settings.chat_model,
        gateway_port=settings.gateway_port,
    )
    gw_url = f"http://127.0.0.1:{gw_settings.gateway_port}"
    _serve(create_gateway(gw_settings), "127.0.0.1", gw_settings.gateway_port)
    if not _wait(f"{gw_url}/api/health"):
        report["gateway"] = {"ok": False, "error": "登录页没起来"}
        ok = False
    else:
        with httpx.Client(timeout=20.0, trust_env=False) as client:
            login_resp = client.post(
                f"{gw_url}/api/login",
                json={"username": username, "password": password},
            )
            extract_payload = {
                "model": settings.chat_model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "你只输出一个 JSON 对象。第一个字符是 {，最后一个是 }。",
                    },
                    {"role": "user", "content": "联调探测，空 rows 即可"},
                ],
            }
            chat_resp = client.post(
                f"{gw_url}/v1/chat/completions",
                headers={"Authorization": "Bearer local"},
                json=extract_payload,
            )
        gw_ok = login_resp.status_code == 200 and chat_resp.status_code == 200
        report["gateway"] = {
            "ok": gw_ok,
            "url": gw_url,
            "login_status": login_resp.status_code,
            "extract_shape_status": chat_resp.status_code,
        }
        if not gw_ok:
            ok = False
            report["gateway"]["login_body"] = _clip(login_resp.text)
            report["gateway"]["chat_body"] = _clip(chat_resp.text)
        elif chat_resp.status_code == 200:
            try:
                report["gateway"]["json_preview"] = (
                    chat_resp.json()["choices"][0]["message"]["content"][:80]
                )
            except Exception:
                pass

    electrical = settings.electrical_backend_url.rstrip("/")
    try:
        h = httpx.get(f"{electrical}/api/health", timeout=3.0, trust_env=False)
        body = h.json() if "json" in h.headers.get("content-type", "") else {}
        report["electrical"] = {
            "ok": h.status_code == 200,
            "url": electrical,
            "health": body,
            "note": "出表服务默认仍打本机识别；要改走本登录页，再设 SPEC_SHEET_LLM_URL="
            + gw_url,
        }
        if h.status_code != 200:
            ok = False
    except httpx.HTTPError as exc:
        report["electrical"] = {
            "ok": False,
            "url": electrical,
            "error": str(exc),
            "note": "出表后端未开。需要时另开 python -m electrical.backend --port 8765",
        }

    try:
        sys.path.insert(0, "/Users/wwj/电子电器项目/electrical")
        from electrical.extract import require_workstation_endpoint

        allowed = require_workstation_endpoint(gw_url)
        try:
            require_workstation_endpoint("https://api.krow.cn")
            blocked = False
        except Exception:
            blocked = True
        report["extract_contract"] = {
            "ok": allowed == gw_url and blocked,
            "gateway_allowed": allowed,
            "public_cloud_blocked": blocked,
        }
        if not report["extract_contract"]["ok"]:
            ok = False
    except Exception as exc:
        report["extract_contract"] = {"ok": False, "error": str(exc)}
        ok = False

    _print(report)
    complete_ok = bool((report.get("complete") or {}).get("ok"))
    return 0 if ok and complete_ok else 1


def _origin_or_empty(url: str) -> str:
    try:
        return require_private_endpoint(url)
    except ConfigError:
        return ""


def _reachable(url: str) -> bool:
    if not url:
        return False
    try:
        resp = httpx.get(url, timeout=2.0, trust_env=False)
        return resp.status_code < 500
    except httpx.HTTPError:
        return False


def _serve(app: object, host: str, port: int) -> None:
    if _port_open(host, port):
        return
    thread = threading.Thread(
        target=lambda: uvicorn.run(app, host=host, port=port, log_level="error"),
        daemon=True,
        name=f"krow-{port}",
    )
    thread.start()


def _wait(url: str, tries: int = 40) -> bool:
    for _ in range(tries):
        if _reachable(url):
            return True
        time.sleep(0.05)
    return False


def _port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def _clip(text: str, n: int = 200) -> str:
    return (text or "").strip().replace("\n", " ")[:n]


def _print(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
