"""选中文件后的轻量体检：类型、页数、是否扫描件、按历史估时。不抽取、不落盘。"""
from __future__ import annotations

import re
import statistics
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from electrical_krow.bridge import ensure_electrical

_SAMPLE_PAGES = 12
_HEAD_CHARS = 16000
# 与 electrical.read_doc 的扫描件判定同阈值：每页原生字符 < 80 视为扫描件
_SCAN_CHARS_PER_PAGE = 80
_TAG = re.compile(r"<[^>]+>")


def _pdf_probe(data: bytes) -> tuple[int, str, bool]:
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = int(doc.page_count)
        texts: list[str] = []
        chars = 0
        sampled = 0
        for i, page in enumerate(doc):
            if i >= _SAMPLE_PAGES:
                break
            text = page.get_text("text") or ""
            chars += len(text.strip())
            sampled += 1
            if sum(len(t) for t in texts) < _HEAD_CHARS:
                texts.append(text)
        likely_scan = page_count > 0 and sampled > 0 and (chars / sampled) < _SCAN_CHARS_PER_PAGE
        return page_count, "\n".join(texts)[:_HEAD_CHARS], likely_scan
    finally:
        doc.close()


def _docx_probe(data: bytes) -> tuple[int, str]:
    # docProps/app.xml 的 <Pages> 常是保存时的旧值，不可信；Word 页数按 0（未知）
    try:
        with ZipFile(BytesIO(data)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", "ignore")
    except (BadZipFile, KeyError, OSError):
        return 0, ""
    xml = re.sub(r"</w:p>", "\n", xml)
    return 0, _TAG.sub("", xml)[:_HEAD_CHARS]


def _xlsx_probe(data: bytes) -> tuple[int, str]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return 0, ""
    try:
        parts: list[str] = list(wb.sheetnames)
        budget = _HEAD_CHARS
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=1, max_row=120, values_only=True):
                line = " ".join(str(v) for v in row if v not in (None, ""))
                if line:
                    parts.append(line)
                    budget -= len(line)
                if budget <= 0:
                    break
            if budget <= 0:
                break
        return len(wb.sheetnames), "\n".join(parts)[:_HEAD_CHARS]
    finally:
        wb.close()


def _classify(filename: str, head: str) -> dict[str, object]:
    try:
        ensure_electrical()
        from electrical.doc_kind import classify_document

        kind = classify_document(Path(filename or "upload"), head)
    except Exception:  # noqa: BLE001
        return {"kind_code": "", "kind_label": "", "extract": True, "kind_note": ""}
    return {
        "kind_code": kind.code,
        "kind_label": kind.label,
        "extract": bool(kind.extract),
        "kind_note": kind.note if not kind.extract else "",
    }


def estimate_seconds(
    history: list[dict[str, object]], *, kind_label: str, likely_scan: bool
) -> dict[str, object]:
    """按历史成功出表的中位耗时估时。优先同类型 + 同扫描属性，再同类型，再全部。"""
    done = [
        rec
        for rec in history
        if str(rec.get("status") or "") == "done"
        and rec.get("extract", True) is not False
        and not rec.get("stopped_early")
        and float(rec.get("elapsed_seconds") or 0) > 0
    ]
    tiers: list[tuple[str, list[dict[str, object]]]] = []
    if kind_label:
        same_kind = [r for r in done if str(r.get("kind_label") or "") == kind_label]
        tiers.append(
            ("同类型同介质", [r for r in same_kind if bool(r.get("likely_scan")) == likely_scan])
        )
        tiers.append(("同类型", same_kind))
    tiers.append(("全部历史", done))
    for scope, rows in tiers:
        if len(rows) >= 1:
            values = sorted(float(r.get("elapsed_seconds") or 0) for r in rows)
            median = statistics.median(values)
            return {
                "estimate_seconds": round(median),
                "estimate_low": round(values[0]),
                "estimate_high": round(values[-1]),
                "estimate_n": len(rows),
                "estimate_scope": scope,
            }
    return {"estimate_seconds": 0, "estimate_n": 0, "estimate_scope": ""}


def inspect_upload(
    filename: str, data: bytes, history: list[dict[str, object]] | None = None
) -> dict[str, object]:
    suffix = Path(filename or "").suffix.lower()
    page_count = 0
    head = ""
    likely_scan = False
    unit = "页"
    if suffix == ".pdf":
        try:
            page_count, head, likely_scan = _pdf_probe(data)
        except Exception:  # noqa: BLE001
            page_count, head, likely_scan = 0, "", False
    elif suffix == ".docx":
        page_count, head = _docx_probe(data)
    elif suffix in {".xlsx", ".xlsm"}:
        page_count, head = _xlsx_probe(data)
        unit = "个工作表"
    else:
        head = data[:_HEAD_CHARS * 2].decode("utf-8", "ignore")[:_HEAD_CHARS]
    info: dict[str, object] = {
        "name": filename or "",
        "size": len(data),
        "suffix": suffix,
        "page_count": page_count,
        "page_unit": unit,
        "likely_scan": likely_scan,
        "ocr": likely_scan,
    }
    info.update(_classify(filename, head))
    info.update(
        estimate_seconds(
            history or [],
            kind_label=str(info.get("kind_label") or ""),
            likely_scan=likely_scan,
        )
    )
    return info
