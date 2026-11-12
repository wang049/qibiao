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
    page: str = ""
    clause: str = ""


def _locate(text: str, index: int) -> tuple[str, str]:
    """命中点之前最近的印页和条款号。没有就不编。"""
    if index < 0:
        return "", ""
    page = ""
    for match in re.finditer(r"## 第 (\d+) [页节]", text):
        if match.start() <= index:
            page = match.group(1)
        else:
            break
    clause = ""
    for match in _CLAUSE_HEAD.finditer(text[: index + 1]):
        clause = match.group(1)
    return page, clause


def _mark(
    level: str,
    kind: str,
    sentence: str,
    text: str,
    index: int,
    clause: str = "",
) -> ContentFinding:
    page, found = _locate(text, index)
    return ContentFinding(level, kind, sentence, page, clause or found)


def _first_at(text: str, pattern: str) -> int:
    match = re.search(pattern, text or "", re.I)
    return match.start() if match else -1


def review_document_content(markdown: str) -> list[ContentFinding]:
    """对照当份正文。数字只用来标冲突，不提供抽出值。"""
    text = markdown or ""
    if len(re.sub(r"\s+", "", text)) < 40:
        return []
    found: list[ContentFinding] = []
    found.extend(_hvac_amp_conflicts(text))
    hvac_amps = _hvac_amp_present(text)
    for _clause, window, start in _clause_windows(text):
        found.extend(_bilingual_unit_conflicts(window, text, start, skip_a=hvac_amps))
        found.extend(_semantic_reversals(window, text, start))
        found.extend(_claimed_power_vs_ui(window, text, start))
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
    return "、".join(bits) + "。详见「03_提取质量审查」。"


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


def _clause_windows(markdown: str) -> list[tuple[str, str, int]]:
    text = markdown or ""
    matches = list(_CLAUSE_HEAD.finditer(text))
    raw: list[tuple[str, str, int]] = []
    if matches:
        for i, match in enumerate(matches[:120]):
            start = match.start()
            end = (
                matches[i + 1].start()
                if i + 1 < len(matches)
                else min(len(text), start + 4000)
            )
            raw.append((match.group(1), text[start:end][:4000], start))
        merged: list[tuple[str, str, int]] = []
        for cid, chunk, start in raw:
            if merged and len(chunk) < 160:
                prev_id, prev, prev_at = merged[-1]
                merged[-1] = (prev_id, (prev + "\n" + chunk)[:4500], prev_at)
            else:
                merged.append((cid, chunk, start))
        lead = text[: matches[0].start()].strip()
        if len(lead) >= 200:
            merged.insert(0, ("", lead[:4000], 0))
        return merged[:80]
    blocks = [p for p in _PAGE_SPLIT.split(text) if p.strip()]
    if not blocks:
        return [("", text[:8000], 0)]
    located: list[tuple[str, str, int]] = []
    cursor = 0
    for block in blocks[:40]:
        at = text.find(block[:60], cursor)
        if at < 0:
            at = cursor
        located.append(("", block[:4000], at))
        cursor = at + 1
    return located


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


_UNIT_SAY = {
    "h": "小时",
    "kW": "功率",
    "A": "电流",
    "kg": "重量",
    "kPa": "压力",
    "mA": "电流",
    "µA": "电流",
}


