"""企标对话：先整理问题，再读网址，最后用本地企标关键行出结果。

网址由 ENTERPRISE_TEST_SOURCE_URL 指定，未给时不发起抓取。
域名、账号、密码不代填，也不从环境变量读取。
本地企标目录默认是已核对过的那份测试材料，也可用 ENTERPRISE_STD_DIR 换。
"""
from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from electrical_krow.enterprise_test import (
    BY_RULE,
    CASE_HEADERS,
    COMPARE_HEADERS,
    DRAFT,
    FILL_HEADERS,
    LINKED,
    LIST_HEADERS,
    REVIEW,
    SHEET_CASES,
    SHEET_COMPARE,
    SHEET_FILL,
    SHEET_LIST,
    TEMPLATE_MISSING,
    TestItem,
    build_cases,
    build_compare,
    extract_from_pages,
    read_standard,
)

DEFAULT_STANDARDS_DIR = Path(r"D:\企标测试\针对企标提取测试项的企标文件")
_BRIEF_LIMIT = 40
_PAGE_LIMIT = 12000
_FETCH_BYTES = 512_000
_CACHE: tuple[tuple, str] | None = None
# 目录当时在场，扫描只把 09 号的前三行原文打了出来。其余命中行没有留下原文。
_RECORDED_BRIEF = """抽条规则：编号中含点，且整行以“试验”或“测试”结束。Word 读出的页码为空。
09_Q-JLY J7110137D-2019-电动汽车车载充电机技术条件.docx | 7.7 | 无页码 | 电气安全试验
09_Q-JLY J7110137D-2019-电动汽车车载充电机技术条件.docx | 7.7.1 | 无页码 | 绝缘性能试验
09_Q-JLY J7110137D-2019-电动汽车车载充电机技术条件.docx | 7.7.3 | 无页码 | 电气间隙和爬电距离试验
09 号当时共命中 21 行，这里只保留已打印的 3 行原文。
05 号 PDF 共 31 页且都有文字层，命中 8 行，行文本没有留下。
其余 docx 当时命中 0 行。06 号 .doc 未读取。
没有留下原文的行不要补写。"""
_BRIEF_LINE = re.compile(
    r"^(?P<doc>.+?) \| (?P<id>\d+(?:\.\d+)+) \| (?P<page>.+?) \| (?P<name>\S.*?)\s*$"
)


