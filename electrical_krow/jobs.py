"""出表任务：全站同一时刻只跑一份（与协议「工位一份」一致）。流水线在 electrical。"""
from __future__ import annotations

import json
import os
import re
import shutil
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
    "chunk_count",
    "topup_count",
    "chunk_failures",
    "chunk_error",
    # 结果摘要：待专家口径格数、按业务分组的检索结论、与上次同名文件的差异
    "pending_note",
    "groups",
    "compare",
    "detail",
    "kind",
    "mcu",
    "package",
    "pins",
    "changes",
    "previous",
    "version",
    # 架构材料对照：文件数、条目数、整表页数、未能读取数
    "files",
    "rows",
    "tables",
    "unreadable",
)
ARCH_PREFIX = "架构对照-"
ICD_PREFIX = "ICD引脚清单-"
BOM_PREFIX = "CEBOM-"
ETEST_PREFIX = "企标测试清单-"
OUTPUT_KINDS = {
    "icd": (ICD_PREFIX, "引脚清单已生成"),
    "bom": (BOM_PREFIX, "CE BOM 已生成"),
    "etest": (ETEST_PREFIX, "企标测试清单已生成"),
}
RECORD_KINDS = frozenset({"jobs", "hsi", "arch", "icd", "bom", "etest"})
# 出表中的实时计数（不进历史）：已处理分段 / 分段总数 / 已抽出格数
_LIVE_FIELDS = {"chunk_done", "chunk_total", "filled"}
_COMPARE_LIST_LIMIT = 20
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


def _template_cells(cells: object) -> list:
    if not isinstance(cells, (list, tuple)):
        return []
    return [c for c in cells if not bool(getattr(c, "extra", False))]


def pending_note_count(cells: object) -> int:
    """复核备注里带「待专家口径」的模板格数。electrical 不在时按 0。"""
    rows = _template_cells(cells)
    if not rows:
        return 0
    try:
        from electrical.pending_rulings import pending_text
    except Exception:  # noqa: BLE001
        return 0
    return sum(1 for c in rows if pending_text(str(getattr(c, "note", "") or "")))


def group_summary(cells: object) -> list[dict[str, object]]:
    """按业务分组数三类检索结论。顺序按清单序号首次出现。"""
    rows = _template_cells(cells)
    if not rows:
        return []
    try:
        from electrical.schema import item_group
    except Exception:  # noqa: BLE001
        return []
    order: list[str] = []
    acc: dict[str, dict[str, object]] = {}
    for cell in rows:
        name = str(getattr(cell, "name", "") or "")
        seq = int(getattr(cell, "seq", 0) or 0)
        group = str(item_group(name, seq) or "其他")
        if group not in acc:
            order.append(group)
            acc[group] = {"name": group, "total": 0, "found": 0, "partial": 0, "miss": 0}
        item = acc[group]
        item["total"] = int(item["total"]) + 1
        status = str(getattr(cell, "review_status", "") or "").strip()
        if status == "已检索到":
            item["found"] = int(item["found"]) + 1
        elif status.startswith("局部对应"):
            item["partial"] = int(item["partial"]) + 1
        elif status == "未检索到":
            item["miss"] = int(item["miss"]) + 1
    return [acc[g] for g in order]


def _found_names(cells: object) -> dict[str, str]:
    """已检索到的格子（含表外补充项，与 found 计数口径一致）：键 = 序号或名称，值 = 显示名。"""
    out: dict[str, str] = {}
    if not isinstance(cells, (list, tuple)):
        return out
    for cell in cells:
        if str(getattr(cell, "review_status", "") or "").strip() != "已检索到":
            continue
        name = str(getattr(cell, "name", "") or "").strip()
        seq = int(getattr(cell, "seq", 0) or 0)
        key = f"{seq}" if seq else name
        if key and key not in out:
            out[key] = name or key
    return out


