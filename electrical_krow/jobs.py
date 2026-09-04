"""出表任务：全站同一时刻只跑一份（与协议「工位一份」一致）。流水线在 electrical。"""
from __future__ import annotations

import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile

from electrical_krow.bridge import ensure_electrical
from electrical_krow.knowledge import knowledge_version
from electrical_krow.paths import MAX_BYTES, MAX_MB, OUTPUT_DIR, PROJECT_ROOT, SUPPORTED, UPLOAD_DIR


def retrieval_counts(cells: object) -> tuple[int, int, int]:
    """已检索到 / 局部对应 / 未检索到。不是「有抽出值」的格子数。"""
    found = miss = partial = 0
    if not isinstance(cells, (list, tuple)):
        return found, miss, partial
    for cell in cells:
        status = str(getattr(cell, "review_status", "") or "").strip()
        if status == "已检索到":
            found += 1
        elif status == "未检索到":
            miss += 1
        elif status.startswith("局部对应"):
            partial += 1
    return found, miss, partial


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", stem).strip("._") or "upload"
    return stem[:80]


def review_sheet_name(original_name: str, when: datetime | None = None) -> str:
    """核对表文件名：原文件名 + 出表时间（年月日时分秒）。"""
    stamp = (when or datetime.now()).strftime("%Y%m%d%H%M%S")
    return f"{_safe_stem(original_name or 'upload')}_{stamp}.xlsx"


def _run_pipeline(incoming: Path, out: Path, *, model: str = ""):
    ensure_electrical()
    lexicon = PROJECT_ROOT / "docs" / "clause_lexicon.json"
    if lexicon.is_file():
        os.environ.setdefault("SPEC_SHEET_CLAUSE_LEXICON", str(lexicon))
    version = knowledge_version()
    if version:
        os.environ["SPEC_SHEET_KB_VERSION"] = version
    else:
        os.environ.pop("SPEC_SHEET_KB_VERSION", None)
    from electrical.pipeline import run

    kwargs = {}
    if (model or "").strip():
        kwargs["model"] = model.strip()
    return run(incoming, out, **kwargs)


class JobStore:
    def __init__(self) -> None:
        self._run_lock = threading.Lock()
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._controls: dict[str, object] = {}

    def busy(self) -> bool:
        return self._run_lock.locked()

    def snapshot(self, job_id: str) -> dict[str, object]:
        with self._lock:
            data = self._jobs.get(job_id)
            if data is None:
                raise HTTPException(404, "找不到该出表任务")
            return dict(data)

    def update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def control(self, job_id: str):
        ensure_electrical()
        with self._lock:
            ctrl = self._controls.get(job_id)
            if ctrl is None:
                raise HTTPException(404, "找不到该出表任务")
            status = str(self._jobs.get(job_id, {}).get("status") or "")
            if status in {"done", "error"}:
                raise HTTPException(409, "该任务已经结束")
            return ctrl

    def prepare_upload(self, file: UploadFile, data: bytes) -> tuple[Path, Path]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(
                400, f"暂不支持 {suffix or '该类型'}。请用 PDF / Word / Excel。"
            )
        if not data:
            raise HTTPException(400, "文件是空的")
        if len(data) > MAX_BYTES:
            raise HTTPException(400, f"文件超过 {MAX_MB}MB")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        incoming = UPLOAD_DIR / f"{token}_{_safe_stem(file.filename or 'upload')}{suffix}"
        incoming.write_bytes(data)
        out = OUTPUT_DIR / review_sheet_name(file.filename or "upload")
        return incoming, out

    def start(
        self, filename: str | None, incoming: Path, out: Path, *, model: str = ""
    ) -> str:
        if not self._run_lock.acquire(blocking=False):
            raise HTTPException(
                409, "已有任务在出表（全站同时一份）。请等当前这份完成后再提交。"
            )
        try:
            ensure_electrical()
            from electrical.progress import JobControl
        except FileNotFoundError as exc:
            self._run_lock.release()
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            self._run_lock.release()
            raise HTTPException(503, f"无法加载出表流水线：{exc}") from exc
        job_id = uuid.uuid4().hex[:12]
        ctrl = JobControl()
        with self._lock:
            self._controls[job_id] = ctrl
            self._jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "percent": 2,
                "stage": "read",
                "message": "已接收文件，开始读取…",
                "source": filename,
                "model": (model or "").strip(),
                "stopped_early": False,
                "knowledge_version": knowledge_version(),
            }
        worker = threading.Thread(
            target=self._run,
            args=(job_id, incoming, out, (model or "").strip()),
            daemon=True,
        )
        worker.start()
        return job_id

    def _run(self, job_id: str, incoming: Path, out: Path, model: str = "") -> None:
        from electrical.progress import set_control, set_reporter

        def reporter(message: str, percent: int, stage: str) -> None:
            fields: dict[str, object] = {"message": message, "stage": stage}
            if percent:
                fields["percent"] = percent
            ctrl = self._controls.get(job_id)
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.get("status") in {"done", "error"}:
                    return
                if ctrl and ctrl.stopped():
                    fields["status"] = "stopping"
                elif ctrl and ctrl.paused():
                    fields["status"] = "paused"
                else:
                    fields["status"] = "running"
                job.update(fields)

        ctrl = self._controls.get(job_id)
        set_reporter(reporter)
        set_control(ctrl)
        try:
            result = _run_pipeline(incoming, out, model=model)
            stopped = bool(result.stopped_early)
            found, miss, partial = retrieval_counts(getattr(result, "cells", None))
            self.update(
                job_id,
                status="done",
                percent=100,
                message="已按已抽出内容出表" if stopped else "出表完成",
                elapsed_seconds=result.elapsed_seconds,
                field_count=len(result.cells),
                filled=result.filled,
                found=found,
                miss=miss,
                partial=partial,
                pending_review=result.pending_review,
                likely_scan=result.likely_scan,
                extract=result.extract,
                kind_label=result.kind_label,
                kind_note=result.kind_note,
                coverage_note=result.coverage_note,
                stopped_early=stopped,
                download=f"/files/{result.output_xlsx.name}",
                llm_calls=getattr(result, "llm_calls", 0),
                rule_filled=getattr(result, "rule_filled", 0),
                chunk_count=getattr(result, "chunk_count", 0),
                topup_count=getattr(result, "topup_count", 0),
                knowledge_version=knowledge_version(),
            )
        except (FileNotFoundError, ValueError) as exc:
            self.update(job_id, status="error", detail=str(exc), message="出表失败")
        except Exception as exc:  # noqa: BLE001
            kind = "抽取失败" if type(exc).__name__ == "ExtractError" else "出表失败"
            self.update(job_id, status="error", detail=str(exc), message=kind)
        finally:
            set_reporter(None)
            set_control(None)
            self._run_lock.release()
