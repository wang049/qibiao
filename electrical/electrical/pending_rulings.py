"""待专家口径：出表时把「还没定口径」的格子在复核备注里标出来。

数据文件 `docs/knowledge/pending_rulings.json`（electrical-krow 维护，按核对表「需求序号」写），
每条形如::

    {
      "id": "ratio-format",
      "items": [75],
      "when": "filled",            # filled / empty / any
      "family": ["dpr"],           # 可省略 = 所有文档类型；取 doc_kind.family：dpr / inverter / generic
      "match": "P3",               # 可省略；正则，对抽出值 + 摘录检索，命中才标
      "note": "速比填整组还是只填 P3 电机速比",
      "lesson": "2026-09-16-prompt-lists-field-by-strong-alias-ratio"
    }

标注只写进「复核备注」（前缀 `待专家口径：`）和抽出值批注，不改检索结论，不改抽出值。
口径定下来后从文件里删掉这条，并把结论落到规则 / 黄金集。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from electrical.schema import (
    PENDING_RULING_PREFIX as PENDING_PREFIX,
    ExtractedCell,
    _note_for_status,
    review_item_no,
)
_WHEN = {"filled", "empty", "any"}


@dataclass(frozen=True)
class PendingRuling:
    id: str
    items: tuple[int, ...]
    when: str
    family: tuple[str, ...]
    match: str
    note: str
    lesson: str = ""

    def applies(self, cell: ExtractedCell, family: str) -> bool:
        if review_item_no(cell.seq) not in self.items:
            return False
        if self.family and (family or "generic") not in self.family:
            return False
        filled = bool((cell.value or "").strip())
        if self.when == "filled" and not filled:
            return False
        if self.when == "empty" and filled:
            return False
        if self.match:
            blob = f"{cell.value or ''}\n{cell.excerpt or ''}"
            if re.search(self.match, blob, re.I) is None:
                return False
        return True


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    projects = here.parents[1]
    override = os.environ.get("SPEC_SHEET_PENDING_RULINGS", "").strip()
    out: list[Path] = []
    if override:
        out.append(Path(override))
    out.extend(
        [
            here / "templates" / "pending_rulings.json",
            here.parent / "docs" / "knowledge" / "pending_rulings.json",
            # Windows 包：app/electrical/electrical ← app/docs/knowledge
            here.parents[1] / "docs" / "knowledge" / "pending_rulings.json",
            Path.cwd() / "docs" / "knowledge" / "pending_rulings.json",
            here.parents[2] / "docs" / "knowledge" / "pending_rulings.json",
            projects / "electrical-krow" / "docs" / "knowledge" / "pending_rulings.json",
        ]
    )
    return out


def pending_rulings_path() -> Path | None:
    return next((p for p in _candidates() if p.is_file()), None)


def _parse(payload: object) -> tuple[PendingRuling, ...]:
    rows = payload.get("rulings") if isinstance(payload, dict) else payload
    out: list[PendingRuling] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        note = str(raw.get("note") or "").strip()
        items_raw = raw.get("items") or raw.get("item") or ()
        if isinstance(items_raw, int):
            items_raw = (items_raw,)
        items: list[int] = []
        for it in items_raw:
            try:
                items.append(int(it))
            except (TypeError, ValueError):
                continue
        if not note or not items:
            continue
        when = str(raw.get("when") or "any").strip().lower()
        if when not in _WHEN:
            when = "any"
        fam_raw = raw.get("family") or ()
        if isinstance(fam_raw, str):
            fam_raw = (fam_raw,)
        out.append(
            PendingRuling(
                id=str(raw.get("id") or f"item-{'-'.join(map(str, items))}"),
                items=tuple(items),
                when=when,
                family=tuple(str(f).strip() for f in fam_raw if str(f).strip()),
                match=str(raw.get("match") or "").strip(),
                note=note,
                lesson=str(raw.get("lesson") or "").strip(),
            )
        )
    return tuple(out)


@lru_cache(maxsize=1)
def load_pending_rulings() -> tuple[PendingRuling, ...]:
    path = pending_rulings_path()
    if path is None:
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return _parse(payload)


def is_pending_note(note: str) -> bool:
    return (note or "").strip().startswith(PENDING_PREFIX)


def note_without_pending(note: str) -> str:
    """去掉「待专家口径」段，剩下的才参与检索结论判定。标注总是追加在原备注末尾。"""
    return _note_for_status(note)


def pending_text(note: str) -> str:
    """只取「待专家口径：…」这一段，用于抽出值批注。"""
    text = (note or "").strip()
    idx = text.find(PENDING_PREFIX)
    return text[idx:] if idx >= 0 else ""


def apply_pending_rulings(
    cells: list[ExtractedCell],
    family: str = "",
    rulings: tuple[PendingRuling, ...] | None = None,
) -> int:
    """给命中的格子追加「待专家口径：…」备注。返回标注格数。不改抽出值和检索结论。"""
    active = load_pending_rulings() if rulings is None else rulings
    if not active:
        return 0
    count = 0
    for cell in cells:
        if cell.extra:
            continue
        existing = (cell.note or "").strip()
        if is_pending_note(existing) or PENDING_PREFIX in existing:
            continue
        hits = [r.note for r in active if r.applies(cell, family)]
        if not hits:
            continue
        tag = PENDING_PREFIX + "；".join(dict.fromkeys(hits))
        if existing:
            sep = "" if existing.endswith(("。", "；", ";", "!", "！")) else "；"
            cell.note = f"{existing}{sep}{tag}"
        else:
            cell.note = tag
        count += 1
    return count
