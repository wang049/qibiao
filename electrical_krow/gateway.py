"""登录后出表：识别转到指定场所；填表仍走 electrical 流水线。

默认只监听 127.0.0.1（客户端）。场所网页须显式 delivery=site，
应用仍建议绑回环，由内网 nginx HTTPS 转发。规格书不出公网。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
import threading
import webbrowser
from datetime import date
from dataclasses import replace
from pathlib import Path
from typing import Any

import uvicorn

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from electrical_krow.about import OpenError, open_locally, versions as about_versions
from electrical_krow.arch_contrast import build_contrast, contrast_file_name
from electrical_krow.hsi_book import (
    DEFAULT_HSI_TEMPLATE,
    build_hsi,
    hsi_template_by_id,
    hsi_template_for_mcu,
    hsi_template_for_schematic,
    list_hsi_templates,
    revise_hsi_from_schematic,
)
from electrical_krow.ce_bom import DEFAULT_CE_BOM_TEMPLATE, build_ce_bom, ce_bom_file_name
from electrical_krow.enterprise_dialogue import (
    analysis_messages,
    clean_turns,
    fetch_source_page,
    file_key_brief,
    output_tables,
    source_url,
)
from electrical_krow.enterprise_test import Clock, build_enterprise_test, enterprise_test_file_name
from electrical_krow.icd_book import build_icd, icd_file_name
from electrical_krow.mcu_pins import mcu_name, packages_in_pdf
from electrical_krow.io_plan import write_io_sheet

_MCU_MODEL = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,31}$")
from electrical_krow.bridge import wire_extract_endpoint
from electrical_krow.config import (
    SERVER_ENV_BY_ID,
    Settings,
    allows_page_images,
    apply_macos_client_server,
    apply_server_environment,
    available_server_environments,
    load_settings,
    match_server_environment,
    packaged_environment_lock,
    require_gateway_bind,
)
from electrical_krow.errors import ConfigError, LLMError, LoginError
from electrical_krow.jobs import JobStore
from electrical_krow import paths as path_limits
from electrical_krow.inspect_doc import document_needs_ocr, inspect_upload
from electrical_krow.knowledge import browse_catalog, feature_library, knowledge_summary, pending_rulings_count
from electrical_krow.llm import (
    chat_model_candidates,
    complete,
    list_models,
    looks_like_model_unavailable,
)
from electrical_krow.login import login_with_password, refresh_sdk_key, revoke_sdk_key
from electrical_krow.ocr import decode_image_payload, prepare_page_ocr, recognize_page
from electrical_krow.paths import FRONTEND_DIR, OUTPUT_DIR
from electrical_krow.session import SessionStore, StoredSession
from electrical_krow.vision import is_text_chat_model, message_has_image, pick_vision_model

COOKIE = "electrical_krow_sid"
FRONTEND = FRONTEND_DIR
_AUTH_REFRESH = threading.Lock()
_ARCH_PROGRESS: dict[str, dict[str, object]] = {}
_ARCH_PROGRESS_LOCK = threading.Lock()
_HSI_PROGRESS: dict[str, dict[str, object]] = {}
_HSI_PROGRESS_LOCK = threading.Lock()


def _arch_progress_set(job_id: str, percent: int, stage: str, detail: str = "", *, done: bool = False) -> None:
    if not job_id:
        return
    with _ARCH_PROGRESS_LOCK:
        _ARCH_PROGRESS[job_id] = {"percent": percent, "stage": stage, "detail": detail, "done": done}
        if len(_ARCH_PROGRESS) > 40:
            for key in list(_ARCH_PROGRESS)[:-20]:
                _ARCH_PROGRESS.pop(key, None)


def _hsi_progress_set(job_id: str, percent: int, stage: str, detail: str = "", *, done: bool = False) -> None:
    if not job_id:
        return
    with _HSI_PROGRESS_LOCK:
        _HSI_PROGRESS[job_id] = {"percent": percent, "stage": stage, "detail": detail, "done": done}
        if len(_HSI_PROGRESS) > 40:
            for key in list(_HSI_PROGRESS)[:-20]:
                _HSI_PROGRESS.pop(key, None)


async def read_capped_upload(file: UploadFile) -> bytes:
    """按块读取，超过限额立刻拒绝，避免先把整文件读进内存。"""
    limit = path_limits.MAX_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        block = await file.read(1024 * 1024)
        if not block:
            break
        total += len(block)
        if total > limit:
            raise HTTPException(400, f"文件超过 {path_limits.MAX_MB}MB")
        chunks.append(block)
    if total == 0:
        raise HTTPException(400, "文件是空的")
    return b"".join(chunks)


def _digital_page_env() -> None:
    """电子版不探测 OCR，也不把上一份扫描件的开关留在进程里。"""
    os.environ["SPEC_SHEET_PAGE_OCR"] = "0"
    os.environ.pop("SPEC_SHEET_OCR_TASK", None)
    os.environ["SPEC_SHEET_PAGE_VISION"] = "0"
    os.environ.pop("SPEC_SHEET_VISION_MODEL", None)


def _looks_like_auth_error(exc: BaseException) -> bool:
    text = str(exc)
    return any(mark in text for mark in ("未授权", "请重新登录", "Unauthorized", "401"))


def prepare_page_vision(settings: Settings, item: StoredSession | None) -> str:
    """出表前选定看图模型。公网 krow.cn 一律关闭页图。"""
    if not allows_page_images(settings.server_url):
        os.environ["SPEC_SHEET_PAGE_VISION"] = "0"
        os.environ.pop("SPEC_SHEET_VISION_MODEL", None)
        return ""
    names: list[str] = []
    if item is not None:
        try:
            names = list_models(
                settings.server_url,
                item.auth,
                timeout=min(settings.timeout_sec, 8.0),
            )
        except (LLMError, ConfigError):
            names = []
    vision = pick_vision_model(names, settings.vision_model)
    if vision:
        os.environ["SPEC_SHEET_PAGE_VISION"] = "1"
        os.environ["SPEC_SHEET_VISION_MODEL"] = vision
        return vision
    os.environ["SPEC_SHEET_PAGE_VISION"] = "0"
    os.environ.pop("SPEC_SHEET_VISION_MODEL", None)
    return ""


def _safe_call(fn, fallback):
    """启动探测不能因为关于页或知识库读失败而把整个服务判死。"""
    try:
        return fn()
    except Exception:
        return fallback


def apply_windows_event_loop_policy() -> None:
    """避免 Windows 默认 Proactor 循环和窗口消息泵抢同一进程。"""
    if sys.platform != "win32":
        return
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""


class ChatMessageIn(BaseModel):
    role: str
    content: Any = ""


class ChatIn(BaseModel):
    model: str = ""
    messages: list[ChatMessageIn] = Field(default_factory=list)
    temperature: float = 0.0
    # 推理模型控制：出表只要 JSON，不要长推理。原样透传给识别服务，上游不认就忽略。
    thinking: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    max_tokens: int | None = None


class ModelIn(BaseModel):
    model: str = ""


class SettingsIn(BaseModel):
    id: str = ""


# /api/jobs 的 thinking：工位页不传。空/off = 关掉推理（出表只要 JSON）；on 才走上游默认。
THINKING_MODES = frozenset({"", "on", "off"})


class OcrIn(BaseModel):
    image: str = ""
    task: str = "table"


class RecordFolderIn(BaseModel):
    kind: str = ""
    name: str = ""


class RecordPlaceIn(BaseModel):
    kind: str = ""
    record_id: str = ""
    folder_id: str = ""


def create_app(
    settings: Settings | None = None,
    *,
    extract_url: str | None = None,
    output_dir: Path | None = None,
) -> FastAPI:
    cfg = settings or load_settings()
    wire_extract_endpoint(cfg, origin=extract_url)
    app = FastAPI(title="电子电器 · SOR填表", docs_url=None, redoc_url=None)
    app.state.settings = cfg
    app.state.store = SessionStore()
    app.state.jobs = JobStore(output_dir=output_dir)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        path = FRONTEND / "index.html"
        if not path.is_file():
            return HTMLResponse("<p>找不到界面文件。</p>", status_code=500)
        return HTMLResponse(
            path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store"},
        )

    def _active_model(item: StoredSession | None) -> str:
        chosen = (item.chat_model if item else "") or ""
        return chosen.strip() or cfg.chat_model

    def _settings_payload() -> dict[str, object]:
        env = match_server_environment(cfg.server_url)
        lock = packaged_environment_lock()
        try:
            origin = cfg.server_origin()
        except ConfigError:
            origin = cfg.server_url
        return {
            "ok": True,
            "id": env.id if env else "",
            "label": env.label if env else "",
            "server": origin,
            "environment_locked": lock is not None,
            "environments": [
                {"id": item.id, "label": item.label, "server": item.server_url}
                for item in available_server_environments()
            ],
        }

    @app.get("/api/health")
    def health() -> dict[str, object]:
        item = app.state.store.default()
        logged = item is not None
        env = match_server_environment(cfg.server_url)
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
            "model": _active_model(item),
            "detail": server_error,
            "fill": True,
            "delivery": cfg.delivery,
            "busy": app.state.jobs.busy(),
            "active_job": app.state.jobs.active(),
            "environment": env.id if env else "",
            "environment_label": env.label if env else "",
            "environment_locked": packaged_environment_lock() is not None,
            # 「关于」页：版本与核对表目录
            "versions": _safe_call(about_versions, {}),
            "output_dir": str(app.state.jobs.output_dir),
            # 工作台摘要卡：知识库数量与待专家口径条目数（只有数字，不含条目内容）
            "knowledge": _safe_call(knowledge_summary, {}),
            "pending_rulings": _safe_call(pending_rulings_count, 0),
        }

    @app.get("/api/settings")
    def get_settings() -> dict[str, object]:
        return _settings_payload()

    @app.post("/api/settings")
    def set_settings(
        body: SettingsIn, request: Request, response: Response
    ) -> dict[str, object]:
        nonlocal cfg
        env_id = (body.id or "").strip()
        if env_id not in SERVER_ENV_BY_ID:
            raise HTTPException(400, "请选择公网联调或现场识别。")
        lock = packaged_environment_lock()
        if lock is not None and env_id != lock.id:
            raise HTTPException(403, "本包为现场识别，不能切换到公网联调。")
        current = match_server_environment(cfg.server_url)
        if current is not None and current.id == env_id:
            return {
                **_settings_payload(),
                "changed": False,
                "logged_in": app.state.store.default() is not None,
            }
        if app.state.jobs.busy():
            raise HTTPException(409, "当前有任务在出表，结束后再切换环境。")
        old_url = cfg.server_url
        for item in app.state.store.clear():
            try:
                revoke_sdk_key(old_url, item.auth)
            except Exception:
                pass
        response.delete_cookie(COOKIE, path="/")
        cfg = apply_server_environment(cfg, env_id)
        app.state.settings = cfg
        wire_extract_endpoint(cfg, origin=extract_url)
        return {**_settings_payload(), "changed": True, "logged_in": False}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, object]:
        try:
                auth = login_with_password(
                    cfg.server_url,
                    body.username,
                    body.password,
                    timeout=min(cfg.timeout_sec, 30.0),
                )
        except (LoginError, ConfigError) as exc:
            raise HTTPException(401, str(exc)) from exc
        stored = request.app.state.store.put(auth, chat_model=cfg.chat_model)
        response.set_cookie(COOKIE, stored.sid, **_cookie_kwargs(request))
        return {
            "ok": True,
            "username": auth.username,
            "source": auth.source,
            "model": stored.chat_model or cfg.chat_model,
        }

    @app.post("/api/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        item = _session_from(request, None)
        if item is not None:
            try:
                revoke_sdk_key(cfg.server_url, item.auth)
            except Exception:
                pass
            request.app.state.store.drop(item.sid)
        else:
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
            "model": _active_model(item),
        }

    @app.get("/api/knowledge")
    def knowledge_view(
        request: Request,
        authorization: str | None = Header(default=None),
        library: str = "",
    ) -> dict[str, object]:
        _require_session(request, authorization)
        chosen = (library or "sor").strip().lower()
        if chosen in {"arch", "hsi"}:
            data = feature_library(chosen)
            if not data.get("version"):
                raise HTTPException(404, "没有这份知识库")
            return data
        if chosen not in {"", "sor"}:
            raise HTTPException(404, "没有这份知识库")
        data = browse_catalog()
        if not data.get("version"):
            raise HTTPException(503, "知识库尚未发布")
        return data

    @app.get("/api/models")
    def models(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        names: list[str] = []
        try:
            names = list_models(cfg.server_url, item.auth, timeout=min(cfg.timeout_sec, 20.0))
        except (LLMError, ConfigError):
            names = []
        current = _active_model(item)
        if names:
            picked = chat_model_candidates(names, current)
            if current not in names and picked:
                current = picked[0]
                request.app.state.store.set_chat_model(item, current)
        elif current and current not in names:
            names = [current, *names]
        seen: set[str] = set()
        ordered: list[str] = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        # 推荐模型 = 配置默认（deepseek-v4-pro：09-15 专家认可稿所用），前端在名字后标「推荐」
        return {"models": ordered, "model": current, "recommended": cfg.chat_model}

    @app.post("/api/model")
    def set_model(
        body: ModelIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        name = (body.model or "").strip()
        if not name:
            raise HTTPException(400, "请选择模型。")
        if len(name) > 80 or any(ch in name for ch in " \t\n"):
            raise HTTPException(400, "模型名不合法。")
        request.app.state.store.set_chat_model(item, name)
        return {"ok": True, "model": name}

    @app.post("/v1/chat/completions")
    def chat_completions(
        body: ChatIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _session_from(request, authorization)
        if item is None:
            raise HTTPException(401, "请先登录")
        requested = (body.model or _active_model(item)).strip() or cfg.chat_model
        model = (item.extract_model or requested).strip() or requested
        messages = [{"role": m.role, "content": m.content} for m in body.messages]
        if any(message_has_image(m.content) for m in body.messages):
            if not allows_page_images(cfg.server_url):
                raise HTTPException(403, "扫描页图不得打公网识别。")
            if is_text_chat_model(model):
                vision = (
                    (os.environ.get("SPEC_SHEET_VISION_MODEL") or "").strip()
                    or (cfg.vision_model or "").strip()
                )
                if not vision or is_text_chat_model(vision):
                    raise HTTPException(
                        400,
                        "页图请使用看图模型。deepseek-v4-pro / GLM-5.2 文本版不用于扫描页。",
                    )
                model = vision

        def _call(auth, model_name: str):
            return complete(
                cfg.server_url,
                auth,
                messages,
                model=model_name,
                temperature=body.temperature,
                timeout=cfg.timeout_sec,
                extra={
                    "thinking": body.thinking,
                    "reasoning_effort": body.reasoning_effort,
                    "max_tokens": body.max_tokens,
                },
            )

        def _fallback_model(auth, failed: str, exc: LLMError):
            dead = {failed}
            names: list[str] = []
            try:
                names = list_models(cfg.server_url, auth, timeout=15.0)
            except (LLMError, ConfigError):
                names = []
            for alt in chat_model_candidates(names, _active_model(item)):
                if alt in dead:
                    continue
                try:
                    result = _call(auth, alt)
                except LLMError as inner:
                    if looks_like_model_unavailable(body=str(inner)):
                        dead.add(alt)
                        continue
                    raise
                item.extract_model = alt
                if not item.chat_model or item.chat_model in dead:
                    item.chat_model = alt
                return result
            raise HTTPException(
                400,
                f"识别模型「{failed}」当前不可用，请改选其他 chat 模型。",
            ) from exc

        try:
            result = _call(item.auth, model)
        except ConfigError as exc:
            raise HTTPException(502, str(exc)) from exc
        except LLMError as exc:
            if looks_like_model_unavailable(body=str(exc)):
                result = _fallback_model(item.auth, model, exc)
            elif not _looks_like_auth_error(exc):
                raise HTTPException(502, str(exc)) from exc
            else:
                try:
                    with _AUTH_REFRESH:
                        try:
                            result = _call(item.auth, model)
                        except LLMError as inner:
                            if looks_like_model_unavailable(body=str(inner)):
                                result = _fallback_model(item.auth, model, inner)
                            elif not _looks_like_auth_error(inner):
                                raise
                            else:
                                item.auth = refresh_sdk_key(cfg.server_url, item.auth)
                                result = _call(item.auth, model)
                except HTTPException:
                    raise
                except LoginError as exc2:
                    raise HTTPException(401, str(exc2)) from exc2
                except LLMError as exc2:
                    if looks_like_model_unavailable(body=str(exc2)):
                        result = _fallback_model(item.auth, model, exc2)
                    elif _looks_like_auth_error(exc2):
                        raise HTTPException(401, "识别未授权，请重新登录。") from exc2
                    else:
                        raise HTTPException(502, str(exc2)) from exc2
        return result.raw

    @app.post("/v1/ocr")
    def page_ocr(
        body: OcrIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _session_from(request, authorization)
        if item is None:
            raise HTTPException(401, "请先登录")
        try:
            image = decode_image_payload(body.image)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        task = (body.task or "table").strip().lower() or "table"
        if task not in {"table", "ocr"}:
            raise HTTPException(400, "task 只能是 table 或 ocr。")
        try:
            result = recognize_page(
                cfg.server_url,
                item.auth,
                image,
                task=task,
            )
        except (LLMError, ConfigError) as exc:
            raise HTTPException(502, str(exc)) from exc
        return result

    @app.post("/api/jobs")
    async def start_job(
        request: Request,
        file: UploadFile = File(...),
        thinking: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        mode = (thinking or "").strip().lower()
        if mode not in THINKING_MODES:
            raise HTTPException(400, "thinking 只能是 on / off。")
        data = await read_capped_upload(file)
        incoming, out = request.app.state.jobs.prepare_upload(file, data)
        model = item.extract_model or _active_model(item)
        needs_ocr = document_needs_ocr(file.filename or "", data)
        if needs_ocr is False:
            _digital_page_env()
        elif prepare_page_ocr(cfg, item):
            os.environ["SPEC_SHEET_PAGE_VISION"] = "0"
            os.environ.pop("SPEC_SHEET_VISION_MODEL", None)
        else:
            prepare_page_vision(cfg, item)
        # 模型推理开关：同一时刻只跑一份，进程级环境变量即本次任务的开关。
        # 空/off → thinking.type=disabled。现场 deepseek 开推理时常只回 reasoning_content，
        # 工位会把整层分段记成失败，两分钟出一张只有规则的表。
        if mode == "on":
            os.environ.pop("SPEC_SHEET_LLM_THINKING", None)
        else:
            os.environ["SPEC_SHEET_LLM_THINKING"] = "disabled"
        try:
            job_id = request.app.state.jobs.start(
                file.filename,
                incoming,
                out,
                model=model,
                username=item.auth.username,
                thinking=mode,
            )
        except HTTPException:
            incoming.unlink(missing_ok=True)
            raise
        return {"id": job_id}

    @app.post("/api/inspect")
    async def inspect_file(
        request: Request,
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """选中文件后的体检：类型 / 页数 / 是否扫描件 / 按历史估时。不落盘、不抽取。"""
        item = _require_session(request, authorization)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".pdf", ".docx", ".xlsx", ".xlsm"}:
            raise HTTPException(400, f"暂不支持 {suffix or '该类型'}。请用 PDF / Word / Excel。")
        data = await read_capped_upload(file)
        history = request.app.state.jobs.list_recent(limit=80, username=item.auth.username)
        return await asyncio.to_thread(inspect_upload, file.filename or "", data, history)

    @app.get("/api/jobs")
    def list_jobs(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_recent(username=user)
        return {
            "jobs": request.app.state.jobs.with_sources(rows, user, "jobs"),
            "folders": request.app.state.jobs.list_record_folders(user, "jobs"),
        }

    @app.post("/api/records/folders")
    def create_record_folder(
        body: RecordFolderIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        try:
            folder = request.app.state.jobs.create_record_folder(
                username=item.auth.username,
                kind=body.kind,
                name=body.name,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "folder": folder}

    @app.post("/api/records/place")
    def place_record(
        body: RecordPlaceIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        try:
            request.app.state.jobs.place_record(
                username=item.auth.username,
                kind=body.kind,
                record_id=body.record_id,
                folder_id=body.folder_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @app.post("/api/records/sources")
    async def add_record_source(
        request: Request,
        file: UploadFile = File(...),
        kind: str = Form(default=""),
        folder_id: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """把检测原件放进某一类记录。指定文件夹时归到该文件夹，否则按文件名和同名输出放一起。"""
        item = _require_session(request, authorization)
        data = await read_capped_upload(file)
        try:
            row = request.app.state.jobs.keep_source(
                username=item.auth.username,
                kind=kind,
                filename=file.filename or "",
                data=data,
                folder_id=folder_id,
                group_title=Path(file.filename or "").name,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "source": row}

    @app.get("/api/records/sources/{source_id}/file")
    def download_source(
        source_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        item = _require_session(request, authorization)
        try:
            path, name = request.app.state.jobs.source_file(item.auth.username, source_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(path, filename=name)

    @app.post("/api/records/sources/{source_id}/open")
    def open_source(
        source_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        try:
            path, name = request.app.state.jobs.source_file(item.auth.username, source_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            open_locally(path)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"ok": True, "name": name}

    @app.get("/api/jobs/{job_id}")
    def job_status(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        return request.app.state.jobs.snapshot(
            job_id, username=item.auth.username
        )

    @app.post("/api/jobs/{job_id}/pause")
    def pause_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        ctrl = request.app.state.jobs.control(
            job_id, username=item.auth.username
        )
        ctrl.request_pause()
        request.app.state.jobs.update(
            job_id, status="pausing", message="将在本批结束后暂停…"
        )
        return request.app.state.jobs.snapshot(
            job_id, username=item.auth.username
        )

    @app.post("/api/jobs/{job_id}/resume")
    def resume_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        ctrl = request.app.state.jobs.control(
            job_id, username=item.auth.username
        )
        ctrl.request_resume()
        request.app.state.jobs.update(
            job_id, status="running", message="已继续出表…"
        )
        return request.app.state.jobs.snapshot(
            job_id, username=item.auth.username
        )

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(
        job_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        ctrl = request.app.state.jobs.control(
            job_id, username=item.auth.username
        )
        ctrl.request_stop()
        request.app.state.jobs.update(
            job_id,
            status="stopping",
            message="将在本批结束后结束，并按已抽出内容出表…",
        )
        return request.app.state.jobs.snapshot(
            job_id, username=item.auth.username
        )

    @app.post("/api/io-sheet")
    def create_io_sheet(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """第3项空表。不填引脚，端口名留空，并用本机表格程序打开。"""
        _require_session(request, authorization)
        dest = request.app.state.jobs.output_dir / "IO口初始配置表.xlsx"
        write_io_sheet(dest)
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"ok": True, "name": dest.name}

    @app.get("/api/hsi/templates")
    def hsi_templates() -> dict[str, object]:
        """按 MCU（TC499 / TC387 / TC399）列模板。选模板不必先登录；真正出表仍要登录。"""
        rows = list_hsi_templates()
        default_id = "TC499" if any(row.get("id") == "TC499" for row in rows) else (rows[0]["id"] if rows else "")
        return {"templates": rows, "default": default_id}

    @app.post("/api/hsi/packages")
    async def list_hsi_packages(
        request: Request,
        datasheet: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """选中手册后立刻返回封装，供页面点选。不生成表。"""
        _require_session(request, authorization)
        manual_name = Path(datasheet.filename or "").name
        if Path(manual_name).suffix.lower() != ".pdf":
            raise HTTPException(400, "芯片手册请用 PDF。")
        manual_bytes = await read_capped_upload(datasheet)

        def scan() -> tuple[str, tuple[str, ...]]:
            with tempfile.TemporaryDirectory() as raw:
                manual_path = Path(raw) / manual_name
                manual_path.write_bytes(manual_bytes)
                return mcu_name(manual_path.name), packages_in_pdf(manual_path)

        try:
            mcu, packages = await asyncio.to_thread(scan)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not packages:
            raise HTTPException(400, "手册中没有读到封装引脚表。")
        return {"ok": True, "mcu": mcu, "packages": list(packages)}

    @app.get("/api/hsi/history")
    def hsi_history(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_hsi(username=user)
        return {
            "records": request.app.state.jobs.with_sources(rows, user, "hsi"),
            "folders": request.app.state.jobs.list_record_folders(user, "hsi"),
        }

    @app.get("/api/hsi/progress/{job_id}")
    def hsi_progress(
        request: Request,
        job_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_session(request, authorization)
        with _HSI_PROGRESS_LOCK:
            found = _HSI_PROGRESS.get(job_id)
        if not found:
            return {"percent": 0, "stage": "read", "detail": "", "done": False}
        return found

    @app.post("/api/hsi")
    async def create_hsi(
        request: Request,
        datasheet: UploadFile | None = File(default=None),
        template: UploadFile | None = File(default=None),
        previous: UploadFile | None = File(default=None),
        schematic: UploadFile | None = File(default=None),
        package: str = Form(default=""),
        mode: str = Form(default="mcu"),
        mcu: str = Form(default=""),
        template_id: str = Form(default=""),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """按原理图生成 HSI，或按芯片手册生成。"""
        item = _require_session(request, authorization)
        progress_id = (request.headers.get("x-hsi-progress") or "").strip()[:80]
        chosen = (mode or "mcu").strip().lower()
        if chosen not in {"mcu", "schematic"}:
            raise HTTPException(400, "请选择按原理图生成，或按芯片手册生成。")
        manual_name = Path(datasheet.filename or "").name if datasheet is not None else ""
        manual_bytes = b""
        typed_mcu = mcu.strip()
        picked_template_id = template_id.strip()
        if chosen == "mcu":
            if Path(manual_name).suffix.lower() != ".pdf":
                raise HTTPException(400, "芯片手册请用 PDF。")
            manual_bytes = await read_capped_upload(datasheet)
            if typed_mcu and (_MCU_MODEL.match(typed_mcu) is None or not any(ch.isdigit() for ch in typed_mcu)):
                raise HTTPException(400, "MCU 型号请写成如 TC399、TC387、TC324。")
        elif not schematic or not Path(schematic.filename or "").name:
            raise HTTPException(400, "请选择原理图网表（.edf）或原理图 PDF。")
        template_name = Path(template.filename or "").name if template is not None else ""
        template_bytes = b""
        if template_name:
            if Path(template_name).suffix.lower() not in {".xlsx", ".xlsm"}:
                raise HTTPException(400, "HSI 模板请用 Excel。")
            template_bytes = await read_capped_upload(template)
        builtin_template = hsi_template_by_id(picked_template_id) if picked_template_id else None
        if chosen == "schematic" and not template_bytes and builtin_template is None:
            raise HTTPException(400, "请选择 HSI 模板。")
        if not template_bytes and builtin_template is None and not DEFAULT_HSI_TEMPLATE.is_file():
            raise HTTPException(400, "当前 HSI 模板不在程序里。")
        previous_name = Path(previous.filename or "").name if previous is not None else ""
        previous_bytes = b""
        if previous_name:
            if Path(previous_name).suffix.lower() not in {".xlsx", ".xlsm"}:
                raise HTTPException(400, "上一版 HSI 请用 Excel。")
            previous_bytes = await read_capped_upload(previous)
        schematic_name = Path(schematic.filename or "").name if schematic is not None else ""
        schematic_bytes = b""
        if schematic_name:
            if Path(schematic_name).suffix.lower() not in {".pdf", ".xlsx", ".xlsm", ".edf"}:
                raise HTTPException(400, "原理图请用 EDIF、PDF 或 Excel。")
            schematic_bytes = await read_capped_upload(schematic)
        model = (item.extract_model or _active_model(item)).strip() or cfg.chat_model

        def ask(messages: list[dict[str, str]]) -> str:
            """HSI 工程质检用：模型只对已对齐行的模板定义做矛盾与硬件复用核查，不生成引脚事实。"""
            extra = {"thinking": {"type": "disabled"}}
            try:
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content
            except LLMError as exc:
                if not _looks_like_auth_error(exc):
                    raise
                with _AUTH_REFRESH:
                    item.auth = refresh_sdk_key(cfg.server_url, item.auth)
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            manual_path = None
            if manual_bytes:
                manual_path = folder / manual_name
                manual_path.write_bytes(manual_bytes)
            if template_bytes:
                template_path = folder / template_name
                template_path.write_bytes(template_bytes)
            elif chosen == "schematic":
                template_path = hsi_template_for_schematic(picked_template_id or typed_mcu)
            elif builtin_template is not None:
                template_path = builtin_template
            else:
                template_path = hsi_template_for_mcu(typed_mcu) if typed_mcu else DEFAULT_HSI_TEMPLATE
            previous_path = None
            if previous_bytes:
                previous_path = folder / previous_name
                previous_path.write_bytes(previous_bytes)
            schematic_path = None
            if schematic_bytes:
                schematic_path = folder / schematic_name
                schematic_path.write_bytes(schematic_bytes)
            def on_progress(percent: int, stage: str, detail: str = "") -> None:
                _hsi_progress_set(progress_id, percent, stage, detail)

            _hsi_progress_set(progress_id, 1, "read", "")
            try:
                if chosen == "schematic":
                    if schematic_path is None or schematic_path.suffix.lower() not in {".edf", ".pdf"}:
                        raise ValueError("按原理图生成请用 EDIF（.edf）网表或原理图 PDF。")
                    result = await asyncio.to_thread(
                        revise_hsi_from_schematic,
                        previous_path or template_path,
                        folder / "hsi.xlsx",
                        schematic_path,
                        on_progress=on_progress,
                    )
                else:
                    result = await asyncio.to_thread(
                        build_hsi,
                        template_path,
                        manual_path,
                        folder / "hsi.xlsx",
                        package=package,
                        previous=previous_path,
                        ask=ask,
                        on_progress=on_progress,
                        mcu=typed_mcu,
                    )
            except ValueError as exc:
                _hsi_progress_set(progress_id, 0, "write", "", done=True)
                raise HTTPException(400, str(exc)) from exc
            except Exception:
                _hsi_progress_set(progress_id, 0, "write", "", done=True)
                raise
            _hsi_progress_set(progress_id, 100, "write", "", done=True)
            stamp = result.issued or date.today().strftime("%Y%m%d")
            dest = request.app.state.jobs.output_dir / f"HSI-{result.version}-{stamp}.xlsx"
            dest.write_bytes(result.path.read_bytes())
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        saved = request.app.state.jobs.remember_hsi(
            name=dest.name,
            username=item.auth.username,
            mcu=result.mcu,
            package=result.package,
            pins=result.pins,
            changes=result.changes,
            version=result.version,
            previous=bool(previous_bytes),
        )
        schematic_stem = Path(schematic_name).stem if schematic_name else ""
        group = " ".join(part for part in (result.mcu, result.package) if part).strip() or schematic_stem or manual_name
        try:
            if manual_bytes:
                request.app.state.jobs.keep_source(
                    username=item.auth.username,
                    kind="hsi",
                    filename=manual_name,
                    data=manual_bytes,
                    run_id=str(saved.get("id") or ""),
                    group_title=group,
                )
            if schematic_bytes:
                request.app.state.jobs.keep_source(
                    username=item.auth.username,
                    kind="hsi",
                    filename=schematic_name,
                    data=schematic_bytes,
                    run_id=str(saved.get("id") or ""),
                    group_title=group,
                )
        except ValueError:
            pass
        return {
            "ok": True,
            "name": dest.name,
            "download": f"/files/{dest.name}",
            "mcu": result.mcu,
            "package": result.package,
            "version": result.version,
            "pins": result.pins,
            "changes": result.changes,
            "conflicts": result.conflicts,
            "model_used": result.model_used,
            "previous": bool(previous_bytes),
            "schematic": bool(schematic_bytes),
            "schematic_updates": result.schematic_updates,
            "mode": chosen,
        }

    @app.get("/api/arch/history")
    def arch_history(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_arch(username=user)
        return {
            "records": request.app.state.jobs.with_sources(rows, user, "arch"),
            "folders": request.app.state.jobs.list_record_folders(user, "arch"),
        }

    @app.get("/api/arch/progress/{job_id}")
    def arch_progress(
        request: Request,
        job_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        _require_session(request, authorization)
        with _ARCH_PROGRESS_LOCK:
            found = _ARCH_PROGRESS.get(job_id)
        if not found:
            return {"percent": 0, "stage": "text", "detail": "", "done": False}
        return found

    @app.post("/api/arch")
    async def create_arch(
        request: Request,
        files: list[UploadFile] = File(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """架构填报：把当份需求 PDF 拆成材料对照稿。只摘原文，不写满足结论。"""
        item = _require_session(request, authorization)
        progress_id = (request.headers.get("x-arch-progress") or "").strip()[:80]
        if not files:
            raise HTTPException(400, "请选择需求文件 PDF。")
        payloads: list[tuple[str, bytes]] = []
        for upload in files:
            name = Path(upload.filename or "").name
            if Path(name).suffix.lower() != ".pdf":
                raise HTTPException(400, f"{name or '所选文件'} 不是 PDF。需求文件请用 PDF。")
            payloads.append((name, await read_capped_upload(upload)))
        model = (item.extract_model or _active_model(item)).strip() or cfg.chat_model

        def ask(messages: list[dict[str, str]]) -> str:
            """参数清单用：模型只给正文参数起名、归并同义名，不产生取值。关掉推理，只要 JSON。"""
            extra = {"thinking": {"type": "disabled"}}
            try:
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content
            except LLMError as exc:
                if not _looks_like_auth_error(exc):
                    raise
                with _AUTH_REFRESH:
                    item.auth = refresh_sdk_key(cfg.server_url, item.auth)
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            sources: list[Path] = []
            # 每份放各自的子目录，文件名原样进对照稿；同名文件也不互相覆盖
            for index, (name, data) in enumerate(payloads, start=1):
                target = folder / f"{index:02d}" / name
                target.parent.mkdir()
                target.write_bytes(data)
                sources.append(target)
            def on_progress(percent: int, stage: str, detail: str = "") -> None:
                _arch_progress_set(progress_id, percent, stage, detail)

            _arch_progress_set(progress_id, 1, "text", "")
            try:
                result = await asyncio.to_thread(build_contrast, sources, folder / "arch.xlsx", ask, on_progress)
            except ValueError as exc:
                _arch_progress_set(progress_id, 0, "write", "", done=True)
                raise HTTPException(400, str(exc)) from exc
            _arch_progress_set(progress_id, 100, "write", "", done=True)
            dest = request.app.state.jobs.output_dir / contrast_file_name(
                sources=[name for name, _data in payloads]
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(result.path.read_bytes())
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        unreadable = [{"name": u.name, "pages": u.pages, "reason": u.reason} for u in result.unreadable]
        saved = request.app.state.jobs.remember_arch(
            name=dest.name,
            username=item.auth.username,
            files=result.files,
            rows=result.rows,
            tables=result.tables,
            unreadable=len(unreadable),
        )
        names = [name for name, _data in payloads]
        if len(names) == 1:
            group = names[0]
        else:
            shown = "、".join(names[:3])
            group = shown + ("等" if len(names) > 3 else "")
        for name, data in payloads:
            try:
                request.app.state.jobs.keep_source(
                    username=item.auth.username,
                    kind="arch",
                    filename=name,
                    data=data,
                    run_id=str(saved.get("id") or ""),
                    group_title=group or name,
                )
            except ValueError:
                continue
        return {
            "ok": True,
            "name": dest.name,
            "download": f"/files/{dest.name}",
            "files": result.files,
            "rows": result.rows,
            "tables": result.tables,
            "params": result.params,
            "conflicts": result.conflicts,
            "model_used": result.model_used,
            "image_tables": result.image_tables,
            "figures": result.figures,
            "reqs": result.reqs,
            "shots": result.shots,
            "quality_summary": result.quality_summary,
            "bilingual_conflicts": result.bilingual_conflicts,
            "logic_conflicts": result.logic_conflicts,
            "tbd_count": result.tbd_count,
            "quality_issues": list(result.quality_issues),
            "unreadable": unreadable,
        }

    @app.post("/api/icd")
    async def create_icd(
        request: Request,
        file: UploadFile = File(...),
        previous: UploadFile | None = File(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """按当份接插件 ICD 抽出引脚。有上一版时写差异总结。不补当份没有的信号。"""
        item = _require_session(request, authorization)
        name = Path(file.filename or "").name
        if Path(name).suffix.lower() not in {".xlsx", ".xlsm"}:
            raise HTTPException(400, "ICD 请用 Excel。")
        current_bytes = await read_capped_upload(file)
        previous_name = Path(previous.filename or "").name if previous is not None else ""
        previous_bytes = b""
        if previous_name:
            if Path(previous_name).suffix.lower() not in {".xlsx", ".xlsm"}:
                raise HTTPException(400, "上一版 ICD 请用 Excel。")
            previous_bytes = await read_capped_upload(previous)
        model = (_active_model(item)).strip() or cfg.chat_model

        def ask(messages: list[dict[str, str]]) -> str:
            """只给已对照出来的差异做措辞和说明判断，不生成脚号或取值。"""
            extra = {"thinking": {"type": "disabled"}}
            try:
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content
            except LLMError as exc:
                if not _looks_like_auth_error(exc):
                    raise
                with _AUTH_REFRESH:
                    item.auth = refresh_sdk_key(cfg.server_url, item.auth)
                return complete(cfg.server_url, item.auth, messages, model=model, temperature=0.0, timeout=cfg.timeout_sec, extra=extra).content

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            current_path = folder / (name or "icd.xlsx")
            current_path.write_bytes(current_bytes)
            previous_path = None
            if previous_bytes:
                previous_path = folder / f"previous-{previous_name}"
                previous_path.write_bytes(previous_bytes)
            dest_tmp = folder / "icd.xlsx"
            try:
                result = await asyncio.to_thread(build_icd, current_path, dest_tmp, previous_path, ask if previous_path else None)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            dest = request.app.state.jobs.output_dir / icd_file_name()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(dest_tmp.read_bytes())
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        request.app.state.jobs.remember_output(
            kind="icd",
            name=dest.name,
            username=item.auth.username,
            pins=result.pins,
            rows=result.parts,
            tables=result.hv,
            changes=result.changes,
        )
        return {
            "ok": True,
            "name": dest.name,
            "download": f"/files/{dest.name}",
            "pins": result.pins,
            "parts": result.parts,
            "hv": result.hv,
            "changes": result.changes,
        }

    @app.get("/api/icd/history")
    def icd_history(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_output("icd", username=user)
        return {
            "records": request.app.state.jobs.with_sources(rows, user, "icd"),
            "folders": request.app.state.jobs.list_record_folders(user, "icd"),
        }

    @app.post("/api/ce-bom")
    async def create_ce_bom(
        request: Request,
        manuals: list[UploadFile] | None = File(default=None),
        template: UploadFile | None = File(default=None),
        previous: UploadFile | None = File(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """按确认的 CE BOM 表格式，从当份物料手册抽出尺寸和重量。不补手册没有的数。"""
        item = _require_session(request, authorization)
        if not manuals:
            manuals = []
        payloads: list[tuple[str, bytes]] = []
        for upload in manuals:
            name = Path(upload.filename or "").name
            if Path(name).suffix.lower() not in {".xlsx", ".xlsm", ".pdf", ".docx", ".edf"}:
                raise HTTPException(400, f"{name or '所选文件'} 不是物料手册。请用 Excel、PDF、Word 或 EDIF（.edf）。")
            payloads.append((name, await read_capped_upload(upload)))
        template_bytes = b""
        template_name = ""
        if template is not None and template.filename:
            template_name = Path(template.filename).name
            if Path(template_name).suffix.lower() not in {".xlsx", ".xlsm"}:
                raise HTTPException(400, "CE BOM 模板请用 Excel。")
            template_bytes = await read_capped_upload(template)
        elif not DEFAULT_CE_BOM_TEMPLATE.is_file():
            raise HTTPException(400, "找不到默认 CE BOM 表格式。")
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            if template_bytes:
                template_path = folder / (template_name or "template.xlsx")
                template_path.write_bytes(template_bytes)
            else:
                template_path = DEFAULT_CE_BOM_TEMPLATE
            manual_paths: list[Path] = []
            for index, (name, data) in enumerate(payloads, start=1):
                target = folder / f"{index:02d}-{name}"
                target.write_bytes(data)
                manual_paths.append(target)
            previous_path = None
            if previous is not None and previous.filename:
                previous_name = Path(previous.filename).name
                if Path(previous_name).suffix.lower() not in {".xlsx", ".xlsm"}:
                    raise HTTPException(400, "上一版 CE BOM 请用 Excel。")
                previous_path = folder / f"previous-{previous_name}"
                previous_path.write_bytes(await read_capped_upload(previous))
            dest_tmp = folder / "ce-bom.xlsx"
            try:
                result = await asyncio.to_thread(
                    build_ce_bom, manual_paths, template_path, dest_tmp, previous_path,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            dest = request.app.state.jobs.output_dir / ce_bom_file_name()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(dest_tmp.read_bytes())
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        request.app.state.jobs.remember_output(
            kind="bom",
            name=dest.name,
            username=item.auth.username,
            rows=result.rows,
            pins=result.filled,
            changes=result.conflicts,
        )
        return {
            "ok": True,
            "name": dest.name,
            "download": f"/files/{dest.name}",
            "rows": result.rows,
            "filled": result.filled,
            "blank": result.blank,
            "conflicts": result.conflicts,
            "standard": result.standard,
        }

    @app.get("/api/ce-bom/history")
    def ce_bom_history(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_output("bom", username=user)
        return {
            "records": request.app.state.jobs.with_sources(rows, user, "bom"),
            "folders": request.app.state.jobs.list_record_folders(user, "bom"),
        }

    @app.post("/api/enterprise-test")
    async def create_enterprise_test(
        request: Request,
        standard: UploadFile = File(...),
        existing: UploadFile | None = File(default=None),
        rules: UploadFile | None = File(default=None),
        report_template: UploadFile | None = File(default=None),
        plan_template: UploadFile | None = File(default=None),
        supplier: str = Form(""),
        start_date: str = Form(""),
        day_count: str = Form(""),
        material_version: str = Form(""),
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """生成企标测试清单、对比表和用例，并按已给阶段模板填报。"""
        item = _require_session(request, authorization)
        standard_name = Path(standard.filename or "").name
        if Path(standard_name).suffix.lower() not in {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}:
            raise HTTPException(400, "企标请用 PDF、Word、Excel 或文本。")
        standard_bytes = await read_capped_upload(standard)

        async def _optional(
            upload: UploadFile | None,
            allowed: set[str],
            message: str,
        ) -> tuple[str, bytes]:
            if upload is None or not upload.filename:
                return "", b""
            name = Path(upload.filename).name
            if Path(name).suffix.lower() not in allowed:
                raise HTTPException(400, message)
            return name, await read_capped_upload(upload)

        existing_name, existing_bytes = await _optional(
            existing, {".docx", ".xlsx", ".xlsm", ".txt", ".md"}, "既有测试项请用 Excel、Word 或文本。"
        )
        rules_name, rules_bytes = await _optional(
            rules, {".docx", ".xlsx", ".xlsm", ".txt", ".md"}, "测试用例规则请用 Excel、Word 或文本。"
        )
        report_name, report_bytes = await _optional(
            report_template, {".docx", ".xlsx", ".xlsm"}, "测试报告阶段模板请用 Word 或 Excel。"
        )
        plan_name, plan_bytes = await _optional(
            plan_template, {".docx", ".xlsx", ".xlsm"}, "测试方案阶段模板请用 Word 或 Excel。"
        )
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)

            def _write(name: str, payload: bytes) -> Path | None:
                if not name or not payload:
                    return None
                path = folder / name
                path.write_bytes(payload)
                return path

            standard_path = folder / standard_name
            standard_path.write_bytes(standard_bytes)
            final_name = enterprise_test_file_name()
            dest_tmp = folder / final_name
            try:
                result = await asyncio.to_thread(
                    build_enterprise_test,
                    standard_path,
                    dest_tmp,
                    existing=_write(existing_name, existing_bytes),
                    rules=_write(rules_name, rules_bytes),
                    report_template=_write(report_name, report_bytes),
                    plan_template=_write(plan_name, plan_bytes),
                    supplier=supplier,
                    clock=Clock(start_date, day_count, material_version),
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            dest = request.app.state.jobs.output_dir / final_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(dest_tmp.read_bytes())
            saved: dict[str, Path | None] = {"report": None, "plan": None}
            for key, produced in (("report", result.report_path), ("plan", result.plan_path)):
                if produced is None or not produced.is_file():
                    continue
                copy = dest.parent / produced.name
                copy.write_bytes(produced.read_bytes())
                saved[key] = copy
        try:
            open_locally(dest)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        request.app.state.jobs.remember_output(
            kind="etest",
            name=dest.name,
            username=item.auth.username,
            rows=result.listed,
            pending_note=result.pending,
        )
        return {
            "ok": True,
            "name": dest.name,
            "download": f"/files/{dest.name}",
            "items": result.items,
            "listed": result.listed,
            "pending": result.pending,
            "clock_started": result.clock_started,
            "due": result.due,
            "cases": result.cases,
            "ruled": result.ruled,
            "drafts": result.drafts,
            "report": saved["report"].name if saved["report"] else "",
            "report_download": f"/files/{saved['report'].name}" if saved["report"] else "",
            "plan": saved["plan"].name if saved["plan"] else "",
            "plan_download": f"/files/{saved['plan'].name}" if saved["plan"] else "",
        }

    @app.post("/api/enterprise-test/chat")
    async def enterprise_test_chat(
        body: ChatIn,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """对话整理问题，读取已配置网址，再对照本地企标关键行作答。"""
        item = _require_session(request, authorization)
        try:
            turns = clean_turns(
                [{"role": row.role, "content": row.content} for row in body.messages]
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        model = (item.extract_model or _active_model(item) or cfg.chat_model).strip()
        try:
            analysed = await asyncio.to_thread(
                complete,
                cfg.server_url,
                item.auth,
                analysis_messages(turns),
                model=model,
                temperature=0.0,
                timeout=cfg.timeout_sec,
                extra={"thinking": {"type": "disabled"}},
            )
            page_text, page_note = await asyncio.to_thread(fetch_source_page, source_url())
            brief = await asyncio.to_thread(file_key_brief)
            tables = output_tables(page_text, brief)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        return {
            "reply": "已按企标测试清单、测试项对比表、测试用例和填报记录列出。",
            "tables": tables,
            "analysis": analysed.content,
            "page_note": page_note,
            "source_url_set": bool(source_url()),
        }

    @app.get("/api/enterprise-test/history")
    def enterprise_test_history(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        item = _require_session(request, authorization)
        user = item.auth.username
        rows = request.app.state.jobs.list_output("etest", username=user)
        return {
            "records": request.app.state.jobs.with_sources(rows, user, "etest"),
            "folders": request.app.state.jobs.list_record_folders(user, "etest"),
        }

    @app.get("/files/{name}")
    def download(
        name: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        _require_session(request, authorization)
        root = request.app.state.jobs.output_dir
        path = (root / name).resolve()
        if path.parent != root.resolve() or not path.is_file():
            raise HTTPException(404, "找不到核对表")
        media = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
        }.get(
            path.suffix.lower(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        return FileResponse(path, filename=path.name, media_type=media)

    @app.post("/api/files/{name}/open")
    def open_file(
        name: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """用本机默认程序（Excel / WPS）打开核对表。只认核对表目录里的文件。"""
        _require_session(request, authorization)
        root = request.app.state.jobs.output_dir.resolve()
        path = (root / name).resolve()
        if path.parent != root or not path.is_file():
            raise HTTPException(404, "找不到核对表")
        try:
            open_locally(path)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"ok": True, "name": path.name}

    @app.post("/api/output/open")
    def open_output_dir(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """用系统文件管理器打开核对表目录（gateway.log 也在这里）。"""
        _require_session(request, authorization)
        root = request.app.state.jobs.output_dir
        root.mkdir(parents=True, exist_ok=True)
        try:
            open_locally(root)
        except OpenError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"ok": True, "path": str(root)}

    if FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.middleware("http")
    async def no_store_ui(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    return app


def _cookie_kwargs(request: Request) -> dict[str, object]:
    proto = (
        (request.headers.get("x-forwarded-proto") or request.url.scheme or "")
        .split(",")[0]
        .strip()
        .lower()
    )
    return {
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": proto == "https",
    }


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
    # 本机工位同时只有一份登录。WebView2 上传 FormData 时偶尔不带 cookie，
    # 抽取流水线也只带 Bearer local。场所网页必须继续靠 cookie，避免串号。
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and getattr(settings, "delivery", "client") != "site":
        return sessions.default()
    return None


def _require_session(
    request: Request, authorization: str | None
) -> StoredSession:
    item = _session_from(request, authorization)
    if item is None:
        raise HTTPException(401, "请先登录")
    return item


app = create_app()


def parse_gateway_argv(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="电子电器 · SOR填表")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--site",
        action="store_true",
        help="场所网页模式（默认仍绑 127.0.0.1，由内网 nginx 转发）",
    )
    return parser.parse_args(argv)


def listen_from_args(args: argparse.Namespace) -> tuple[Settings, str, int, str]:
    settings = load_settings()
    if args.site and settings.delivery != "site":
        settings = replace(settings, delivery="site")
    host = args.host or settings.gateway_host
    port = args.port or settings.gateway_port
    host = require_gateway_bind(host, settings.delivery)
    origin = f"http://{host}:{port}"
    return settings, host, port, origin


def announce(settings: Settings, host: str, origin: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if os.environ.get("ELECTRICAL_KROW_NESTED", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return
    print(f"电子电器智能体：{origin}/", flush=True)
    print(f"识别服务：{settings.server_url}", flush=True)
    print(f"默认模型：{settings.chat_model}", flush=True)
    if settings.delivery == "site":
        print("场所网页：请用内网 nginx HTTPS 反代，不要把本服务直接暴露到公网。", flush=True)
        print("规格书落本场所磁盘，不出公网。全站同时只跑一份出表。", flush=True)
        if host in {"0.0.0.0", "::", "*"}:
            print("警告：正在监听全部网卡。务必只放行场所内网，并在前面加 HTTPS 反代。", flush=True)
    else:
        print("客户端：用登录邮箱登录后出表。文件在本机读。", flush=True)
    rules_only = os.environ.get("SPEC_SHEET_RULES_ONLY", "").strip().lower()
    if rules_only in {"1", "true", "yes"}:
        print("警告：SPEC_SHEET_RULES_ONLY 已开，将跳过模型抽取。", flush=True)


def main(argv: list[str] | None = None) -> int:
    apply_windows_event_loop_policy()
    apply_macos_client_server()
    args = parse_gateway_argv(argv)
    try:
        settings, host, port, origin = listen_from_args(args)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    announce(settings, host, origin)
    if not args.no_browser:
        webbrowser.open(f"{origin}/")
    uvicorn.run(
        create_app(settings, extract_url=origin),
        host=host,
        port=port,
        log_level=os.environ.get("KROW_UVICORN_LOG", "warning"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
