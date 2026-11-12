"""对照阅读路径：现网 Markdown（含整页 OCR）vs SDK 结构表 + 图片 OCR 回调。

只跑逆变器 SR 与扫描件 DPR。规则抽取对齐，不改 SuperEvo / read_doc 主路径。
"""
from __future__ import annotations

import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path

os.environ["SPEC_SHEET_RULES_ONLY"] = "1"

from modules.document_reader.pdf_reader import PdfReader
from modules.document_reader.utils import table_to_markdown
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from electrical.doc_kind import classify_document, drop_toc_pages, page_text_kind
from electrical.extract import (
    _fold_text,
    _value_fits_field,
    _value_in_source,
    extract_cells,
)
from electrical.ocr_local import (
    MAX_OCR_PAGES,
    MAX_SCAN_OCR_PAGES,
    ocr_available,
    ocr_image,
    scan_image_pages,
    sparse_pdf_pages,
)
from electrical.read_doc import MAX_CHARS, LoadedDocument, load_document
from electrical.schema import STATUS_FOUND, ExtractedCell, finalize_retrieval_statuses

SAMPLES = [
    Path(
        "/Users/wwj/电子电器项目/资料/电控开发部Agent开发第一阶段需求-1"
        "/Inverter SR from Outside.pdf"
    ),
    Path(
        "/Users/wwj/电子电器项目/资料/电控开发部Agent开发第一阶段需求-1"
        "/4LDHT260_DPR(扫描件).pdf"
    ),
]
OUT_DIR = Path("/Users/wwj/电子电器项目/electrical/output/reader_compare")
XLSX = OUT_DIR / "逆变器SR_扫描件_阅读路径对照.xlsx"

MIN_IMG_BYTES = 8_000
MIN_TABLE_IMG_BYTES = 20_000


def _ocr_bytes(image_data: bytes, mime: str) -> str:
    ext = "jpg" if "jpeg" in (mime or "") or "jpg" in (mime or "") else "png"
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=True) as handle:
        handle.write(image_data)
        handle.flush()
        text = ocr_image(Path(handle.name))
    kind = page_text_kind(text)
    if kind == "toc":
        return ""
    return text.strip() if len(text.strip()) >= 40 else ""


def _pick_images(reader: PdfReader, pages: list[int], per_page: int, min_bytes: int):
    by_page: dict[int, list] = defaultdict(list)
    want = set(pages)
    for img in reader.get_extracted_images():
        if img.page_number not in want:
            continue
        n = len(img.image_data or b"")
        if n < min_bytes:
            continue
        by_page[img.page_number].append(img)
    picked = []
    for page in pages:
        imgs = sorted(
            by_page.get(page, []),
            key=lambda item: len(item.image_data or b""),
            reverse=True,
        )
        picked.extend(imgs[:per_page])
    return picked


def load_sdk_document(path: Path) -> tuple[LoadedDocument, dict]:
    started = time.perf_counter()
    reader = PdfReader(
        path,
        extract_tables=True,
        extract_images=True,
        use_ocr=False,
    )
    reader.load()
    meta = reader.get_metadata()
    page_count = int(meta.page_count or 0)
    native_md = reader.to_markdown() or ""
    text_len = len(native_md.strip())
    likely_scan = page_count > 0 and (text_len / max(page_count, 1)) < 80

    tables_by_page: dict[int, list] = defaultdict(list)
    for table in reader.get_tables():
        tables_by_page[int(table.get("page") or 0)].append(table.get("data") or [])

    if likely_scan:
        pages = scan_image_pages(path, page_count)
        per_page, min_bytes, cap = 1, MIN_IMG_BYTES, MAX_SCAN_OCR_PAGES
        label = "扫描件图片"
    else:
        pages = sparse_pdf_pages(path, page_count) if page_count > 6 else []
        per_page, min_bytes, cap = 2, MIN_TABLE_IMG_BYTES, MAX_OCR_PAGES
        label = "表格图"
    pages = pages[:cap]
    picked = _pick_images(reader, pages, per_page=per_page, min_bytes=min_bytes)

    ocr_by_page: dict[int, list[str]] = defaultdict(list)
    if picked and ocr_available():
        n = len(picked)
        for i, img in enumerate(picked, 1):
            print(f"  SDK OCR {label} {i}/{n}  第 {img.page_number} 页", flush=True)
            text = _ocr_bytes(img.image_data or b"", img.mime_type)
            if text:
                ocr_by_page[img.page_number].append(text)

    parts: list[str] = [f"# {path.stem}", ""]
    used_pages = set(tables_by_page) | set(ocr_by_page)
    for page in reader.get_pages():
        used_pages.add(int(page["number"]))
    if not used_pages:
        used_pages = set(range(1, page_count + 1))
    for page_no in sorted(used_pages):
        parts.append(f"## 第 {page_no} 页")
        page = reader.get_page(page_no)
        if page and (page.get("content") or "").strip():
            parts.append((page["content"] or "").strip())
        for data in tables_by_page.get(page_no, []):
            if any(any(str(cell or "").strip() for cell in row) for row in data):
                parts.append(table_to_markdown(data))
        for text in ocr_by_page.get(page_no, []):
            parts.append(f"[本页为 SDK 图片 OCR]\n{text}")
        parts.append("")

    markdown = drop_toc_pages("\n\n".join(parts))
    if len(markdown) > MAX_CHARS:
        markdown = (
            markdown[:MAX_CHARS]
            + "\n\n[文档过长，已截断。优先使用前半部分已出现的参数表。]\n"
        )
    kind = classify_document(path, markdown)
    doc = LoadedDocument(
        path=path,
        markdown=markdown,
        page_count=page_count,
        likely_scan=likely_scan,
        parser="PdfReader+tables+ocr_callback",
        ocr_pages=len(ocr_by_page),
        kind=kind,
    )
    stats = {
        "elapsed": round(time.perf_counter() - started, 1),
        "tables": len(reader.get_tables()),
        "images": len(reader.get_extracted_images()),
        "ocr_images": len(picked),
        "ocr_pages": len(ocr_by_page),
        "md_chars": len(markdown),
        "kind": kind.code if kind else "",
        "extract": bool(kind.extract) if kind else True,
        "likely_scan": likely_scan,
    }
    return doc, stats


