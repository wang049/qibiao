"""电机控制器条款框架：词典 + 禁配表。

用来读懂 DPR 行业写法并对齐 120 项。不是标准答案库：
取值只来自这一份原文，禁止用行业常识补空。
选段检索只启用 retrieve=True 的整词别名（先开已验证条），
强别名进 prompt 认名；弱别名需判别词，不进选段、不进认条提示。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 选段检索已开通的清单关键子串（不是 120 条全开）
RETRIEVE_KEYS = frozenset({"耐电压"})
_VALUEISH = frozenset(
    {
        "kg",
        "years",
        "µF",
        "uF",
        "@14V",
        "Vpp",
        "Vp-p",
        "vpp",
        "Cy",
        "Iq",
        "Apk",
        "Arms",
        "ΔP",
        "dP",
        "PSD",
        "Grms",
        "Tamb",
        "Tstg",
        "Tvj",
        "Ploss",
        "Mohm",
        "MΩ",
    }
)
_PROMPT_SKIP = frozenset(
    {
        "击穿",
        "无击穿",
        "闪络",
        "漏电流",
        "breakdown",
        "flashover",
        "leakage current",
        "打耐压",
        "耐压值",
        "耐压要求",
    }
)
_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent


@dataclass(frozen=True)
class ClauseFrame:
    seq: int
    name: str
    aliases: tuple[str, ...]
    reject_patterns: tuple[str, ...]
    conflict: str
    retrieve: bool
    split_harm: str = ""
    weak_aliases: tuple[str, ...] = ()
    retrieve_aliases: tuple[str, ...] = ()
    gloss: str = ""
    unit_cues: tuple[str, ...] = ()
    unverified: tuple[str, ...] = ()


def lexicon_json_path() -> Path | None:
    override = (os.environ.get("SPEC_SHEET_CLAUSE_LEXICON") or "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    candidates = [
        _PROJECT_ROOT / "docs" / "clause_lexicon.json",
        Path.cwd() / "docs" / "clause_lexicon.json",
        _PROJECT_ROOT.parent / "electrical" / "electrical" / "templates" / "clause_lexicon.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _tuple_field(raw: dict, *keys: str) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        for item in raw.get(key) or ():
            text = str(item).strip()
            if text:
                values.append(text)
    return tuple(dict.fromkeys(values))


@lru_cache(maxsize=1)
def load_frames() -> tuple[ClauseFrame, ...]:
    path = lexicon_json_path()
    if path is None:
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    frames: list[ClauseFrame] = []
    for raw in payload.get("frames") or []:
        try:
            seq = int(raw["seq"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        aliases = _tuple_field(raw, "aliases")
        retrieve_aliases = _tuple_field(raw, "retrieve_aliases")
        frames.append(
            ClauseFrame(
                seq=seq,
                name=name,
                aliases=aliases,
                weak_aliases=_tuple_field(raw, "weak_aliases"),
                retrieve_aliases=retrieve_aliases,
                reject_patterns=_tuple_field(raw, "reject_patterns"),
                conflict=str(raw.get("conflict") or "").strip(),
                retrieve=bool(raw.get("retrieve")),
                split_harm=str(raw.get("split_harm") or "").strip(),
                gloss=str(raw.get("gloss") or "").strip(),
                unit_cues=_tuple_field(raw, "unit_cues"),
                unverified=_tuple_field(raw, "unverified"),
            )
        )
    return tuple(frames)


def frame_for_seq(seq: int) -> ClauseFrame | None:
    try:
        key = int(seq)
    except (TypeError, ValueError):
        return None
    for frame in load_frames():
        if frame.seq == key:
            return frame
    return None


def frames_for_name(name: str) -> tuple[ClauseFrame, ...]:
    text = (name or "").strip()
    return tuple(frame for frame in load_frames() if frame.name == text)


def aliases_for_seq(seq: int, name: str = "") -> tuple[str, ...]:
    """强别名：进 prompt。弱别名不算。"""
    frame = frame_for_seq(seq)
    if frame is not None:
        return frame.aliases
    found = frames_for_name(name)
    return found[0].aliases if found else ()


def retrieve_enabled_for_name(name: str) -> bool:
    text = name or ""
    return any(key in text for key in RETRIEVE_KEYS)


def retrieve_aliases_for_name(name: str) -> tuple[str, ...]:
    """选段用的整词别名；未开通检索的条目返回空。"""
    if not retrieve_enabled_for_name(name):
        return ()
    out: list[str] = []
    text = name or ""
    for frame in load_frames():
        if not frame.retrieve:
            continue
        if not any(key in text and key in frame.name for key in RETRIEVE_KEYS):
            continue
        out.extend(frame.retrieve_aliases or frame.aliases)
    return tuple(dict.fromkeys(out))


def conflict_for_name(name: str) -> str:
    text = name or ""
    if "升压纹波" in text:
        return "boost_ripple"
    for frame in load_frames():
        if frame.name == text and frame.conflict:
            return frame.conflict
    if "P1" in text and ("反电动势" in text or "Back EMF" in text):
        return "p1_back_emf"
    if "P3" in text and ("反电动势" in text or "Back EMF" in text):
        return "p3_back_emf"
    if "高压安全" in text and "纹波" in text:
        return "hv_safety_ripple"
    if "纹波" in text:
        return "bus_ripple"
    return ""


def reject_patterns_for_name(name: str) -> tuple[str, ...]:
    text = name or ""
    out: list[str] = []
    for frame in load_frames():
        if not frame.reject_patterns:
            continue
        if frame.name == text or frame.name in text:
            out.extend(frame.reject_patterns)
        elif "耐电压" in text and "耐电压" in frame.name:
            out.extend(frame.reject_patterns)
    return tuple(dict.fromkeys(out))


def prompt_aliases(aliases: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """进模型认名；丢掉像取值的片段，避免抄进格子。"""
    out: list[str] = []
    for raw in aliases:
        alias = (raw or "").strip()
        if not alias or alias in _VALUEISH or alias in _PROMPT_SKIP:
            continue
        if re.search(r"\d", alias):
            if re.search(
                r"IP\s*X|IP\d|ISO\s*\d|J\d+|ASIL|CAL\s*\d|CAN|CISPR|UL\s*\d",
                alias,
                re.I,
            ):
                out.append(alias)
            continue
        out.append(alias)
    return tuple(dict.fromkeys(out))


def format_prompt_field(seq: int, name: str, aliases: tuple[str, ...] = ()) -> str:
    """14.高压安全-耐电压（规格常见：耐压 / hipot / 工频耐压）"""
    shown = [
        alias
        for alias in prompt_aliases(aliases or aliases_for_seq(seq, name))
        if alias not in (name or "")
    ]
    zh = [alias for alias in shown if re.search(r"[\u4e00-\u9fff]", alias)]
    en = [alias for alias in shown if alias not in zh]
    zh_sorted = sorted(zh, key=lambda item: (len(item), item))
    en_sorted = sorted(en, key=lambda item: (len(item), item.lower()))
    mixed = list(dict.fromkeys([*zh_sorted[:3], *en_sorted[:2]]))[:5]
    label = f"{seq}.{name}"
    if mixed:
        return f"{label}（规格常见：{' / '.join(mixed)}）"
    return label