def standards_dir() -> Path:
    raw = (os.environ.get("ENTERPRISE_STD_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_STANDARDS_DIR


def source_url() -> str:
    return (os.environ.get("ENTERPRISE_TEST_SOURCE_URL") or "").strip()


# 这些名字一旦有值，说明有人准备让程序代填企标网址的登录。直接拒绝。
_LOGIN_ENVS = (
    "ENTERPRISE_TEST_DOMAIN",
    "ENTERPRISE_TEST_USER",
    "ENTERPRISE_TEST_USERNAME",
    "ENTERPRISE_TEST_ACCOUNT",
    "ENTERPRISE_TEST_PASSWORD",
    "ENTERPRISE_SSO_USER",
    "ENTERPRISE_SSO_PASSWORD",
    "ENTERPRISE_DOMAIN_USER",
    "ENTERPRISE_DOMAIN_PASSWORD",
)
_NO_FILL = "企标网址不代填域名、账号或密码。请在浏览器里自行登录。"


def refuse_credential_fill(url: str = "") -> None:
    """企标来源站只打开页面，不提交域名、账号或密码。"""
    parsed = urlparse((url or "").strip())
    if parsed.username or parsed.password:
        raise ValueError(_NO_FILL)
    if any((os.environ.get(name) or "").strip() for name in _LOGIN_ENVS):
        raise ValueError(_NO_FILL)


# 企标来源门户。内网电脑上它会解析到内网地址，只放行这个域名。
_INTRANET_HOSTS = {"sso.aurobaytech.com"}
_MAX_HOPS = 5
_LOGIN_NOTE = "登录尚未完成，未读取文件。"


def _host_name(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _allows_intranet(host: str) -> bool:
    low = host.lower().rstrip(".")
    if low in _INTRANET_HOSTS:
        return True
    configured = _host_name(source_url())
    return bool(configured) and low == configured


def public_http_url(url: str) -> str:
    """只接受 http(s)。本机地址一律拒绝；内网地址只放行企标来源域名。"""
    refuse_credential_fill(url)
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").strip()
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("网址须为 http 或 https。")
    low = host.lower().rstrip(".")
    if low in {"localhost"} or low.endswith(".local"):
        raise ValueError("不读取本机网址。")
    addresses: list[str] = []
    try:
        addresses.append(str(ipaddress.ip_address(low)))
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise ValueError("网址无法解析。") from exc
        addresses = [item[4][0] for item in infos]
    intranet = _allows_intranet(low)
    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr.is_multicast:
            raise ValueError("不读取本机网址。")
        if intranet:
            continue
        if addr.is_private or addr.is_reserved:
            raise ValueError("不读取内网网址。")
    return parsed._replace(fragment="").geturl()


def _is_login_page(url: str, body: str) -> bool:
    parsed = urlparse(url)
    place = f"{parsed.path} {parsed.fragment}"
    if re.search(r"login", place, re.I):
        return True
    title = re.search(r"(?is)<title>(.*?)</title>", body or "")
    return bool(title and "登录" in re.sub(r"\s+", "", title.group(1)))


def follow_same_host(url: str, get) -> tuple[str, bytes, str]:
    """沿同一站点的跳转往下走。落在登录页时不把登录页当成文件清单。"""
    current = public_http_url(url)
    for _ in range(_MAX_HOPS):
        status, location, body = get(current)
        if 300 <= status < 400:
            if not location:
                raise ValueError("网址发生跳转，但没有给出下一页。")
            nxt = urljoin(current, location)
            base = urlparse(nxt)._replace(fragment="").geturl()
            if _host_name(current) != _host_name(base):
                raise ValueError("网址跳到了其他站点，已停止读取。")
            current = public_http_url(base)
            continue
        if status >= 400:
            raise ValueError(f"网址返回 {status}。")
        if _is_login_page(current, body.decode("utf-8", errors="replace")):
            return current, b"", _LOGIN_NOTE
        return current, body, "已读取网址。"
    raise ValueError("跳转次数过多，已停止读取。")


def _http_get(url: str, timeout: float) -> tuple[str, bytes, str]:
    """只 GET 打开页面。不提交登录，不携带账号、密码或 Cookie。"""
    refuse_credential_fill(url)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            def get(current: str) -> tuple[int, str, bytes]:
                response = client.get(current, headers={"User-Agent": "electrical-krow"})
                return response.status_code, response.headers.get("location") or "", response.content[:_FETCH_BYTES]

            return follow_same_host(url, get)
    except httpx.HTTPError as exc:
        raise ValueError(f"读取网址失败：{exc}") from exc


def fetch_source_page(url: str) -> tuple[str, str]:
    """返回 (正文, 说明)。未配置网址时不访问网络。"""
    if not (url or "").strip():
        return "", "网址尚未提供，未抓取网页。"
    _final, raw, note = _http_get(url, 20.0)
    if note == _LOGIN_NOTE:
        return "", note
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > _PAGE_LIMIT:
        text = text[:_PAGE_LIMIT]
    return text, "已读取网页正文。"


def _signature(root: Path) -> tuple:
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".docx", ".pdf", ".txt", ".md"}
    ]
    latest = max((path.stat().st_mtime_ns for path in files), default=0)
    return (str(root.resolve()), len(files), latest)


def file_key_brief(root: Path | None = None) -> str:
    """本地企标里对上抽条规则的关键行。Word 没有页码。"""
    global _CACHE
    folder = root or standards_dir()
    if not folder.is_dir():
        if root is None:
            return _RECORDED_BRIEF
        return "本地企标目录不存在，没有可对照的关键行。"
    sign = _signature(folder)
    if _CACHE and _CACHE[0] == sign:
        return _CACHE[1]
    lines = [
        "抽条规则：编号中含点，且整行以“试验”或“测试”结束。",
        "Word 读出的页码为空，这些行不能进入已关联清单。",
    ]
    kept = 0
    skipped_doc = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".doc":
            skipped_doc += 1
            continue
        if suffix not in {".docx", ".pdf", ".txt", ".md"}:
            continue
        try:
            items = read_standard(path)
        except (OSError, ValueError):
            continue
        hits = [item for item in items if item.excerpt]
        if not hits:
            continue
        rel = path.relative_to(folder).as_posix()
        for item in hits:
            if kept >= _BRIEF_LIMIT:
                break
            page = item.page or "无页码"
            lines.append(f"{rel} | {item.clause_id} | 第{page}页 | {item.name}")
            kept += 1
        if kept >= _BRIEF_LIMIT:
            lines.append("关键行已截断。")
            break
    if skipped_doc:
        lines.append(f"有 {skipped_doc} 份 .doc 未读取。")
    if kept == 0:
        lines.append("没有对上抽条规则的行。")
    text = "\n".join(lines)
    _CACHE = (sign, text)
    return text


def analysis_messages(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    dialogue = "\n".join(f"{row['role']}: {row['content']}" for row in turns)
    return [
        {
            "role": "system",
            "content": (
                "你在整理企标测试对话。只根据对话写出要查的问题，"
                "一两句，不要编造条款、数值或网址。"
            ),
        },
        {"role": "user", "content": dialogue},
    ]


def _page_label(raw: str) -> str:
    page = raw.strip().removeprefix("第").removesuffix("页").strip()
    if page in {"", "无页码", "无"}:
        return ""
    return page


def items_from_materials(page_text: str, brief: str) -> list[TestItem]:
    """网页正文和关键行里对上抽条规则的测试项。同一条款只留一条。"""
    found: list[TestItem] = []
    seen: set[tuple[str, str]] = set()

    def add(item: TestItem) -> None:
        key = (item.clause_id, item.name)
        if not item.clause_id or not item.name or key in seen:
            return
        seen.add(key)
        found.append(item)

    for line in brief.splitlines():
        match = _BRIEF_LINE.match(line.strip())
        if not match:
            continue
        clause_id = match.group("id")
        name = match.group("name").strip()
        add(
            TestItem(
                clause_id=clause_id,
                name=name,
                document=match.group("doc").strip(),
                page=_page_label(match.group("page")),
                excerpt=f"{clause_id} {name}",
            )
        )
    for item in extract_from_pages([("", page_text or "")], document="网页"):
        add(item)
    return found


def output_tables(page_text: str, brief: str) -> list[dict[str, object]]:
    """技术标输出：清单、对比表、用例、填报记录。无页码不进清单和用例。"""
    items = items_from_materials(page_text, brief)
    compared = build_compare(items, [])
    cases = build_cases(items, [])
    ruled = sum(1 for case in cases if case.method == BY_RULE)
    drafts = sum(1 for case in cases if case.method == DRAFT)
    list_rows = [
        [item.clause_id, item.name, item.document, "", item.page, item.excerpt, LINKED, ""]
        for item in items
        if item.linked
    ]
    compare_rows = [
        [row.clause_id, row.name, row.page, row.excerpt, row.existing, row.disposition, row.status, ""]
        for row in compared
    ]
    case_rows = [
        [
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
            "",
        ]
        for case in cases
    ]
    fill_rows = [
        ["测试用例", "未提供", f"按规则 {ruled} 条，初稿 {drafts} 条。只覆盖已列入清单的测试项。"],
        ["测试报告", "未提供", TEMPLATE_MISSING],
        ["测试方案", "未提供", TEMPLATE_MISSING],
    ]
    sheets = (
        (SHEET_LIST, LIST_HEADERS, list_rows),
        (SHEET_COMPARE, COMPARE_HEADERS, compare_rows),
        (SHEET_CASES, CASE_HEADERS, case_rows),
        (SHEET_FILL, FILL_HEADERS, fill_rows),
    )
    return [
        {"title": title, "headers": list(headers), "rows": rows}
        for title, headers, rows in sheets
    ]


def result_messages(
    turns: list[dict[str, str]],
    analysis: str,
    page_text: str,
    page_note: str,
    brief: str,
) -> list[dict[str, str]]:
    dialogue = "\n".join(f"{row['role']}: {row['content']}" for row in turns)
    page = page_text or "（无网页正文）"
    return [
        {
            "role": "system",
            "content": (
                "根据对话意图、网页正文和本地企标关键行作答。"
                "数值和条款只使用这三块材料里已经出现的内容。"
                "材料里没有的，写明未在材料中找到，不要补写。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"对话：\n{dialogue}\n\n"
                f"整理后的问题：\n{analysis}\n\n"
                f"网页：{page_note}\n{page}\n\n"
                f"本地企标关键行：\n{brief}"
            ),
        },
    ]


def clean_turns(messages: list[dict[str, object]]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for row in messages[-12:]:
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        turns.append({"role": role, "content": content[:4000]})
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("请先输入要查的内容。")
    return turns


COMPARE_HEADERS_OUT = (
    "阶段",
    "序号",
    "试验项目",
    "标准号",
    "条款",
    "试验条件",
    "目标要求",
    "标准文件",
    "标准条件",
    "来源",
    "对比",
    "指标",
)
_LINK = re.compile(
    r"(?is)<a\b[^>]*?\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*>(.*?)</a>"
)
_TAG = re.compile(r"(?s)<[^>]+>")
_REPLACED = re.compile(r"已替换|已被替换|作废|已废止|被替代|已被替代")
_STD_NUM = re.compile(r"J\s*(\d{4,})", re.I)
_YEAR = re.compile(r"(20\d{2}|19\d{2})")
_LETTER = re.compile(r"J\s*\d{4,}\s*([A-Z])", re.I)
_MARKS = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
_CLAUSE_LINE = re.compile(
    r"^(?P<id>\d+(?:\.\d+)+)[\s\u3000]+(?P<title>\S.{0,80})"
)
_ITEM_NO = re.compile(r"^(?:Leg\d{2}(?:-\d{2})?|\d+(?:\.\d+)+)$", re.I)
_CLAUSE_MARK = re.compile(r"(?:技术)?要求|执行")
_DOTTED = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})+)")
_REF_ROW = re.compile(r"参考\s*(DV|ECV|PV)?\s*(Leg\d{2}-\d{2})", re.I)
_CONDITION = re.compile(r"条件|要求|判定|温度|湿度|电压|电流|应")
_FILE_SUFFIX = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}


