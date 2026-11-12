"""用 krow runtime 的 document_reader 做 System-1 读文件，不走 LLM。"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from modules.document_reader import get_reader

from electrical.doc_kind import DocKind, classify_document, drop_toc_pages
from electrical.progress import report
from electrical.ocr_local import (
    MAX_OCR_PAGES,
    _keep_ocr_page,
    merge_ocr_into_markdown,
    ocr_available,
    ocr_image,
    ocr_pdf_pages,
    scan_image_pages,
    sparse_pdf_pages,
)

SUPPORTED = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}
MAX_CHARS = 400_000
_TABLE_CELL_WIDTH = 200
_MIN_DOCX_IMAGE_BYTES = 12_000
_MIN_NATIVE_DOCX_CHARS = 2_500
_MD_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_TABLE_SEP_CELL = re.compile(r"^:?-{3,}:?$")


def _heading_level(style_name: str) -> int:
    name = (style_name or "").strip()
    if name.startswith("Heading") and name[-1:].isdigit():
        return int(name[-1])
    match = re.match(r"标题\s*(\d)", name)
    return int(match.group(1)) if match else 0


def _is_vmerge_continue(tc) -> bool:
    return getattr(tc, "vMerge", None) == "continue"


def _paragraph_text(p_elm, parent) -> str:
    from docx.text.paragraph import Paragraph

    return Paragraph(p_elm, parent).text.strip()


def _iter_txbx_blocks(p_elm):
    from docx.oxml.ns import qn
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for txbx in p_elm.findall(".//" + qn("w:txbxContent")):
        for child in txbx.iterchildren():
            if isinstance(child, (CT_P, CT_Tbl)):
                yield child


def _tc_direct_text(tc, parent) -> str:
    from docx.oxml.text.paragraph import CT_P

    parts: list[str] = []
    for child in tc.iterchildren():
        if not isinstance(child, CT_P):
            continue
        text = _paragraph_text(child, parent)
        if text:
            parts.append(text)
        for inner in _iter_txbx_blocks(child):
            if isinstance(inner, CT_P):
                boxed = _paragraph_text(inner, parent)
                if boxed:
                    parts.append(boxed)
    return " ".join(parts)


def _iter_nested_tbls(tc):
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P

    for child in tc.iterchildren():
        if isinstance(child, CT_Tbl):
            yield child
        elif isinstance(child, CT_P):
            for inner in _iter_txbx_blocks(child):
                if isinstance(inner, CT_Tbl):
                    yield inner


def _pad_table_rows(rows: list[list[str]]) -> list[list[str]]:
    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return []
    return [row + [""] * (width - len(row)) for row in rows]


def _convert_tbl(tbl_elm, parent) -> list[str]:
    """一张表转 Markdown；合并格只保留一次，内表跟在后面。"""
    from docx.table import Table
    from modules.document_reader.utils import table_to_markdown

    table = Table(tbl_elm, parent)
    rows_out: list[list[str]] = []
    nested_md: list[str] = []
    for row in table.rows:
        line: list[str] = []
        for tc in row._tr.tc_lst:
            span = max(int(getattr(tc, "grid_span", 1) or 1), 1)
            if _is_vmerge_continue(tc):
                line.extend([""] * span)
                continue
            line.append(_tc_direct_text(tc, parent))
            line.extend([""] * (span - 1))
            for nested in _iter_nested_tbls(tc):
                nested_md.extend(_convert_tbl(nested, parent))
        rows_out.append(line)
    rows_out = _pad_table_rows(rows_out)
    chunks: list[str] = []
    if any(any(cell for cell in row) for row in rows_out):
        chunks.append(table_to_markdown(rows_out, max_col_width=_TABLE_CELL_WIDTH))
    chunks.extend(nested_md)
    return chunks


# 印在页上的页码形如 3 (116) / Page No 78 (116) / 第 78 页。
_HEADER_PAGE_PAIR = re.compile(r"(\d{1,4})\s*[\(（]\s*(\d{1,4})\s*[\)）]")
_PAGE_SLASH_PAIR = re.compile(
    r"(?i)(?:page\s*(?:no\.?)?|页码)\s*[:：]?\s*(\d{1,4})\s*(?:/|of|／)\s*(\d{1,4})"
)
_PAGE_NO_CAPTION = re.compile(
    r"(?i)(?:page\s*no\.?|页码)\s*[:：]?\s*(\d{1,4})\s*[\(（]\s*(\d{1,4})\s*[\)）]"
)
_CHROME_SLASH_PAIR = re.compile(r"(?i)(\d{1,4})\s*(?:/|of|／)\s*(\d{1,4})")
_CHROME_CN_PAGE = re.compile(r"第\s*(\d{1,4})\s*页")
_TOC_TRAILING_PAGE = re.compile(r"\s+\d{1,3}$")
_WML = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_OUTLINE_LVL_TEXT = re.compile(r"^%1(?:\.%[2-9])*\.?$")
_LEADING_DOTTED_HEADING = re.compile(r"^\d{1,2}(?:\.\d{1,3})+\.?\s")
# 对齐 Word 段落时去掉写回的 x.y.z；不要误伤 20.2kg 这种一位小数。
_LEADING_CLAUSE_KEY = re.compile(r"^\d{1,2}(?:\.\d{1,3}){2,5}\.?")
_WD_PRINT_VIEW = 3
_WD_ACTIVE_END_PAGE_NUMBER = 3
_OFFICE_WORD_PROG_IDS = (
    "Word.Application",
    "Kwps.Application",
    "KWPS.Application",
    "wps.Application",
)


def _dispatch_office_word():
    """Windows 上启动 Word 或 WPS 文字。没有办公套件时返回 None。"""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    pythoncom.CoInitialize()
    for prog_id in _OFFICE_WORD_PROG_IDS:
        try:
            app = win32com.client.DispatchEx(prog_id)
        except Exception:
            continue
        try:
            app.Visible = False
        except Exception:
            pass
        try:
            app.DisplayAlerts = 0
        except Exception:
            pass
        return app
    return None


def _close_office_document(document, app) -> None:
    if document is not None:
        try:
            document.Close(False)
        except Exception:
            pass
    if app is not None:
        try:
            app.Quit()
        except Exception:
            pass


def _norm_page_key(text: str) -> str:
    blob = re.sub(r"\s+", "", (text or "").replace("\xa0", " ")).lower()
    return _LEADING_CLAUSE_KEY.sub("", blob, count=1)


def _event_page_needle(event: tuple) -> str:
    kind = event[0]
    if kind in {"heading", "para"}:
        return _norm_page_key(event[1] or "")
    chunks = event[1] or []
    blob = " ".join(str(chunk) for chunk in chunks[:2]).replace("|", " ")
    return _norm_page_key(blob)


def _page_keys_hit(needle: str, key: str) -> bool:
    if len(needle) < 18 or len(key) < 12:
        return False
    prefix = needle[:28]
    return prefix in key or key[:28] in needle


def _align_events_to_word_pages(
    events: list[tuple],
    para_pages: list[tuple[str, int]],
    *,
    fill_unmatched: bool = False,
) -> list[int]:
    """按正文顺序，把每个块对到 Word 给出的印页。"""
    keys = [(_norm_page_key(text), int(page)) for text, page in para_pages]
    keys = [(text, page) for text, page in keys if text and page >= 1]
    used = [False] * len(keys)
    cursor = 0
    out = [0] * len(events)
    for i, event in enumerate(events):
        needle = _event_page_needle(event)
        found = -1
        if len(needle) >= 18:
            for j in range(cursor, len(keys)):
                if used[j]:
                    continue
                if _page_keys_hit(needle, keys[j][0]):
                    found = j
                    break
        if found >= 0:
            out[i] = keys[found][1]
            used[found] = True
            cursor = found + 1
            continue
        if not fill_unmatched or not keys:
            continue
        if cursor < len(keys):
            out[i] = keys[cursor][1]
        else:
            out[i] = keys[-1][1]
    return out


def _office_paragraph_pages(path: Path) -> list[tuple[str, int]] | None:
    """打开后问 Word / WPS：这一段印在第几页（页眉 PAGE，不是目录、也不是 XML 缓存）。"""
    if os.name != "nt":
        return None
    app = None
    document = None
    try:
        app = _dispatch_office_word()
        if app is None:
            return None
        document = app.Documents.Open(str(path.resolve()), ReadOnly=True)
        try:
            app.ActiveWindow.View.Type = _WD_PRINT_VIEW
        except Exception:
            pass
        try:
            document.Repaginate()
        except Exception:
            pass
        try:
            document.Fields.Update()
        except Exception:
            pass
        out: list[tuple[str, int]] = []
        for para in document.Paragraphs:
            raw = para.Range.Text or ""
            text = " ".join(raw.replace("\x07", " ").split())
            if len(text) < 4:
                continue
            try:
                page = int(para.Range.Information(_WD_ACTIVE_END_PAGE_NUMBER))
            except Exception:
                continue
            if page >= 1:
                out.append((text, page))
        return out if len(out) >= 3 else None
    except Exception:
        return None
    finally:
        _close_office_document(document, app)


def _pages_from_word_app(path: Path, events: list[tuple]) -> list[int] | None:
    if os.name == "nt":
        report("正在用本机 Word 读取页眉页码…", percent=5, stage="read")
    pairs = _office_paragraph_pages(path)
    if not pairs:
        return None
    matched = _align_events_to_word_pages(events, pairs)
    hits = sum(1 for page in matched if page)
    long_n = sum(1 for event in events if len(_event_page_needle(event)) >= 18)
    if not hits:
        return None
    if long_n and hits < max(3, long_n * 2 // 10):
        return None
    return _align_events_to_word_pages(events, pairs, fill_unmatched=True)


def _event_search_text(event: tuple) -> str:
    if event[0] in {"heading", "para"}:
        return re.sub(r"\s+", " ", (event[1] or "").strip())
    return ""


def _has_mupdf_body_prose(text: str) -> bool:
    collapsed = re.sub(r"\s+", " ", text or "")
    for match in re.finditer(r"[A-Z][^.!?]{40,}[.!?]", collapsed):
        if len(re.findall(r"[A-Za-z]{3,}", match.group())) >= 10:
            return True
    return bool(re.search(r"[\u4e00-\u9fff].{8,}[。]", collapsed))


def _is_mupdf_toc_page(text: str) -> bool:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) < 6:
        return False
    trailing = sum(
        1 for line in lines if _TOC_TRAILING_PAGE.search(line) and len(line) >= 8
    )
    return trailing >= 6 and not _has_mupdf_body_prose(text)


def _mupdf_toc_only_pages(pages_text: list[str]) -> set[int]:
    """正文前连续的目录页（1-based）。目录和正文挤在同一页的不算。"""
    out: set[int] = set()
    started = False
    for index, text in enumerate(pages_text[:16], 1):
        if _is_mupdf_toc_page(text):
            out.add(index)
            started = True
            continue
        if started:
            break
    return out


def _carry_printed_pages(pages: list[int]) -> list[int]:
    """未对上的块沿用上一处读到的印页，不按字数插值。"""
    if not pages or not any(pages):
        return pages
    first = next(page for page in pages if page)
    last = 0
    out = [0] * len(pages)
    for i, page in enumerate(pages):
        if page:
            last = page
            first = page
            out[i] = page
        else:
            out[i] = last or first
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def _search_event_physical_pages(raw_pages: list[str], events: list[tuple]) -> list[int] | None:
    """把每个正文块对到渲染页（1-based）；对不上的为 0。"""
    if len(raw_pages) < 8 or not events:
        return None
    pages_text = [re.sub(r"\s+", " ", text) for text in raw_pages]
    lowered = [text.lower() for text in pages_text]
    toc_only = _mupdf_toc_only_pages(raw_pages)
    n = len(events)
    pms = [0] * n
    prev = 1
    long_n = 0
    hits = 0
    for i, event in enumerate(events):
        raw = _event_search_text(event)
        if len(raw) < 20:
            continue
        if len(raw) >= 24:
            long_n += 1
        needle = (raw[:40] if len(raw) > 40 else raw).lower()
        all_hits = [pi + 1 for pi, blob in enumerate(lowered) if needle in blob]
        if not all_hits:
            continue
        body_hits = [page for page in all_hits if page not in toc_only]
        if not body_hits:
            continue
        on_toc = any(page in toc_only for page in all_hits)
        forward = [page for page in body_hits if page >= prev]
        if on_toc and len(raw) < 36:
            hit = forward[0] if forward else 0
            if not hit or hit - prev > 20:
                continue
        elif forward:
            hit = forward[0]
        elif len(body_hits) == 1:
            hit = body_hits[0]
        else:
            continue
        pms[i] = hit
        prev = max(prev, hit)
        hits += 1
    if long_n and hits < max(8, long_n * 2 // 10):
        return None
    return pms


def _printed_from_physical(
    physical: list[int],
    labels: list[int] | None = None,
) -> list[int]:
    pages = [0] * len(physical)
    if not labels:
        return pages
    for i, pm in enumerate(physical):
        if pm and 1 <= pm <= len(labels):
            pages[i] = labels[pm - 1]
    return pages


def _pages_from_rendered_texts(
    raw_pages: list[str],
    events: list[tuple],
    labels: list[int] | None = None,
) -> list[int] | None:
    physical = _search_event_physical_pages(raw_pages, events)
    if not physical or not labels:
        return None
    pages = _printed_from_physical(physical, labels=labels)
    filled = _carry_printed_pages(pages)
    if not any(filled):
        return None
    return filled


def _pages_from_pdf_file(pdf_path: Path, events: list[tuple]) -> list[int] | None:
    try:
        import fitz

        doc = fitz.open(str(pdf_path))
    except Exception:
        return None
    try:
        raw_pages = [page.get_text("text") or "" for page in doc]
        labels = _pdf_page_labels(doc, require_chrome=True)
    finally:
        doc.close()
    if len(raw_pages) < 2 or not labels:
        return None
    return _pages_from_rendered_texts(raw_pages, events, labels=labels)


def _sidecar_pdf(path: Path) -> Path | None:
    pdf = path.with_suffix(".pdf")
    try:
        if pdf.is_file() and pdf.stat().st_size >= 1000:
            return pdf
    except OSError:
        return None
    return None


def _w(tag: str) -> str:
    return f"{_WML}{tag}"


def _xml_val(node, attr: str = "val") -> str:
    if node is None:
        return ""
    return node.get(_w(attr)) or node.get(attr) or ""


def _prefix_printed_number(text: str, number: str) -> str:
    """标题无手打条款号时，把 Word 大纲自动编号写回正文。"""
    text = (text or "").strip()
    number = (number or "").strip().rstrip(".")
    if not text or not number:
        return text
    if text.startswith(number):
        return text
    if _LEADING_DOTTED_HEADING.match(text):
        return text
    return f"{number} {text}"


class _DocxOutline:
    """按 numbering.xml 还原标题上的十进制大纲号（印在页上，python-docx 的 para.text 不含）。"""

    def __init__(self, path: Path) -> None:
        self._ok = False
        self._counters: dict[str, list[int]] = {}
        self._num_abs: dict[str, str] = {}
        self._lvl: dict[tuple[str, int], tuple[str, str, int]] = {}
        self._style: dict[str, tuple[int | None, str | None]] = {}
        try:
            self._load(path)
            self._ok = True
        except Exception:
            self._ok = False

    def _load(self, path: Path) -> None:
        with ZipFile(path) as z:
            names = set(z.namelist())
            if "word/numbering.xml" not in names or "word/styles.xml" not in names:
                raise FileNotFoundError("no numbering")
            numbering = ET.fromstring(z.read("word/numbering.xml"))
            styles = ET.fromstring(z.read("word/styles.xml"))
        for num in numbering.iter(_w("num")):
            num_id = num.get(_w("numId")) or num.get("numId") or ""
            abs_el = num.find(_w("abstractNumId"))
            abs_id = _xml_val(abs_el)
            if num_id and abs_id:
                self._num_abs[num_id] = abs_id
        for abstract in numbering.iter(_w("abstractNum")):
            abs_id = abstract.get(_w("abstractNumId")) or abstract.get("abstractNumId") or ""
            for lvl in abstract.findall(_w("lvl")):
                ilvl = int(_xml_val(lvl, "ilvl") or lvl.get(_w("ilvl")) or 0)
                fmt = _xml_val(lvl.find(_w("numFmt"))) or "decimal"
                text = _xml_val(lvl.find(_w("lvlText")))
                start_el = lvl.find(_w("start"))
                start = int(_xml_val(start_el) or "1")
                self._lvl[(abs_id, ilvl)] = (fmt, text, start)
        for style in styles.iter(_w("style")):
            style_id = style.get(_w("styleId")) or style.get("styleId") or ""
            if not style_id:
                continue
            self._style[style_id] = self._style_num(styles, style_id)

    def _style_num(self, styles, style_id: str) -> tuple[int | None, str | None]:
        current = style_id
        seen: set[str] = set()
        ilvl: int | None = None
        num_id: str | None = None
        while current and current not in seen:
            seen.add(current)
            node = next(
                (
                    item
                    for item in styles.iter(_w("style"))
                    if (item.get(_w("styleId")) or item.get("styleId")) == current
                ),
                None,
            )
            if node is None:
                break
            p_pr = node.find(_w("pPr"))
            num_pr = p_pr.find(_w("numPr")) if p_pr is not None else None
            if num_pr is not None:
                if ilvl is None:
                    raw = _xml_val(num_pr.find(_w("ilvl")), "val") or _xml_val(
                        num_pr.find(_w("ilvl")), "ilvl"
                    )
                    if raw.isdigit():
                        ilvl = int(raw)
                if num_id is None:
                    raw_id = _xml_val(num_pr.find(_w("numId")))
                    if raw_id:
                        num_id = raw_id
            based = node.find(_w("basedOn"))
            current = _xml_val(based) if based is not None else ""
        return ilvl, num_id

    def _para_num(self, p_elm) -> tuple[int | None, str | None]:
        p_pr = p_elm.find(_w("pPr"))
        style_id = ""
        if p_pr is not None:
            p_style = p_pr.find(_w("pStyle"))
            if p_style is not None:
                style_id = _xml_val(p_style)
            num_pr = p_pr.find(_w("numPr"))
            if num_pr is not None:
                raw_id = _xml_val(num_pr.find(_w("numId")))
                if raw_id == "0":
                    return None, "0"
                ilvl = None
                raw_ilvl = _xml_val(num_pr.find(_w("ilvl")))
                if raw_ilvl.isdigit():
                    ilvl = int(raw_ilvl)
                if raw_id:
                    return ilvl, raw_id
        if style_id:
            return self._style.get(style_id, (None, None))
        return None, None

    def next_heading_number(self, p_elm) -> str:
        if not self._ok:
            return ""
        ilvl, num_id = self._para_num(p_elm)
        if not num_id or num_id == "0":
            return ""
        abs_id = self._num_abs.get(num_id)
        if not abs_id:
            return ""
        level = 0 if ilvl is None else ilvl
        fmt, lvl_text, start = self._lvl.get((abs_id, level), ("", "", 1))
        if fmt != "decimal" or not _OUTLINE_LVL_TEXT.match((lvl_text or "").strip()):
            return ""
        counters = self._counters.setdefault(num_id, [0] * 9)
        if level < 0 or level > 8:
            return ""
        counters[level] = counters[level] + 1 if counters[level] else max(start, 1)
        for deeper in range(level + 1, 9):
            counters[deeper] = 0
        parts: list[str] = []
        token = lvl_text or ""
        for idx in range(9):
            needle = f"%{idx + 1}"
            if needle in token:
                value = counters[idx]
                if value <= 0:
                    return ""
                parts.append(str(value))
        if not parts:
            return ""
        return ".".join(parts)


def _pages_from_printed_docx(path: Path, events: list[tuple]) -> list[int] | None:
    """印页只认打开后的 PAGE：先问本机 Word/WPS，没有再读同目录现成 PDF。目录缓存不当印页。"""
    if not events:
        return None
    from_word = _pages_from_word_app(path, events)
    if from_word:
        return from_word
    pdf_path = _sidecar_pdf(path)
    if pdf_path is None:
        return None
    return _pages_from_pdf_file(pdf_path, events)


def _docx_markdown_in_order(path: Path) -> str:
    """按正文顺序输出。页码只写页眉或页脚上印出来的 PAGE。"""
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    outline = _DocxOutline(path)
    parts: list[str] = []
    last_emitted_page = 0

    def emit_page(page: int) -> None:
        nonlocal last_emitted_page
        if page < 1:
            return
        if page != last_emitted_page:
            parts.append(f"## 第 {page} 页")
            last_emitted_page = page

    events: list[tuple] = []

    def add_paragraph_event(p_elm) -> None:
        para = Paragraph(p_elm, doc)
        text = para.text.strip()
        style = para.style.name if para.style else "Normal"
        if style.lower().startswith("toc"):
            return
        if text:
            level = _heading_level(style)
            if level:
                text = _prefix_printed_number(text, outline.next_heading_number(p_elm))
            events.append(("heading" if level else "para", text, level, None))
        for inner in _iter_txbx_blocks(p_elm):
            if isinstance(inner, CT_P):
                boxed = _paragraph_text(inner, doc)
                if boxed:
                    events.append(("para", boxed, 0, None))
            elif isinstance(inner, CT_Tbl):
                chunks = _convert_tbl(inner, doc)
                if chunks:
                    events.append(("table", chunks, 0, None))

    for child in doc.element.body.iterchildren():
        if isinstance(child, CT_P):
            add_paragraph_event(child)
        elif isinstance(child, CT_Tbl):
            table = Table(child, doc)
            chunks = _convert_tbl(child, doc)
            if chunks:
                events.append(("table", chunks, len(table.rows), None))

    pages = _pages_from_printed_docx(path, events) or [0] * len(events)
    for index, event in enumerate(events):
        emit_page(pages[index] if index < len(pages) else 0)
        kind = event[0]
        if kind in {"heading", "para"}:
            text = event[1]
            level = event[2]
            if level:
                parts.append(f"{'#' * min(level, 6)} {text}")
            else:
                parts.append(text)
        else:
            for chunk in event[1]:
                if chunk.strip():
                    parts.append(chunk)

    return "\n\n".join(parts)


BBox = tuple[float, float, float, float]
_TABLE_COVER_FRAC = 0.35
_TABLE_DEDUP_IOU = 0.55


@dataclass
class _PdfLoad:
    markdown: str
    page_count: int
    native_chars: int
    table_pages: set[int]
    page_labels: list[int] | None = None


def _bbox_overlap_frac(inner: BBox, outer: BBox) -> float:
    ax0, ay0, ax1, ay1 = inner
    bx0, by0, bx1, by1 = outer
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    area = max((ax1 - ax0) * (ay1 - ay0), 1e-6)
    return ((ix1 - ix0) * (iy1 - iy0)) / area


def _bbox_iou(a: BBox, b: BBox) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union if union > 0 else 0.0


def _line_covered(bbox: BBox, tables: list[BBox]) -> bool:
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for table in tables:
        if _bbox_overlap_frac(bbox, table) >= _TABLE_COVER_FRAC:
            return True
        tx0, ty0, tx1, ty1 = table
        if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
            return True
    return False


def _clean_cell(cell: object) -> str:
    if cell is None:
        return ""
    return str(cell).replace("\n", " ").strip()


def _normalize_table(data: list[list[object]]) -> list[list[str]]:
    rows = [[_clean_cell(cell) for cell in (row or [])] for row in data]
    width = max((len(row) for row in rows), default=0)
    if width < 2:
        return []
    return [row + [""] * (width - len(row)) for row in rows]


def _useful_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    nonempty = sum(1 for row in rows for cell in row if cell)
    return nonempty >= 3


def _dedupe_tables(
    items: list[tuple[BBox, list[list[str]]]],
) -> list[tuple[BBox, list[list[str]]]]:
    ranked = sorted(
        items,
        key=lambda item: (
            -sum(1 for row in item[1] for cell in row if cell),
            item[0][1],
            item[0][0],
        ),
    )
    kept: list[tuple[BBox, list[list[str]]]] = []
    for bbox, rows in ranked:
        if any(_bbox_iou(bbox, other[0]) >= _TABLE_DEDUP_IOU for other in kept):
            continue
        kept.append((bbox, rows))
    kept.sort(key=lambda item: (item[0][1], item[0][0]))
    return kept


def _page_text_lines(page) -> list[tuple[BBox, str]]:
    payload = page.get_text("dict") or {}
    out: list[tuple[BBox, str]] = []
    for block in payload.get("blocks") or []:
        if int(block.get("type") or 0) != 0:
            continue
        for line in block.get("lines") or []:
            text = "".join(str(span.get("text") or "") for span in line.get("spans") or [])
            text = text.strip()
            if not text:
                continue
            bbox = line.get("bbox")
            if not bbox or len(bbox) < 4:
                continue
            out.append(((float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])), text))
    return out


def _page_tables(page) -> list[tuple[BBox, list[list[str]]]]:
    try:
        found = page.find_tables()
    except Exception:
        return []
    raw_tables = getattr(found, "tables", None)
    if raw_tables is None:
        raw_tables = list(found) if found else []
    items: list[tuple[BBox, list[list[str]]]] = []
    for table in raw_tables:
        try:
            raw = table.extract() or []
            bbox = tuple(float(v) for v in table.bbox)
        except Exception:
            continue
        if len(bbox) < 4:
            continue
        rows = _normalize_table(raw)
        if not _useful_table(rows):
            continue
        items.append(((bbox[0], bbox[1], bbox[2], bbox[3]), rows))
    return _dedupe_tables(items)


def _page_markdown(page) -> tuple[str, bool]:
    from modules.document_reader.utils import table_to_markdown

    tables = _page_tables(page)
    table_boxes = [bbox for bbox, _ in tables]
    events: list[tuple[float, float, str, str]] = []
    for bbox, rows in tables:
        events.append(
            (
                bbox[1],
                bbox[0],
                "table",
                table_to_markdown(rows, max_col_width=_TABLE_CELL_WIDTH),
            )
        )
    for bbox, text in _page_text_lines(page):
        if table_boxes and _line_covered(bbox, table_boxes):
            continue
        events.append((bbox[1], bbox[0], "text", text))
    events.sort()
    chunks: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            chunks.append("\n".join(buf).strip())
            buf.clear()

    for _y, _x, kind, payload in events:
        if kind == "table":
            flush()
            if payload.strip():
                chunks.append(payload.strip())
        else:
            buf.append(payload)
    flush()
    return "\n\n".join(chunk for chunk in chunks if chunk), bool(tables)


def _plausible_printed_page(current: int, total: int, page_count: int) -> bool:
    if current < 1 or total < 2 or current > total:
        return False
    if page_count >= 8 and total < max(8, page_count * 6 // 10):
        return False
    return True


def _printed_page_from_chrome(text: str, physical: int, page_count: int) -> int | None:
    """从页眉或页脚文字里取印出来的页码。"""
    blob = text or ""
    found: list[int] = []
    for match in _PAGE_NO_CAPTION.finditer(blob):
        current, total = int(match.group(1)), int(match.group(2))
        if _plausible_printed_page(current, total, page_count):
            found.append(current)
    for match in _HEADER_PAGE_PAIR.finditer(blob):
        current, total = int(match.group(1)), int(match.group(2))
        if _plausible_printed_page(current, total, page_count):
            found.append(current)
    for match in _PAGE_SLASH_PAIR.finditer(blob):
        current, total = int(match.group(1)), int(match.group(2))
        if _plausible_printed_page(current, total, page_count):
            found.append(current)
    for match in _CHROME_SLASH_PAIR.finditer(blob):
        current, total = int(match.group(1)), int(match.group(2))
        if _plausible_printed_page(current, total, page_count):
            found.append(current)
    if not found:
        for match in _CHROME_CN_PAGE.finditer(blob):
            current = int(match.group(1))
            if 1 <= current <= max(page_count * 2, current):
                if page_count <= 5 or abs(current - physical) <= max(6, page_count // 8):
                    found.append(current)
    if not found:
        return None
    return min(found, key=lambda page: abs(page - physical))


def _page_edge_lines(text: str, *, head: int = 16, tail: int = 12) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= head + tail:
        return "\n".join(lines)
    return "\n".join(lines[:head] + lines[-tail:])


def _pdf_span_chrome_text(page) -> str:
    rect = page.rect
    height = float(rect.height or 0)
    if height <= 0:
        return ""
    try:
        payload = page.get_text("dict") or {}
    except Exception:
        return ""
    parts: list[str] = []
    for block in payload.get("blocks") or []:
        bbox = block.get("bbox") or (0, 0, 0, 0)
        if len(bbox) < 4:
            continue
        y0, y1 = float(bbox[1]), float(bbox[3])
        if y1 > height * 0.30 and y0 < height * 0.72:
            continue
        for line in block.get("lines") or []:
            text = "".join(str(span.get("text") or "") for span in line.get("spans") or [])
            text = text.strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _pdf_chrome_text(page) -> str:
    import fitz

    rect = page.rect
    height = rect.height
    width = rect.width
    bands = (
        (0, 0, width, height * 0.30),
        (0, height * 0.72, width, height),
        (width * 0.50, 0, width, height * 0.32),
        (width * 0.50, height * 0.70, width, height),
    )
    parts: list[str] = []
    seen: set[str] = set()

    def take(blob: str) -> None:
        blob = (blob or "").strip()
        if blob and blob not in seen:
            seen.add(blob)
            parts.append(blob)

    for x0, y0, x1, y1 in bands:
        try:
            take(page.get_text("text", clip=fitz.Rect(x0, y0, x1, y1)) or "")
        except Exception:
            continue
    take(_pdf_span_chrome_text(page))
    take(_page_edge_lines(page.get_text("text") or ""))
    return "\n".join(parts)


def _pdf_page_labels(doc, *, require_chrome: bool = False) -> list[int]:
    """物理页 → 印在页上的页码；页眉右上、页脚右下都能认。"""
    count = int(doc.page_count or 0)
    if count <= 0:
        return []
    raw = [0] * count
    hits = 0
    for index, page in enumerate(doc):
        printed = _printed_page_from_chrome(
            _pdf_chrome_text(page),
            index + 1,
            count,
        )
        if printed:
            raw[index] = printed
            hits += 1
    min_hits = 1 if count <= 5 else max(3, count * 3 // 10)
    if hits < min_hits:
        return [] if require_chrome else list(range(1, count + 1))
    offsets = [printed - (index + 1) for index, printed in enumerate(raw) if printed]
    if not offsets:
        return [] if require_chrome else list(range(1, count + 1))
    offsets.sort()
    median = offsets[len(offsets) // 2]
    if all(abs(offset - median) <= 1 for offset in offsets):
        return [max(1, physical + median) for physical in range(1, count + 1)]
    labels = list(range(1, count + 1))
    last = 0
    for index, printed in enumerate(raw):
        if printed:
            labels[index] = printed
            last = printed
        elif last:
            labels[index] = last
    return labels


def _remap_ocr_pages(ocr_by_page: dict[int, str], labels: list[int] | None) -> dict[int, str]:
    if not ocr_by_page or not labels:
        return ocr_by_page
    out: dict[int, str] = {}
    for physical, text in ocr_by_page.items():
        printed = labels[physical - 1] if 1 <= physical <= len(labels) else physical
        out[printed] = text
    return out


def _load_pdf(path: Path) -> _PdfLoad:
    import fitz

    doc = fitz.open(str(path))
    try:
        page_count = int(doc.page_count or 0)
        labels = _pdf_page_labels(doc)
        native: list[str] = []
        for page in doc:
            native.append(page.get_text() or "")
        native_chars = sum(len(text.strip()) for text in native)
        sparse = page_count > 0 and (native_chars / max(page_count, 1)) < 80
        # 长扫描件 skip find_tables；短页即使字少也可能是矢量表，仍要按页抽表。
        skip_tables = sparse and page_count >= 10
        parts: list[str] = [f"# {path.stem}", ""]
        table_pages: set[int] = set()
        if skip_tables:
            for index, text in enumerate(native, 1):
                label = labels[index - 1] if index <= len(labels) else index
                parts.append(f"## 第 {label} 页")
                parts.append((text or "").strip())
                parts.append("")
        else:
            if page_count >= 20:
                report("正在按页整理 PDF 表格…", percent=6, stage="read")
            for index, page in enumerate(doc, 1):
                body, has_table = _page_markdown(page)
                if has_table:
                    table_pages.add(index)
                label = labels[index - 1] if index <= len(labels) else index
                parts.append(f"## 第 {label} 页")
                parts.append(body or (native[index - 1] or "").strip())
                parts.append("")
        return _PdfLoad(
            markdown="\n".join(parts).strip(),
            page_count=page_count,
            native_chars=native_chars,
            table_pages=table_pages,
            page_labels=labels,
        )
    finally:
        doc.close()


def _split_md_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.replace("\\|", "|").strip() for cell in re.split(r"(?<!\\)\|", raw)]


def _is_md_table_row(line: str) -> bool:
    return bool(_MD_TABLE_ROW.match(line or "")) and (line or "").count("|") >= 2


def _is_md_table_sep(line: str) -> bool:
    if not _is_md_table_row(line):
        return False
    cells = _split_md_row(line)
    return bool(cells) and all(_MD_TABLE_SEP_CELL.match(cell or "") for cell in cells)


def _flatten_table_block(block: list[str]) -> list[str]:
    """把 Markdown 表再写成「条目  值」行，方便规则和模型对齐单元格。"""
    rows = [_split_md_row(line) for line in block if _is_md_table_row(line)]
    if len(rows) < 2:
        return []
    start = 1
    if rows[1] and all(_MD_TABLE_SEP_CELL.match(cell or "") for cell in rows[1]):
        start = 2
    out: list[str] = []
    for row in rows[start:]:
        cells = [cell for cell in row if cell]
        if cells:
            out.append("  ".join(cells))
    return out


def _expand_markdown_tables(markdown: str) -> str:
    if not markdown or "|" not in markdown:
        return markdown
    lines = markdown.splitlines()
    out: list[str] = []
    index = 0
    while index < len(lines):
        if (
            _is_md_table_row(lines[index])
            and index + 1 < len(lines)
            and _is_md_table_sep(lines[index + 1])
        ):
            block = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and _is_md_table_row(lines[index]):
                block.append(lines[index])
                index += 1
            out.extend(block)
            flat = _flatten_table_block(block)
            if flat:
                out.append("")
                out.extend(flat)
            continue
        out.append(lines[index])
        index += 1
    return "\n".join(out)


def _prepare_markdown(markdown: str) -> str:
    markdown = drop_toc_pages(markdown)
    markdown = _expand_markdown_tables(markdown)
    if len(markdown) > MAX_CHARS:
        markdown = (
            markdown[:MAX_CHARS]
            + "\n\n[文档过长，已截断。优先使用前半部分已出现的参数表。]\n"
        )
    return markdown


def _append_ocr_blocks(markdown: str, texts: list[str]) -> tuple[str, int]:
    parts = [markdown.rstrip()] if markdown.strip() else []
    added = 0
    for text in texts:
        blob = (text or "").strip()
        if not blob:
            continue
        added += 1
        parts.append(f"## OCR图 {added}\n\n[本页为本机 OCR]\n{blob}")
    return "\n\n".join(parts), added


def _ocr_docx_images(path: Path, deadline: float | None = None) -> list[str]:
    """Word 里贴的参数表图：够大才认，认出来不像参数页则丢弃。"""
    if not ocr_available():
        return []
    from docx import Document
    from docx.oxml.ns import qn

    try:
        doc = Document(str(path))
    except Exception:
        return []
    blobs: list[bytes] = []
    seen: set[str] = set()
    for blip in doc.element.body.findall(".//" + qn("a:blip")):
        rid = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
        if not rid:
            continue
        try:
            part = doc.part.related_parts.get(rid)
        except Exception:
            part = None
        if part is None:
            continue
        try:
            data = part.blob
        except Exception:
            continue
        if not data or len(data) < _MIN_DOCX_IMAGE_BYTES:
            continue
        digest = hashlib.sha1(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        blobs.append(data)
        if len(blobs) >= MAX_OCR_PAGES:
            break
    if not blobs:
        return []
    out: list[str] = []
    with tempfile.TemporaryDirectory(prefix="electrical-docx-ocr-") as tmp:
        tmp_path = Path(tmp)
        n = len(blobs)
        for i, data in enumerate(blobs, 1):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            report(
                f"本机识别 Word 插图：{i}/{n}",
                percent=8 + int(20 * i / max(n, 1)),
                stage="ocr",
            )
            ext = ".png"
            if data[:3] == b"\xff\xd8\xff":
                ext = ".jpg"
            image_path = tmp_path / f"img-{i}{ext}"
            image_path.write_bytes(data)
            text = ocr_image(image_path)
            if _keep_ocr_page(text):
                out.append(text.strip())
    return out


@dataclass
class LoadedDocument:
    path: Path
    markdown: str
    page_count: int
    likely_scan: bool
    parser: str
    ocr_pages: int = 0
    kind: DocKind | None = None


def load_document(path: Path, deadline: float | None = None) -> LoadedDocument:
    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(
            f"暂不支持 {ext}。第一版请用 PDF / Word(.docx) / Excel(.xlsx)"
        )

    report("正在读取规格书…", percent=4, stage="read")
    if ext == ".docx":
        markdown = _docx_markdown_in_order(path)
        native_chars = len(re.sub(r"\s+", "", markdown))
        ocr_pages = 0
        extra: list[str] = []
        if native_chars < _MIN_NATIVE_DOCX_CHARS:
            extra = _ocr_docx_images(path, deadline=deadline)
        if extra:
            markdown, ocr_pages = _append_ocr_blocks(markdown, extra)
        page_count = len(set(re.findall(r"## 第 (\d+) 页", markdown))) or len(
            re.findall(r"## 第 \d+ [页节]", markdown)
        )
        markdown = _prepare_markdown(markdown)
        return LoadedDocument(
            path=path,
            markdown=markdown,
            page_count=page_count,
            likely_scan=native_chars < 12 and ocr_pages > 0,
            parser="DocxReader",
            ocr_pages=ocr_pages,
            kind=classify_document(path, markdown),
        )

    if ext == ".pdf":
        try:
            pdf = _load_pdf(path)
        except ImportError:
            pdf = None
        if pdf is not None:
            return _finish_pdf(
                path,
                pdf,
                deadline=deadline,
            )

    reader = get_reader(path)
    if reader is None:
        raise ValueError(f"没有读取器: {path.name}")

    markdown = reader.to_markdown() or ""
    meta = reader.get_metadata()
    page_count = int(meta.page_count or 0)
    markdown = _prepare_markdown(markdown)

    return LoadedDocument(
        path=path,
        markdown=markdown,
        page_count=page_count,
        likely_scan=False,
        parser=type(reader).__name__,
        ocr_pages=0,
        kind=classify_document(path, markdown),
    )


def _finish_pdf(
    path: Path,
    pdf: _PdfLoad,
    *,
    deadline: float | None,
) -> LoadedDocument:
    markdown = pdf.markdown
    page_count = pdf.page_count
    likely_scan = (
        page_count > 0
        and (pdf.native_chars / max(page_count, 1)) < 80
        and not pdf.table_pages
    )
    ocr_pages = 0
    if page_count > 0:
        if likely_scan:
            pages = scan_image_pages(path, page_count)
            label = "扫描件"
        else:
            pages = [
                page
                for page in sparse_pdf_pages(path, page_count)
                if page not in pdf.table_pages
            ]
            label = "表格图"
        if pages and ocr_available():
            ocr_by_page = ocr_pdf_pages(
                path, pages, deadline=deadline, label=label
            )
            if ocr_by_page:
                markdown = merge_ocr_into_markdown(
                    markdown,
                    _remap_ocr_pages(ocr_by_page, pdf.page_labels),
                )
                ocr_pages = len(ocr_by_page)
        elif pages and not ocr_available():
            markdown += (
                "\n\n[提示：本机未接 OCR。Mac 使用系统 Vision（已内置脚本）；"
                "Windows 请安装 tesseract 并保证命令在 PATH 中。]\n"
            )

    if likely_scan and len(markdown.strip()) < 80:
        raise ValueError(
            "这是扫描件，本机没有可用的识别结果，无法抽表。"
            "请确认本机 Vision / Tesseract 可用，或换可检索的 PDF / Word。"
        )

    markdown = _prepare_markdown(markdown)
    return LoadedDocument(
        path=path,
        markdown=markdown,
        page_count=page_count,
        likely_scan=likely_scan,
        parser="PdfReader",
        ocr_pages=ocr_pages,
        kind=classify_document(path, markdown),
    )
