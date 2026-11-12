"""出表前文件质检：先看当份能不能读，再对照知识库主题（不填格）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from electrical.doc_content_qa import ContentFinding, content_summary, review_document_content
from electrical.doc_kind import PARAM_RE, TOC_RE, page_text_kind
from electrical.read_doc import LoadedDocument
from electrical.schema import aliases_for_seq, item_group, load_template_fields

_USABLE_STRIP = re.compile(r"(?m)^#{1,6}\s*|\[本机 OCR\]|\[本页为本机 OCR\]")
_PAGE_SPLIT = re.compile(r"(?=## 第 \d+ [页节])")
_VALUEISH = re.compile(
    r"^\d[\d.\s]*$|8000\s*小时|15\s*年|13\.5\s*V|5\.3\.10|J7110218"
)

# 清单主题探针：只认主题词，不用典型值。
_THEME_NEEDLES: dict[str, tuple[str, ...]] = {
    "设计范围": (
        "Design Prerequisites",
        "XCM shall",
        "电控设计",
        "DHTS",
        "SuperEvo",
    ),
    "直流高压": (
        "HVDC",
        "Vdc",
        "直流工作电压",
        "母线电压",
        "HV input voltage",
    ),
    "高压安全": (
        "绝缘电阻",
        "耐电压",
        "主动放电",
        "insulation resistance",
        "active discharge",
        "HVIL",
    ),
    "低压": ("低压电源", "12V supply", "KL30", "LV voltage", "低压供电"),
    "P1": ("P1 inverter", "P1电机", "P1 peak", "P1 峰值", "P1逆变器"),
    "P3": ("P3 inverter", "P3电机", "P3 peak", "P3 峰值", "P3逆变器"),
    "升压": ("boost the HV", "驱动升压", "Buck/Boost", "行车升压", "Charging Boost"),
    "冷却": ("coolant", "冷却液", "LPM", "pressure drop", "压降"),
    "环境与材料": (
        "operating temperature",
        "工作温度",
        "IP67",
        "vibration",
        "振动",
    ),
    "采样与控制": (
        "current sensing",
        "相电流",
        "CAN FD",
        "扭矩精度",
        "采样精度",
    ),
    "整机": ("weight of the XCM", "总成重量", "外形尺寸"),
    "安全与功能": ("ASIL", "ISO 26262", "功能安全"),
}

VERDICT_LABEL = {"pass": "通过", "warn": "需注意", "fail": "不可读"}


@dataclass
class DocQaReport:
    verdict: str
    skip_extract: bool
    summary: str
    file_note: str
    kb_note: str
    progress_message: str
    groups_seen: tuple[str, ...] = ()
    groups_missing: tuple[str, ...] = ()
    findings: list[str] = field(default_factory=list)
    content_findings: list[ContentFinding] = field(default_factory=list)


def inspect_document(doc: LoadedDocument) -> DocQaReport:
    """读完规格书、抽取之前。交叉检查不得写入抽出值。"""
    markdown = doc.markdown or ""
    usable = _usable_chars(markdown)
    findings: list[str] = []
    verdict = "pass"
    skip = False

    if usable < 40:
        findings.append("正文几乎抽不出字，文件可能是空页、加密或纯图。")
        verdict = "fail"
        skip = True
    elif doc.likely_scan and usable < 80:
        findings.append("扫描件识别后仍几乎没有可检索正文。")
        verdict = "fail"
        skip = True

    garbage_n, sampled, samples = _ocr_garbage_stats(markdown)
    if sampled and garbage_n:
        ratio = garbage_n / sampled
        shown = "、".join(samples[:3]) if samples else "花字"
        if ratio >= 0.7 and sampled >= 4 and usable < 400:
            findings.append(
                f"多数页被扫描识别花成「{shown}」这类字，正文不可靠。"
            )
            verdict = "fail"
            skip = True
        elif ratio >= 0.3:
            findings.append(
                f"部分页扫描识别花成「{shown}」这类字，抽取后仍须对照原页。"
            )
            if verdict == "pass":
                verdict = "warn"

    if doc.likely_scan and verdict != "fail":
        findings.append("按扫描件处理，数字稿可能不全。")
        verdict = "warn"

    toc_hits = len(TOC_RE.findall(markdown[:20000]))
    param_hits = len(PARAM_RE.findall(markdown[:20000]))
    if toc_hits >= 3 and param_hits < 5 and verdict != "fail":
        findings.append("识别到的主要是目录或标准清单，电控参数句很少。")
        verdict = "warn"

    page_kinds = _page_kind_counts(markdown)
    if page_kinds.get("toc", 0) >= 3 and page_kinds.get("param", 0) <= 1:
        if verdict != "fail" and "目录" not in "".join(findings):
            findings.append("多数页像目录，不像参数页。")
            verdict = "warn"

    if not findings and verdict == "pass":
        findings.append(
            f"可读正文约 {usable} 字"
            + (f"，{doc.page_count} 页。" if doc.page_count else "。")
        )

    kb_note = ""
    seen: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    want_extract = bool(doc.kind.extract) if doc.kind is not None else True
    if not skip:
        seen, missing, kb_extra = _kb_cross_check(markdown, want_extract=want_extract)
        if kb_extra:
            findings.extend(kb_extra)
        if want_extract and len(seen) < 3 and verdict != "fail":
            verdict = "warn"
        kb_note = _kb_note(seen, want_extract=want_extract)
    else:
        kb_note = "正文不足，未做知识库交叉。交叉检查不填抽出值。"

    content_findings: list[ContentFinding] = []
    if not skip:
        content_findings = review_document_content(markdown)
        if content_findings:
            findings.insert(0, content_summary(content_findings))
            if verdict != "fail":
                verdict = "warn"

    file_note = " ".join(findings)
    label = VERDICT_LABEL.get(verdict, verdict)
    if skip:
        summary = f"{label}。{file_note} 已跳过抽取，核对表为空表。"
        progress = "文件质检：不可读，跳过抽取。"
    else:
        summary = f"{label}。{file_note}"
        progress = f"文件质检：{label}。"

    return DocQaReport(
        verdict=verdict,
        skip_extract=skip,
        summary=_clip(summary, 480),
        file_note=_clip(file_note, 280),
        kb_note=_clip(kb_note, 240),
        progress_message=progress,
        groups_seen=seen,
        groups_missing=missing,
        findings=findings,
        content_findings=content_findings,
    )


def _clip(text: str, n: int) -> str:
    raw = (text or "").strip()
    if len(raw) <= n:
        return raw
    return raw[: n - 1] + "…"


def _usable_chars(markdown: str) -> int:
    raw = _USABLE_STRIP.sub("", markdown or "")
    return len(re.sub(r"\s+", "", raw))


def _ocr_garbage_stats(markdown: str) -> tuple[int, int, list[str]]:
    from electrical.extract import _looks_like_ocr_garbage, _ocr_garbage_samples

    blocks = [p for p in _PAGE_SPLIT.split(markdown or "") if p.strip()]
    if not blocks:
        blocks = [markdown or ""]
    if len(blocks) > 16:
        step = max(1, len(blocks) // 16)
        blocks = blocks[::step][:16]
    bad = 0
    samples: list[str] = []
    for block in blocks:
        if not _looks_like_ocr_garbage(block):
            continue
        bad += 1
        for token in _ocr_garbage_samples(block):
            if token not in samples:
                samples.append(token)
            if len(samples) >= 3:
                break
    return bad, len(blocks), samples


def _page_kind_counts(markdown: str) -> dict[str, int]:
    counts = {"toc": 0, "param": 0, "other": 0}
    blocks = [p for p in _PAGE_SPLIT.split(markdown or "") if p.strip()]
    if not blocks:
        counts[page_text_kind(markdown or "")] += 1
        return counts
    for block in blocks[:40]:
        kind = page_text_kind(block)
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _contains(hay: str, needle: str) -> bool:
    n = (needle or "").strip()
    if len(n) < 3 or _VALUEISH.search(n):
        return False
    if re.fullmatch(r"[A-Za-z0-9]{3,8}", n):
        return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(n)}(?![A-Za-z0-9])", hay, re.I))
    if n.isascii():
        return n.lower() in hay.lower()
    return n in hay


@lru_cache(maxsize=1)
def _group_needles() -> dict[str, tuple[str, ...]]:
    out: dict[str, list[str]] = {name: list(needles) for name, needles in _THEME_NEEDLES.items()}
    try:
        specs = load_template_fields()
    except Exception:
        return {name: tuple(needles) for name, needles in out.items()}
    for spec in specs:
        group = item_group(spec.name, spec.seq)
        bucket = out.setdefault(group, [])
        for alias in aliases_for_seq(spec.seq, spec.name):
            text = str(alias or "").strip()
            if len(text) < 4 or _VALUEISH.search(text):
                continue
            if text not in bucket:
                bucket.append(text)
            if len(bucket) >= 14:
                break
    return {name: tuple(needles) for name, needles in out.items()}


def _kb_cross_check(
    markdown: str, *, want_extract: bool
) -> tuple[tuple[str, ...], tuple[str, ...], list[str]]:
    extra: list[str] = []
    if not want_extract:
        return (), (), extra
    hay = markdown or ""
    seen: list[str] = []
    missing: list[str] = []
    for group, needles in _group_needles().items():
        if group in {"其他", "额外抽出"}:
            continue
        hit = any(_contains(hay, n) for n in needles)
        if hit:
            seen.append(group)
        else:
            missing.append(group)
    if len(seen) < 3:
        extra.append(
            "对照清单主题，当份正文覆盖偏少（只标覆盖，不把库典型值写入抽出值）。"
        )
    return tuple(seen), tuple(missing), extra


def _kb_note(seen: tuple[str, ...], *, want_extract: bool) -> str:
    if not want_extract:
        return "分流后不按 120 项抽取，知识库交叉只作参考，不填格。"
    if not seen:
        return "未对照到清单主题词。交叉检查不填抽出值。"
    return "交叉检查不填抽出值。"