class CatalogFile:
    def __init__(self, name: str, url: str, replaced: bool) -> None:
        self.name = name
        self.url = url
        self.replaced = replaced

    @property
    def family(self) -> str:
        found = _STD_NUM.search(self.name)
        return found.group(1) if found else re.sub(r"[\s\u3000]+", "", self.name.lower())

    @property
    def rank(self) -> tuple[int, str, int]:
        year = _YEAR.search(self.name)
        letter = _LETTER.search(self.name)
        mark = 0
        for glyph, value in _MARKS.items():
            if glyph in self.name:
                mark = max(mark, value)
        return (
            int(year.group(1)) if year else 0,
            (letter.group(1).upper() if letter else ""),
            mark,
        )


class ManualItem:
    def __init__(
        self,
        clause_id: str,
        name: str,
        *,
        stage: str = "",
        number: str = "",
        standard: str = "",
        condition: str = "",
        criteria: str = "",
    ) -> None:
        self.clause_id = clause_id
        self.name = name
        self.stage = stage
        self.number = number
        self.standard = standard
        self.condition = condition
        self.criteria = criteria


class StandardCondition:
    def __init__(
        self,
        clause_id: str,
        name: str,
        condition: str,
        document: str,
        page: str,
        excerpt: str,
    ) -> None:
        self.clause_id = clause_id
        self.name = name
        self.condition = condition
        self.document = document
        self.page = page
        self.excerpt = excerpt


