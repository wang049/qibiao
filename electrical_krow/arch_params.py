"""参数清单：把拆条结果里「参数 → 取值」汇成一张表，并标出同一参数在不同段落取值不一致的地方。

取值一律是当份原文里的字串：表格行取要求格原文；正文条目由模型指出「哪个字串是哪个参数的值」，
程序再核对该字串确实在该条原文里，对不上的丢弃。模型只负责起名和把同义的参数名归到一起，不产生取值。
没有模型（离线、调用失败）时退回规则：正文参数名用数前的引导词，归并按去标点小写的原名。
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from electrical_krow.arch_contrast import _UNIT, COLUMNS, _QUANTITY, _compact
from electrical_krow.arch_contrast import quantities as _lead_quantities

Ask = Callable[[list[dict[str, str]]], str]

SHEET_PARAMS = "参数清单"
PARAM_COLUMNS = (
    "参数序号",
    "归并名",
    "参数（原文名）",
    "取值（原文）",
    "适用条件",
    "一致性",
    "同一参数其他取值",
    "对象",
    "文件",
    "PDF页码",
    "章节",
    "来源条目",
    "来源",
    "状态",
    "备注",
)
CONSIST_SINGLE = "唯一"
CONSIST_SAME = "多处一致"
CONSIST_DIFF = "多处不一致·请审核"
CONSIST_COND = "多处·条件不同"
SOURCE_TABLE = "表格行"
SOURCE_TABLE_OCR = "图片表格·OCR"
SOURCE_RULE = "规则拆分"
SOURCE_MODEL = "模型指认"
_BATCH = 10
_SHORT_VALUE = 60  # 表格要求格超过这个长度的是整句要求，不算参数取值

_COL = {name: index for index, name in enumerate(COLUMNS)}

_NAME_PROMPT = (
    "你是需求文件参数提取助手。对给出的每条原文（有的是正文句子，有的是表格某一格的内容，括号里注明了表格栏目），列出其中带数值或明确取值的参数。"
    "一格或一句里有几个不同的量就列几个参数（如可靠度、保修时间、温度各算一个）；"
    "同一个量的范围、或原文写在一起的一组数（如「15 years / 300,000 km」的耐久寿命）算一个参数，取值保留整组原字串。"
    "每个参数输出三项：参数（不超过12个字的中文名，说明这个数是什么量，不要重复栏目名）、"
    "取值（必须是该条原文里连续的原字串，一个字符都不改，带上单位、范围符号和↑↓等后缀）、"
    "条件（原文里紧挨着的适用条件原字串，没有就留空字符串）。"
    "不要换算、不要补充原文没有的信息；没有数值的条目返回空数组。"
    "只输出 JSON 数组，每个元素形如 {\"序号\": 12, \"参数\": [{\"参数\": \"…\", \"取值\": \"…\", \"条件\": \"…\"}]}。"
)
_CANON_PROMPT = (
    "下面是同一份需求文件里出现的参数名（有的是表格栏目名，几级栏目用「 / 」连；有的是从条文里提取的中文名）。"
    "把指同一个物理量或同一项要求的名字归到同一个归并名下，归并名用不超过10个字的中文；"
    "拿不准是否相同的不要合并，各自给归并名即可。不要漏掉任何一个原名。"
    "只输出一个 JSON 对象：{原名: 归并名}。"
)


@dataclass
class Param:
    name: str
    value: str
    cond: str
    obj: str
    file: str
    page: int
    section: str
    row_seq: int
    source: str
    canon: str = ""
    consistency: str = ""
    others: str = ""
    note: str = ""


@dataclass
class ParamResult:
    params: list[Param]
    conflicts: int
    model_used: bool
    notes: list[str] = field(default_factory=list)
    conflict_rows: dict[int, str] = field(default_factory=dict)  # 条目序号 → 备注


def _norm_value(value: str) -> str:
    text = re.sub(r"\s+", "", value or "").lower()
    return text.rstrip(".。;；,，")


def _norm_name(name: str) -> str:
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", (name or "").lower())
    words = [w for w in text.split() if w not in {"the", "of", "and", "for", "a", "an", "to", "in", "requirement", "requirements", "spec", "specification"}]
    return " ".join(words) or _compact(name).lower()


def _no_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _json_block(blob: str, opener: str, closer: str):
    text = (blob or "").strip()
    start, end = text.find(opener), text.rfind(closer)
    if start < 0 or end < 0 or end <= start:
        raise ValueError("模型回包里没有 JSON")
    return json.loads(text[start : end + 1])


@dataclass
class Target:
    """要请模型（或规则）指认「哪个数是哪个参数的值」的一段原文。表格里一格写了好几个数的也算。"""

    seq: int
    text: str  # 给模型看的原文：正文整条，表格行是那一格
    qty: str  # 规则兜底用的「数值与单位」列
    base: str  # 表格行的栏目名；正文为空
    row: list[object]


def _param_from(row: list[object], name: str, value: str, cond: str, source: str) -> Param:
    return Param(name, value, cond, str(row[_COL["对象"]] or ""), str(row[_COL["文件"]] or ""), int(row[_COL["PDF页码"]] or 0),
                 str(row[_COL["章节"]] or ""), int(row[_COL["序号"]] or 0), source)


def split_rows(rows: list[list[object]]) -> tuple[list[Param], list[Target]]:
    """表格行：一格只有一个数（或没有数但很短）的直接成参数；一格里几个数的交给指认。正文：数值列非空的交给指认。"""
    # 同一页同一栏目名下有好几行、值里又没有数的，是清单表（DESIGN：十项设计方法），不是参数
    repeats: dict[tuple[str, int, str], int] = {}
    for row in rows:
        item = str(row[_COL["项目（表格栏目）"]] or "").strip()
        if item:
            key = (str(row[_COL["文件"]] or ""), int(row[_COL["PDF页码"]] or 0), item)
            repeats[key] = repeats.get(key, 0) + 1
    simple: list[Param] = []
    targets: list[Target] = []
    for row in rows:
        if str(row[_COL["章节"]] or "") in {"", "封面", "目录"}:
            continue  # 封面、目录、还没进正文的修订页不算
        item = str(row[_COL["项目（表格栏目）"]] or "").strip()
        value = str(row[_COL["数值与单位"]] or "").strip()
        text = str(row[_COL["原文摘录"]] or "")
        if not value or text.startswith("本页"):
            continue
        seq = int(row[_COL["序号"]] or 0)
        if not item:
            targets.append(Target(seq, _compact(text), value, "", row))
            continue
        quantities = list(_QUANTITY.finditer(value))
        if len(quantities) >= 2:
            targets.append(Target(seq, value, _lead_quantities(value), item, row))  # 规则兜底用「引导词 + 数」的分段
            continue
        if not quantities and len(value) > _SHORT_VALUE:
            continue  # 整句要求，不是参数取值
        if not quantities and repeats[(str(row[_COL["文件"]] or ""), int(row[_COL["PDF页码"]] or 0), item)] >= 2:
            continue
        source = SOURCE_TABLE_OCR if "OCR" in str(row[_COL["备注"]] or "") else SOURCE_TABLE
        simple.append(_param_from(row, item, value, str(row[_COL["适用条件（原文括注）"]] or ""), source))
    return simple, targets


def rule_split(targets: list[Target]) -> list[Param]:
    """没有模型时：「数值与单位」列按「；」分段，每段「引导词 + 数」算一条，参数名就是引导词（表格行前面带栏目名）。
    一段里写在一起的几个数（15 years / 300,000 km）不拆；没有引导词的段沿用上一段的名字。"""
    out: list[Param] = []
    for target in targets:
        last = "（未命名）"
        for piece in target.qty.split("；"):
            piece = piece.strip()
            match = _QUANTITY.search(piece)
            if not match:
                continue
            lead = piece[: match.start()].strip(" ,:：(（•") or last
            last = lead
            name = f"{target.base} / {lead}" if target.base else lead
            out.append(_param_from(target.row, name, piece[match.start():].strip(" )）"), "", SOURCE_RULE))
    return out


def model_split(targets: list[Target], ask: Ask) -> tuple[list[Param], list[str]]:
    """让模型指认每段里每个数属于哪个参数；取值字串必须原样出现在该段原文里，否则丢弃。"""
    by_seq = {target.seq: target for target in targets}
    out: list[Param] = []
    notes: list[str] = []
    dropped = 0
    dropped_examples: list[str] = []
    for start in range(0, len(targets), _BATCH):
        batch = targets[start : start + _BATCH]
        user = "\n\n".join(
            f"序号 {t.seq}" + (f"（表格栏目：{t.base}）" if t.base else "") + f"：\n{t.text}" for t in batch
        )
        try:
            data = _json_block(ask([{"role": "system", "content": _NAME_PROMPT}, {"role": "user", "content": user}]), "[", "]")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"第 {start // _BATCH + 1} 批参数指认模型未返回可用结果（{str(exc)[:60]}），该批按规则命名")
            out.extend(rule_split(batch))
            continue
        answered: set[int] = set()
        for item in data if isinstance(data, list) else []:
            try:
                seq = int(item.get("序号"))
            except (AttributeError, TypeError, ValueError):
                continue
            target = by_seq.get(seq)
            if target is None:
                continue
            answered.add(seq)
            text_key = _no_space(target.text)
            for entry in item.get("参数") or []:
                if not isinstance(entry, dict):
                    continue
                value = _compact(str(entry.get("取值") or ""))
                name = _compact(str(entry.get("参数") or ""))
                cond = _compact(str(entry.get("条件") or ""))
                if not value or not name or _no_space(value) not in text_key:
                    dropped += 1
                    if len(dropped_examples) < 5 and value:
                        dropped_examples.append(f"第 {target.row[_COL['PDF页码']]} 页「{name or '?'}」：{value[:30]}")
                    continue
                if cond and _no_space(cond) not in text_key:
                    cond = ""
                full = f"{target.base} / {name}" if target.base else name
                out.append(_param_from(target.row, full, value, cond, SOURCE_MODEL))
        for target in batch:
            if target.seq not in answered:
                out.extend(rule_split([target]))
    if dropped:
        notes.append(f"模型指认的取值有 {dropped} 处在原文里找不到原字串，已丢弃（如 " + "；".join(dropped_examples) + "）")
    return out, notes


def canonicalize(params: list[Param], ask: Ask | None) -> tuple[bool, list[str]]:
    """给每个参数一个归并名。先按去标点小写的原名合并，再请模型把同义名归到一起；模型没给的保留规则名。"""
    for param in params:
        param.canon = _norm_name(param.name)
    names = sorted({param.name for param in params})
    if ask is None or not names:
        return False, []
    mapping: dict[str, str] = {}
    notes: list[str] = []
    step = 120
    for start in range(0, len(names), step):
        chunk = names[start : start + step]
        try:
            data = _json_block(ask([{"role": "system", "content": _CANON_PROMPT}, {"role": "user", "content": "\n".join(chunk)}]), "{", "}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"参数归并模型未返回可用结果（{str(exc)[:60]}），这部分按原名归并")
            continue
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(key, str) and isinstance(val, str) and val.strip():
                    mapping[key.strip()] = _compact(val)
    if not mapping:
        return False, notes
    for param in params:
        canon = mapping.get(param.name)
        if canon:
            param.canon = canon
    return True, notes


def _value_key(value: str) -> str:
    """比取值时，两边都带数就只比数和单位（「…(15 years / 300,000 Km)」和「15 years/ 300,000km」算同一个）；没有数才比整句。"""
    quantities = sorted(_norm_value(m.group(0)) for m in _QUANTITY.finditer(value or ""))
    return "|".join(quantities) if quantities else _norm_value(value)


_ROMAN_DIGITS = str.maketrans({
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
    "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X",
    "ⅰ": "I", "ⅱ": "II", "ⅲ": "III", "ⅳ": "IV", "ⅴ": "V",
})


def _qty_pairs(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for match in _QUANTITY.finditer(value or ""):
        pairs.append((_unit_class(match.group(0)), _norm_value(match.group(0))))
    return pairs


def _citation_key(value: str) -> str:
    """标准号和罗马数字区段：R10.05/06 与分开写的 R10.05、R10.06 相同，Ⅳ 与 IV 相同。"""
    text = (value or "").translate(_ROMAN_DIGITS).lower()
    text = re.sub(
        r"([a-z]*\d+\.)(\d+)/(\d+)",
        lambda match: f"{match.group(1)}{match.group(2)} {match.group(1)}{match.group(3)}",
        text,
    )
    tokens = sorted(set(re.findall(r"[a-z]+\d+(?:\.\d+)?|\d+(?:\.\d+)?|[a-z]{2,}", text)))
    return " ".join(tokens)


def _values_compatible(left: str, right: str) -> bool:
    """同一取值的两种写法。短的只少写了另一种单位（15 years 对 15 years / 300,000 km）时不算冲突。"""
    if _value_key(left) == _value_key(right):
        return True
    if re.search(r"cispr|ece|\biso\b|region", f"{left} {right}", re.I):
        key_left, key_right = _citation_key(left), _citation_key(right)
        if key_left and key_left == key_right:
            return True
    pairs_left, pairs_right = _qty_pairs(left), _qty_pairs(right)
    if not pairs_left or not pairs_right:
        return False
    short, long = (pairs_left, pairs_right) if len(pairs_left) <= len(pairs_right) else (pairs_right, pairs_left)
    by_unit: dict[str, set[str]] = {}
    for unit, norm in long:
        by_unit.setdefault(unit, set()).add(norm)
    for unit, norm in short:
        found = by_unit.get(unit) or set()
        if norm not in found or len(found) > 1:
            return False
    return True


_UNIT_RE = re.compile(r"(" + _UNIT + r")$")
_UNIT_ALIAS = {"℃": "°c", "degc": "°c", "deg": "°", "hrs": "h", "hr": "h", "hours": "h", "hour": "h", "hs": "h", "yrs": "year", "yr": "year", "years": "year",
               "minutes": "min", "minute": "min", "sec": "s", "ohm": "ω", "times": "cycle", "cycles": "cycle", "vdc": "v", "vac": "v", "adc": "a", "ac": "a"}


def _unit_class(value: str) -> str:
    """取值里第一个数的单位（去掉 k/m/M 等倍率、合并别名）。同一归并名下单位不同的，不是同一个量，不作比较。"""
    match = _QUANTITY.search(value or "")
    if not match:
        return ""
    unit = _UNIT_RE.search(match.group(0).replace(" ", ""))
    if not unit:
        return ""
    text = unit.group(1).lower()
    text = _UNIT_ALIAS.get(text, text)
    if len(text) > 1 and text[0] in "kmµμug" and re.fullmatch(_UNIT, text[1:], flags=re.IGNORECASE):
        text = text[1:]
    return _UNIT_ALIAS.get(text, text)


def check_consistency(params: list[Param]) -> int:
    """同一归并名、同一单位下取值不同的标「多处不一致·请审核」，并把其他处的取值列出来。
    适用条件不同的（不同标准、不同工况）不算冲突，标「多处·条件不同」。
    单位不同的（「输出电流 2%」是精度、「输出电流 180A」是电流）不是同一个量，各算各的。"""
    groups: dict[tuple[str, str], list[Param]] = {}
    for param in params:
        groups.setdefault((param.canon, _unit_class(param.value)), []).append(param)
    conflicts = 0
    for members in groups.values():
        if len(members) == 1:
            members[0].consistency = CONSIST_SINGLE
            continue
        for param in members:
            # 同一条里列出的几个值（如一格里按工况分列）不算「别处」，不互相比
            others = [p for p in members if p is not param and p.row_seq != param.row_seq]
            if not others:
                param.consistency = CONSIST_SINGLE
                continue
            same_value = [p for p in others if _values_compatible(p.value, param.value)]
            differing = [p for p in others if p not in same_value and _norm_value(p.cond) == _norm_value(param.cond)]
            other_cond = [p for p in others if p not in same_value and p not in differing]
            if differing:
                param.consistency = CONSIST_DIFF
                param.others = "；".join(f"第 {p.page} 页「{p.name}」：{p.value}" for p in differing)
                conflicts += 1
            elif same_value:
                param.consistency = CONSIST_SAME
                param.others = "；".join(f"第 {p.page} 页「{p.name}」" for p in same_value)
            else:
                param.consistency = CONSIST_COND
                param.others = "；".join(f"第 {p.page} 页「{p.name}」（{p.cond[:30]}）：{p.value}" for p in other_cond)
    return conflicts


def collect_params(rows: list[list[object]], ask: Ask | None) -> ParamResult:
    params, targets = split_rows(rows)
    notes: list[str] = []
    model_used = False
    if ask is None:
        params.extend(rule_split(targets))
    else:
        split, split_notes = model_split(targets, ask)
        params.extend(split)
        notes.extend(split_notes)
        model_used = any(p.source == SOURCE_MODEL for p in split)
    canon_used, canon_notes = canonicalize(params, ask)
    notes.extend(canon_notes)
    model_used = model_used or canon_used
    params.sort(key=lambda p: (p.file, p.page, p.row_seq))
    conflicts = check_consistency(params)
    conflict_rows: dict[int, str] = {}
    for param in params:
        if param.consistency == CONSIST_DIFF:
            hint = f"「{param.name}」此处 {param.value}，与别处不一致：{param.others}"
            conflict_rows[param.row_seq] = "；".join(filter(None, (conflict_rows.get(param.row_seq, ""), hint)))
    return ParamResult(params, conflicts, model_used, notes, conflict_rows)


def param_rows(result: ParamResult) -> list[list[object]]:
    out: list[list[object]] = []
    for index, p in enumerate(result.params, start=1):
        out.append([index, p.canon, p.name, p.value, p.cond, p.consistency, p.others, p.obj, p.file, p.page, p.section, p.row_seq, p.source, "待确认", p.note])
    return out
