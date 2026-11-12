"""当份正文内容审查：中英冲突、内部打架、模板残留。只报发现，不填格。"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PAGE_SPLIT = re.compile(r"(?=## 第 \d+ [页节])")
_CLAUSE_HEAD = re.compile(
    r"(?m)^(?:#{1,6}\s+)?((?:\d+\.){1,5}\d+)"
    r"(?!\d)(?!\s*(?:kg|kW|kPa|kV|Nm|A|V|h|µA|uA)\b)",
    re.I,
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_Q = re.compile(
    r"(?<![\d.])(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>µA|μA|uA|mA|kPa|kW|kg|微安|毫安|千帕|千瓦|公斤|小时|h|A)\b",
    re.I,
)
_UNIT_NORM = {
    "ua": "µA",
    "µa": "µA",
    "μa": "µA",
    "微安": "µA",
    "ma": "mA",
    "毫安": "mA",
    "kpa": "kPa",
    "千帕": "kPa",
    "kw": "kW",
    "千瓦": "kW",
    "kg": "kg",
    "公斤": "kg",
    "h": "h",
    "小时": "h",
    "a": "A",
}
_GENERIC_UNITS = frozenset({"µA", "mA", "kPa", "kW", "kg", "h", "A"})


@dataclass(frozen=True)
class ContentFinding:
    level: str
    kind: str
    text: str


def review_document_content(markdown: str) -> list[ContentFinding]:
    """对照当份正文。数字只用来标冲突，不提供抽出值。"""
    text = markdown or ""
    if len(re.sub(r"\s+", "", text)) < 40:
        return []
    found: list[ContentFinding] = []
    found.extend(_hvac_amp_conflicts(text))
    hvac_amps = _hvac_amp_present(text)
    for clause, window in _clause_windows(text):
        found.extend(_bilingual_unit_conflicts(clause, window, skip_a=hvac_amps))
        found.extend(_semantic_reversals(clause, window))
        found.extend(_claimed_power_vs_ui(clause, window))
    found.extend(_weight_over_limit(text))
    found.extend(_can_channel_mismatch(text))
    found.extend(_model_mix(text))
    found.extend(_hardware_vs_software(text))
    found.extend(_template_residue(text))
    found.extend(_placeholders(text))
    found.extend(_bad_dates(text))
    found.extend(_empty_tables(text))
    return _dedupe(found)[:20]


def content_summary(findings: list[ContentFinding]) -> str:
    if not findings:
        return ""
    p0 = sum(1 for f in findings if f.level == "P0")
    p1 = sum(1 for f in findings if f.level == "P1")
    bits: list[str] = []
    if p0:
        bits.append(f"中英冲突 {p0} 条")
    if p1:
        bits.append(f"内部/模板 {p1} 条")
    return "、".join(bits) + "。详见「文件审查」页。"


def _dedupe(items: list[ContentFinding]) -> list[ContentFinding]:
    seen: set[str] = set()
    out: list[ContentFinding] = []
    for item in items:
        key = f"{item.level}|{item.kind}|{item.text}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    out.sort(key=lambda f: (0 if f.level == "P0" else 1, f.kind, f.text))
    return out


def _clause_windows(markdown: str) -> list[tuple[str, str]]:
    text = markdown or ""
    matches = list(_CLAUSE_HEAD.finditer(text))
    raw: list[tuple[str, str]] = []
    if matches:
        for i, match in enumerate(matches[:120]):
            start = match.start()
            end = (
                matches[i + 1].start()
                if i + 1 < len(matches)
                else min(len(text), start + 4000)
            )
            raw.append((match.group(1), text[start:end][:4000]))
        merged: list[tuple[str, str]] = []
        for cid, chunk in raw:
            if merged and len(chunk) < 160:
                prev_id, prev = merged[-1]
                merged[-1] = (prev_id, (prev + "\n" + chunk)[:4500])
            else:
                merged.append((cid, chunk))
        lead = text[: matches[0].start()].strip()
        if len(lead) >= 200:
            merged.insert(0, ("", lead[:4000]))
        return merged[:80]
    blocks = [p for p in _PAGE_SPLIT.split(text) if p.strip()]
    if not blocks:
        return [("", text[:8000])]
    return [("", block[:4000]) for block in blocks[:40]]


def _has_bilingual(text: str) -> bool:
    return len(_CJK.findall(text or "")) >= 4 and len(_LATIN.findall(text or "")) >= 8


def _lang_near(text: str, pos: int) -> str:
    ctx = text[max(0, pos - 56) : min(len(text), pos + 72)]
    cjk = len(_CJK.findall(ctx))
    lat = len(_LATIN.findall(ctx))
    if cjk >= 4 and cjk >= lat:
        return "zh"
    if lat >= 6 and lat > cjk:
        return "en"
    return ""


def _norm_unit(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _UNIT_NORM.get(key, raw)


def _fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text


def _hvac_motor_lang_amps(text: str, motor: str) -> tuple[str, str]:
    block = text or ""
    cn = ""
    match = re.search(
        rf"测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A峰值范围内.{{0,80}}{motor}",
        block,
        re.I,
    )
    if match:
        cn = match.group(1)
    else:
        match = re.search(
            rf"{motor}逆变器[^\n]{{0,48}}测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            cn = match.group(1)
    en = ""
    match = re.search(
        rf"PEI {motor}:[\s\S]{{0,280}}?-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
        block,
        re.I,
    )
    if match:
        en = match.group(1)
    else:
        match = re.search(
            rf"PEI {motor} within the range\s*-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            en = match.group(1)
    return cn, en


def _hvac_amp_present(text: str) -> bool:
    for motor in ("P1", "P3"):
        cn, en = _hvac_motor_lang_amps(text, motor)
        if cn or en:
            return True
    return False


def _hvac_amp_conflicts(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    for motor in ("P1", "P3"):
        cn, en = _hvac_motor_lang_amps(text, motor)
        if cn and en and cn != en:
            out.append(
                ContentFinding(
                    "P0",
                    "中英冲突",
                    f"{motor} 交流电流量程中英不一致：中文 ±{cn}A，英文 ±{en}A。",
                )
            )
    return out


def _bilingual_unit_conflicts(
    clause: str, window: str, *, skip_a: bool
) -> list[ContentFinding]:
    if not _has_bilingual(window):
        return []
    by_unit: dict[str, dict[str, set[float]]] = {}
    for match in _Q.finditer(window):
        unit = _norm_unit(match.group("unit"))
        if unit not in _GENERIC_UNITS:
            continue
        if unit == "A" and skip_a:
            continue
        lang = _lang_near(window, match.start())
        if lang not in {"zh", "en"}:
            continue
        try:
            num = float(match.group("num"))
        except ValueError:
            continue
        bucket = by_unit.setdefault(unit, {"zh": set(), "en": set()})
        bucket[lang].add(round(num, 4))
    out: list[ContentFinding] = []
    prefix = f"{clause} " if clause else ""
    for unit, langs in by_unit.items():
        zh_vals = langs["zh"]
        en_vals = langs["en"]
        if not zh_vals or not en_vals or zh_vals == en_vals:
            continue
        zh_txt = "、".join(_fmt_num(v) for v in sorted(zh_vals))
        en_txt = "、".join(_fmt_num(v) for v in sorted(en_vals))
        out.append(
            ContentFinding(
                "P0",
                "中英冲突",
                f"{prefix}{unit} 中英数字不一致：英文 {en_txt}{unit}，中文 {zh_txt}{unit}。",
            )
        )
    return out


def _semantic_reversals(clause: str, window: str) -> list[ContentFinding]:
    if not _has_bilingual(window):
        return []
    prefix = f"{clause} " if clause else ""
    out: list[ContentFinding] = []
    for match in re.finditer(
        r"at\s+least\s+(\d+(?:\.\d+)?)\s*(A|V|kg)", window, re.I
    ):
        num, unit = match.group(1), match.group(2)
        if re.search(rf"小于\s*{re.escape(num)}\s*(?:{re.escape(unit)}|安)", window):
            out.append(
                ContentFinding(
                    "P0",
                    "语义相反",
                    f"{prefix}英文 at least {num}{unit}，中文写成小于 {num}{unit}。",
                )
            )
    if re.search(
        r"(?:shall not|must not|not allowing).{0,80}(?:unsafe|dangerous|hazardous)",
        window,
        re.I,
    ) and re.search(
        r"(?:误操作|错误操作).{0,24}(?:可能|也许).{0,20}(?:不安全|危险)",
        window,
    ):
        out.append(
            ContentFinding(
                "P0",
                "语义相反",
                f"{prefix}英文禁止危险误操作，中文写成可能不安全。",
            )
        )
    return out


def _claimed_power_vs_ui(clause: str, window: str) -> list[ContentFinding]:
    kws = [
        float(x)
        for x in re.findall(
            r"(?:Max(?:imum)?|max\.?|峰值|最大)\s*(\d+(?:\.\d+)?)\s*kW",
            window,
            re.I,
        )
    ]
    kws += [
        float(x)
        for x in re.findall(r"(\d+(?:\.\d+)?)\s*kW\s*@", window, re.I)
    ]
    if not kws:
        return []
    pairs = re.findall(
        r"(\d{2,4})\s*V(?:dc|DC)?(?:\s*[×x*]\s*|\s+)(\d{2,4})\s*A",
        window,
        re.I,
    )
    prefix = f"{clause} " if clause else ""
    out: list[ContentFinding] = []
    claimed = kws[0]
    for volt_s, amp_s in pairs[:3]:
        volt, amp = float(volt_s), float(amp_s)
        if volt < 48 or amp < 50:
            continue
        calc = volt * amp / 1000.0
        if claimed <= 0:
            continue
        if abs(calc - claimed) / claimed < 0.04:
            continue
        out.append(
            ContentFinding(
                "P1",
                "内部不一致",
                f"{prefix}声称 {_fmt_num(claimed)}kW，"
                f"按当份 {_fmt_num(volt)}V×{_fmt_num(amp)}A 为 {calc:.2f}kW。",
            )
        )
        break
    return out


def _weight_over_limit(text: str) -> list[ContentFinding]:
    limits = [
        float(x)
        for x in re.findall(
            r"(?:shall (?:not exceed|be (?:less|lower) than)|"
            r"不得超过|应(?:小于|不超过)|less than)\s*"
            r"(\d+(?:\.\d+)?)\s*kg",
            text,
            re.I,
        )
    ]
    if not limits:
        return []
    limit = min(limits)
    weights = [
        float(x)
        for x in re.findall(r"(?<![\d.])(\d{2}(?:\.\d+)?)\s*kg\b", text, re.I)
    ]
    over = sorted({w for w in weights if w > limit + 0.049})
    if not over:
        return []
    shown = "、".join(_fmt_num(w) for w in over[:4])
    return [
        ContentFinding(
            "P1",
            "内部不一致",
            f"重量限值 {_fmt_num(limit)}kg，正文另有 {shown}kg。",
        )
    ]


def _can_channel_mismatch(text: str) -> list[ContentFinding]:
    nums = [
        int(x)
        for x in re.findall(
            r"(?:at least|至少|≥|>=)\s*(\d{1,2})\s*(?:independent\s+)?CAN",
            text,
            re.I,
        )
    ]
    nums += [
        int(x)
        for x in re.findall(
            r"(?:CAN(?:\s+FD)?(?:\s+channels?)?|路CAN|CAN通道)"
            r"[^\n]{0,16}(?:≥|>=|至少)\s*(\d{1,2})",
            text,
            re.I,
        )
    ]
    nums = [n for n in nums if n >= 6]
    uniq = sorted(set(nums))
    if len(uniq) < 2:
        return []
    shown = "、".join(str(n) for n in uniq)
    return [
        ContentFinding(
            "P1",
            "内部不一致",
            f"CAN 通道数量写法不一致：{shown}。",
        )
    ]


def _model_mix(text: str) -> list[ContentFinding]:
    has_s = bool(re.search(r"\bDHTS160S\b", text))
    has_plain = bool(re.search(r"\bDHTS160\b", text))
    if has_s and has_plain:
        return [
            ContentFinding(
                "P1",
                "内部不一致",
                "型号 DHTS160 与 DHTS160S 同时出现。",
            )
        ]
    return []


def _hardware_vs_software(text: str) -> list[ContentFinding]:
    if re.search(r"Hardware only", text, re.I) and re.search(
        r"(?:OD\s+software|软件白盒|白盒交付)", text, re.I
    ):
        return [
            ContentFinding(
                "P1",
                "内部不一致",
                "附录写 Hardware only，正文又出现软件白盒交付。",
            )
        ]
    return []


def _template_residue(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    if re.search(r"\bVolvo\b", text):
        extra = "，中英主体不一致" if re.search(r"吉利|Geely", text, re.I) else ""
        out.append(
            ContentFinding("P1", "模板残留", f"残留 Volvo 模板用语{extra}。")
        )
    if re.search(r"Subject Matter Expert", text, re.I):
        out.append(
            ContentFinding("P1", "模板残留", "残留 Subject Matter Expert 模板句。")
        )
    return out


def _placeholders(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    tags = sorted(set(re.findall(r"<<[A-Z][A-Z0-9_ /.-]{2,}>>", text)))
    if tags:
        shown = "、".join(tags[:3])
        out.append(
            ContentFinding("P1", "占位未填", f"封面或正文仍有占位符 {shown}。")
        )
    head = text[:2500]
    if re.search(r"\b(?:TBD|TBC)\b", head):
        out.append(ContentFinding("P1", "占位未填", "文首仍有 TBD/TBC 未填。"))
    return out


def _bad_dates(text: str) -> list[ContentFinding]:
    hits = re.findall(r"(?<!\d)(20\d{7})(?!\d)", text)
    if not hits:
        return []
    shown = "、".join(hits[:3])
    return [
        ContentFinding("P1", "日期格式", f"日期位数异常：{shown}。")
    ]


def _empty_tables(text: str) -> list[ContentFinding]:
    lines = (text or "").splitlines()
    empty_n = 0
    i = 0
    while i < len(lines) - 2:
        line = lines[i]
        nxt = lines[i + 1]
        if "|" not in line or not re.search(r"^\s*\|?\s*-{3,}", nxt.replace(":", "")):
            i += 1
            continue
        j = i + 2
        body = 0
        blank = 0
        while j < len(lines) and "|" in lines[j] and not lines[j].strip().startswith("#"):
            cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
            if not any(cells):
                blank += 1
            body += 1
            j += 1
        if body >= 2 and blank == body:
            empty_n += 1
        i = j
    if not empty_n:
        return []
    return [
        ContentFinding("P1", "空表", f"有 {empty_n} 张表表头后无内容。")
    ]