def _plain(value: str) -> str:
    text = _TAG.sub(" ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parse_catalog(page_html: str, page_url: str) -> list[CatalogFile]:
    """从网址页面列出文件。标成已替换、作废或被替代的记下来。"""
    found: list[CatalogFile] = []
    seen: set[str] = set()
    for match in _LINK.finditer(page_html or ""):
        href = html.unescape(match.group(1)).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        label = _plain(match.group(2))
        tail = _plain((page_html or "")[match.end() : match.end() + 48])
        name = label or Path(urlparse(href).path).name
        if Path(name).suffix.lower() not in _FILE_SUFFIX and Path(href).suffix.lower() not in _FILE_SUFFIX:
            continue
        if Path(name).suffix.lower() not in _FILE_SUFFIX:
            name = Path(urlparse(href).path).name or name
        absolute = urljoin(page_url, href)
        try:
            absolute = public_http_url(absolute)
        except ValueError:
            continue
        if (urlparse(page_url).hostname or "").lower() != (urlparse(absolute).hostname or "").lower():
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(CatalogFile(name, absolute, bool(_REPLACED.search(f"{label} {tail}"))))
    return found


def keep_latest(files: list[CatalogFile]) -> list[CatalogFile]:
    """同一标准只留最新一份，已替换的不留。"""
    grouped: dict[str, CatalogFile] = {}
    for item in files:
        if item.replaced:
            continue
        current = grouped.get(item.family)
        if current is None or item.rank > current.rank:
            grouped[item.family] = item
    return list(grouped.values())


def files_for_table(files: list[CatalogFile], manual_text: str) -> list[CatalogFile]:
    """只取测试表里写到的标准。表里没有标准号时，用测试项名称对文件名。"""
    latest = keep_latest(files)
    numbers = {item.group(1) for item in _STD_NUM.finditer(manual_text or "")}
    if numbers:
        return [item for item in latest if item.family in numbers]
    names = [line.strip() for line in (manual_text or "").splitlines() if len(line.strip()) >= 2]
    picked = []
    for item in latest:
        folded = re.sub(r"[\s\u3000]+", "", item.name)
        if any(re.sub(r"[\s\u3000]+", "", name) in folded for name in names):
            picked.append(item)
    return picked


def _cell_rows(sheet) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        rows.append([str(cell).strip() if cell is not None else "" for cell in row])
    return rows


def _input_sheet_rows(path: Path) -> list[list[str]]:
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        names = list(book.sheetnames)
        picked = next((name for name in names if name.strip() == "DVP&R"), names[0])
        return _cell_rows(book[picked])
    finally:
        book.close()


def read_manual_table(path: Path) -> list[ManualItem]:
    suffix = path.suffix.lower()
    rows: list[list[str]] = []
    if suffix in {".xlsx", ".xlsm"}:
        rows = _input_sheet_rows(path)
    elif suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        if document.tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in document.tables[0].rows]
        else:
            rows = [[paragraph.text.strip()] for paragraph in document.paragraphs if paragraph.text.strip()]
    elif suffix in {".txt", ".md"}:
        rows = [[line.strip()] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raise ValueError("测试表请用 Excel、Word 或文本。")
    items = _manual_items(rows)
    if not items:
        raise ValueError("测试表里没有可读的测试项。")
    _resolve_references(items)
    return items


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _is_dvp_header(row: list[str]) -> bool:
    cells = [_compact(cell) for cell in row]
    return any("序号" in cell for cell in cells) and any("试验项目" in cell for cell in cells)


def _column_contains(header: list[str], token: str) -> int | None:
    for index, cell in enumerate(header):
        if token in _compact(cell):
            return index
    return None


def _stage_name(row: list[str]) -> str:
    text = _compact("".join(row))
    if "ECV性能" in text or "ECV试验" in text:
        return "ECV"
    if "PV性能" in text or "PV试验" in text:
        return "PV"
    if "DV性能" in text or "DV试验" in text:
        return "DV"
    return ""


def _clauses_near_mark(text: str) -> list[str]:
    found: list[str] = []
    for marker in _CLAUSE_MARK.finditer(text or ""):
        window = (text or "")[max(0, marker.start() - 48) : marker.start()]
        tail = re.search(
            r"(\d{1,2}(?:\.\d{1,2})+(?:\s*(?:和|及|、|,|，)\s*\d{1,2}(?:\.\d{1,2})+)*)$",
            window.rstrip(),
        )
        chunk = tail.group(1) if tail else ""
        found.extend(_DOTTED.findall(chunk))
    kept: list[str] = []
    for item in found:
        if item not in kept:
            kept.append(item)
    return kept


def _dvp_items(rows: list[list[str]]) -> list[ManualItem]:
    header: list[str] = []
    stage = ""
    found: list[ManualItem] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        if _is_dvp_header(row):
            header = row
            continue
        named = _stage_name(row)
        if named:
            stage = named
            continue
        if not header:
            continue
        padded = list(row) + [""] * (len(header) + 2)
        number = padded[_column_contains(header, "序号") or 0].strip()
        if not _ITEM_NO.match(number):
            continue
        name_at = _column_contains(header, "试验项目")
        spec_at = _column_contains(header, "试验标准")
        cond_at = _column_contains(header, "试验条件")
        crit_at = _column_contains(header, "目标要求")
        name = padded[name_at].strip() if name_at is not None else ""
        standard = padded[spec_at].strip() if spec_at is not None else ""
        condition = padded[cond_at].strip() if cond_at is not None else ""
        criteria = padded[crit_at].strip() if crit_at is not None else ""
        if not name:
            continue
        clauses = _clauses_near_mark(standard) or _clauses_near_mark(criteria)
        key = (stage, number, name)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            ManualItem(
                "、".join(clauses),
                name,
                stage=stage,
                number=number,
                standard=standard,
                condition=condition,
                criteria=criteria,
            )
        )
    return found


