"""出表任务：全站同一时刻只跑一份（与协议「工位一份」一致）。流水线在 electrical。"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile

from electrical_krow.bridge import ensure_electrical
from electrical_krow.knowledge import knowledge_version
from electrical_krow.paths import MAX_BYTES, MAX_MB, PROJECT_ROOT, SUPPORTED, data_root

_HISTORY_FIELDS = (
    "id",
    "status",
    "percent",
    "stage",
    "message",
    "source",
    "username",
    "model",
    "stopped_early",
    "knowledge_version",
    "created_at",
    "elapsed_seconds",
    "field_count",
    "filled",
    "found",
    "miss",
    "partial",
    "pending_review",
    "likely_scan",
    "extract",
    "kind_label",
    "kind_note",
    "qa_verdict",
    "qa_summary",
    "download",
    "llm_calls",
    "rule_filled",
    "chunk_failures",
    "detail",
)
_HISTORY_LIMIT = 40
_OPEN_STATUSES = frozenset({"running", "paused", "pausing", "stopping", "queued"})


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


def review_sheet_stamp(when: datetime | None = None) -> str:
    """出表时刻：2026年09月10日17：25：14。时分秒用全角冒号，避免 Windows 文件名非法。"""
    return (when or datetime.now()).strftime("%Y年%m月%d日%H：%M：%S")


def review_sheet_name(original_name: str, when: datetime | None = None) -> str:
    """核对表文件名：原文件名 + 出表时间。"""
    return f"{_safe_stem(original_name or 'upload')}_{review_sheet_stamp(when)}.xlsx"


def _run_pipeline(incoming: Path, out: Path, *, model: str = ""):
    ensure_electrical()
    lexicon = PROJECT_ROOT / "docs" / "clause_lexicon.json"
    if lexicon.is_file():
        os.environ.setdefault("SPEC_SHEET_CLAUSE_LEXICON", str(lexicon))
    manifest = PROJECT_ROOT / "docs" / "knowledge" / "published" / "manifest.json"
    if manifest.is_file():
        os.environ.setdefault("SPEC_SHEET_KB_MANIFEST", str(manifest))
    try:
        from electrical.extract import _enterprise_manifest

        _enterprise_manifest.cache_clear()
    except Exception:
        pass
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


def _history_record(job: dict[str, object]) -> dict[str, object]:
    return {key: job[key] for key in _HISTORY_FIELDS if key in job}


def _created_at(item: dict[str, object]) -> float:
    try:
        return float(item.get("created_at") or 0)
    except (TypeError, ValueError):
        return 0.0


def job_visible_to(rec: dict[str, object], username: str) -> bool:
    """当前登录人能看见的出表记录。

    记了发起人的只给本人。未记登录名的旧行：留下有核对表或抽出格的真人出表，
    丢掉测试残渣、读失败和目录里捡到的 xlsx。
    """
    want = (username or "").strip()
    if not want:
        return True
    owner = str(rec.get("username") or "").strip()
    if owner:
        return owner == want
    if str(rec.get("id") or "").startswith("xlsx-"):
        return False
    if str(rec.get("kind_label") or "") == "测试":
        return False
    if str(rec.get("status") or "") == "error":
        return False
    return bool(rec.get("download") or rec.get("field_count"))


def _xlsx_history(path: Path) -> dict[str, object]:
    stamp = path.stat().st_mtime
    return {
        "id": f"xlsx-{path.name}",
        "status": "done",
        "message": "核对表已生成",
        "source": path.stem,
        "created_at": stamp,
        "download": f"/files/{path.name}",
    }


class JobStore:
    def __init__(self, output_dir: Path | None = None) -> None:
        self._output_dir = Path(output_dir) if output_dir is not None else data_root()
        self._upload_dir = self._output_dir / "uploads"
        self._run_lock = threading.Lock()
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._controls: dict[str, object] = {}

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def busy(self) -> bool:
        return self._run_lock.locked()

    def active(self) -> dict[str, object] | None:
        with self._lock:
            open_jobs = [
                dict(job)
                for job in self._jobs.values()
                if str(job.get("status") or "") in _OPEN_STATUSES
            ]
        if not open_jobs:
            return None
        open_jobs.sort(key=lambda item: _created_at(item), reverse=True)
        job = open_jobs[0]
        return {
            "id": job.get("id") or "",
            "status": job.get("status") or "",
            "message": job.get("message") or "",
            "source": job.get("source") or "",
        }

    def conflict_detail(self) -> str:
        job = self.active()
        status = str((job or {}).get("status") or "")
        if status == "stopping":
            return "上一份正在结束出表。结束后即可再提交。"
        return "已有任务在出表（全站同时一份）。请等当前这份完成后再提交。"

    def snapshot(self, job_id: str, *, username: str = "") -> dict[str, object]:
        with self._lock:
            data = self._jobs.get(job_id)
            if data is not None:
                found = dict(data)
            else:
                found = None
        if found is None:
            found = self._from_history(job_id)
        if found is None:
            raise HTTPException(404, "找不到该出表任务")
        if (username or "").strip() and not job_visible_to(found, username):
            raise HTTPException(404, "找不到该出表任务")
        return found

    def list_recent(
        self, limit: int = _HISTORY_LIMIT, *, username: str = ""
    ) -> list[dict[str, object]]:
        by_id: dict[str, dict[str, object]] = {}
        for rec in self._read_history():
            job_id = str(rec.get("id") or "")
            if job_id:
                by_id[job_id] = rec
        with self._lock:
            for job in self._jobs.values():
                rec = _history_record(job)
                job_id = str(rec.get("id") or "")
                if job_id:
                    by_id[job_id] = rec
        seen_files = {
            str(item.get("download") or "").rsplit("/", 1)[-1]
            for item in by_id.values()
            if item.get("download")
        }
        if self._output_dir.is_dir():
            for path in self._output_dir.glob("*.xlsx"):
                if path.name.startswith("~$") or path.name in seen_files:
                    continue
                rec = _xlsx_history(path)
                by_id[str(rec["id"])] = rec
        jobs = sorted(
            by_id.values(),
            key=lambda item: _created_at(item),
            reverse=True,
        )
        if (username or "").strip():
            jobs = [item for item in jobs if job_visible_to(item, username)]
        return jobs[: max(1, min(int(limit), 80))]

    def update(self, job_id: str, **fields: object) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def control(self, job_id: str, *, username: str = ""):
        ensure_electrical()
        with self._lock:
            ctrl = self._controls.get(job_id)
            job = self._jobs.get(job_id) or {}
            if ctrl is None:
                raise HTTPException(404, "找不到该出表任务")
            if (username or "").strip() and not job_visible_to(job, username):
                raise HTTPException(404, "找不到该出表任务")
            status = str(job.get("status") or "")
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
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        incoming = self._upload_dir / f"{token}_{_safe_stem(file.filename or 'upload')}{suffix}"
        incoming.write_bytes(data)
        out = self._output_dir / review_sheet_name(file.filename or "upload")
        return incoming, out

    def start(
        self,
        filename: str | None,
        incoming: Path,
        out: Path,
        *,
        model: str = "",
        username: str = "",
        thinking: str = "",
    ) -> str:
        if not self._run_lock.acquire(blocking=False):
            raise HTTPException(409, self.conflict_detail())
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
                "username": (username or "").strip(),
                "model": (model or "").strip(),
                "thinking": (thinking or "").strip(),
                "stopped_early": False,
                "knowledge_version": knowledge_version(),
                "created_at": time.time(),
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
                qa_verdict=getattr(result, "qa_verdict", "") or "",
                qa_summary=getattr(result, "qa_summary", "") or "",
                stopped_early=stopped,
                download=f"/files/{result.output_xlsx.name}",
                llm_calls=getattr(result, "llm_calls", 0),
                rule_filled=getattr(result, "rule_filled", 0),
                chunk_count=getattr(result, "chunk_count", 0),
                topup_count=getattr(result, "topup_count", 0),
                chunk_failures=getattr(result, "chunk_failures", 0),
                knowledge_version=knowledge_version(),
            )
        except (FileNotFoundError, ValueError) as exc:
            self.update(job_id, status="error", detail=str(exc), message="出表失败")
        except Exception as exc:  # noqa: BLE001
            kind = "抽取失败" if type(exc).__name__ == "ExtractError" else "出表失败"
            self.update(job_id, status="error", detail=str(exc), message=kind)
        finally:
            self._remember(job_id)
            set_reporter(None)
            set_control(None)
            self._run_lock.release()

    def _history_path(self) -> Path:
        return self._output_dir / "jobs.jsonl"

    def _remember(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.get("status") not in {"done", "error"}:
                return
            record = _history_record(job)
        path = self._history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            with self._persist_lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            return

    def _read_history(self) -> list[dict[str, object]]:
        path = self._history_path()
        if not path.is_file():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows: list[dict[str, object]] = []
        for line in lines[-200:]:
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("id"):
                rows.append(_history_record(data))
        return rows

    def _from_history(self, job_id: str) -> dict[str, object] | None:
        for rec in reversed(self._read_history()):
            if str(rec.get("id") or "") == job_id:
                return rec
        if job_id.startswith("xlsx-"):
            name = job_id[5:]
            if name and "/" not in name and "\\" not in name and name not in {".", ".."}:
                path = (self._output_dir / name).resolve()
                if path.parent == self._output_dir.resolve() and path.is_file():
                    return _xlsx_history(path)
        return None