def compare_with_previous(
    cells: object, previous: dict[str, object] | None, output_dir: Path
) -> dict[str, object]:
    """同名文件再出表：与上一份核对表逐条比已检索到。读不到上一份就返回空。"""
    if not previous or not isinstance(cells, (list, tuple)):
        return {}
    name = str(previous.get("download") or "").rsplit("/", 1)[-1]
    if not name or "/" in name or "\\" in name:
        return {}
    path = (output_dir / name).resolve()
    if path.parent != output_dir.resolve() or not path.is_file():
        return {}
    try:
        from electrical.write_excel import load_review_cells

        prev_cells, _meta = load_review_cells(path)
    except Exception:  # noqa: BLE001
        return {}
    before = _found_names(prev_cells)
    after = _found_names(cells)
    gained = [after[k] for k in after if k not in before]
    lost = [before[k] for k in before if k not in after]
    return {
        "prev_id": str(previous.get("id") or ""),
        "prev_at": _created_at(previous),
        "prev_found": len(before),
        "found": len(after),
        "gained": gained[:_COMPARE_LIST_LIMIT],
        "lost": lost[:_COMPARE_LIST_LIMIT],
        "gained_n": len(gained),
        "lost_n": len(lost),
    }


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
            if str(rec.get("kind") or "") in {"hsi", "arch", "icd", "bom"}:
                continue
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
                if path.name.startswith(("HSI-", ARCH_PREFIX, ICD_PREFIX, BOM_PREFIX)):
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

    def remember_hsi(
        self,
        *,
        name: str,
        username: str,
        mcu: str,
        package: str,
        pins: int,
        changes: int,
        version: str,
        previous: bool = False,
    ) -> dict[str, object]:
        """记下一次 HSI 生成。不进 SOR 出表记录。previous 记有没有带上一版。"""
        record = {
            "id": f"hsi-{uuid.uuid4().hex[:12]}",
            "status": "done",
            "kind": "hsi",
            "message": "HSI 已生成",
            "source": name,
            "username": (username or "").strip(),
            "created_at": time.time(),
            "download": f"/files/{name}",
            "mcu": mcu,
            "package": package,
            "pins": pins,
            "changes": changes,
            "previous": bool(previous),
            "version": version,
        }
        path = self._history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(_history_record(record), ensure_ascii=False)
            with self._persist_lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            return record
        return record

    def list_hsi(
        self, limit: int = _HISTORY_LIMIT, *, username: str = ""
    ) -> list[dict[str, object]]:
        """规划记录：已记下的 HSI，再加上本机目录里还没记过的 HSI 文件。"""
        by_name: dict[str, dict[str, object]] = {}
        for rec in self._read_history():
            if str(rec.get("kind") or "") != "hsi":
                continue
            if (username or "").strip() and not job_visible_to(rec, username):
                continue
            name = str(rec.get("download") or "").rsplit("/", 1)[-1]
            if name:
                by_name[name] = rec
        if self._output_dir.is_dir():
            for path in self._output_dir.glob("HSI-*.xlsx"):
                if path.name.startswith("~$") or path.name in by_name:
                    continue
                by_name[path.name] = {
                    "id": f"hsi-file-{path.name}",
                    "status": "done",
                    "kind": "hsi",
                    "message": "HSI 已生成",
                    "source": path.name,
                    "created_at": path.stat().st_mtime,
                    "download": f"/files/{path.name}",
                }
        rows = sorted(by_name.values(), key=_created_at, reverse=True)
        return rows[: max(1, min(int(limit), 80))]

    def remember_arch(
        self,
        *,
        name: str,
        username: str,
        files: int,
        rows: int,
        tables: int,
        unreadable: int,
    ) -> dict[str, object]:
        """记下一次架构材料对照。不进 SOR 出表记录。"""
        record = {
            "id": f"arch-{uuid.uuid4().hex[:12]}",
            "status": "done",
            "kind": "arch",
            "message": "材料对照稿已生成",
            "source": name,
            "username": (username or "").strip(),
            "created_at": time.time(),
            "download": f"/files/{name}",
            "files": files,
            "rows": rows,
            "tables": tables,
            "unreadable": unreadable,
        }
        path = self._history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(_history_record(record), ensure_ascii=False)
            with self._persist_lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            return record
        return record

    def list_arch(
        self, limit: int = _HISTORY_LIMIT, *, username: str = ""
    ) -> list[dict[str, object]]:
        """拆解记录：已记下的对照稿，再加上本机目录里还没记过的对照稿文件。"""
        by_name: dict[str, dict[str, object]] = {}
        for rec in self._read_history():
            if str(rec.get("kind") or "") != "arch":
                continue
            if (username or "").strip() and not job_visible_to(rec, username):
                continue
            name = str(rec.get("download") or "").rsplit("/", 1)[-1]
            if name:
                by_name[name] = rec
        if self._output_dir.is_dir():
            for path in self._output_dir.glob(f"{ARCH_PREFIX}*.xlsx"):
                if path.name.startswith("~$") or path.name in by_name:
                    continue
                by_name[path.name] = {
                    "id": f"arch-file-{path.name}",
                    "status": "done",
                    "kind": "arch",
                    "message": "材料对照稿已生成",
                    "source": path.name,
                    "created_at": path.stat().st_mtime,
                    "download": f"/files/{path.name}",
                }
        rows = sorted(by_name.values(), key=_created_at, reverse=True)
        return rows[: max(1, min(int(limit), 80))]

    def remember_output(
        self,
        *,
        kind: str,
        name: str,
        username: str,
        **fields: object,
    ) -> dict[str, object]:
        """记下 ICD 或 CE BOM 的一次生成。不进 SOR 出表记录。"""
        _prefix, message = OUTPUT_KINDS[kind]
        record = {
            "id": f"{kind}-{uuid.uuid4().hex[:12]}",
            "status": "done",
            "kind": kind,
            "message": message,
            "source": name,
            "username": (username or "").strip(),
            "created_at": time.time(),
            "download": f"/files/{name}",
        }
        record.update({key: value for key, value in fields.items() if key in _HISTORY_FIELDS})
        path = self._history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(_history_record(record), ensure_ascii=False)
            with self._persist_lock:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except OSError:
            return record
        return record

    def list_output(
        self, kind: str, limit: int = _HISTORY_LIMIT, *, username: str = ""
    ) -> list[dict[str, object]]:
        prefix, message = OUTPUT_KINDS[kind]
        by_name: dict[str, dict[str, object]] = {}
        for rec in self._read_history():
            if str(rec.get("kind") or "") != kind:
                continue
            if (username or "").strip() and not job_visible_to(rec, username):
                continue
            name = str(rec.get("download") or "").rsplit("/", 1)[-1]
            if name:
                by_name[name] = rec
        if self._output_dir.is_dir():
            for path in self._output_dir.glob(f"{prefix}*.xlsx"):
                if path.name.startswith("~$") or path.name in by_name:
                    continue
                by_name[path.name] = {
                    "id": f"{kind}-file-{path.name}",
                    "status": "done",
                    "kind": kind,
                    "message": message,
                    "source": path.name,
                    "created_at": path.stat().st_mtime,
                    "download": f"/files/{path.name}",
                }
        rows = sorted(by_name.values(), key=_created_at, reverse=True)
        return rows[: max(1, min(int(limit), 80))]

    def list_record_folders(self, username: str, kind: str) -> list[dict[str, object]]:
        """这个人在某一类记录里建的文件夹。按新建时间从新到旧。"""
        raw = self._folder_board(username)
        folders = raw.get("folders") if isinstance(raw.get("folders"), list) else []
        rows = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "kind": kind,
                "created_at": _created_at(item),
            }
            for item in folders
            if isinstance(item, dict) and str(item.get("kind") or "") == kind and item.get("id") and item.get("name")
        ]
        rows.sort(key=_created_at, reverse=True)
        return rows

    def attach_record_folders(
        self, rows: list[dict[str, object]], username: str, kind: str
    ) -> list[dict[str, object]]:
        """给记录带上 folder_id。没放进自建文件夹的不写这个字段，界面按同一文件归类。"""
        placed = self._folder_board(username).get("placed")
        if not isinstance(placed, dict):
            placed = {}
        known = {str(item["id"]) for item in self.list_record_folders(username, kind)}
        out: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            folder_id = str(placed.get(str(item.get("id") or "")) or "")
            if folder_id in known:
                item["folder_id"] = folder_id
            out.append(item)
        return out

    def create_record_folder(self, *, username: str, kind: str, name: str) -> dict[str, object]:
        owner = (username or "").strip()
        if not owner:
            raise ValueError("请先登录。")
        if kind not in RECORD_KINDS:
            raise ValueError("记录类型不对。")
        title = (name or "").strip()
        if not title:
            raise ValueError("请填写文件夹名称。")
        if len(title) > 40:
            raise ValueError("文件夹名称请控制在 40 字以内。")
        if any(mark in title for mark in "/\\"):
            raise ValueError("文件夹名称不能包含斜杠。")
        folder = {
            "id": "fld-" + uuid.uuid4().hex[:12],
            "name": title,
            "kind": kind,
            "created_at": time.time(),
        }
        with self._persist_lock:
            book = self._load_folder_book()
            board = self._folder_board_mut(book, owner)
            folders = board["folders"]
            if any(str(item.get("kind") or "") == kind and str(item.get("name") or "") == title for item in folders):
                raise ValueError("已有同名文件夹。")
            folders.append(folder)
            self._save_folder_book(book)
        return folder

    def place_record(self, *, username: str, kind: str, record_id: str, folder_id: str) -> None:
        owner = (username or "").strip()
        if not owner:
            raise ValueError("请先登录。")
        if kind not in RECORD_KINDS:
            raise ValueError("记录类型不对。")
        record = (record_id or "").strip()
        if not record or len(record) > 180:
            raise ValueError("找不到这条记录。")
        if not self._record_visible(owner, kind, record):
            raise ValueError("找不到这条记录。")
        target = (folder_id or "").strip()
        with self._persist_lock:
            book = self._load_folder_book()
            board = self._folder_board_mut(book, owner)
            if target:
                folders = board["folders"]
                if not any(str(item.get("id") or "") == target and str(item.get("kind") or "") == kind for item in folders):
                    raise ValueError("找不到这个文件夹。")
                board["placed"][record] = target
            else:
                board["placed"].pop(record, None)
            self._save_folder_book(book)

    def _record_visible(self, username: str, kind: str, record_id: str) -> bool:
        if kind == "jobs":
            rows = self.list_recent(limit=80, username=username)
        elif kind == "hsi":
            rows = self.list_hsi(limit=80, username=username)
        elif kind == "arch":
            rows = self.list_arch(limit=80, username=username)
        elif kind in OUTPUT_KINDS:
            rows = self.list_output(kind, limit=80, username=username)
        else:
            rows = []
        if any(str(row.get("id") or "") == record_id for row in rows):
            return True
        return any(str(row.get("id") or "") == record_id for row in self.list_source_rows(username, kind))

    def _folders_path(self) -> Path:
        return self._output_dir / "record-folders.json"

    def _load_folder_book(self) -> dict[str, object]:
        path = self._folders_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_folder_book(self, book: dict[str, object]) -> None:
        path = self._folders_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")

    def _folder_board(self, username: str) -> dict[str, object]:
        book = self._load_folder_book()
        raw = book.get((username or "").strip())
        return raw if isinstance(raw, dict) else {}

    def _folder_board_mut(self, book: dict[str, object], username: str) -> dict[str, object]:
        raw = book.get(username)
        if not isinstance(raw, dict):
            raw = {}
            book[username] = raw
        folders = raw.get("folders")
        if not isinstance(folders, list):
            folders = []
            raw["folders"] = folders
        placed = raw.get("placed")
        if not isinstance(placed, dict):
            placed = {}
            raw["placed"] = placed
        sources = raw.get("sources")
        if not isinstance(sources, list):
            sources = []
            raw["sources"] = sources
        return raw

    def keep_source(
        self,
        *,
        username: str,
        kind: str,
        filename: str,
        data: bytes | None = None,
        path: Path | None = None,
        run_id: str = "",
        group_title: str = "",
        folder_id: str = "",
    ) -> dict[str, object]:
        """留下检测用的原件，和同一次输出放在一起。folder_id 有值时放进这个人建的文件夹。"""
        owner = (username or "").strip()
        if not owner:
            raise ValueError("请先登录。")
        if kind not in RECORD_KINDS:
            raise ValueError("记录类型不对。")
        name = Path(filename or "").name.strip()
        suffix = Path(name).suffix.lower()
        if not name or suffix not in SUPPORTED:
            raise ValueError("检测文件请用 PDF、Word 或 Excel。")
        if path is not None and path.is_file():
            size = path.stat().st_size
        elif data:
            size = len(data)
        else:
            raise ValueError("文件是空的")
        if size > MAX_BYTES:
            raise ValueError(f"文件超过 {MAX_MB}MB")
        title = (group_title or name).strip()[:80] or name
        target = (folder_id or "").strip()
        run = (run_id or "").strip()
        with self._persist_lock:
            book = self._load_folder_book()
            board = self._folder_board_mut(book, owner)
            sources = board["sources"]
            if run:
                for item in sources:
                    if (
                        str(item.get("kind") or "") == kind
                        and str(item.get("run_id") or "") == run
                        and str(item.get("name") or "") == name
                    ):
                        return self._source_row(item)
            if target and not any(
                str(item.get("id") or "") == target and str(item.get("kind") or "") == kind
                for item in board["folders"]
            ):
                raise ValueError("找不到这个文件夹。")
            source_id = "src-" + uuid.uuid4().hex[:12]
            stored = f"{source_id}{suffix}"
            dest = self._sources_dir() / stored
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path is not None and path.is_file():
                shutil.copyfile(path, dest)
            else:
                dest.write_bytes(data or b"")
            record = {
                "id": source_id,
                "kind": kind,
                "name": name,
                "stored": stored,
                "run_id": run,
                "group_title": title,
                "created_at": time.time(),
            }
            sources.append(record)
            if target:
                board["placed"][source_id] = target
            self._save_folder_book(book)
        return self._source_row(record)

    def list_source_rows(self, username: str, kind: str) -> list[dict[str, object]]:
        raw = self._folder_board(username)
        sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
        rows = [
            self._source_row(item)
            for item in sources
            if isinstance(item, dict) and str(item.get("kind") or "") == kind and item.get("id")
        ]
        rows.sort(key=_created_at, reverse=True)
        return rows[:80]

    def with_sources(
        self, rows: list[dict[str, object]], username: str, kind: str
    ) -> list[dict[str, object]]:
        """输出记录和检测原件合成一份列表。同一次生成的原件和输出用同一个文件夹名。"""
        linked = self.attach_record_folders(rows, username, kind)
        sources = self.attach_record_folders(self.list_source_rows(username, kind), username, kind)
        titles: dict[str, str] = {}
        for item in sources:
            run = str(item.get("run_id") or "")
            title = str(item.get("group_title") or "")
            if run and title and run not in titles:
                titles[run] = title
        merged: list[dict[str, object]] = []
        for row in linked:
            item = dict(row)
            title = titles.get(str(item.get("id") or ""))
            if title:
                item["group_title"] = title
            merged.append(item)
        merged.extend(sources)
        return merged

    def source_file(self, username: str, source_id: str) -> tuple[Path, str]:
        raw = self._folder_board(username)
        sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
        found = None
        for item in sources:
            if isinstance(item, dict) and str(item.get("id") or "") == source_id:
                found = item
                break
        if found is None:
            raise ValueError("找不到这份检测文件。")
        stored = Path(str(found.get("stored") or "")).name
        if not stored or stored in {".", ".."}:
            raise ValueError("找不到这份检测文件。")
        path = (self._sources_dir() / stored).resolve()
        root = self._sources_dir().resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("找不到这份检测文件。")
        return path, str(found.get("name") or stored)

    def _sources_dir(self) -> Path:
        return self._output_dir / "sources"

    def _source_row(self, item: dict[str, object]) -> dict[str, object]:
        source_id = str(item.get("id") or "")
        return {
            "id": source_id,
            "role": "source",
            "status": "done",
            "kind": str(item.get("kind") or ""),
            "source": str(item.get("name") or ""),
            "message": "检测文件",
            "created_at": _created_at(item),
            "download": f"/api/records/sources/{source_id}/file",
            "group_title": str(item.get("group_title") or item.get("name") or ""),
            "run_id": str(item.get("run_id") or ""),
        }

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

    def _previous_done(self, job_id: str, source: str) -> dict[str, object] | None:
        """同名文件上一次成功出表的记录（含核对表文件）。"""
        want = (source or "").strip()
        if not want:
            return None
        rows = [
            rec
            for rec in self.list_recent(limit=80)
            if str(rec.get("id") or "") != job_id
            and str(rec.get("status") or "") == "done"
            and str(rec.get("source") or "").strip() == want
            and rec.get("download")
            and rec.get("extract", True) is not False
        ]
        return rows[0] if rows else None

    def _run(self, job_id: str, incoming: Path, out: Path, model: str = "") -> None:
        from electrical.progress import set_control, set_reporter

        try:
            from electrical.progress import set_stats_reporter
        except ImportError:  # 旧版流水线没有实时计数
            set_stats_reporter = None

        def stats_reporter(fields: dict[str, int]) -> None:
            picked = {k: int(v) for k, v in fields.items() if k in _LIVE_FIELDS}
            if not picked:
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.get("status") in {"done", "error"}:
                    return
                job.update(picked)

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
        if set_stats_reporter is not None:
            set_stats_reporter(stats_reporter)
        with self._lock:
            source = str((self._jobs.get(job_id) or {}).get("source") or "")
        previous = self._previous_done(job_id, source)
        try:
            result = _run_pipeline(incoming, out, model=model)
            stopped = bool(result.stopped_early)
            cells = getattr(result, "cells", None)
            found, miss, partial = retrieval_counts(cells)
            extract_on = bool(getattr(result, "extract", True))
            compare = (
                compare_with_previous(cells, previous, self._output_dir)
                if extract_on and not stopped
                else {}
            )
            try:
                self._keep_job_source(job_id, incoming)
            except Exception:
                pass
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
                chunk_error=getattr(result, "chunk_error", "") or "",
                pending_note=pending_note_count(cells) if extract_on else 0,
                groups=group_summary(cells) if extract_on else [],
                compare=compare,
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
            if set_stats_reporter is not None:
                set_stats_reporter(None)
            self._run_lock.release()

    def _history_path(self) -> Path:
        return self._output_dir / "jobs.jsonl"

    def _keep_job_source(self, job_id: str, incoming: Path) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or {}
            username = str(job.get("username") or "")
            filename = Path(str(job.get("source") or incoming.name)).name
        if not username or not incoming.is_file():
            return
        self.keep_source(
            username=username,
            kind="jobs",
            filename=filename,
            path=incoming,
            run_id=job_id,
            group_title=filename,
        )

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
