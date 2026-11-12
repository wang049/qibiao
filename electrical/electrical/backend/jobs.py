"""出表任务：同一时刻只跑一份。"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile

from electrical.backend.paths import MAX_BYTES, MAX_MB, OUTPUT_DIR, UPLOAD_DIR
from electrical.extract import ExtractError
from electrical.pipeline import run
from electrical.progress import JobControl, set_control, set_reporter
from electrical.read_doc import SUPPORTED


def _safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", stem).strip("._") or "upload"
    return stem[:80]


def review_sheet_stamp(when: datetime | None = None) -> str:
    """出表时刻：2026年09月10日17：25：14。时分秒用全角冒号，避免 Windows 文件名非法。"""
    return (when or datetime.now()).strftime("%Y年%m月%d日%H：%M：%S")


def review_sheet_name(original_name: str, when: datetime | None = None) -> str:
    """核对表文件名：原文件名 + 出表时间。"""
    return f"{_safe_stem(original_name or 'upload')}_{review_sheet_stamp(when)}.xlsx"


class JobStore:
    def __init__(self) -> None:
        self._run_lock = threading.Lock()
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._controls: dict[str, JobControl] = {}

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

    def control(self, job_id: str) -> JobControl:
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
            raise HTTPException(400, f"暂不支持 {suffix or '该类型'}。请用 PDF / Word / Excel。")
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

    def start(self, filename: str | None, incoming: Path, out: Path) -> str:
        if not self._run_lock.acquire(blocking=False):
            raise HTTPException(409, "已有任务在出表，请等当前这份完成。")
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
                "stopped_early": False,
            }
        worker = threading.Thread(
            target=self._run,
            args=(job_id, incoming, out),
            daemon=True,
        )
        worker.start()
        return job_id

    def _run(self, job_id: str, incoming: Path, out: Path) -> None:
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
            result = run(incoming, out)
            stopped = bool(result.stopped_early)
            self.update(
                job_id,
                status="done",
                percent=100,
                message="已按已抽出内容出表" if stopped else "出表完成",
                elapsed_seconds=result.elapsed_seconds,
                field_count=len(result.cells),
                filled=result.filled,
                pending_review=result.pending_review,
                likely_scan=result.likely_scan,
                extract=result.extract,
                kind_label=result.kind_label,
                kind_note=result.kind_note,
                coverage_note=result.coverage_note,
                qa_verdict=getattr(result, "qa_verdict", "") or "",
                qa_summary=getattr(result, "qa_summary", "") or "",
                stopped_early=stopped,
                download=f"/files/{result.output_xlsx.name}",
            )
        except (FileNotFoundError, ValueError) as exc:
            self.update(job_id, status="error", detail=str(exc), message="出表失败")
        except ExtractError as exc:
            self.update(job_id, status="error", detail=str(exc), message="抽取失败")
        except Exception as exc:  # noqa: BLE001
            self.update(job_id, status="error", detail=str(exc), message="出表失败")
        finally:
            set_reporter(None)
            set_control(None)
            self._run_lock.release()