def _hvac_motor_lang_amps(text: str, motor: str) -> tuple[str, str, int]:
    block = text or ""
    cn = ""
    at = -1
    match = re.search(
        rf"测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A峰值范围内.{{0,80}}{motor}",
        block,
        re.I,
    )
    if match:
        cn = match.group(1)
        at = match.start()
    else:
        match = re.search(
            rf"{motor}逆变器[^\n]{{0,48}}测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            cn = match.group(1)
            at = match.start()
    en = ""
    match = re.search(
        rf"PEI {motor}:[\s\S]{{0,280}}?-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
        block,
        re.I,
    )
    if match:
        en = match.group(1)
        if at < 0:
            at = match.start()
    else:
        match = re.search(
            rf"PEI {motor} within the range\s*-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            en = match.group(1)
            if at < 0:
                at = match.start()
    return cn, en, at


def _hvac_amp_present(text: str) -> bool:
    for motor in ("P1", "P3"):
        cn, en, _at = _hvac_motor_lang_amps(text, motor)
        if cn or en:
            return True
    return False


def _hvac_amp_conflicts(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    for motor in ("P1", "P3"):
        cn, en, at = _hvac_motor_lang_amps(text, motor)
        if cn and en and cn != en:
            out.append(
                _mark(
                    "P0",
                    "中英冲突",
                    f"{motor} 交流电流：中文写 ±{cn}A，英文写 ±{en}A，两边对不上。",
                    text,
                    at,
                )
            )
    return out


def _bilingual_unit_conflicts(
    window: str, text: str, start: int, *, skip_a: bool
) -> list[ContentFinding]:
    if not _has_bilingual(window):
        return []
    by_unit: dict[str, dict[str, set[float]]] = {}
    first_at: dict[str, int] = {}
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
        first_at.setdefault(unit, match.start())
    out: list[ContentFinding] = []
    for unit, langs in by_unit.items():
        zh_vals = langs["zh"]
        en_vals = langs["en"]
        if not zh_vals or not en_vals or zh_vals == en_vals:
            continue
        zh_txt = "、".join(f"{_fmt_num(v)}{unit}" for v in sorted(zh_vals))
        en_txt = "、".join(f"{_fmt_num(v)}{unit}" for v in sorted(en_vals))
        name = _UNIT_SAY.get(unit, unit)
        out.append(
            _mark(
                "P0",
                "中英冲突",
                f"英文{name}写 {en_txt}，中文写 {zh_txt}，两边对不上。",
                text,
                start + first_at.get(unit, 0),
            )
        )
    return out


def _semantic_reversals(
    window: str, text: str, start: int
) -> list[ContentFinding]:
    if not _has_bilingual(window):
        return []
    out: list[ContentFinding] = []
    for match in re.finditer(
        r"at\s+least\s+(\d+(?:\.\d+)?)\s*(A|V|kg)", window, re.I
    ):
        num, unit = match.group(1), match.group(2)
        if re.search(rf"小于\s*{re.escape(num)}\s*(?:{re.escape(unit)}|安)", window):
            out.append(
                _mark(
                    "P0",
                    "语义相反",
                    f"英文写 at least {num}{unit}，中文写成小于 {num}{unit}，意思相反。",
                    text,
                    start + match.start(),
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
        hit = re.search(r"误操作|错误操作|shall not|must not", window, re.I)
        out.append(
            _mark(
                "P0",
                "语义相反",
                "英文写禁止危险误操作，中文写成可能不安全，意思相反。",
                text,
                start + (hit.start() if hit else 0),
            )
        )
    return out


def _claimed_power_vs_ui(
    window: str, text: str, start: int
) -> list[ContentFinding]:
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
        hit = re.search(
            r"(?:Max(?:imum)?|max\.?|峰值|最大)\s*\d+(?:\.\d+)?\s*kW|\d+(?:\.\d+)?\s*kW\s*@",
            window,
            re.I,
        )
        out.append(
            _mark(
                "P1",
                "内部不一致",
                f"写的是 {_fmt_num(claimed)}kW，"
                f"按同段 {_fmt_num(volt)}V×{_fmt_num(amp)}A 算是 {calc:.2f}kW。",
                text,
                start + (hit.start() if hit else 0),
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
    at = _first_at(text, rf"(?<![\d.]){re.escape(_fmt_num(over[0]))}\s*kg")
    return [
        _mark(
            "P1",
            "内部不一致",
            f"限值是 {_fmt_num(limit)}kg，正文里另有 {shown}kg。",
            text,
            at,
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
    at = _first_at(
        text,
        r"(?:at least|至少|≥|>=)\s*\d{1,2}\s*(?:independent\s+)?CAN|路CAN|CAN通道",
    )
    return [
        _mark(
            "P1",
            "内部不一致",
            f"CAN 通道有的写 {shown}，数量对不上。",
            text,
            at,
        )
    ]


def _model_mix(text: str) -> list[ContentFinding]:
    has_s = bool(re.search(r"\bDHTS160S\b", text))
    has_plain = bool(re.search(r"\bDHTS160\b", text))
    if has_s and has_plain:
        spots = [
            n
            for n in (
                _first_at(text, r"\bDHTS160S\b"),
                _first_at(text, r"\bDHTS160\b"),
            )
            if n >= 0
        ]
        return [
            _mark(
                "P1",
                "内部不一致",
                "型号同时写了 DHTS160 和 DHTS160S。",
                text,
                min(spots) if spots else -1,
            )
        ]
    return []


def _hardware_vs_software(text: str) -> list[ContentFinding]:
    if re.search(r"Hardware only", text, re.I) and re.search(
        r"(?:OD\s+software|软件白盒|白盒交付)", text, re.I
    ):
        return [
            _mark(
                "P1",
                "内部不一致",
                "附录写 Hardware only，正文又写软件白盒交付。",
                text,
                _first_at(text, r"Hardware only"),
            )
        ]
    return []


def _template_residue(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    if re.search(r"\bVolvo\b", text):
        tail = "。文中主体写的是吉利" if re.search(r"吉利|Geely", text, re.I) else ""
        out.append(
            _mark(
                "P1",
                "模板残留",
                f"还留着 Volvo 的模板用语{tail}。",
                text,
                _first_at(text, r"\bVolvo\b"),
            )
        )
    if re.search(r"Subject Matter Expert", text, re.I):
        out.append(
            _mark(
                "P1",
                "模板残留",
                "还留着 Subject Matter Expert 这句模板。",
                text,
                _first_at(text, r"Subject Matter Expert"),
            )
        )
    return out


def _placeholders(text: str) -> list[ContentFinding]:
    out: list[ContentFinding] = []
    tags = sorted(set(re.findall(r"<<[A-Z][A-Z0-9_ /.-]{2,}>>", text)))
    if tags:
        shown = "、".join(tags[:3])
        out.append(
            _mark(
                "P1",
                "占位未填",
                f"占位符 {shown} 还在，没有填上具体名称。",
                text,
                _first_at(text, r"<<[A-Z][A-Z0-9_ /.-]{2,}>>"),
            )
        )
    head = text[:2500]
    if re.search(r"\b(?:TBD|TBC)\b", head):
        out.append(
            _mark(
                "P1",
                "占位未填",
                "文首还有 TBD/TBC，没有填上。",
                text,
                _first_at(head, r"\b(?:TBD|TBC)\b"),
            )
        )
    return out


def _bad_dates(text: str) -> list[ContentFinding]:
    hits = list(dict.fromkeys(re.findall(r"(?<!\d)(20\d{7})(?!\d)", text)))
    if not hits:
        return []
    shown = "、".join(hits[:3])
    return [
        _mark(
            "P1",
            "日期格式",
            f"日期写成 {shown}，位数不对，不是正常的年月日。",
            text,
            _first_at(text, r"(?<!\d)20\d{7}(?!\d)"),
        )
    ]


def _empty_tables(text: str) -> list[ContentFinding]:
    lines = (text or "").splitlines()
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    empty_n = 0
    first_at = -1
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
            if first_at < 0:
                first_at = offsets[i]
        i = j
    if not empty_n:
        return []
    return [
        _mark(
            "P1",
            "空表",
            f"有 {empty_n} 张表只有表头，下面是空的。",
            text,
            first_at,
        )
    ]