def _followed_text(item: ManualItem, field: str, items: dict[tuple[str, str], ManualItem], depth: int = 0) -> str:
    text = getattr(item, field) or ""
    match = _REF_ROW.search(text)
    if not match or depth > 4:
        return text
    compact = _compact(text)
    if len(compact) > len(_compact(match.group(0))) + 12:
        return text
    stage = (match.group(1) or item.stage or "").upper()
    target = items.get((stage, match.group(2).upper()))
    if target is None or target is item:
        return text
    return _followed_text(target, field, items, depth + 1)


def _resolve_references(items: list[ManualItem]) -> None:
    index = {(item.stage.upper(), item.number.upper()): item for item in items if item.number}
    for item in items:
        item.condition = _followed_text(item, "condition", index)
        item.criteria = _followed_text(item, "criteria", index)


def _manual_items(rows: list[list[str]]) -> list[ManualItem]:
    if any(_is_dvp_header(row) for row in rows):
        return _dvp_items(rows)
    header_at = None
    for index, row in enumerate(rows):
        joined = " ".join(row)
        if "测试项" in joined or "项目" in joined or "名称" in joined:
            header_at = index
            break
    found: list[ManualItem] = []
    seen: set[tuple[str, str]] = set()
    data = rows[(header_at + 1) if header_at is not None else 0 :]
    header = rows[header_at] if header_at is not None else []

    def column(names: tuple[str, ...]) -> int | None:
        for name in names:
            if name in header:
                return header.index(name)
        return None

    clause_at = column(("条款号", "编号"))
    name_at = column(("测试项", "项目", "名称"))
    for row in data:
        padded = list(row) + [""] * 6
        if clause_at is not None or name_at is not None:
            clause_id = padded[clause_at] if clause_at is not None else ""
            name = padded[name_at] if name_at is not None else ""
        else:
            text = next((cell for cell in padded if cell), "")
            parsed = _CLAUSE_LINE.match(text)
            clause_id = parsed.group("id") if parsed else ""
            name = parsed.group("title").strip() if parsed else text
        clause_id = clause_id.strip()
        name = name.strip()
        if name in {"测试项", "项目", "名称", "条款号", "编号"}:
            continue
        if not name:
            continue
        key = (clause_id, name)
        if key in seen:
            continue
        seen.add(key)
        found.append(ManualItem(clause_id, name))
    return found


