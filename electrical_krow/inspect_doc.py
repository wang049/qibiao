"""选中文件后的轻量体检：类型、页数、是否扫描件、按历史估时。不抽取、不落盘。"""
from __future__ import annotations

import statistics
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from electrical_krow.bridge import ensure_electrical

# 长文档前后各抽一半，避免只看封面把后半本扫描页当成电子版。
_SAMPLE_PAGES = 24
_HEAD_PAGES = 8
_HEAD_CHARS = 16000
# 与 electrical.read_doc 的扫描件判定同阈值：每页原生字符 < 80 视为扫描件
_SCAN_CHARS_PER_PAGE = 80
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _sample_indexes(page_count: int, limit: int = _SAMPLE_PAGES) -> list[int]:
    """页数不超过上限时全读；更长则前半本、后半本各均匀抽一半。"""
    if page_count <= 0:
        return []
    if page_count <= limit:
        return list(range(page_count))
    mid = page_count // 2
    per = max(2, limit // 2)

    def pick(start: int, end: int, count: int) -> list[int]:
        span = end - start
        if span <= count:
            return list(range(start, end))
        step = (span - 1) / (count - 1)
        return sorted({start + int(round(i * step)) for i in range(count)})

    return sorted(set(pick(0, mid, per) + pick(mid, page_count, per)))


def _mean(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _pdf_is_scan(page_count: int, counts: list[tuple[int, int]]) -> bool:
    """全文抽样偏少，或后半本抽样骤降到阈值以下，整本按扫描件。"""
    if page_count <= 0 or not counts:
        return False
    overall = _mean([n for _, n in counts])
    if overall is not None and overall < _SCAN_CHARS_PER_PAGE:
        return True
    mid = page_count / 2
    second = [n for index, n in counts if index >= mid]
    # 至少两页，避免文末单独一张空白页把整本判成扫描件。
    second_avg = _mean(second)
    return second_avg is not None and len(second) >= 2 and second_avg < _SCAN_CHARS_PER_PAGE


def _pdf_probe(data: bytes) -> tuple[int, str, bool]:
    import fitz

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = int(doc.page_count)
        texts: list[str] = []
        used = 0
        # 分类用的摘录仍取开头，避免把后半本抽样灌进类型判断。
        for i in range(min(page_count, _HEAD_PAGES)):
            if used >= _HEAD_CHARS:
                break
            text = doc[i].get_text("text") or ""
            texts.append(text)
            used += len(text)
        counts: list[tuple[int, int]] = []
        for index in _sample_indexes(page_count):
            text = doc[index].get_text("text") or ""
            counts.append((index, len(text.strip())))
        return page_count, "\n".join(texts)[:_HEAD_CHARS], _pdf_is_scan(page_count, counts)
    finally:
        doc.close()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_text(node: ET.Element) -> str:
    return "".join(piece.text or "" for piece in node.iter(f"{_W}t")).strip()


def _part_lines(xml: bytes) -> tuple[list[str], int]:
    """正文按段落和表格单元格取出。返回行，以及显式分页次数。"""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return [], 0
    breaks = 0
    for node in root.iter(f"{_W}br"):
        if node.get(f"{_W}type") == "page":
            breaks += 1
    breaks += sum(1 for _ in root.iter(f"{_W}lastRenderedPageBreak"))
    lines: list[str] = []
    body = root.find(f"{_W}body")
    nodes = list(body) if body is not None else [root]
    for node in nodes:
        kind = _local(node.tag)
        if kind == "tbl":
            for row in node.findall(f"{_W}tr"):
                cells = [_xml_text(cell) for cell in row.findall(f"{_W}tc")]
                line = " | ".join(cell for cell in cells if cell)
                if line:
                    lines.append(line)
        elif kind == "p":
            line = _xml_text(node)
            if line:
                lines.append(line)
    if not lines and body is None:
        line = _xml_text(root)
        if line:
            lines.append(line)
    return lines, breaks


def _docx_probe(data: bytes) -> tuple[int, str]:
    # docProps/app.xml 的 Pages 常是保存时的旧值，不用。
    # 没有显式分页时页数仍为未知（0）；有分页符则按分页次数加一页。
    try:
        with ZipFile(BytesIO(data)) as zf:
            names = zf.namelist()
            document = zf.read("word/document.xml") if "word/document.xml" in names else b""
            headers = [zf.read(name) for name in names if name.startswith("word/header") and name.endswith(".xml")]
            footers = [zf.read(name) for name in names if name.startswith("word/footer") and name.endswith(".xml")]
    except (BadZipFile, KeyError, OSError):
        return 0, ""
    body, breaks = _part_lines(document) if document else ([], 0)
    sections: list[str] = []
    for blob in headers:
        lines, _ = _part_lines(blob)
        if lines:
            sections.append("【页眉】\n" + "\n".join(lines))
    if body:
        sections.append("【正文】\n" + "\n".join(body))
    for blob in footers:
        lines, _ = _part_lines(blob)
        if lines:
            sections.append("【页脚】\n" + "\n".join(lines))
    page_count = breaks + 1 if breaks else 0
    return page_count, "\n".join(sections)[:_HEAD_CHARS]


def _row_text(row: tuple[object, ...]) -> str:
    return " | ".join(str(value) for value in row if value not in (None, ""))


def _xlsx_probe(data: bytes) -> tuple[int, str]:
    try:
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return 0, ""
    try:
        parts: list[str] = []
        budget = _HEAD_CHARS
        for ws in wb.worksheets:
            span = getattr(ws, "dimensions", "") or ""
            title = f"[{ws.title}] 范围 {span}".rstrip()
            parts.append(title)
            budget -= len(title)
            for row in ws.iter_rows(values_only=True):
                line = _row_text(row)
                if not line:
                    continue
                parts.append(line)
                budget -= len(line)
                if budget <= 0:
                    break
            if budget <= 0:
                break
        return len(wb.sheetnames), "\n".join(parts)[:_HEAD_CHARS]
    finally:
        wb.close()


def document_needs_ocr(filename: str, data: bytes) -> bool | None:
    """体检口径：PDF 判为扫描件才需要远程 OCR。无法判断时返回 None。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix != ".pdf":
        return False
    try:
        _pages, _head, likely_scan = _pdf_probe(data)
    except Exception:  # noqa: BLE001
        return None
    return likely_scan


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
