"""第一功能流水线：读文件 → 分流 → 质检 → 抽字段 → 写出可核对 Excel。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from electrical.doc_kind import coverage_note
from electrical.doc_qa import inspect_document
from electrical.extract import BUDGET_SEC, DEFAULT_MODEL, ExtractMeta, extract_cells
from electrical.read_doc import load_document
from electrical.schema import (
    STATUS_NA,
    ExtractedCell,
    empty_template_rows,
    finalize_retrieval_statuses,
)
from electrical.progress import report, was_stopped
from electrical.write_excel import write_review_workbook


@dataclass
class RunResult:
    output_xlsx: Path
    cells: list[ExtractedCell]
    elapsed_seconds: float
    likely_scan: bool
    pending_review: int
    filled: int = 0
    kind_code: str = ""
    kind_label: str = ""
    kind_note: str = ""
    extract: bool = True
    family: str = ""
    coverage_note: str = ""
    stopped_early: bool = False
    llm_calls: int = 0
    rule_filled: int = 0
    chunk_count: int = 0
    topup_count: int = 0
    chunk_failures: int = 0
    chunk_error: str = ""
    qa_verdict: str = ""
    qa_summary: str = ""


def run(
    input_path: Path,
    output_path: Path | None = None,
    *,
    model: str = DEFAULT_MODEL,
) -> RunResult:
    started = time.perf_counter()
    # 默认不设总时限：OCR / 抽取跑完再出表。仅当 SPEC_SHEET_BUDGET_SEC>0 才截断。
    deadline = started + BUDGET_SEC if BUDGET_SEC > 0 else None
    doc = load_document(input_path, deadline=deadline)
    kind = doc.kind
    note = coverage_note(kind, doc.likely_scan) if kind is not None else ""
    qa = inspect_document(doc)
    report(qa.progress_message, percent=32, stage="qc")
    meta = ExtractMeta()
    extract = kind.extract if kind is not None else True
    kind_note = kind.note if kind else ""
    if qa.skip_extract:
        extract = False
        kind_note = qa.summary
        cells = empty_template_rows()
        for cell in cells:
            cell.review_status = STATUS_NA
    else:
        cells = extract_cells(doc, model=model, deadline=deadline, meta=meta)
    finalize_retrieval_statuses(cells)
    extract_warning = ""
    if meta.chunk_failures:
        extract_warning = (
            f"有 {meta.chunk_failures} 个分段识别失败，结果可能不完整；"
            "请重点复核未检索到和局部对应条目。"
        )
        if meta.chunk_error:
            extract_warning += f" 原因：{meta.chunk_error}"

    if output_path is None:
        stamp = datetime.now().strftime("%Y年%m月%d日%H：%M：%S")
        output_path = Path.cwd() / "output" / f"{doc.path.stem}_{stamp}.xlsx"
    report("正在写入核对表…", percent=96, stage="write")
    xlsx = write_review_workbook(
        cells,
        output_path,
        source_name=doc.path.name,
        likely_scan=doc.likely_scan,
        parser=doc.parser,
        kind_label=kind.label if kind else "",
        kind_note=kind_note,
        extract=extract,
        family=kind.family if kind else "",
        coverage=note,
        model=model,
        extract_warning=extract_warning,
        qa=qa,
    )
    elapsed = time.perf_counter() - started
    filled = sum(1 for cell in cells if (cell.value or "").strip())
    pending = 0
    if extract:
        pending = sum(1 for cell in cells if cell.needs_review())
    return RunResult(
        output_xlsx=xlsx,
        cells=cells,
        elapsed_seconds=elapsed,
        likely_scan=doc.likely_scan,
        pending_review=pending,
        filled=filled,
        kind_code=kind.code if kind else "",
        kind_label=kind.label if kind else "",
        kind_note=kind_note,
        extract=extract,
        family=kind.family if kind else "",
        coverage_note=note,
        stopped_early=was_stopped(),
        llm_calls=meta.llm_calls,
        rule_filled=meta.rule_filled,
        chunk_count=meta.chunk_count,
        topup_count=meta.topup_count,
        chunk_failures=meta.chunk_failures,
        chunk_error=meta.chunk_error,
        qa_verdict=qa.verdict,
        qa_summary=qa.summary,
    )
