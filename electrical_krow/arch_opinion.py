"""电驱需求清单的初步意见。只引用当份原文和已登记来源的名称，不把库里的限值写进格子。"""
from __future__ import annotations

import re

_STD = re.compile(
    r"(?:GB\s*/?\s*T|ISO|IEC|QC\s*/?\s*T|VW|AQG)\s*[-–]?\s*\d{3,}(?:[.\-]\d+)*"
    r"|Q\s*[-–/]?\s*JL[YY]?\s*J?\s*\d{5,}",
    re.I,
)
_FOLD = re.compile(r"[\s/_．.－–—]")


def _fold(text: str) -> str:
    return _FOLD.sub("", text or "").upper()


def _clip(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _cards(library: dict) -> dict[str, dict]:
    return {str(card.get("id") or ""): card for card in (library.get("clauses") or []) if card.get("id")}


def _emit(cards: dict[str, dict], card_id: str, extra: str = "") -> tuple[str, str]:
    card = cards.get(card_id) or cards.get("arch-no-source") or {}
    opinion = str(card.get("opinion") or "知识库尚无对应口径，需专家给出处理意见。")
    reason = str(card.get("reason") or "已按来源登记核对，没有对上的标准号、图号、接口文件或同文件冲突。")
    if extra:
        reason = f"{reason}{extra}"
    return opinion, reason


def _qa_card(note: str) -> str:
    text = note or ""
    if "中英" in text and "数值" in text:
        return "arch-bilingual-number"
    if "重量" in text:
        return "arch-same-file-weight"
    if ("功率" in text or re.search(r"kW", text, re.I)) and any(word in text for word in ("不一致", "口径不一", "又写")):
        return "arch-same-file-power"
    if any(word in text for word in ("输出电压", "冲击")) and any(word in text for word in ("不一致", "冲突")):
        return "arch-same-file-spec"
    return ""


def _cite(excerpt: str, sources: list[dict]) -> tuple[str, dict, str] | None:
    folded = _fold(excerpt)
    for source in sources:
        if source.get("role") != "标准":
            continue
        title = str(source.get("title") or "")
        matched = _STD.search(title)
        if not matched:
            continue
        token = _fold(matched.group(0))
        if len(token) >= 6 and token in folded:
            return "标准", source, matched.group(0)
    for source in sources:
        if source.get("role") != "图纸":
            continue
        for number in re.findall(r"\d{10}", str(source.get("title") or "")):
            if number in excerpt:
                return "图纸", source, number
    upper = excerpt.upper()
    if "ICD" not in upper and "HSI" not in upper:
        return None
    for source in sources:
        if source.get("role") != "接口":
            continue
        for version in re.findall(r"V\d+(?:\.\d+)?", str(source.get("title") or ""), re.I):
            if version.upper() in upper:
                return "接口", source, version
    return None


def assign_opinion(excerpt: str, note: str = "", library: dict | None = None) -> tuple[str, str]:
    """返回（初步意见，理由）。意见不写满足或不满足，数值只出现在当份质检原句里。"""
    if library is None:
        from electrical_krow.knowledge import feature_library

        library = feature_library("arch")
    cards = _cards(library)
    sources = [row for row in (library.get("sources") or []) if isinstance(row, dict)]
    qa = _qa_card(note)
    if qa:
        return _emit(cards, qa, f"。当份质检：{_clip(note)}")
    cited = _cite(excerpt or "", sources)
    if cited:
        role, source, token = cited
        card_id = {"标准": "arch-cite-standard", "图纸": "arch-cite-drawing", "接口": "arch-cite-interface"}[role]
        return _emit(cards, card_id, f"。来源 {source.get('id') or ''}。当份原句点名 {token}：{_clip(excerpt)}")
    return _emit(cards, "arch-no-source")
