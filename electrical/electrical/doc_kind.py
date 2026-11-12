"""判断规格书类型：先分流，再决定是否按 120 项电控清单抽取。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

TOC_RE = re.compile(
    r"目\s*录|目\s*次|\bcontents\b|table of contents|"
    r"引用标准|规范性引用|normative references?|"
    r"修订记录|修订履历|revision history|change history|"
    r"标准清单|适用标准|引用文件",
    re.I,
)
PARAM_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:V(?:dc|ac)?|A(?:rms)?|kW|kVA|rpm|N[·.]?m|℃|°C|LPM|lpm|mbar|MΩ|Mohm)|"
    r"直流工作电压|母线电压|相电流|峰值功率|额定扭矩|主动放电|绝缘电阻|"
    r"inverter|dc-?link|hvdc|boost|buck|asil",
    re.I,
)
ESOW_RE = re.compile(
    r"(?<![A-Za-z0-9])ESOW(?![A-Za-z0-9])|"
    r"Engineering Statement of Work|工作说明书|scope of work",
    re.I,
)
TRANS_RE = re.compile(
    r"\btransmission\b|\bgearbox\b|变速器|变速箱|速比|gear ratio",
    re.I,
)
INVERTER_RE = re.compile(
    r"\binverter\b|逆变|dc-?link|igbt|主动放电|active discharge",
    re.I,
)
DPR_RE = re.compile(
    r"\bDPR\b|Design Prerequisites|DHTS|SuperEvo|XCM控制器|电控设计需求",
    re.I,
)


@dataclass(frozen=True)
class DocKind:
    code: str
    label: str
    extract: bool
    family: str
    note: str


def page_text_kind(text: str) -> str:
    """toc / param / other。用于 OCR 选页。"""
    blob = text or ""
    if len(blob.strip()) < 24:
        return "other"
    toc = len(TOC_RE.findall(blob))
    param = len(PARAM_RE.findall(blob))
    chapter_dots = len(re.findall(r"[…]{2,}|\.{4,}|…+\s*\d+\s*$", blob, re.M))
    ocr = "[本机 OCR]" in blob or "[本页为本机 OCR]" in blob
    if ocr:
        looks_toc = bool(re.search(r"(?i)\bcontents\b|目\s*录", blob))
        if looks_toc and param < 3 and (chapter_dots >= 4 or toc >= 2):
            return "toc"
        if param >= 3:
            return "param"
        return "other"
    if toc >= 2 and param < 4:
        return "toc"
    if chapter_dots >= 8 and param < 4:
        return "toc"
    if param >= 3:
        return "param"
    if toc and param == 0:
        return "toc"
    return "other"


def _has_rich_electrical(text: str) -> bool:
    return len(PARAM_RE.findall(text or "")) >= 8


def classify_document(path: Path, markdown: str) -> DocKind:
    name = path.name
    head = (markdown or "")[:16000]
    blob = f"{name}\n{head}"

    if ESOW_RE.search(name) or (
        ESOW_RE.search(blob) and not _has_rich_electrical(head)
    ):
        return DocKind(
            "esow",
            "工作说明书 / ESOW",
            False,
            "none",
            "该文件是工作说明书，不是电控规格。不按 120 项电控清单抽取。请换 DPR / 电控规格书。",
        )

    item_trans = bool(re.search(r"Item\s+.{0,80}Transmission", blob, re.I | re.S))
    item_inv = bool(re.search(r"Item\s+.{0,80}Inverter", blob, re.I | re.S))
    trans = bool(TRANS_RE.search(blob)) or item_trans
    inverter = bool(INVERTER_RE.search(blob)) or item_inv

    if (item_trans and not item_inv) or (
        trans and not inverter and not _has_rich_electrical(head)
    ):
        return DocKind(
            "transmission_sr",
            "变速器 / 传动 SR",
            False,
            "none",
            "该文件是变速器/传动规格，不是电控规格。不按 120 项电控清单抽取。",
        )

    toc_hits = len(TOC_RE.findall(head))
    param_hits = len(PARAM_RE.findall(head))
    if toc_hits >= 3 and param_hits < 5:
        return DocKind(
            "scan_toc",
            "目录 / 标准清单页",
            False,
            "none",
            "识别到的主要是目录或标准清单，不是电控参数页。请提供参数页清晰扫描件（不要只扫目录）。",
        )

    if DPR_RE.search(blob) or (
        re.search(r"冷启动|PCM母线|P1逆变器|P3逆变器", head)
        and _has_rich_electrical(head)
    ):
        return DocKind(
            "xcm_dpr",
            "电控 DPR",
            True,
            "dpr",
            "按电控 DPR 抽取。空行表示原文未给出或未对上清单，待用标准答案复核。",
        )

    if (
        item_inv
        or re.search(r"HMC Spec|Hyundai\s*/\s*Kia", blob, re.I)
        or (inverter and re.search(r"12\s*LPM", blob, re.I))
    ):
        return DocKind(
            "inverter_sr",
            "逆变器 SR",
            True,
            "inverter",
            "按逆变器规格抽取。空行表示原文未给出或未对上清单，待用标准答案复核。",
        )

    if _has_rich_electrical(head):
        return DocKind(
            "electrical",
            "电控规格",
            True,
            "generic",
            "按电控清单抽取。换一份新 DPR 仍可能漏项或错绑，空行待标准答案。",
        )

    return DocKind(
        "not_electrical",
        "非电控规格",
        False,
        "none",
        "未识别为电控规格书（DPR / 逆变器 SR）。不按 120 项电控清单硬抽。",
    )


def drop_toc_pages(markdown: str) -> str:
    """去掉目录/标准清单页，避免把目录字塞进抽取。"""
    if not markdown or not re.search(r"## 第 \d+ [页节]", markdown):
        return markdown
    parts = re.split(r"(?=## 第 \d+ [页节])", markdown)
    kept = [p for p in parts if p.strip() and page_text_kind(p) != "toc"]
    body = "".join(kept).strip()
    if not body:
        return markdown
    if len(PARAM_RE.findall(body)) >= 3:
        return body
    if len(body) < 200 and len(markdown) > 2000:
        return markdown
    return body


def coverage_note(kind: DocKind, likely_scan: bool) -> str:
    """覆盖预期：不要暗示再堆规则就能到满分。"""
    if not kind.extract:
        return kind.note
    scan = (
        "扫描件优先走识别服务 OCR（/v1/ocr），没有该接口时回退本机 RapidOCR。"
        "扫描件覆盖率和耗时不按数字稿约五分钟承诺。"
        if likely_scan
        else ""
    )
    return (
        (scan + " " if scan else "")
        + "数字稿常见只能抽到约三分之二。空行多为原文未给出、表格跨页或条目未对上。"
        "请用标准答案逐格标：格子 / 页码 / 正确值。"
        "换一份新规格仍可能漏项或错绑。"
        "识别模型以工位所选为准；出表不强制约五分钟。"
    )
