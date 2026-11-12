"""电机控制器条款框架：词典 + 禁配表。

用来读懂 DPR 行业写法并对齐 120 项清单。不是标准答案库：
取值只来自这一份原文，禁止用行业常识补空。
选段检索只启用 retrieve=True 的整词别名（先开已验证条），
其余别名只进 prompt 认名，按黄格再开检索。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 选段检索已开通的清单关键子串（不是 120 条全开）
_RETRIEVE_KEYS = frozenset({"耐电压"})
_VALUEISH = frozenset({"kg", "years", "µF", "uF", "@14V"})


@dataclass(frozen=True)
class ClauseFrame:
    seq: int
    name: str
    aliases: tuple[str, ...]
    reject_patterns: tuple[str, ...]
    conflict: str
    retrieve: bool
    split_harm: str = ""
    retrieve_aliases: tuple[str, ...] = ()
    weak_aliases: tuple[str, ...] = ()
    unit_cues: tuple[str, ...] = ()


def _json_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    projects = here.parents[1]  # …/电子电器项目
    return [
        here / "templates" / "clause_lexicon.json",
        here.parent / "docs" / "clause_lexicon.json",
        here.parents[2] / "docs" / "clause_lexicon.json",
        projects / "electrical-krow" / "docs" / "clause_lexicon.json",
    ]


@lru_cache(maxsize=1)
def _load_frames() -> tuple[ClauseFrame, ...]:
    path = next((p for p in _json_candidates() if p.is_file()), None)
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
        aliases = tuple(
            str(item).strip()
            for item in (raw.get("aliases") or ())
            if str(item).strip()
        )
        retrieve_aliases = tuple(
            str(item).strip()
            for item in (raw.get("retrieve_aliases") or ())
            if str(item).strip()
        )
        frames.append(
            ClauseFrame(
                seq=seq,
                name=name,
                aliases=aliases,
                weak_aliases=tuple(
                    str(item).strip()
                    for item in (raw.get("weak_aliases") or ())
                    if str(item).strip()
                ),
                unit_cues=tuple(
                    str(item).strip()
                    for item in (raw.get("unit_cues") or ())
                    if str(item).strip()
                ),
                retrieve_aliases=retrieve_aliases,
                reject_patterns=tuple(
                    str(item) for item in (raw.get("reject_patterns") or ()) if item
                ),
                conflict=str(raw.get("conflict") or "").strip(),
                retrieve=bool(raw.get("retrieve")),
                split_harm=str(raw.get("split_harm") or "").strip(),
            )
        )
    return tuple(frames)


def FRAMES() -> tuple[ClauseFrame, ...]:
    return _load_frames()


def frame_for_seq(seq: int) -> ClauseFrame | None:
    try:
        key = int(seq)
    except (TypeError, ValueError):
        return None
    for frame in _load_frames():
        if frame.seq == key:
            return frame
    return None


def frames_for_name(name: str) -> tuple[ClauseFrame, ...]:
    text = (name or "").strip()
    return tuple(frame for frame in _load_frames() if frame.name == text)


def aliases_for_seq(seq: int, name: str = "") -> tuple[str, ...]:
    frame = frame_for_seq(seq)
    if frame is not None:
        return frame.aliases
    found = frames_for_name(name)
    return found[0].aliases if found else ()


def weak_aliases_for_seq(seq: int) -> tuple[str, ...]:
    """弱别名：整词但多条目共享（#73/#101 重量、#74/#102 防腐）。只用来找段和认条，不计分填值。"""
    frame = frame_for_seq(seq)
    return tuple(frame.weak_aliases) if frame is not None else ()


def unit_cues_for_seq(seq: int) -> tuple[str, ...]:
    frame = frame_for_seq(seq)
    return tuple(frame.unit_cues) if frame is not None else ()


def retrieve_enabled_for_name(name: str) -> bool:
    text = name or ""
    return any(key in text for key in _RETRIEVE_KEYS)


def retrieve_aliases_for_name(name: str) -> tuple[str, ...]:
    """选段用的整词别名；未开通检索的条目返回空。"""
    if not retrieve_enabled_for_name(name):
        return ()
    out: list[str] = []
    text = name or ""
    for frame in _load_frames():
        if frame.retrieve and any(
            key in text and key in frame.name for key in _RETRIEVE_KEYS
        ):
            out.extend(frame.retrieve_aliases or frame.aliases)
    return tuple(dict.fromkeys(out))


def conflict_for_name(name: str) -> str:
    text = name or ""
    if "升压纹波" in text:
        return "boost_ripple"
    for frame in _load_frames():
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
    for frame in _load_frames():
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
        if not alias or alias in _VALUEISH:
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
    shown = prompt_aliases(aliases or aliases_for_seq(seq, name))[:4]
    label = f"{seq}.{name}"
    if shown:
        return f"{label}（规格常见：{' / '.join(shown)}）"
    return label
