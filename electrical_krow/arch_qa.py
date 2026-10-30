"""电驱需求拆解前的文件内容质量检查：先查可读性、同文件参数前后冲突、中英数值/语义冲突、内部算式/限值打架与待定项（TBD）。

只报当份文件自身的冲突与质量问题，所有数字和摘录均取自当份原文，绝不引入外部标准值或替用户填格。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from electrical_krow.arch_contrast import (
    COLUMNS,
    SECTION_COVER,
    SECTION_TOC,
    SourceDoc,
    Unreadable,
    _compact,
    _join_notes,
)
from electrical_krow.arch_params import CONSIST_DIFF, ParamResult

_COL = {name: index for index, name in enumerate(COLUMNS)}

_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af]")
_GARBLED = re.compile(r"\ufffd{2,}")
_TBD_RE = re.compile(r"(?<![A-Za-z])(?:T\.?B\.?D\.?|T\.?B\.?C\.?|TODO)(?![A-Za-z])|<<[A-Z][A-Z0-9_ /.-]{2,}>>", re.I)

# 双语数值比对：提取「数字 + 常见工程单位」
_BI_QTY = re.compile(
    r"(?<![\d.])(?P<num>[-+]?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>kV|mV|V(?:dc|ac|DC|AC)?|µA|μA|uA|mA|A(?:dc|ac|DC|AC)?|kW|W|Nm|N·m|N\.m|rpm|r/min|"
    r"°C|℃|kPa|MPa|bar|kg|ms|s|min|h|hr|hours?|years?|km|kHz|Hz|%|MΩ|mΩ|Ω|"
    r"千伏|毫伏|伏|微安|毫安|安|千瓦|瓦|牛米|转/分|摄氏度|千帕|兆帕|公斤|千克|毫秒|秒|分钟|小时|年|公里|千米|赫兹|欧姆)"
    r"(?![A-Za-z])",
)
_UNIT_MAP = {
    "kv": "kV", "千伏": "kV",
    "mv": "mV", "毫伏": "mV",
    "v": "V", "vdc": "V", "vac": "V", "伏": "V",
    "µa": "µA", "μa": "µA", "ua": "µA", "微安": "µA",
    "ma": "mA", "毫安": "mA",
    "a": "A", "adc": "A", "aac": "A", "安": "A",
    "kw": "kW", "千瓦": "kW",
    "w": "W", "瓦": "W",
    "nm": "Nm", "n·m": "Nm", "n.m": "Nm", "牛米": "Nm",
    "rpm": "rpm", "r/min": "rpm", "转/分": "rpm",
    "°c": "°C", "℃": "°C", "摄氏度": "°C",
    "kpa": "kPa", "千帕": "kPa",
    "mpa": "MPa", "兆帕": "MPa",
    "bar": "bar",
    "kg": "kg", "公斤": "kg", "千克": "kg",
    "ms": "ms", "毫秒": "ms",
    "s": "s", "秒": "s",
    "min": "min", "分钟": "min",
    "h": "h", "hr": "h", "hour": "h", "hours": "h", "小时": "h",
    "year": "year", "years": "year", "年": "year",
    "km": "km", "公里": "km", "千米": "km",
    "khz": "kHz",
    "hz": "Hz", "赫兹": "Hz",
    "%": "%",
    "mω": "mΩ",
    "ω": "Ω", "欧姆": "Ω",
}


@dataclass(frozen=True)
class ArchIssue:
    level: str  # "conflict" | "warn"
    kind: str  # "中英数值冲突" | "中英语义冲突" | "内部逻辑冲突" | "跨处参数冲突" | "未定项" | "可读性"
    file: str
    page: int
    row_seq: int
    text: str


@dataclass
class ArchQualityReport:
    verdict: str  # "pass" | "warn"
    summary: str
    detail_lines: list[str] = field(default_factory=list)
    issues: list[ArchIssue] = field(default_factory=list)
    row_notes: dict[int, str] = field(default_factory=dict)
    flagged_seqs: set[int] = field(default_factory=set)
    tbd_count: int = 0
    bilingual_conflicts: int = 0
    logic_conflicts: int = 0
    param_conflicts: int = 0


def _fmt_num(val: float) -> str:
    if abs(val - round(val)) < 1e-6:
        return str(int(round(val)))
    return f"{val:.4f}".rstrip("0").rstrip(".")


def _norm_unit(raw: str) -> str:
    low = (raw or "").strip().lower()
    if raw == "MΩ":
        return "MΩ"
    return _UNIT_MAP.get(low, raw)


def _is_bilingual(text: str) -> bool:
    return len(_CJK.findall(text or "")) >= 2 and len(_LATIN.findall(text or "")) >= 4


def _lang_around(text: str, start: int, end: int, raw_unit: str) -> str:
    """按数值前后的引导词判断它属于中文表述还是英文表述。"""
    if _CJK.search(raw_unit):
        return "zh"
    seps_left = ("\n", "|", "/", "／", "；", ";", "。", "（", "(")
    seps_right = ("\n", "|", "/", "／", "；", ";", "。", "）", ")")
    left_bound = max(text.rfind(sep, 0, start) for sep in seps_left)
    right_candidates = [text.find(sep, end) for sep in seps_right]
    right_filtered = [pos for pos in right_candidates if pos >= 0]
    right_bound = min(right_filtered) if right_filtered else len(text)
    # 优先看紧邻数值前的引导词（如 "Maximum Output Power: " vs "最大输出功率："）
    lead = text[max(0, left_bound + 1) : start]
    lead_cjk = len(_CJK.findall(lead))
    lead_lat = len(_LATIN.findall(lead))
    if lead_cjk >= 2 and lead_cjk * 2 >= lead_lat:
        return "zh"
    if lead_lat >= 3 and lead_lat > lead_cjk * 2:
        return "en"
    clause = text[max(0, left_bound + 1) : right_bound]
    cjk = len(_CJK.findall(clause))
    lat = len(_LATIN.findall(clause))
    if cjk >= 2 and cjk * 2 >= lat:
        return "zh"
    if lat >= 3 and lat > cjk * 2:
        return "en"
    # 退回紧邻前窗
    near = text[max(0, start - 24) : start]
    cjk_n = len(_CJK.findall(near))
    lat_n = len(_LATIN.findall(near))
    if cjk_n >= 2 and cjk_n >= lat_n:
        return "zh"
    if lat_n >= 3 and lat_n > cjk_n:
        return "en"
    return ""


def _check_bilingual_numbers(file: str, page: int, seq: int, text: str) -> list[ArchIssue]:
    if not _is_bilingual(text):
        return []
    by_unit: dict[str, dict[str, set[float]]] = {}
    for match in _BI_QTY.finditer(text):
        raw_unit = match.group("unit")
        unit = _norm_unit(raw_unit)
        lang = _lang_around(text, match.start(), match.end(), raw_unit)
        if lang not in {"zh", "en"}:
            continue
        try:
            num = round(float(match.group("num")), 4)
        except ValueError:
            continue
        bucket = by_unit.setdefault(unit, {"zh": set(), "en": set()})
        bucket[lang].add(num)
    out: list[ArchIssue] = []
    for unit, langs in by_unit.items():
        zh_vals, en_vals = langs["zh"], langs["en"]
        if not zh_vals or not en_vals or zh_vals == en_vals:
            continue
        zh_str = "、".join(f"{_fmt_num(v)}{unit}" for v in sorted(zh_vals))
        en_str = "、".join(f"{_fmt_num(v)}{unit}" for v in sorted(en_vals))
        out.append(
            ArchIssue(
                "conflict",
                "中英数值冲突",
                file,
                page,
                seq,
                f"同条中英数值不一致：中文 {zh_str}，英文 {en_str}",
            )
        )
    return out


def _check_bilingual_semantics(file: str, page: int, seq: int, text: str) -> list[ArchIssue]:
    if not _is_bilingual(text):
        return []
    out: list[ArchIssue] = []
    for match in re.finditer(r"(?:at\s+least|not\s+less\s+than|no\s+less\s+than|minimum)\s+(\d+(?:\.\d+)?)\s*([A-Za-z%℃°Ω]+)?", text, re.I):
        num = match.group(1)
        unit = (match.group(2) or "").strip()
        if re.search(rf"(?:小于|不超过|低于|至多|最多)\s*{re.escape(num)}", text):
            out.append(
                ArchIssue(
                    "conflict",
                    "中英语义冲突",
                    file,
                    page,
                    seq,
                    f"同条中英方向相反：英文写 at least {num}{unit}，中文写小于/不超过 {num}{unit}",
                )
            )
    for match in re.finditer(r"(?:at\s+most|not\s+more\s+than|no\s+more\s+than|shall\s+not\s+exceed|less\s+than|maximum)\s+(\d+(?:\.\d+)?)\s*([A-Za-z%℃°Ω]+)?", text, re.I):
        num = match.group(1)
        unit = (match.group(2) or "").strip()
        if re.search(rf"(?:大于|至少|不小于|不少于|高于|超过)\s*{re.escape(num)}", text):
            out.append(
                ArchIssue(
                    "conflict",
                    "中英语义冲突",
                    file,
                    page,
                    seq,
                    f"同条中英方向相反：英文写不超过/小于 {num}{unit}，中文写大于/至少 {num}{unit}",
                )
            )
    if re.search(r"(?:shall\s+not|must\s+not|not\s+allowing).{0,60}(?:unsafe|dangerous|hazardous)", text, re.I) and re.search(
        r"(?<!不)(?:可能|也许|会)\s*(?:导致|造成|进入|处于)?.{0,16}(?:不安全|危险)", text
    ):
        out.append(
            ArchIssue(
                "conflict",
                "中英语义冲突",
                file,
                page,
                seq,
                "同条中英语义相反：英文禁止危险误操作，中文写成可能不安全",
            )
        )
    return out


_DIRECT_UI_EQ = re.compile(
    r"(?P<v>\d+(?:\.\d+)?)\s*V(?:dc|DC)?\s*[×x*]\s*(?P<i>\d+(?:\.\d+)?)\s*A\s*=\s*(?P<p>\d+(?:\.\d+)?)\s*kW",
    re.I,
)
_P_THEN_UI = re.compile(
    r"(?P<p>\d+(?:\.\d+)?)\s*kW[^\n;|]{0,40}?(?:Vo|V|电压)\s*[=:：]?\s*(?P<v>\d+(?:\.\d+)?)\s*V(?:dc|DC)?[^\n;|]{0,24}?(?:Io|Iout|I|电流)\s*[=:：]?\s*(?P<i>\d+(?:\.\d+)?)\s*A",
    re.I,
)
_EXPLICIT_MIN_MAX = re.compile(
    r"\bmin\.?\s*[=:：]?\s*(?P<lo>[-+]?\d+(?:\.\d+)?)\s*(?P<u1>[A-Za-z%℃°Ω]{1,4})?[^\n;|]{1,30}?\bmax\.?\s*[=:：]?\s*(?P<hi>[-+]?\d+(?:\.\d+)?)\s*(?P<u2>[A-Za-z%℃°Ω]{1,4})",
    re.I,
)
_MAX_OUTPUT_DUAL_KW = re.compile(
    r"^[•·\s]*(?P<p1>\d+(?:\.\d+)?)\s*kW\b[\s\S]*?\bMax\.?\s*output\s*=\s*[^=\n;|]{1,30}?=\s*(?P<p2>\d+(?:\.\d+)?)\s*kW\b",
    re.I,
)


def _check_row_logic(file: str, page: int, seq: int, text: str, item_name: str = "") -> list[ArchIssue]:
    out: list[ArchIssue] = []
    # 1. 显式算式 U × I = P kW 核对
    seen_pairs: set[tuple[float, float, float]] = set()
    for match in _DIRECT_UI_EQ.finditer(text):
        v, i, p = float(match.group("v")), float(match.group("i")), float(match.group("p"))
        if p <= 0:
            continue
        calc = v * i / 1000.0
        seen_pairs.add((v, i, p))
        if abs(calc - p) / p >= 0.04:
            out.append(
                ArchIssue(
                    "conflict",
                    "内部逻辑冲突",
                    file,
                    page,
                    seq,
                    f"功率算式不一致：原文写 {_fmt_num(v)}V×{_fmt_num(i)}A={_fmt_num(p)}kW，实算为 {calc:.2f}kW",
                )
            )
    # 2. 同一分句内「P kW (@Vo=..., Io=...)」或「Max P kW (U V × I A)」核对
    for match in _P_THEN_UI.finditer(text):
        v, i, p = float(match.group("v")), float(match.group("i")), float(match.group("p"))
        if p <= 0 or (v, i, p) in seen_pairs:
            continue
        calc = v * i / 1000.0
        if abs(calc - p) / p >= 0.05:
            out.append(
                ArchIssue(
                    "conflict",
                    "内部逻辑冲突",
                    file,
                    page,
                    seq,
                    f"功率与电压电流不一致：声称 {_fmt_num(p)}kW，按同处 {_fmt_num(v)}V×{_fmt_num(i)}A 计算为 {calc:.2f}kW",
                )
            )
    kws = [float(x) for x in re.findall(r"(?:Max(?:imum)?|max\.?|峰值|最大|额定)\s*(\d+(?:\.\d+)?)\s*kW", text, re.I)]
    ui_mul = [(float(v), float(i)) for v, i in re.findall(r"(\d+(?:\.\d+)?)\s*V(?:dc|DC)?\s*[×x*]\s*(\d+(?:\.\d+)?)\s*A", text, re.I)]
    if len(kws) == 1 and len(ui_mul) == 1 and not out:
        p = kws[0]
        v, i = ui_mul[0]
        calc = v * i / 1000.0
        if p > 0 and abs(calc - p) / p >= 0.05:
            out.append(
                ArchIssue(
                    "conflict",
                    "内部逻辑冲突",
                    file,
                    page,
                    seq,
                    f"功率与电压电流不一致：声称 {_fmt_num(p)}kW，按同处 {_fmt_num(v)}V×{_fmt_num(i)}A 计算为 {calc:.2f}kW",
                )
            )
    # 3. 同一「最大输出」条目内同时写两个不同的最大功率（如主项写 2.5kW，同格又写 Max. output = 2.72kW）
    if re.search(r"max\.?\s*output|maximum\s*output|最大输出", f"{item_name} {text}", re.I):
        # 取 Specification 字段或整段文本里的双功率表述
        if "Specification：" in text:
            spec_tail = text.split("Specification：", 1)[-1]
        elif "：" in text:
            spec_tail = text.split("：", 1)[-1]
        else:
            spec_tail = text
        dual = _MAX_OUTPUT_DUAL_KW.search(spec_tail)
        if dual:
            p1, p2 = float(dual.group("p1")), float(dual.group("p2"))
            if abs(p1 - p2) >= 0.05:
                out.append(
                    ArchIssue(
                        "conflict",
                        "内部逻辑冲突",
                        file,
                        page,
                        seq,
                        f"同条最大输出功率口径不一：既写 {_fmt_num(p1)}kW，又写 Max. output = {_fmt_num(p2)}kW",
                    )
                )
    # 4. 显式 Min > Max 颠倒
    for match in _EXPLICIT_MIN_MAX.finditer(text):
        u1 = _norm_unit(match.group("u1") or match.group("u2") or "")
        u2 = _norm_unit(match.group("u2") or "")
        if u1 != u2:
            continue
        lo, hi = float(match.group("lo")), float(match.group("hi"))
        if lo > hi:
            out.append(
                ArchIssue(
                    "conflict",
                    "内部逻辑冲突",
                    file,
                    page,
                    seq,
                    f"上下限颠倒：Min 写成 {_fmt_num(lo)}{u2}，大于 Max {_fmt_num(hi)}{u2}",
                )
            )
    return out


_WEIGHT_LIMIT_RE = re.compile(
    r"(?:weight[^\n]{0,30}?(?:shall\s+(?:not\s+exceed|be\s+(?:less|lower)\s+than)|≤|<=|<)|"
    r"重量[^\n]{0,20}?(?:不得超过|应?(?:小于|不超过)|≤|<=|<))\s*(\d+(?:\.\d+)?)\s*kg"
    r"|(?P<item_w>weight|重量)[^\n]{0,30}?(\d+(?:\.\d+)?)\s*kg\s*(?:↓|max\.?|以下|以内)",
    re.I,
)
_WEIGHT_VAL_RE = re.compile(
    r"(?:weight|重量|mass)[^\n]{0,40}?(?<![\d.])(\d+(?:\.\d+)?)\s*kg\b",
    re.I,
)


def _check_doc_weight_conflicts(rows: list[list[object]]) -> list[ArchIssue]:
    """同一份文件里，一处写明重量上限（如 ≤12kg），另一处给出超出上限的重量值（如 14.5kg）。"""
    by_file: dict[str, list[list[object]]] = {}
    for row in rows:
        by_file.setdefault(str(row[_COL["文件"]] or ""), []).append(row)
    out: list[ArchIssue] = []
    for file, frows in by_file.items():
        limits: list[tuple[float, int, int]] = []
        values: list[tuple[float, int, int]] = []
        for row in frows:
            if str(row[_COL["章节"]] or "") in {SECTION_COVER, SECTION_TOC}:
                continue
            text = str(row[_COL["原文摘录"]] or "")
            if text.startswith(("本页表格", "本页图片表格", "本页为数值表", "本页图表", "本页表格块")):
                continue
            seq = int(row[_COL["序号"]] or 0)
            page = int(row[_COL["PDF页码"]] or 0)
            blob = f"{row[_COL['项目（表格栏目）']] or ''} {row[_COL['原文摘录']] or ''}"
            for m in _WEIGHT_LIMIT_RE.finditer(blob):
                num_s = m.group(1) or m.group(3)
                if num_s:
                    limits.append((float(num_s), page, seq))
            for m in _WEIGHT_VAL_RE.finditer(blob):
                values.append((float(m.group(1)), page, seq))
        if not limits or not values:
            continue
        lim_val, lim_page, lim_seq = min(limits, key=lambda x: x[0])
        over = [(v, p, s) for v, p, s in values if v > lim_val + 0.049 and s != lim_seq]
        if not over:
            continue
        over_str = "、".join(f"第 {p} 页 {_fmt_num(v)}kg" for v, p, _ in over[:3])
        out.append(
            ArchIssue(
                "conflict",
                "内部逻辑冲突",
                file,
                lim_page,
                lim_seq,
                f"重量限值不一致：此处限值 {_fmt_num(lim_val)}kg，同文件另有 {over_str}",
            )
        )
        for v, p, s in over:
            out.append(
                ArchIssue(
                    "conflict",
                    "内部逻辑冲突",
                    file,
                    p,
                    s,
                    f"重量超出同文件限值：此处 {_fmt_num(v)}kg，超过第 {lim_page} 页限值 {_fmt_num(lim_val)}kg",
                )
            )
    return out


_VO_RANGE_RE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*V?\s*(?:~|–|-|to)\s*(?P<hi>\d+(?:\.\d+)?)\s*V\b",
    re.I,
)
_VO_INEQ_RE = re.compile(
    r"(?P<lo>\d+(?:\.\d+)?)\s*V\s*(?:<|≤|<=)\s*Vo(?:ut)?\s*(?:<|≤|<=)\s*(?P<hi>\d+(?:\.\d+)?)\s*V\b",
    re.I,
)
_SHOCK_G_RE = re.compile(
    r"(?:over\s+|≥\s*|>\s*)?\d+(?:\.\d+)?\s*G(?:\s*/\s*\d+(?:\.\d+)?\s*G)*(?![A-Za-z])",
    re.I,
)


def _check_doc_spec_conflicts(rows: list[list[object]], valid_seqs: set[int] | None = None) -> list[ArchIssue]:
    """同一份文件内跨章节/跨表的关键规格范围冲突（如输出电压范围 Vo 前后不一致、机械冲击 G 值前后不一致）。"""
    by_file: dict[str, list[list[object]]] = {}
    for row in rows:
        by_file.setdefault(str(row[_COL["文件"]] or ""), []).append(row)
    out: list[ArchIssue] = []
    for file, frows in by_file.items():
        # 1. 输出电压范围（Output / Voltage、Output voltage command range、Line/Load regulation 中的 aV < Vo < bV）
        vo_entries: list[tuple[int, int, str, frozenset[tuple[float, float]], str]] = []
        # 2. 机械冲击加速度（Mech.shock / Mechanical shock / SHOCK）
        shock_entries: list[tuple[int, int, str, str, str]] = []
        for row in frows:
            if str(row[_COL["章节"]] or "") in {SECTION_COVER, SECTION_TOC}:
                continue
            seq = int(row[_COL["序号"]] or 0)
            if valid_seqs is not None and seq not in valid_seqs:
                continue
            page = int(row[_COL["PDF页码"]] or 0)
            item = str(row[_COL["项目（表格栏目）"]] or "").strip()
            qty = str(row[_COL["数值与单位"]] or "").strip()
            text = str(row[_COL["原文摘录"]] or "").strip()
            spec_text = qty or text

            is_vo_item = bool(
                re.search(
                    r"(?:^|/)\s*output\s*/\s*voltage\s*$|(?:^|/)\s*output\s+voltage\s+(?:command\s+)?range\s*$|输出电压(?:指令)?范围",
                    item,
                    re.I,
                )
            )
            ineq_matches = list(_VO_INEQ_RE.finditer(spec_text))
            if is_vo_item or ineq_matches:
                bounds: list[tuple[float, float]] = []
                raw_parts: list[str] = []
                if ineq_matches:
                    for m in ineq_matches:
                        b = (round(float(m.group("lo")), 3), round(float(m.group("hi")), 3))
                        if b not in bounds:
                            bounds.append(b)
                            raw_parts.append(_compact(m.group(0)))
                else:
                    for m in _VO_RANGE_RE.finditer(spec_text):
                        b = (round(float(m.group("lo")), 3), round(float(m.group("hi")), 3))
                        if b not in bounds:
                            bounds.append(b)
                            raw_parts.append(_compact(m.group(0)))
                if bounds:
                    vo_entries.append((page, seq, item or "输出电压范围", frozenset(bounds), " / ".join(raw_parts)))

            if re.search(r"mech\.?\s*shock|mechanical\s*shock|\bshock\b|机械冲击", item, re.I):
                g_hits: list[str] = []
                for m in _SHOCK_G_RE.finditer(spec_text):
                    val = _compact(m.group(0))
                    if val not in g_hits:
                        g_hits.append(val)
                if g_hits:
                    disp = "、".join(g_hits)
                    norm_g = re.sub(r"\s+", "", disp).upper()
                    shock_entries.append((page, seq, item, norm_g, disp))

        if len({e[3] for e in vo_entries}) >= 2:
            for page, seq, item, bset, disp in vo_entries:
                diff_others: list[str] = []
                for opage, oseq, oitem, obset, odisp in vo_entries:
                    if oseq != seq and obset != bset:
                        tag = f"第 {opage} 页「{oitem}」{odisp}"
                        if tag not in diff_others:
                            diff_others.append(tag)
                if diff_others:
                    out.append(
                        ArchIssue(
                            "conflict",
                            "跨处参数冲突",
                            file,
                            page,
                            seq,
                            f"输出电压范围前后不一致：此处「{item}」为 {disp}，同文件另有 " + "、".join(diff_others[:3]),
                        )
                    )

        if len({e[3] for e in shock_entries}) >= 2:
            for page, seq, item, norm_g, disp in shock_entries:
                diff_others = []
                for opage, oseq, oitem, onorm, odisp in shock_entries:
                    if oseq != seq and onorm != norm_g:
                        tag = f"第 {opage} 页「{oitem}」{odisp}"
                        if tag not in diff_others:
                            diff_others.append(tag)
                if diff_others:
                    out.append(
                        ArchIssue(
                            "conflict",
                            "跨处参数冲突",
                            file,
                            page,
                            seq,
                            f"机械冲击加速度前后不一致：此处「{item}」为 {disp}，同文件另有 " + "、".join(diff_others[:3]),
                        )
                    )
    return out


def check_arch_quality(
    docs: list[SourceDoc],
    unreadable: list[Unreadable],
    all_rows: list[list[object]],
    params: ParamResult,
    req_map: dict[int, tuple[int, str]] | None = None,
) -> ArchQualityReport:
    """对拆解前的文档及拆出的条目执行内容质量检查。req_map: 序号 -> (需求清单Excel行号, REQ-ID)。"""
    issues: list[ArchIssue] = []
    row_notes: dict[int, str] = {}
    flagged_seqs: set[int] = set()
    valid_seqs = set(req_map) if req_map is not None else None

    def add_row_note(seq: int, note: str, *, flag: bool = False) -> None:
        if seq <= 0:
            return
        if note not in (row_notes.get(seq) or ""):
            row_notes[seq] = _join_notes(row_notes.get(seq, ""), note)
        if flag:
            flagged_seqs.add(seq)

    # 1. 文件级可读性与页面花字检查
    for item in unreadable:
        pages_note = f"（{item.pages} 页）" if item.pages else ""
        issues.append(ArchIssue("warn", "可读性", item.name, 0, 0, f"{item.name}{pages_note}：{item.reason}"))

    for doc in docs:
        garbled_pages: list[int] = []
        for page_no, raw in doc.pages:
            if _GARBLED.search(raw or ""):
                garbled_pages.append(page_no)
        if garbled_pages:
            shown = "、".join(str(p) for p in garbled_pages[:6])
            issues.append(
                ArchIssue("warn", "可读性", doc.name, garbled_pages[0], 0, f"{doc.name} 第 {shown} 页存在编码替换符或乱码字符，请对照原页核对。")
            )

    # 2. 逐条检查：中英数值冲突、中英语义冲突、内部算式/上下限冲突、待定项（TBD/TBC）
    tbd_pages: list[tuple[str, int]] = []
    tbd_count = 0
    for row in all_rows:
        section = str(row[_COL["章节"]] or "")
        if section in {SECTION_COVER, SECTION_TOC}:
            continue
        text = str(row[_COL["原文摘录"]] or "")
        if text.startswith(("本页表格", "本页图片表格", "本页为数值表", "本页图表", "本页表格块")) or "（表格块，整块见" in text:
            continue
        seq = int(row[_COL["序号"]] or 0)
        if valid_seqs is not None and seq not in valid_seqs:
            continue
        file = str(row[_COL["文件"]] or "")
        page = int(row[_COL["PDF页码"]] or 0)
        item_name = str(row[_COL["项目（表格栏目）"]] or "")
        qty = str(row[_COL["数值与单位"]] or "")
        cond = str(row[_COL["适用条件（原文括注）"]] or "")
        # 原文摘录已含本条完整句；表格行补上未进摘录的适用条件列，不重复拼接已挑出的数值列以免干扰中英分句
        extra_parts = [p for p in (qty if item_name and qty not in text else "", cond if cond not in text else "") if p]
        full_text = _compact(" ".join([text, *extra_parts]))

        for issue in _check_bilingual_numbers(file, page, seq, full_text):
            issues.append(issue)
            add_row_note(seq, f"【内容质检】{issue.text}", flag=True)

        for issue in _check_bilingual_semantics(file, page, seq, full_text):
            issues.append(issue)
            add_row_note(seq, f"【内容质检】{issue.text}", flag=True)

        for issue in _check_row_logic(file, page, seq, full_text, item_name):
            issues.append(issue)
            add_row_note(seq, f"【内容质检】{issue.text}", flag=True)

        if _TBD_RE.search(full_text):
            tbd_count += 1
            if (file, page) not in tbd_pages:
                tbd_pages.append((file, page))
            label = f"「{item_name}」" if item_name else ""
            issues.append(ArchIssue("warn", "待定项", file, page, seq, f"{label}原文含待定项（TBD/TBC）"))
            add_row_note(seq, "【内容质检】原文含待定项（TBD/TBC）", flag=True)

    # 3. 同文件重量限值冲突
    for issue in _check_doc_weight_conflicts(all_rows):
        if valid_seqs is not None and issue.row_seq not in valid_seqs:
            continue
        issues.append(issue)
        add_row_note(issue.row_seq, f"【内容质检】{issue.text}", flag=True)

    # 4. 同文件内跨处同一参数前后取值不一致（含规则关键规格核对与参数表归并核对）
    param_conflict_seqs: set[int] = set()
    for issue in _check_doc_spec_conflicts(all_rows, valid_seqs):
        issues.append(issue)
        add_row_note(issue.row_seq, f"【内容质检】{issue.text}", flag=True)
        param_conflict_seqs.add(issue.row_seq)

    for param in params.params:
        if param.consistency == CONSIST_DIFF:
            if valid_seqs is not None and param.row_seq not in valid_seqs:
                continue
            hint = f"「{param.name}」此处 {param.value}，与别处不一致：{param.others}"
            if param.row_seq not in param_conflict_seqs:
                issues.append(ArchIssue("conflict", "跨处参数冲突", param.file, param.page, param.row_seq, hint))
                add_row_note(param.row_seq, f"【内容质检】{hint}", flag=True)
                param_conflict_seqs.add(param.row_seq)

    bilingual_n = sum(1 for i in issues if i.kind in {"中英数值冲突", "中英语义冲突"})
    logic_n = sum(1 for i in issues if i.kind == "内部逻辑冲突")
    param_n = len(param_conflict_seqs)
    read_n = sum(1 for i in issues if i.kind == "可读性")

    verdict = "warn" if (bilingual_n or logic_n or param_n or read_n or tbd_count) else "pass"
    parts: list[str] = []
    if bilingual_n:
        parts.append(f"中英数值/语义冲突 {bilingual_n} 处")
    if logic_n:
        parts.append(f"内部逻辑冲突 {logic_n} 处")
    if param_n:
        parts.append(f"同参数前后取值不一致 {param_n} 处")
    if tbd_count:
        page_str = "、".join(f"第 {p} 页" for _, p in tbd_pages[:5])
        if len(tbd_pages) > 5:
            page_str += "等"
        parts.append(f"待定项（TBD/TBC）{tbd_count} 条（{page_str}）")
    if read_n:
        parts.append(f"不可读/乱码提醒 {read_n} 处")

    if parts:
        flagged_n = len(flagged_seqs)
        summary = (
            "文件内容质检：需注意（"
            + "；".join(parts)
            + f"）。冲突行与待定项共 {flagged_n} 行已在「需求清单」整行标红并写入 M 列「备注」（可在 M 列筛选「内容质检」）。"
        )
    else:
        summary = "文件内容质检：通过（文字层可读，未发现中英冲突、内部算式冲突或同参数前后取值不一致）。"

    # 冲突项排在前面，待定项排在后面，每条写明「需求清单第 X 行（REQ-ID，第 P 页）」方便直接定位
    ordered_issues = sorted(
        issues,
        key=lambda i: (0 if i.level == "conflict" else 1, req_map.get(i.row_seq, (999999, ""))[0] if req_map else i.row_seq, i.page),
    )
    detail_lines: list[str] = [summary]
    for issue in ordered_issues[:40]:
        if req_map and issue.row_seq in req_map:
            xl_row, req_id = req_map[issue.row_seq]
            loc = f"需求清单第 {xl_row} 行（{req_id}，第 {issue.page} 页）"
        else:
            loc = f"{issue.file} 第 {issue.page} 页" if issue.page else issue.file
        detail_lines.append(f"• [{issue.kind}] {loc}：{issue.text}")

    return ArchQualityReport(
        verdict=verdict,
        summary=summary,
        detail_lines=detail_lines,
        issues=ordered_issues,
        row_notes=row_notes,
        flagged_seqs=flagged_seqs,
        tbd_count=tbd_count,
        bilingual_conflicts=bilingual_n,
        logic_conflicts=logic_n,
        param_conflicts=param_n,
    )
