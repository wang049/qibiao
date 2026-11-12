"""出表字段以客户《电机控制需求清单》为准。"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

# 系统检索结论（自动）
STATUS_FOUND = "已检索到"
STATUS_MISS = "未检索到"
STATUS_PARTIAL = "局部对应/需人工复核"
# 人工核对结论
STATUS_PASS = "通过"
STATUS_FIX = "需修改"
STATUS_NA = "不适用"

RETRIEVAL_STATUSES = frozenset({STATUS_FOUND, STATUS_MISS, STATUS_PARTIAL})
HUMAN_STATUSES = frozenset({STATUS_PASS, STATUS_FIX, STATUS_NA})
ALL_REVIEW_STATUSES = RETRIEVAL_STATUSES | HUMAN_STATUSES

# 抽出值列里的占位文案（读回时还原为空值）
VALUE_MARKERS = frozenset({STATUS_MISS, STATUS_PARTIAL, "未抽出", "未知/需人工复核"})


@dataclass(frozen=True)
class FieldSpec:
    seq: int
    name: str
    hint: str = ""
    impact: str = ""
    example: str = ""
    aliases: tuple[str, ...] = ()
    weak_aliases: tuple[str, ...] = ()
    unit_cues: tuple[str, ...] = ()


# 选段检索只开已验证整词别名，不要一次灌全部条目。
_RETRIEVE_KEYS = frozenset({"耐电压"})
_VALUEISH_ALIASES = frozenset({"kg", "years", "µF", "uF", "@14V"})
_NAME_STOP = frozenset({"是否", "包含", "要求", "指标", "范围", "功能", "设计", "是否包含"})
# 源表重复项已从出表删除。知识库仍用源表序号；核对表需求序号改为 1–116。
# #18=#13 绝缘电阻；#19=#14 耐电压；#26=#15 主动放电；#27=#16 被动放电。
DROPPED_SEQS = frozenset({18, 19, 26, 27})


def _lexicon_json_candidates() -> list[Path]:
    override = (os.environ.get("SPEC_SHEET_CLAUSE_LEXICON") or "").strip()
    here = Path(__file__).resolve().parent
    out: list[Path] = []
    if override:
        out.append(Path(override).expanduser())
    out.extend(
        [
            here / "templates" / "clause_lexicon.json",
            Path.cwd() / "docs" / "clause_lexicon.json",
            here.parent.parent / "docs" / "clause_lexicon.json",
            here.parent.parent / "electrical-krow" / "docs" / "clause_lexicon.json",
        ]
    )
    return out


def _lexicon_py_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        Path.cwd() / "electrical_krow" / "clause_lexicon.py",
        here.parent.parent / "electrical_krow" / "clause_lexicon.py",
        here.parent.parent / "electrical-krow" / "electrical_krow" / "clause_lexicon.py",
    ]


@lru_cache(maxsize=1)
def _lexicon_mod():
    for path in _lexicon_py_candidates():
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("_electrical_clause_lexicon", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(spec.name, None)
            continue
        return mod
    return None


@lru_cache(maxsize=1)
def _lexicon_rows() -> dict[int, tuple[str, ...]]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "load_frames"):
        return {frame.seq: tuple(frame.aliases) for frame in mod.load_frames()}
    path = next((p for p in _lexicon_json_candidates() if p.is_file()), None)
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[int, tuple[str, ...]] = {}
    for raw in payload.get("frames") or []:
        try:
            seq = int(raw["seq"])
        except (KeyError, TypeError, ValueError):
            continue
        aliases = tuple(
            str(item).strip()
            for item in (raw.get("aliases") or ())
            if str(item).strip()
        )
        rows[seq] = aliases
    return rows


def dropped_template_seqs() -> frozenset[int]:
    path = next((p for p in _lexicon_json_candidates() if p.is_file()), None)
    if path is None:
        return DROPPED_SEQS
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DROPPED_SEQS
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    raw = (meta or {}).get("dropped") or []
    if not raw:
        return DROPPED_SEQS
    try:
        return frozenset(int(x) for x in raw)
    except (TypeError, ValueError):
        return DROPPED_SEQS


def lexicon_knowledge_version() -> str:
    """条款词典 meta 里的知识库版本。electrical 不依赖工位知识库模块。"""
    path = next((p for p in _lexicon_json_candidates() if p.is_file()), None)
    if path is None:
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    meta = payload.get("meta") if isinstance(payload, dict) else {}
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("knowledge_version") or "").strip()


def aliases_for_seq(seq: int, name: str = "") -> tuple[str, ...]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "aliases_for_seq"):
        return tuple(mod.aliases_for_seq(seq, name))
    return _lexicon_rows().get(int(seq), ())


def weak_aliases_for_seq(seq: int) -> tuple[str, ...]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "weak_aliases_for_seq"):
        return tuple(mod.weak_aliases_for_seq(seq))
    return ()


def unit_cues_for_seq(seq: int) -> tuple[str, ...]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "unit_cues_for_seq"):
        return tuple(mod.unit_cues_for_seq(seq))
    return ()


def retrieve_enabled_for_name(name: str) -> bool:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "retrieve_enabled_for_name"):
        return bool(mod.retrieve_enabled_for_name(name))
    return any(key in (name or "") for key in _RETRIEVE_KEYS)


def retrieve_aliases_for_name(name: str) -> tuple[str, ...]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "retrieve_aliases_for_name"):
        return tuple(mod.retrieve_aliases_for_name(name))
    if not retrieve_enabled_for_name(name):
        return ()
    text = name or ""
    out: list[str] = []
    path = next((p for p in _lexicon_json_candidates() if p.is_file()), None)
    if path is None:
        # 与旧 _FIELD_ALIASES 对齐，避免词典文件缺失时认不到「耐压」
        if "耐电压" in text:
            return ("耐压", "withstand", "hipot", "dielectric", "工频耐压", "直流耐压")
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    for raw in payload.get("frames") or []:
        frame_name = str(raw.get("name") or "")
        if raw.get("retrieve") and "耐电压" in text and "耐电压" in frame_name:
            aliases = raw.get("retrieve_aliases") or raw.get("aliases") or ()
            out.extend(str(item).strip() for item in aliases if str(item).strip())
    return tuple(dict.fromkeys(out))


def conflict_for_name(name: str) -> str:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "conflict_for_name"):
        return str(mod.conflict_for_name(name) or "")
    text = name or ""
    if "升压纹波" in text:
        return "boost_ripple"
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
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "reject_patterns_for_name"):
        return tuple(mod.reject_patterns_for_name(name))
    if "耐电压" in (name or ""):
        return (
            r"continuous supply",
            r"withstand continuous",
            r"持续供电",
            r"持续耐受",
            r"on the HVDC bus without",
            r"maximum 500\s*V on the HVDC",
        )
    return ()


def prompt_aliases(aliases: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "prompt_aliases"):
        return tuple(mod.prompt_aliases(aliases))
    out: list[str] = []
    for raw in aliases:
        alias = (raw or "").strip()
        if not alias or alias in _VALUEISH_ALIASES:
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
    mod = _lexicon_mod()
    if mod is not None and hasattr(mod, "format_prompt_field"):
        return str(mod.format_prompt_field(seq, name, aliases or aliases_for_seq(seq, name)))
    shown = prompt_aliases(aliases or aliases_for_seq(seq, name))[:4]
    label = f"{seq}.{name}"
    if shown:
        return f"{label}（规格常见：{' / '.join(shown)}）"
    return label


def whole_name_tokens(name: str) -> list[str]:
    """清单名整词：三字及以上中文、英文代号。不用二字切「电压」「电流」。"""
    tokens = re.findall(r"[\u4e00-\u9fff]{3,}", name or "")
    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9+\-]{1,}", name or ""))
    return [tok for tok in tokens if tok not in _NAME_STOP]


@dataclass
class ExtractedCell:
    name: str
    seq: int = 0
    value: str = ""
    unit: str = ""
    page: str = ""
    excerpt: str = ""
    confidence: float = 0.0
    hint: str = ""
    impact: str = ""
    example: str = ""
    note: str = ""
    review_status: str = ""
    extra: bool = False
    clause: str = ""

    def needs_review(self) -> bool:
        status = (self.review_status or "").strip()
        if status in {STATUS_PASS, STATUS_NA}:
            return False
        if status in {STATUS_MISS, STATUS_PARTIAL, STATUS_FIX, STATUS_FOUND}:
            return True
        if not (self.value or "").strip():
            return True
        return self.confidence < 0.8


PENDING_RULING_PREFIX = "待专家口径："


def _note_for_status(note: str) -> str:
    """去掉「待专家口径：…」标注后的备注；标注不改变已检索到 / 未检索到 / 局部对应。"""
    text = (note or "").strip()
    idx = text.find(PENDING_RULING_PREFIX)
    if idx < 0:
        return text
    return text[:idx].rstrip("；; ").strip()


def finalize_retrieval_statuses(cells: list[ExtractedCell]) -> None:
    """按三类标准写入检索结论：已检索到 / 未检索到 / 局部对应需人工复核。"""
    for cell in cells:
        status = (cell.review_status or "").strip()
        if status in HUMAN_STATUSES:
            continue
        if status == STATUS_PARTIAL:
            # 规则已标局部对应，不得因置信度≥0.8 抬成已检索到。
            continue
        has_val = bool((cell.value or "").strip())
        # 「待专家口径：…」只是标注，不参与检索结论判定
        plain_note = _note_for_status(cell.note)
        has_note = bool(plain_note)
        method_note = plain_note.startswith("企标方法对照")
        if status == STATUS_MISS and not has_val:
            continue
        if has_val:
            if cell.confidence < 0.8 or has_note:
                cell.review_status = STATUS_PARTIAL
                if cell.confidence < 0.8 and not has_note:
                    low = "置信度偏低，请对照原文确认是否满足需求条目"
                    pending = (cell.note or "").strip()
                    cell.note = f"{low}；{pending}" if pending else low
            else:
                cell.review_status = STATUS_FOUND
        elif method_note:
            cell.review_status = STATUS_MISS
        elif has_note:
            cell.review_status = STATUS_PARTIAL
        else:
            cell.review_status = STATUS_MISS


def template_path() -> Path:
    override = os.environ.get("SPEC_SHEET_TEMPLATE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / "templates" / "电机控制需求清单.xlsx"


@lru_cache(maxsize=1)
def load_template_fields() -> tuple[FieldSpec, ...]:
    from openpyxl import load_workbook

    path = template_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到需求清单模板: {path}。请把客户 Excel 放到该路径，"
            "或设置 SPEC_SHEET_TEMPLATE。"
        )
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb.active
        fields: list[FieldSpec] = []
        for row in ws.iter_rows(min_row=3, values_only=True):
            cells = list(row) + [None] * 5
            seq, name, example, hint, impact = cells[:5]
            if seq is None or not str(name or "").strip():
                continue
            try:
                seq_n = int(seq)
            except (TypeError, ValueError):
                continue
            if seq_n in dropped_template_seqs():
                continue
            fields.append(
                FieldSpec(
                    seq=seq_n,
                    name=str(name).strip(),
                    example=str(example or "").strip(),
                    hint=str(hint or "").strip(),
                    impact=str(impact or "").strip(),
                    aliases=aliases_for_seq(seq_n, str(name).strip()),
                    weak_aliases=weak_aliases_for_seq(seq_n),
                    unit_cues=unit_cues_for_seq(seq_n),
                )
            )
    finally:
        wb.close()
    if not fields:
        raise ValueError(f"需求清单是空的: {path}")
    return tuple(fields)


@lru_cache(maxsize=1)
def _review_item_nos() -> dict[int, int]:
    return {spec.seq: i for i, spec in enumerate(load_template_fields(), start=1)}


def review_item_no(seq: int) -> int:
    """核对表「需求序号」：116 项从 1 连续编号。抽出与知识库仍用源表序号。"""
    try:
        key = int(seq)
    except (TypeError, ValueError):
        return 0
    if key <= 0:
        return 0
    return _review_item_nos().get(key, key)


def TEMPLATE_FIELDS() -> tuple[FieldSpec, ...]:
    return load_template_fields()


def empty_template_rows() -> list[ExtractedCell]:
    return [
        ExtractedCell(
            seq=spec.seq,
            name=spec.name,
            hint=spec.hint,
            impact=spec.impact,
            example=spec.example,
        )
        for spec in load_template_fields()
    ]


def compact_field_list() -> str:
    return "、".join(f"{spec.seq}.{spec.name}" for spec in load_template_fields())


def template_title() -> str:
    return "XCM控制器前期设计最小化输入清单"


def item_group(name: str, seq: int = 0) -> str:
    """清单条目分组，便于在核对表里筛选。"""
    if seq:
        if 1 <= seq <= 4:
            return "设计范围"
        if 5 <= seq <= 11:
            return "直流高压"
        if 12 <= seq <= 19 or seq in {24, 25, 26, 27}:
            return "高压安全"
        if 20 <= seq <= 23:
            return "低压"
        if 28 <= seq <= 44:
            return "P1"
        if 45 <= seq <= 60:
            return "P3"
        if 61 <= seq <= 70 or seq == 115:
            return "升压"
        if seq in {71, 72, 110, 111, 112, 113, 119, 120}:
            return "冷却"
        if seq in {77, 78, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 114}:
            return "采样与控制"
        if seq in {80, 81, 116, 117, 118}:
            return "安全与功能"
        if seq == 79 or seq == 95:
            return "整机"
        if 73 <= seq <= 76 or 96 <= seq <= 109:
            return "环境与材料"
    n = (name or "").strip()
    if not n:
        return "其他"
    if n.startswith("设计范围"):
        return "设计范围"
    if n.startswith("P1"):
        return "P1"
    if n.startswith("P3"):
        return "P3"
    if n.startswith("高压安全"):
        return "高压安全"
    if n.startswith(("Boost", "BOOST", "升压")):
        return "升压"
    return "额外抽出" if not seq else "其他"