def conditions_from_pages(pages: list[tuple[str, str]], document: str) -> list[StandardCondition]:
    found: list[StandardCondition] = []
    clause_id = ""
    clause_name = ""
    clause_page = ""
    for page, body in pages:
        for raw in (body or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            parsed = _CLAUSE_LINE.match(line)
            if parsed:
                clause_id = parsed.group("id")
                clause_name = parsed.group("title").strip()
                clause_page = page
                found.append(
                    StandardCondition(clause_id, clause_name, clause_name, document, page, line)
                )
                continue
            if clause_id and _CONDITION.search(line) and len(line) <= 160:
                found.append(
                    StandardCondition(clause_id, clause_name, line, document, clause_page or page, line)
                )
    return found


def _pages_of(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(str(index), page.extract_text() or "") for index, page in enumerate(reader.pages, start=1)]
    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        lines = [paragraph.text for paragraph in document.paragraphs]
        return [("", "\n".join(lines))]
    if suffix in {".txt", ".md"}:
        return [("", path.read_text(encoding="utf-8"))]
    if suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = book[book.sheetnames[0]]
            lines = []
            for row in sheet.iter_rows(values_only=True):
                lines.append(" ".join(str(cell).strip() for cell in row if cell is not None))
        finally:
            book.close()
        return [("", "\n".join(lines))]
    raise ValueError("标准文件请用 PDF、Word、Excel 或文本。")


def _source(item: StandardCondition) -> str:
    page = f"第{item.page}页" if item.page else "无页码"
    return f"{item.document}；{page}；{item.excerpt}"


def _matches(manual: ManualItem, item: StandardCondition) -> bool:
    clauses = [part for part in re.split(r"[、,，\s]+", manual.clause_id or "") if part]
    if clauses:
        return item.clause_id in clauses
    left = re.sub(r"[\s\u3000]+", "", manual.name)
    right = re.sub(r"[\s\u3000]+", "", item.name)
    if not left or not right:
        return False
    return left == right or (len(left) >= 2 and left in right) or (len(right) >= 2 and right in left)


def build_comparison_sheet(
    manual: list[ManualItem],
    conditions: list[StandardCondition],
    *,
    note: str,
) -> dict[str, object]:
    rows: list[list[str]] = []
    used: set[int] = set()
    for item in manual:
        lead = [item.stage, item.number, item.name, item.standard, item.clause_id, item.condition, item.criteria]
        hits = [index for index, condition in enumerate(conditions) if _matches(item, condition)]
        if not hits:
            rows.append([*lead, "", "", "", note or "测试表有、标准未找到", "验证对比"])
            continue
        for index in hits:
            used.add(index)
            condition = conditions[index]
            rows.append(
                [
                    *lead,
                    condition.document,
                    condition.condition,
                    _source(condition),
                    "对应",
                    "验证对比",
                ]
            )
    for index, condition in enumerate(conditions):
        if index in used:
            continue
        rows.append(
            ["", "", "", "", "", "", "", condition.document, condition.condition, _source(condition), "标准有、测试表未列", "欠缺补充"]
        )
    return {
        "title": "对比表",
        "headers": list(COMPARE_HEADERS_OUT),
        "rows": rows,
    }


def fetch_catalog_html(url: str) -> tuple[str, str, str]:
    """返回 (落地页, 原文, 说明)。登录页不返回正文。"""
    if not (url or "").strip():
        return "", "", "网址尚未提供，未抓取网页。"
    final, raw, note = _http_get(url, 20.0)
    if note == _LOGIN_NOTE:
        return final, "", note
    return final, raw.decode("utf-8", errors="replace"), note


def _download_standard(url: str, dest: Path) -> None:
    try:
        _final, raw, note = _http_get(url, 30.0)
    except ValueError as exc:
        raise ValueError(str(exc).replace("读取网址失败", "读取标准文件失败", 1)) from exc
    if note == _LOGIN_NOTE:
        raise ValueError("登录尚未完成，未读取标准文件。")
    dest.write_bytes(raw)


def compare_manual_file(path: Path) -> dict[str, object]:
    """人工测试表对上网址里最新且未被替换的标准，输出一张对比表。"""
    manual = read_manual_table(path)
    manual_text = "\n".join(
        " ".join(part for part in (item.standard, item.clause_id, item.name) if part) for item in manual
    )
    page_url = source_url()
    landed, catalog, note = fetch_catalog_html(page_url)
    conditions: list[StandardCondition] = []
    if catalog:
        chosen = files_for_table(parse_catalog(catalog, landed or page_url), manual_text)
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            for index, item in enumerate(chosen):
                suffix = Path(item.name).suffix.lower()
                if suffix not in _FILE_SUFFIX:
                    suffix = Path(urlparse(item.url).path).suffix.lower()
                if suffix not in _FILE_SUFFIX:
                    continue
                dest = folder / f"{index}{suffix}"
                _download_standard(item.url, dest)
                conditions.extend(conditions_from_pages(_pages_of(dest), item.name))
        if not chosen:
            note = "网址上没有对上的、且仍未被替换的最新文件。"
    sheet = build_comparison_sheet(manual, conditions, note="" if conditions else note)
    files = sorted({row[2] for row in sheet["rows"] if row[2]})
    indicator = COMPARE_HEADERS_OUT.index("指标")
    gaps = sum(1 for row in sheet["rows"] if row[indicator] == "欠缺补充")
    return {
        "reply": f"已生成对比表。采用 {len(files)} 份文件，欠缺补充 {gaps} 条。",
        "tables": [sheet],
        "page_note": note,
        "source_url_set": bool(page_url),
    }
