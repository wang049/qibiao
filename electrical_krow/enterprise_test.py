"""第4项企标测试。

从企标抽出测试项，写清单和对比表。
已列入清单的测试项都生成用例：对上固定规则的按规则填写，其余写用例初稿。
测试报告和测试方案只填甲方给出的阶段模板；没有模板时不另作格式。
起算日、计日方式和资料版本缺一项时，一周时钟不起算。
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook

SHEET_INTAKE = "收资"
SHEET_LIST = "企标测试清单"
SHEET_COMPARE = "测试项对比表"
SHEET_CASES = "测试用例"
SHEET_FILL = "填报记录"

PENDING = "待确认"
LINKED = "已关联"
BY_RULE = "按规则生成"
DRAFT = "用例初稿"
REVIEW = "待人工复核"
TEMPLATE_FILLED = "已按模板填报"
TEMPLATE_COPIED = "未找到可填栏目，已原样复制模板"
TEMPLATE_MISSING = "未提供阶段模板，未另作格式"
DAY_COUNTS = ("自然日", "工作日")
WEEK_DAYS = 7
_FIXED_MARKS = frozenset({"固定规则", "是"})

LIST_HEADERS = (
    "条款号",
    "测试项",
    "来源文件",
    "资料版本",
    "页码",
    "原文摘录",
    "确认状态",
    "人工修订",
)
COMPARE_HEADERS = (
    "企标条款号",
    "企标测试项",
    "来源页码",
    "原文摘录",
    "既有测试项",
    "项目处理",
    "确认状态",
    "人工修订",
)
CASE_HEADERS = (
    "条款号",
    "测试项",
    "来源文件",
    "页码",
    "原文摘录",
    "规则版本",
    "生成方式",
    "测试目的",
    "测试步骤",
    "判定准则",
    "复核状态",
    "人工修订",
)
FILL_HEADERS = ("填报对象", "模板或规则", "结果")

_CLAUSE = re.compile(
    r"^(?P<id>\d+(?:\.\d+)+)[\s\u3000]+(?P<title>\S.{0,40}?(?:试验|测试))\s*$"
)
_NOISE = re.compile(r"[\s\u3000，,。．.、；;：:（）()]")
_HEADER_NAMES = {"条款号", "测试项", "名称", "既有测试项", "项目", "页码", "原文摘录"}
_TOKEN = re.compile(r"\{\{([^{}]+)\}\}")


@dataclass(frozen=True)
class Clock:
    start_date: str = ""
    day_count: str = ""
    material_version: str = ""


@dataclass(frozen=True)
class TestItem:
    clause_id: str
    name: str
    document: str
    page: str
    excerpt: str

    @property
    def linked(self) -> bool:
        return bool(self.page.strip() and self.excerpt.strip())


@dataclass(frozen=True)
class CompareRow:
    clause_id: str
    name: str
    page: str
    excerpt: str
    existing: str
    disposition: str
    status: str


@dataclass(frozen=True)
class Rule:
    clause_id: str
    name: str
    version: str
    fixed: bool
    purpose: str
    steps: str
    verdict: str


@dataclass(frozen=True)
class CaseRow:
    clause_id: str
    name: str
    document: str
    page: str
    excerpt: str
    rule_version: str
    method: str
    purpose: str
    steps: str
    verdict: str


@dataclass
class EnterpriseTestResult:
    path: Path
    items: int
    listed: int
    pending: int
    clock_started: bool
    due: str
    cases: int
    ruled: int
    drafts: int
    report_path: Path | None
    plan_path: Path | None
    report_status: str
    plan_status: str


def _text(value: object) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def _norm(value: str) -> str:
    return _NOISE.sub("", _text(value)).casefold()


def _parse_date(value: str) -> date | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def clock_started(clock: Clock) -> bool:
    return (
        _parse_date(clock.start_date) is not None
        and clock.day_count in DAY_COUNTS
        and bool(_text(clock.material_version))
    )


def week_due(clock: Clock) -> date | None:
    """起算日计满 7 个自然日或 7 个工作日。未起算时不给到期日。"""
    if not clock_started(clock):
        return None
    start = _parse_date(clock.start_date)
    assert start is not None
    if clock.day_count == "自然日":
        return start + timedelta(days=WEEK_DAYS)
    cursor = start
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    left = WEEK_DAYS
    while left > 1:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            left -= 1
    return cursor


def _clause_from_line(line: str) -> tuple[str, str] | None:
    matched = _CLAUSE.match(_text(line))
    if not matched:
        return None
    return matched.group("id"), _text(matched.group("title"))


def extract_from_pages(
    pages: list[tuple[str, str]],
    *,
    document: str,
) -> list[TestItem]:
    """pages 为 (页码, 正文)。页码为空的条目保持待确认。"""
    found: list[TestItem] = []
    seen: set[tuple[str, str]] = set()
    for page, body in pages:
        for line in _text(body).splitlines():
            parsed = _clause_from_line(line)
            if not parsed:
                continue
            clause_id, title = parsed
            key = (clause_id, _norm(title))
            if key in seen:
                continue
            seen.add(key)
            found.append(
                TestItem(
                    clause_id=clause_id,
                    name=title,
                    document=document,
                    page=_text(page),
                    excerpt=_text(line),
                )
            )
    return found


def _read_pdf(path: Path) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError("当前环境读不了 PDF 企标。") from exc
    reader = PdfReader(str(path))
    pages: list[tuple[str, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append((str(index), page.extract_text() or ""))
    return pages


def _read_docx(path: Path) -> list[tuple[str, str]]:
    from docx import Document

    document = Document(str(path))
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" ".join(cell.text for cell in row.cells))
    return [("", "\n".join(lines))]


def _sheet_rows(path: Path) -> list[list[str]]:
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = book[book.sheetnames[0]]
        return [[_text(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def _items_from_table(rows: list[list[str]], document: str) -> list[TestItem] | None:
    header_at = None
    for index, row in enumerate(rows):
        if "条款号" in row and "测试项" in row:
            header_at = index
            break
    if header_at is None:
        return None
    header = rows[header_at]
    column = {name: header.index(name) for name in ("条款号", "测试项") if name in header}
    page_at = header.index("页码") if "页码" in header else None
    excerpt_at = header.index("原文摘录") if "原文摘录" in header else None
    found: list[TestItem] = []
    seen: set[tuple[str, str]] = set()
    width = len(header)
    for row in rows[header_at + 1 :]:
        padded = list(row) + [""] * width
        clause_id = padded[column["条款号"]]
        name = padded[column["测试项"]]
        if not clause_id or not name or clause_id in _HEADER_NAMES:
            continue
        page = padded[page_at] if page_at is not None else ""
        excerpt = padded[excerpt_at] if excerpt_at is not None else ""
        key = (clause_id, _norm(name))
        if key in seen:
            continue
        seen.add(key)
        found.append(
            TestItem(
                clause_id=clause_id,
                name=name,
                document=document,
                page=page,
                excerpt=excerpt,
            )
        )
    return found


def read_standard(path: Path) -> list[TestItem]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_from_pages(_read_pdf(path), document=path.name)
    if suffix == ".docx":
        return extract_from_pages(_read_docx(path), document=path.name)
    if suffix in {".xlsx", ".xlsm"}:
        rows = _sheet_rows(path)
        table = _items_from_table(rows, path.name)
        if table is not None:
            return table
        lines = "\n".join(cell for row in rows for cell in row if cell)
        return extract_from_pages([("", lines)], document=path.name)
    if suffix in {".txt", ".md"}:
        return extract_from_pages([("", path.read_text(encoding="utf-8"))], document=path.name)
    raise ValueError("企标请用 PDF、Word、Excel 或文本。")


def read_existing(path: Path | None) -> list[str]:
    if path is None:
        return []
    suffix = path.suffix.lower()
    lines: list[str] = []
    if suffix in {".xlsx", ".xlsm"}:
        for row in _sheet_rows(path):
            if row and row[0]:
                lines.append(row[0])
    elif suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        lines = [paragraph.text for paragraph in document.paragraphs]
    elif suffix in {".txt", ".md"}:
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        raise ValueError("既有测试项请用 Excel、Word 或文本。")
    names: list[str] = []
    seen: set[str] = set()
    for line in lines:
        parsed = _clause_from_line(line)
        name = parsed[1] if parsed else _text(line)
        if not name or name in _HEADER_NAMES:
            continue
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _same_item(left: str, right: str) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and short in long


def build_compare(items: list[TestItem], existing: list[str]) -> list[CompareRow]:
    used: set[int] = set()
    rows: list[CompareRow] = []
    for item in items:
        match = ""
        for index, name in enumerate(existing):
            if index in used:
                continue
            if _same_item(item.name, name):
                used.add(index)
                match = name
                break
        status = LINKED if item.linked else PENDING
        if status == PENDING:
            disposition = PENDING
        elif match:
            disposition = "对应"
        else:
            disposition = "企标项"
        rows.append(
            CompareRow(
                clause_id=item.clause_id,
                name=item.name,
                page=item.page,
                excerpt=item.excerpt,
                existing=match,
                disposition=disposition,
                status=status,
            )
        )
    for index, name in enumerate(existing):
        if index in used:
            continue
        rows.append(
            CompareRow(
                clause_id="",
                name="",
                page="",
                excerpt="",
                existing=name,
                disposition=PENDING,
                status=PENDING,
            )
        )
    return rows


def _saved_notes(path: Path, sheet_name: str, key_at: tuple[int, ...], note_at: int) -> dict[tuple[str, ...], str]:
    if not path.is_file():
        return {}
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in book.sheetnames:
            return {}
        sheet = book[sheet_name]
        found: dict[tuple[str, ...], str] = {}
        for cells in sheet.iter_rows(min_row=2, values_only=True):
            padded = list(cells) + [None] * (note_at + 1)
            note = _text(padded[note_at])
            if not note:
                continue
            found[tuple(_text(padded[index]) for index in key_at)] = note
        return found
    finally:
        book.close()


def _write_sheet(book: Workbook, title: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    sheet = book.create_sheet(title)
    for column, header in enumerate(headers, start=1):
        sheet.cell(1, column, header)
    for offset, row in enumerate(rows):
        for column, value in enumerate(row, start=1):
            sheet.cell(offset + 2, column, value or None)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{chr(64 + len(headers))}{max(1, 1 + len(rows))}"


def _column(header: list[str], *names: str) -> int | None:
    for name in names:
        if name in header:
            return header.index(name)
    return None


def _rules_from_table(rows: list[list[str]]) -> list[Rule] | None:
    header_at = None
    for index, row in enumerate(rows):
        if "测试项" in row and ("规则状态" in row or "是否固定规则" in row or "测试步骤" in row or "判定准则" in row):
            header_at = index
            break
    if header_at is None:
        return None
    header = rows[header_at]
    name_at = header.index("测试项")
    clause_at = _column(header, "条款号")
    version_at = _column(header, "规则版本")
    status_at = _column(header, "规则状态", "是否固定规则")
    purpose_at = _column(header, "测试目的")
    steps_at = _column(header, "测试步骤")
    verdict_at = _column(header, "判定准则")
    found: list[Rule] = []
    seen: set[tuple[str, str]] = set()
    width = len(header)
    for row in rows[header_at + 1 :]:
        padded = list(row) + [""] * width
        name = padded[name_at]
        clause_id = padded[clause_at] if clause_at is not None else ""
        if not name or name in _HEADER_NAMES:
            continue
        key = (clause_id, _norm(name))
        if key in seen:
            continue
        seen.add(key)
        steps = padded[steps_at] if steps_at is not None else ""
        verdict = padded[verdict_at] if verdict_at is not None else ""
        if status_at is not None:
            fixed = padded[status_at] in _FIXED_MARKS
        else:
            fixed = bool(steps and verdict)
        found.append(
            Rule(
                clause_id=clause_id,
                name=name,
                version=padded[version_at] if version_at is not None else "",
                fixed=fixed,
                purpose=padded[purpose_at] if purpose_at is not None else "",
                steps=steps,
                verdict=verdict,
            )
        )
    return found


def _delimited_rows(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            parts = line.split("\t")
        elif "|" in line:
            parts = line.strip().strip("|").split("|")
        else:
            parts = [line]
        rows.append([_text(part) for part in parts])
    return rows


def _docx_rows(path: Path) -> list[list[str]]:
    from docx import Document

    document = Document(str(path))
    rows: list[list[str]] = []
    for table in document.tables:
        for row in table.rows:
            rows.append([_text(cell.text) for cell in row.cells])
    if rows:
        return rows
    return [[_text(paragraph.text)] for paragraph in document.paragraphs if _text(paragraph.text)]


def read_rules(path: Path | None) -> list[Rule]:
    if path is None:
        return []
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        rows = _sheet_rows(path)
    elif suffix == ".docx":
        rows = _docx_rows(path)
    elif suffix in {".txt", ".md"}:
        rows = _delimited_rows(path)
    else:
        raise ValueError("测试用例规则请用 Excel、Word 或文本。")
    rules = _rules_from_table(rows)
    if rules is None:
        raise ValueError("测试用例规则需要表头，至少包含测试项，以及规则状态或测试步骤、判定准则。")
    return rules


def _take_rule(item: TestItem, rules: list[Rule], used: set[int]) -> Rule | None:
    if item.clause_id:
        for index, rule in enumerate(rules):
            if index not in used and rule.clause_id == item.clause_id:
                used.add(index)
                return rule
    for index, rule in enumerate(rules):
        if index not in used and rule.name and _same_item(item.name, rule.name):
            used.add(index)
            return rule
    return None


def build_cases(items: list[TestItem], rules: list[Rule]) -> list[CaseRow]:
    used: set[int] = set()
    rows: list[CaseRow] = []
    for item in items:
        if not item.linked:
            continue
        rule = _take_rule(item, rules, used)
        if rule is not None and rule.fixed:
            rows.append(
                CaseRow(
                    clause_id=item.clause_id,
                    name=item.name,
                    document=item.document,
                    page=item.page,
                    excerpt=item.excerpt,
                    rule_version=rule.version,
                    method=BY_RULE,
                    purpose=rule.purpose,
                    steps=rule.steps,
                    verdict=rule.verdict,
                )
            )
            continue
        rows.append(
            CaseRow(
                clause_id=item.clause_id,
                name=item.name,
                document=item.document,
                page=item.page,
                excerpt=item.excerpt,
                rule_version="",
                method=DRAFT,
                purpose="",
                steps="",
                verdict="",
            )
        )
    return rows


def _companion(dest: Path, title: str, suffix: str) -> Path:
    stamp = dest.stem.removeprefix("企标测试清单-")
    return dest.with_name(f"{title}-{stamp}{suffix}")


def _replace_tokens(value: str, fields: dict[str, str]) -> tuple[str, int]:
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        key = _text(match.group(1))
        if key not in fields:
            return match.group(0)
        count += 1
        return fields[key] or PENDING

    return _TOKEN.sub(repl, value), count


def _case_fields(case: CaseRow, version: str) -> dict[str, str]:
    status = REVIEW if case.method == DRAFT else BY_RULE
    return {
        "条款号": case.clause_id,
        "测试项": case.name,
        "来源文件": case.document,
        "页码": case.page,
        "原文摘录": case.excerpt,
        "资料版本": version,
        "规则版本": case.rule_version,
        "生成方式": case.method,
        "测试目的": case.purpose,
        "测试步骤": case.steps,
        "判定准则": case.verdict,
        "复核状态": REVIEW,
        "确认状态": status,
    }


def _append_case_rows(sheet, cases: list[CaseRow], version: str) -> int:
    header_row = None
    headers: list[str] = []
    limit = min(sheet.max_row or 1, 20)
    width = max(sheet.max_column or 1, 1)
    for row in range(1, limit + 1):
        headers = [_text(sheet.cell(row, column).value) for column in range(1, width + 1)]
        if "测试项" in headers or "条款号" in headers:
            header_row = row
            break
    if header_row is None:
        return 0
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        return 0
    blank = True
    for row in range(header_row + 1, (sheet.max_row or header_row) + 1):
        for column in range(1, len(headers) + 1):
            if _text(sheet.cell(row, column).value):
                blank = False
                break
        if not blank:
            break
    start = header_row + 1 if blank else (sheet.max_row or header_row) + 1
    written = 0
    for offset, case in enumerate(cases):
        values = _case_fields(case, version)
        for column, header in enumerate(headers, start=1):
            if header not in values or not values[header]:
                continue
            sheet.cell(start + offset, column, values[header])
        written += 1
    return written


def _fill_xlsx(template: Path, target: Path, cases: list[CaseRow], fields: dict[str, str], version: str) -> int:
    book = load_workbook(template)
    hits = 0
    try:
        for sheet in book.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if not isinstance(cell.value, str) or "{{" not in cell.value:
                        continue
                    text, count = _replace_tokens(cell.value, fields)
                    if count:
                        cell.value = text
                        hits += count
            hits += _append_case_rows(sheet, cases, version)
        if hits:
            target.parent.mkdir(parents=True, exist_ok=True)
            book.save(target)
        return hits
    finally:
        book.close()


def _fill_docx(template: Path, target: Path, cases: list[CaseRow], fields: dict[str, str], version: str) -> int:
    from docx import Document

    document = Document(str(template))
    hits = 0
    for paragraph in document.paragraphs:
        if "{{" not in paragraph.text:
            continue
        text, count = _replace_tokens(paragraph.text, fields)
        if count:
            paragraph.text = text
            hits += count
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if "{{" not in paragraph.text:
                        continue
                    text, count = _replace_tokens(paragraph.text, fields)
                    if count:
                        paragraph.text = text
                        hits += count
        headers = [_text(cell.text) for cell in table.rows[0].cells] if table.rows else []
        if "测试项" not in headers and "条款号" not in headers:
            continue
        for case in cases:
            values = _case_fields(case, version)
            added = table.add_row()
            for index, header in enumerate(headers):
                if index < len(added.cells) and values.get(header):
                    added.cells[index].text = values[header]
            hits += 1
    if hits:
        target.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(target))
    return hits


def _fill_template(
    template: Path | None,
    dest: Path,
    title: str,
    cases: list[CaseRow],
    fields: dict[str, str],
    version: str,
) -> tuple[Path | None, str]:
    if template is None:
        return None, TEMPLATE_MISSING
    suffix = template.suffix.lower()
    if suffix not in {".docx", ".xlsx", ".xlsm"}:
        raise ValueError(f"{title}请用 Word 或 Excel。")
    target = _companion(dest, title, suffix)
    if suffix == ".docx":
        hits = _fill_docx(template, target, cases, fields, version)
    else:
        hits = _fill_xlsx(template, target, cases, fields, version)
    if hits:
        return target, TEMPLATE_FILLED
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, target)
    return target, TEMPLATE_COPIED


def enterprise_test_file_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"企标测试清单-{stamp}.xlsx"


def build_enterprise_test(
    standard: Path,
    dest: Path,
    *,
    existing: Path | None = None,
    rules: Path | None = None,
    report_template: Path | None = None,
    plan_template: Path | None = None,
    supplier: str = "",
    clock: Clock | None = None,
) -> EnterpriseTestResult:
    if not standard.is_file():
        raise ValueError("找不到企标文件。")
    plan = clock or Clock()
    started = clock_started(plan)
    due = week_due(plan)
    items = read_standard(standard)
    compared = build_compare(items, read_existing(existing))
    version = _text(plan.material_version) if started else ""
    target = Path(dest)
    rule_rows = read_rules(rules)
    cases = build_cases(items, rule_rows)
    ruled = sum(1 for case in cases if case.method == BY_RULE)
    drafts = sum(1 for case in cases if case.method == DRAFT)
    rule_versions = []
    for rule in rule_rows:
        if rule.version and rule.version not in rule_versions:
            rule_versions.append(rule.version)
    fields = {
        "供应商": _text(supplier),
        "指定供应商": _text(supplier),
        "资料版本": _text(plan.material_version),
        "规则版本": "、".join(rule_versions),
        "起算日": _text(plan.start_date),
        "计日方式": _text(plan.day_count),
        "到期日": due.isoformat() if due else "",
        "清单结构到期日": due.isoformat() if due else "",
        "企标": standard.name,
    }
    report_path, report_status = _fill_template(report_template, target, "测试报告", cases, fields, version)
    plan_path, plan_status = _fill_template(plan_template, target, "测试方案", cases, fields, version)
    list_notes = _saved_notes(target, SHEET_LIST, (0, 5), 7)
    compare_notes = _saved_notes(target, SHEET_COMPARE, (0, 4), 7)
    case_notes = _saved_notes(target, SHEET_CASES, (0, 1), len(CASE_HEADERS) - 1)

    book = Workbook()
    intake = book.active
    intake.title = SHEET_INTAKE
    intake["A1"] = "项目"
    intake["B1"] = "内容"
    intake_rows = (
        ("企标", standard.name),
        ("既有测试项", existing.name if existing else "未提供"),
        ("测试用例规则", rules.name if rules else "未提供"),
        ("规则版本", "、".join(rule_versions) if rule_versions else ("未注明" if rules else "未提供")),
        ("测试报告阶段模板", report_template.name if report_template else "未提供"),
        ("测试方案阶段模板", plan_template.name if plan_template else "未提供"),
        ("指定供应商", _text(supplier) or "未填写"),
        ("起算日", _text(plan.start_date)),
        ("计日方式", _text(plan.day_count)),
        ("资料版本", _text(plan.material_version)),
        ("一周时钟", "已起算" if started else "未起算"),
        ("清单结构到期日", due.isoformat() if due else ""),
        ("本次范围", "清单、对比表和测试用例。报告和方案只填已提供的阶段模板。"),
    )
    for offset, (label, value) in enumerate(intake_rows, start=2):
        intake.cell(offset, 1, label)
        intake.cell(offset, 2, value or None)

    listed = [item for item in items if item.linked]
    list_rows = []
    for item in listed:
        key = (item.clause_id, item.excerpt)
        list_rows.append(
            (
                item.clause_id,
                item.name,
                item.document,
                version,
                item.page,
                item.excerpt,
                LINKED,
                list_notes.get(key, ""),
            )
        )
    compare_rows = []
    for row in compared:
        key = (row.clause_id, row.existing)
        compare_rows.append(
            (
                row.clause_id,
                row.name,
                row.page,
                row.excerpt,
                row.existing,
                row.disposition,
                row.status,
                compare_notes.get(key, ""),
            )
        )
    case_rows = []
    for case in cases:
        case_rows.append(
            (
                case.clause_id,
                case.name,
                case.document,
                case.page,
                case.excerpt,
                case.rule_version,
                case.method,
                case.purpose,
                case.steps,
                case.verdict,
                REVIEW,
                case_notes.get((case.clause_id, case.name), ""),
            )
        )
    fill_rows = [
        ("测试用例", rules.name if rules else "未提供", f"按规则 {ruled} 条，初稿 {drafts} 条。只覆盖已列入清单的测试项。"),
        ("测试报告", report_template.name if report_template else "未提供", report_status),
        ("测试方案", plan_template.name if plan_template else "未提供", plan_status),
    ]
    _write_sheet(book, SHEET_LIST, LIST_HEADERS, list_rows)
    _write_sheet(book, SHEET_COMPARE, COMPARE_HEADERS, compare_rows)
    _write_sheet(book, SHEET_CASES, CASE_HEADERS, case_rows)
    _write_sheet(book, SHEET_FILL, FILL_HEADERS, fill_rows)
    target.parent.mkdir(parents=True, exist_ok=True)
    book.save(target)
    book.close()
    return EnterpriseTestResult(
        path=target,
        items=len(items),
        listed=len(listed),
        pending=sum(1 for row in compared if row.status == PENDING),
        clock_started=started,
        due=due.isoformat() if due else "",
        cases=len(cases),
        ruled=ruled,
        drafts=drafts,
        report_path=report_path,
        plan_path=plan_path,
        report_status=report_status,
        plan_status=plan_status,
    )
