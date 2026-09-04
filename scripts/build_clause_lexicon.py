# -*- coding: utf-8 -*-
"""把扩展版 YAML 收成出表用的 clause_lexicon.json。

YAML 是词条真源；JSON 给 electrical_krow.clause_lexicon 读。
选段检索仍只开耐电压，弱别名不进检索、不进认条提示。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("需要 PyYAML：pip install pyyaml\n")
    raise

ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = ROOT / "docs" / "clause_lexicon.yaml"
JSON_PATH = ROOT / "docs" / "clause_lexicon.json"

# 同名可共享抽出值；口径不同的不要放进同一组。
CONFLICT_BY_SEQ = {
    8: "bus_ripple",
    12: "hv_safety_ripple",
    70: "boost_ripple",
    11: "back_emf",
    37: "p1_back_emf",
    54: "p3_back_emf",
    13: "insulation",
    18: "insulation",
    14: "dielectric",
    19: "dielectric",
    28: "p1_peak_power",
    29: "p1_peak_power_duration",
    45: "p3_peak_power",
    46: "p3_peak_power_duration",
    71: "coolant_drop",
    119: "coolant_drop",
    72: "heat_dissipation",
    120: "heat_dissipation",
    73: "weight_controller",
    101: "weight_requirement",
    74: "corrosion_class",
    102: "corrosion_std",
    75: "vibration",
    103: "vibration",
    80: "cybersecurity",
    118: "cybersecurity",
}

RETRIEVE_SEQS = frozenset({14, 19})
RETRIEVE_CORE = ("耐压", "hipot", "dielectric", "工频耐压", "直流耐压")
RETRIEVE_SKIP = {
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
    "绝缘强度",
    "电气强度",
    "electric strength",
    "高压绝缘测试",
}

DIELECTRIC_REJECT = (
    "continuous supply",
    "withstand continuous",
    "持续供电",
    "持续耐受",
    "on the HVDC bus without",
    r"maximum 500\s*V on the HVDC",
    "器件耐压",
    "耐压等级",
    "耐压选型",
    "绝缘电压等级",
)

STATIC_REJECT = (
    "电容漏电流",
    "DC capacitor",
    "Under 1",
    "Rated Voltage",
    "板级 Dark Current",
    "耐压漏电流",
)


def _clean_alias(raw: object) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\[(?:原字典|清单)\]\s*", "", text).strip()
    return text


def _aliases(values: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        alias = _clean_alias(raw)
        if not alias:
            continue
        key = alias.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(alias)
    return out


def _patterns_from_exclude(items: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        text = str(raw or "").strip()
        if not text:
            continue
        text = re.sub(r"（→[^）]*）", "", text)
        text = re.sub(r"（[^）]{2,40}）", "", text)
        text = re.sub(r"\([^)]{2,40}\)", "", text)
        text = text.strip(" ；;，,")
        for part in re.split(r"[／/]", text):
            part = part.strip()
            if len(part) < 2 or len(part) > 40:
                continue
            if re.fullmatch(r"#?\d+(?:[#\s,，、]*\d+)*", part):
                continue
            if re.fullmatch(r"(?:k?W|k?Hz|V|A|s|ms|nm|rpm)", part, re.I):
                continue
            if part.endswith("语境") and len(part) <= 6:
                continue
            key = part.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(part)
    return out


def _retrieve_aliases(seq: int, strong: list[str]) -> list[str]:
    if seq not in RETRIEVE_SEQS:
        return []
    skip = {item.lower() for item in RETRIEVE_SKIP}
    out: list[str] = []
    for alias in strong:
        if alias.lower() in skip or alias in RETRIEVE_SKIP:
            continue
        if len(alias) <= 2 and alias != "耐压":
            continue
        out.append(alias)
    have = {item.lower() for item in out}
    for core in RETRIEVE_CORE:
        if core.lower() not in have:
            out.append(core)
            have.add(core.lower())
    return out


def _conflict(seq: int, name: str) -> str:
    if seq in CONFLICT_BY_SEQ:
        return CONFLICT_BY_SEQ[seq]
    if "升压纹波" in name:
        return "boost_ripple"
    return ""


def _reject_patterns(seq: int, exclude: object) -> list[str]:
    out = _patterns_from_exclude(exclude)
    extra: tuple[str, ...] = ()
    if seq in {14, 19}:
        extra = DIELECTRIC_REJECT
    elif seq == 22:
        extra = STATIC_REJECT
    seen = {item.lower() for item in out}
    for item in extra:
        if item.lower() not in seen:
            out.append(item)
            seen.add(item.lower())
    return out


def _split_harm(item: dict) -> str:
    notes = [str(n).strip() for n in (item.get("notes") or []) if str(n).strip()]
    if notes:
        return notes[0]
    exclude = [str(x).strip() for x in (item.get("exclude") or []) if str(x).strip()]
    return "；".join(exclude[:2])


def build_frames(payload: dict) -> list[dict]:
    frames: list[dict] = []
    for item in payload.get("items") or []:
        seq = int(item["id"])
        name = str(item.get("name") or "").strip()
        strong = _aliases(
            list(item.get("zh_strong") or []) + list(item.get("en_strong") or [])
        )
        weak = _aliases(
            list(item.get("zh_weak") or []) + list(item.get("en_weak") or [])
        )
        frames.append(
            {
                "seq": seq,
                "name": name,
                "group": str(item.get("group") or "").strip(),
                "gloss": str(item.get("gloss") or "").strip(),
                "aliases": strong,
                "weak_aliases": weak,
                "unit_cues": [
                    str(x).strip() for x in (item.get("cues") or []) if str(x).strip()
                ],
                "exclude": [
                    str(x).strip() for x in (item.get("exclude") or []) if str(x).strip()
                ],
                "unverified": [
                    str(x).strip()
                    for x in (item.get("unverified") or [])
                    if str(x).strip()
                ],
                "std": [
                    str(x).strip() for x in (item.get("std") or []) if str(x).strip()
                ],
                "see": [int(x) for x in (item.get("see") or [])],
                "notes": [
                    str(x).strip() for x in (item.get("notes") or []) if str(x).strip()
                ],
                "reject_patterns": _reject_patterns(seq, item.get("exclude")),
                "retrieve_aliases": _retrieve_aliases(seq, strong),
                "split_harm": _split_harm(item),
                "retrieve": seq in RETRIEVE_SEQS,
                "conflict": _conflict(seq, name),
            }
        )
    frames.sort(key=lambda row: row["seq"])
    return frames


def main() -> None:
    """兼容旧命令；完整发布（索引、图谱、快照）见 publish_knowledge.py。"""
    spec = importlib.util.spec_from_file_location(
        "publish_knowledge",
        Path(__file__).with_name("publish_knowledge.py"),
    )
    if spec is None or spec.loader is None:
        raise SystemExit("找不到 scripts/publish_knowledge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.publish()


if __name__ == "__main__":
    main()