def _extract(doc: LoadedDocument) -> list[ExtractedCell]:
    cells = extract_cells(doc)
    finalize_retrieval_statuses(cells)
    return [c for c in cells if not c.extra]


def _ok(cell: ExtractedCell, markdown: str) -> bool:
    if (cell.review_status or "") != STATUS_FOUND:
        return False
    if not _value_in_source(cell.value, cell.excerpt, markdown):
        return False
    return _value_fits_field(cell.name, cell.value, cell.excerpt)


def _counts(cells: list[ExtractedCell], markdown: str) -> dict[str, int]:
    filled = [c for c in cells if (c.value or "").strip()]
    found = [c for c in cells if (c.review_status or "") == STATUS_FOUND]
    return {
        "filled": len(filled),
        "found": len(found),
        "ok": sum(1 for c in cells if _ok(c, markdown)),
        "found_not_in_src": sum(
            1
            for c in found
            if not _value_in_source(c.value, c.excerpt, markdown)
        ),
    }


def _cell_map(cells: list[ExtractedCell]) -> dict[int, ExtractedCell]:
    return {c.seq: c for c in cells}


def main() -> None:
    if not ocr_available():
        raise SystemExit("本机没有 OCR，无法对照图片回调。")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    summary = wb.active
    summary.title = "对照摘要"
    headers = [
        "文件",
        "路径",
        "分流",
        "页数",
        "Markdown字数",
        "结构表",
        "抽出图片",
        "OCR页/图",
        "读取秒",
        "已填",
        "已检索到",
        "已检索到且对原文",
        "已检索到但不在原文",
        "相对现路径多出的准格",
        "相对现路径丢失的准格",
    ]
    summary.append(headers)
    for col, _ in enumerate(headers, 1):
        summary.cell(1, col).font = Font(bold=True)

    detail = wb.create_sheet("逐条对照")
    detail.append(
        [
            "文件",
            "序号",
            "条目",
            "现路径值",
            "SDK路径值",
            "现状态",
            "SDK状态",
            "现路径准",
            "SDK路径准",
            "变化",
        ]
    )
    detail.cell(1, 1).font = Font(bold=True)
    green = PatternFill("solid", fgColor="C6EFCE")
    red = PatternFill("solid", fgColor="FFC7CE")
    gray = PatternFill("solid", fgColor="D9D9D9")

    print("规则抽取对照（SPEC_SHEET_RULES_ONLY=1），不动 SuperEvo 主路径。", flush=True)
    for path in SAMPLES:
        if not path.is_file():
            raise SystemExit(f"找不到样张: {path}")
        print(f"\n==== {path.name}  现路径 ====", flush=True)
        t0 = time.perf_counter()
        current_doc = load_document(path)
        current_read = round(time.perf_counter() - t0, 1)
        current_cells = _extract(current_doc)
        current_c = _counts(current_cells, current_doc.markdown)
        (OUT_DIR / f"{path.stem}_现路径.md").write_text(
            current_doc.markdown, encoding="utf-8"
        )

        print(f"==== {path.name}  SDK 结构表+图片OCR ====", flush=True)
        sdk_doc, sdk_stats = load_sdk_document(path)
        sdk_cells = _extract(sdk_doc)
        sdk_c = _counts(sdk_cells, sdk_doc.markdown)
        (OUT_DIR / f"{path.stem}_SDK路径.md").write_text(
            sdk_doc.markdown, encoding="utf-8"
        )

        cur_map = _cell_map(current_cells)
        sdk_map = _cell_map(sdk_cells)
        gained: list[str] = []
        lost: list[str] = []
        for seq in sorted(set(cur_map) | set(sdk_map)):
            a = cur_map.get(seq)
            b = sdk_map.get(seq)
            a_ok = _ok(a, current_doc.markdown) if a else False
            b_ok = _ok(b, sdk_doc.markdown) if b else False
            change = ""
            if b_ok and not a_ok:
                change = "SDK新准"
                gained.append((b.name if b else str(seq)))
            elif a_ok and not b_ok:
                change = "SDK丢准"
                lost.append((a.name if a else str(seq)))
            elif (a and a.value) != (b and b.value) and (a_ok or b_ok):
                change = "值不同"
            row = [
                path.name,
                seq,
                (a or b).name if (a or b) else "",
                (a.value if a else ""),
                (b.value if b else ""),
                (a.review_status if a else ""),
                (b.review_status if b else ""),
                "是" if a_ok else "",
                "是" if b_ok else "",
                change,
            ]
            detail.append(row)
            fill = green if change == "SDK新准" else red if change == "SDK丢准" else None
            if fill:
                for col in range(1, 11):
                    detail.cell(detail.max_row, col).fill = fill

        kind_label = (
            current_doc.kind.label if current_doc.kind else sdk_doc.kind.label
            if sdk_doc.kind
            else ""
        )
        summary.append(
            [
                path.name,
                "现路径 Markdown+整页OCR",
                kind_label,
                current_doc.page_count,
                len(current_doc.markdown),
                "含 to_markdown 尾表",
                "-",
                current_doc.ocr_pages,
                current_read,
                current_c["filled"],
                current_c["found"],
                current_c["ok"],
                current_c["found_not_in_src"],
                0,
                0,
            ]
        )
        summary.append(
            [
                path.name,
                "SDK get_tables + 图片OCR回调",
                sdk_doc.kind.label if sdk_doc.kind else "",
                sdk_doc.page_count,
                sdk_stats["md_chars"],
                sdk_stats["tables"],
                sdk_stats["images"],
                f"{sdk_stats['ocr_pages']}页/{sdk_stats['ocr_images']}图",
                sdk_stats["elapsed"],
                sdk_c["filled"],
                sdk_c["found"],
                sdk_c["ok"],
                sdk_c["found_not_in_src"],
                len(gained),
                len(lost),
            ]
        )
        print(
            f"  现路径  已检索到 {current_c['found']}  对准 {current_c['ok']}  "
            f"OCR页 {current_doc.ocr_pages}  {current_read}s",
            flush=True,
        )
        print(
            f"  SDK    已检索到 {sdk_c['found']}  对准 {sdk_c['ok']}  "
            f"表 {sdk_stats['tables']} 图 {sdk_stats['images']}  "
            f"OCR {sdk_stats['ocr_pages']}页  {sdk_stats['elapsed']}s",
            flush=True,
        )
        print(f"  SDK新准 {len(gained)}  SDK丢准 {len(lost)}", flush=True)
        if gained:
            print("  新准:", "、".join(gained[:12]), flush=True)
        if lost:
            print("  丢准:", "、".join(lost[:12]), flush=True)

    note = wb.create_sheet("口径")
    note.append(["对照口径"])
    note.append(["抽取", "SPEC_SHEET_RULES_ONLY=1，排除模型随机性"])
    note.append(["现路径", "electrical.read_doc.load_document：to_markdown + 整页渲染 OCR"])
    note.append(
        [
            "SDK路径",
            "PdfReader.get_tables 按页写入 + 对稀疏页/扫描页的嵌入图做 ocr_callback",
        ]
    )
    note.append(["准", "已检索到，且值/摘录能在该路径 Markdown 里对上，且通过条目拒误绑"])
    note.append(["未改", "SuperEvo 主路径、read_doc.py、extract.py 均未改"])
    note.append(["样张", "Inverter SR from Outside.pdf；4LDHT260_DPR(扫描件).pdf"])
    for col in range(1, 3):
        note.cell(1, col).font = Font(bold=True)
        note.cell(1, col).fill = gray

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wb.save(XLSX)
    print(f"\nwrote {XLSX}", flush=True)


if __name__ == "__main__":
    main()
