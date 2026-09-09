"""摩擦复盘：给人看、给召回。禁止当作抽出值来源。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from electrical_krow.paths import PROJECT_ROOT

LESSONS_DIR = PROJECT_ROOT / ".krow" / "lessons"
_FOLD = re.compile(r"[\s,，;；~～\-—–]")
_SEQ = re.compile(r"#\s*(\d{1,3})\b")
_STATUS = re.compile(r"^-\s*状态[：:]\s*(\S+)", re.M)
_GATE_LINE = re.compile(r"^-\s*闸门[：:]\s*(.+)$", re.M)
_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.M)
_SKIP_PREFIX = "_"


def fill_from_lessons_allowed() -> bool:
    """复盘不得提供抽出值。"""
    return False


def _fold(text: str) -> str:
    return _FOLD.sub("", (text or "")).lower()


@dataclass(frozen=True)
class Lesson:
    path: Path
    title: str
    status: str
    seqs: tuple[int, ...]
    counterfactual: str
    basis: str
    gate: str
    body: str

    @property
    def name(self) -> str:
        return self.path.name


def lessons_dir() -> Path:
    return LESSONS_DIR


def _section(body: str, title: str) -> str:
    matches = list(_HEADING.finditer(body))
    for i, match in enumerate(matches):
        if match.group(1).strip() != title:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        return body[start:end].strip()
    return ""


def _parse(path: Path) -> Lesson | None:
    if path.name.startswith(_SKIP_PREFIX):
        return None
    text = path.read_text(encoding="utf-8")
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    status_match = _STATUS.search(text)
    status = (status_match.group(1) if status_match else "candidate").strip()
    seqs = tuple(dict.fromkeys(int(n) for n in _SEQ.findall(text)))
    header_gate = ""
    gate_line = _GATE_LINE.search(text)
    if gate_line:
        header_gate = gate_line.group(1).strip()
    section_gate = _section(text, "闸门")
    gate = "\n".join(part for part in (header_gate, section_gate) if part)
    return Lesson(
        path=path,
        title=title or path.stem,
        status=status,
        seqs=seqs,
        counterfactual=_section(text, "反事实"),
        basis=_section(text, "二级依据"),
        gate=gate,
        body=text,
    )


@lru_cache(maxsize=1)
def load_lessons() -> tuple[Lesson, ...]:
    if not LESSONS_DIR.is_dir():
        return ()
    rows: list[Lesson] = []
    for path in sorted(LESSONS_DIR.glob("*.md")):
        item = _parse(path)
        if item is not None:
            rows.append(item)
    return tuple(rows)


def _query_seqs(query: str) -> set[int]:
    text = (query or "").strip()
    found = {int(n) for n in _SEQ.findall(text)}
    if text.isdigit():
        found.add(int(text))
    return found


def _score(lesson: Lesson, query: str) -> int:
    raw = (query or "").strip()
    if not raw:
        return 1
    score = 0
    want = _query_seqs(raw)
    if want and want & set(lesson.seqs):
        score += 20
    folded_q = _fold(raw)
    folded_body = _fold(lesson.body)
    if len(folded_q) >= 2 and folded_q in folded_body:
        score += 8
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{3,}", raw):
        folded = _fold(token)
        if len(folded) >= 2 and folded in folded_body:
            score += 2
    return score


def recall_related(query: str, *, limit: int = 8) -> list[Lesson]:
    """按序号或关键词召回复盘。不调 LLM，不返回抽出值。"""
    ranked = []
    for lesson in load_lessons():
        if lesson.status in {"superseded", "retired"}:
            continue
        score = _score(lesson, query)
        if score:
            ranked.append((score, lesson.name, lesson))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[: max(1, limit)]]


def closeout_ok(lesson: Lesson) -> bool:
    """active 复盘必须有反事实、二级依据，且闸门提到测试或规则文件。"""
    if lesson.status != "active":
        return True
    if len(lesson.counterfactual) < 8 or len(lesson.basis) < 8:
        return False
    gate = lesson.gate or ""
    return bool(
        re.search(r"test_|extract\.py|schema\.py|_value_fits_field|\.py", gate)
    )
