"""企标对话：先整理问题，再读网址，最后用本地企标关键行出结果。

文件从 http://arsm.aurobaytech.com/home/index 检索。先在给定网址上找到检索框，填入测试表抽出的文件名和标准号，只取网页搜索结果里的文件；再留最新且未被替换的一份，从中抽出试验条款，最后写回对比表。
可用 ENTERPRISE_TEST_SOURCE_URL 换成该站点上的具体页面。
域名、账号、密码不代填，也不从环境变量读取。
本地企标目录默认是已核对过的那份测试材料，也可用 ENTERPRISE_STD_DIR 换。
"""
from __future__ import annotations

import base64
import html
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

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
_PAGE_BYTES = 8 * 1024 * 1024
_FILE_BYTES = 40 * 1024 * 1024
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


FILE_HOST = "arsm.aurobaytech.com"
DEFAULT_SOURCE_URL = "http://arsm.aurobaytech.com/home/index"


def source_url() -> str:
    raw = (os.environ.get("ENTERPRISE_TEST_SOURCE_URL") or "").strip()
    return raw or DEFAULT_SOURCE_URL


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


# 内网电脑上这些域名会解析到内网地址。文件站是 arsm，登录站只放行解析。
_INTRANET_HOSTS = {"sso.aurobaytech.com", FILE_HOST}
_MAX_HOPS = 5
_MAX_PAGES = 400
_DNS: dict[str, list[str]] = {}
_DNS_LOCK = threading.Lock()


def _host_name(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _addresses(host: str) -> list[str]:
    """同一域名只解析一次，5 秒没有结果就停下，避免把对比请求挂住。"""
    with _DNS_LOCK:
        cached = _DNS.get(host)
    if cached is not None:
        return list(cached)
    box: list[list] = []
    error: list[BaseException] = []

    def work() -> None:
        try:
            box.append(socket.getaddrinfo(host, None))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(5)
    if thread.is_alive() or error or not box:
        raise ValueError("网址无法解析。")
    found = [item[4][0] for item in box[0]]
    with _DNS_LOCK:
        _DNS[host] = found
    return list(found)


def _ssl_context() -> ssl.SSLContext:
    """校验证书时带上系统里已经信任的内网证书。"""
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    enum = getattr(ssl, "enum_certificates", None)
    if enum is None:
        return ctx
    for store in ("ROOT", "CA"):
        try:
            rows = enum(store)
        except OSError:
            continue
        for cert, encoding, _trust in rows:
            if encoding != "x509_asn":
                continue
            try:
                ctx.load_verify_locations(cadata=cert)
            except ssl.SSLError:
                continue
    return ctx


_SSL: ssl.SSLContext | None = None


def _verify() -> ssl.SSLContext:
    global _SSL
    if _SSL is None:
        _SSL = _ssl_context()
    return _SSL


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
        addresses = _addresses(host)
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


def _opens_file_site(current: str, nxt: str) -> bool:
    """同一站点可以继续。跳进 arsm.aurobaytech.com 也继续，从文件站离开则停止。"""
    nxt_host = _host_name(nxt)
    return nxt_host == FILE_HOST or nxt_host == _host_name(current)


def follow_same_host(url: str, get) -> tuple[str, bytes, str]:
    """沿跳转往下走，直到停在文件站页面。不根据路径或标题判断登录页。"""
    current = public_http_url(url)
    for _ in range(_MAX_HOPS):
        status, location, body = get(current)
        if 300 <= status < 400:
            if not location:
                raise ValueError("网址发生跳转，但没有给出下一页。")
            nxt = urljoin(current, location)
            base = urlparse(nxt)._replace(fragment="").geturl()
            if not _opens_file_site(current, base):
                raise ValueError("网址跳到了其他站点，已停止读取。")
            current = public_http_url(base)
            continue
        if status >= 400:
            raise ValueError(f"网址返回 {status}。")
        return current, body, "已读取网址。"
    raise ValueError("跳转次数过多，已停止读取。")


def _read_capped(chunks, max_bytes: int | None) -> bytes:
    total = 0
    parts: list[bytes] = []
    for chunk in chunks:
        if not chunk:
            continue
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise ValueError(f"读取内容超过 {max_bytes // (1024 * 1024)}MB，已停止。")
        parts.append(chunk)
    return b"".join(parts)


def _http_get(url: str, timeout: float, max_bytes: int | None, accept: str = "") -> tuple[str, bytes, str]:
    """只 GET 打开页面。不提交登录，不携带账号、密码或 Cookie。"""
    refuse_credential_fill(url)
    headers = {"User-Agent": "electrical-krow"}
    if accept:
        headers["Accept"] = accept
    try:
        with httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(8.0, timeout)),
            follow_redirects=False,
            trust_env=False,
            verify=_verify(),
        ) as client:
            def get(current: str) -> tuple[int, str, bytes]:
                with client.stream(
                    "GET", current, headers=headers
                ) as response:
                    status = response.status_code
                    location = response.headers.get("location") or ""
                    if status >= 300:
                        return status, location, b""
                    return status, location, _read_capped(response.iter_bytes(), max_bytes)

            return follow_same_host(url, get)
    except httpx.HTTPError as exc:
        raise ValueError(f"读取网址失败：{exc}") from exc


def _http_post_json(action: str, payload: dict[str, object]) -> tuple[str, bytes, str]:
    """用 JSON 调用脚本里的检索接口。不带账号、密码或 Cookie。"""
    target = public_http_url(action)
    refuse_credential_fill(target)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
            verify=_verify(),
        ) as client:
            with client.stream(
                "POST",
                target,
                json=payload,
                headers={
                    "User-Agent": "electrical-krow",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ) as response:
                status = response.status_code
                if status >= 400:
                    raise ValueError(f"网址返回 {status}。")
                body = _read_capped(response.iter_bytes(), _PAGE_BYTES)
                return str(response.url), body, "已读取网址。"
    except httpx.HTTPError as exc:
        raise ValueError(f"读取网址失败：{exc}") from exc


def _http_post_form(action: str, data: dict[str, str]) -> tuple[str, bytes, str]:
    """提交检索表单。只带检索词和页面自带的隐藏字段，不带账号或密码。"""
    refuse_credential_fill(action)
    try:
        with httpx.Client(
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=False,
            trust_env=False,
            verify=_verify(),
        ) as client:
            with client.stream(
                "POST",
                action,
                data=data,
                headers={"User-Agent": "electrical-krow"},
            ) as response:
                status = response.status_code
                location = response.headers.get("location") or ""
                if 300 <= status < 400 and location:
                    nxt = urljoin(str(response.url), location)
                    if not _opens_file_site(action, nxt):
                        raise ValueError("网址跳到了其他站点，已停止读取。")
                    return _http_get(public_http_url(nxt), 20.0, _PAGE_BYTES)
                if status >= 400:
                    raise ValueError(f"网址返回 {status}。")
                body = _read_capped(response.iter_bytes(), _PAGE_BYTES)
                return str(response.url), body, "已读取网址。"
    except httpx.HTTPError as exc:
        raise ValueError(f"读取网址失败：{exc}") from exc


def fetch_source_page(url: str) -> tuple[str, str]:
    """返回 (正文, 说明)。未配置网址时不访问网络。"""
    if not (url or "").strip():
        return "", "网址尚未提供，未抓取网页。"
    _final, raw, _note = _http_get(url, 20.0, _PAGE_BYTES)
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
        if path.is_file() and path.suffix.lower() in {".doc", ".docx", ".pdf", ".txt", ".md"}
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
        if suffix not in {".doc", ".docx", ".pdf", ".txt", ".md"}:
            continue
        try:
            if suffix == ".doc":
                items = extract_from_pages(_read_pages(path), document=path.name)
            else:
                items = read_standard(path)
        except (OSError, ValueError):
            if suffix == ".doc":
                skipped_doc += 1
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
    "结论",
)
_LINK = re.compile(
    r"(?is)<a\b[^>]*?\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))[^>]*>(.*?)</a>"
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
_ITEM_NO = re.compile(r"^(?:Leg\d{2}(?:-\d{2})?|\d+(?:\.\d+)*)$", re.I)
_CLAUSE_MARK = re.compile(r"(?:技术)?要求|执行")
_DOTTED = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,2})+)")
_REF_ROW = re.compile(r"参考\s*(DV|ECV|PV)?\s*(Leg\d{2}-\d{2})", re.I)
_CONDITION = re.compile(r"条件|要求|判定|温度|湿度|电压|电流|应")
_FILE_SUFFIX = {".pdf", ".doc", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}
_SKIP_SUFFIX = _FILE_SUFFIX | {
    ".html", ".htm", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".zip",
}
_NEXT_LABEL = re.compile(r"^(?:下一页|下页|后一页|next(?:\s+page)?|›|»|>>)$", re.I)
_PAGE_NUMBER = re.compile(r"^\d{1,4}$")
_PAGE_PARAM = re.compile(
    r"(?:^|[?&])(?:page|pageno|pagenum|pageindex|currentpage|p)=\d+\b",
    re.I,
)
_BLOCK = re.compile(r"(?is)<(table|ul|ol)\b.*?</\1>")
_CHROME = re.compile(r"(?is)<(nav|header|footer)\b.*?</\1>")
_LINK_TAG = re.compile(r"(?is)<link\b[^>]*>")
_REL_NEXT = re.compile(r"(?is)\brel\s*=\s*['\"]?next\b")
_HREF_ATTR = re.compile(
    r"(?is)\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))"
)
_FORM = re.compile(r"(?is)<form\b[^>]*>.*?</form>")
_FORM_OPEN = re.compile(r"(?is)<form\b[^>]*>")
_INPUT = re.compile(r"(?is)<input\b[^>]*>")
_ATTR = re.compile(
    r"(?is)\b([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+))"
)
_STD_TOKEN = re.compile(r"J\s*\d{4,}\s*[A-Z]?(?:\s*-\s*\d{4})?", re.I)
_SEARCH_FIELD = re.compile(r"keyword|keywords|search|query|^q$|^wd$|key|title|standard|关键字|检索|标准", re.I)
_SEARCH_HINT = re.compile(
    r"keyword|keywords|search|query|standard|关键字|关键词|检索|标准号|标准|文件名称|文件名|搜索|查询|请输入.{0,16}(?:标准|文件|关键字|关键词|检索|搜索|查询)",
    re.I,
)
_SEARCH_BUTTON = re.compile(r"搜索|检索|查询")
_SECRET_FIELD = re.compile(r"pass|pwd|user|account|login", re.I)
_WIDGET = re.compile(r"(?is)<(?:el-input|a-input|van-field|van-search|ion-searchbar)\b[^>]*>")


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
        sheet: str = "",
    ) -> None:
        self.clause_id = clause_id
        self.name = name
        self.stage = stage
        self.number = number
        self.standard = standard
        self.condition = condition
        self.criteria = criteria
        self.sheet = sheet
        self.lookup_standard = ""
        self.lookup_file = ""


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


def _link_status(page_html: str, start: int, end: int, label: str) -> str:
    """替换状态只看链接文字和它所在的那一行，不看下一行。"""
    row_at = page_html.rfind("<tr", 0, start)
    row_end = page_html.find("</tr>", end)
    if row_at != -1 and row_end != -1:
        return _plain(page_html[row_at:row_end])
    rest = page_html[end:]
    lower = rest.lower()
    stops = [len(rest)]
    for marker in ("<a", "</td>", "</li>", "</div>", "</p>"):
        at = lower.find(marker)
        if at >= 0:
            stops.append(at)
    return f"{label} {_plain(rest[: min(stops)])}"


def _href_of(match: re.Match[str]) -> str:
    return html.unescape(next(part for part in match.groups()[:3] if part is not None)).strip()


def _file_name(label: str, href: str) -> str:
    path_name = Path(urlparse(href).path).name
    name = label or path_name
    if Path(name).suffix.lower() in _FILE_SUFFIX:
        return name
    if Path(path_name).suffix.lower() in _FILE_SUFFIX:
        return path_name or name
    return name


def parse_catalog(page_html: str, page_url: str) -> list[CatalogFile]:
    """从网址页面列出文件。标成已替换、作废或被替代的记下来。"""
    found: list[CatalogFile] = []
    seen: set[str] = set()
    page = page_html or ""
    for match in _LINK.finditer(page):
        href = _href_of(match)
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        label = _plain(match.group(4))
        name = _file_name(label, href)
        path_suffix = Path(urlparse(href).path).suffix.lower()
        if Path(name).suffix.lower() not in _FILE_SUFFIX and path_suffix not in _FILE_SUFFIX:
            continue
        absolute = _resolve_link(page_url, href)
        if absolute is None:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        status = _link_status(page, match.start(), match.end(), label)
        found.append(CatalogFile(name, absolute, bool(_REPLACED.search(status))))
    return found


def _join_on_page(page_url: str, href: str) -> str:
    if href.startswith("?") or urlparse(href).scheme or urlparse(href).netloc:
        return urljoin(page_url, href)
    base = urlparse(page_url)
    path = base.path or "/"
    if not path.endswith("/") and Path(path).suffix.lower() not in _SKIP_SUFFIX:
        page_url = base._replace(path=path + "/").geturl()
    return urljoin(page_url, href)


def _resolve_link(page_url: str, href: str) -> str | None:
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return None
    joined = _join_on_page(page_url, href)
    if _host_name(joined) not in {_host_name(page_url), FILE_HOST}:
        return None
    try:
        return public_http_url(joined)
    except ValueError:
        return None


def _looks_like_file(label: str, href: str) -> bool:
    path_suffix = Path(urlparse(href).path).suffix.lower()
    return Path(_file_name(label, href)).suffix.lower() in _FILE_SUFFIX or path_suffix in _FILE_SUFFIX


def _page_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme}://{parsed.netloc}{path}{query}"


def _covered(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= pos < end for start, end in spans)


def _directory(path: str) -> str:
    path = path or "/"
    if path.endswith("/"):
        path = path.rstrip("/") or "/"
    slash = path.rfind("/")
    return path[:slash] or "/"


def _is_page_turn(label: str, absolute: str, page_url: str) -> bool:
    if _NEXT_LABEL.match((label or "").strip()):
        return True
    current = urlparse(page_url)
    nxt = urlparse(absolute)
    same_path = (current.path.rstrip("/") or "/") == (nxt.path.rstrip("/") or "/")
    if _PAGE_PARAM.search(absolute) and same_path:
        return True
    number = (label or "").strip()
    if not _PAGE_NUMBER.match(number):
        return False
    if _host_name(absolute) != _host_name(page_url):
        return False
    if _directory(current.path) == _directory(nxt.path):
        return True
    base = current.path.rstrip("/") or ""
    return (nxt.path.rstrip("/") or "/") == f"{base}/{number}"


def _is_catalog_path(absolute: str) -> bool:
    path = urlparse(absolute).path
    if path in {"", "/"}:
        return False
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        return True
    return suffix not in _SKIP_SUFFIX


def _office_suffix(body: bytes) -> str:
    if body.startswith(b"%PDF"):
        return ".pdf"
    if body.startswith(b"PK\x03\x04"):
        head = body[:12000]
        if b"word/" in head:
            return ".docx"
        if b"xl/" in head:
            return ".xlsx"
    if body.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        head = body[:12000]
        if b"Word.Document" in head or b"WordDocument" in head:
            return ".doc"
    return ""


def continuation_urls(page_html: str, page_url: str) -> list[tuple[str, str]]:
    """目录块里的文件夹，以及任何位置的下一页。导航、页眉、页脚不跟。"""
    page = page_html or ""
    chrome = [(item.start(), item.end()) for item in _CHROME.finditer(page)]
    blocks: list[tuple[int, int, bool]] = []
    for item in _BLOCK.finditer(page):
        if _covered(item.start(), chrome):
            continue
        has_file = False
        for match in _LINK.finditer(item.group(0)):
            href = _href_of(match)
            if _looks_like_file(_plain(match.group(4)), href):
                has_file = True
                break
        blocks.append((item.start(), item.end(), has_file))
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(href: str, label: str, *, turn: bool, folder: bool) -> None:
        absolute = _resolve_link(page_url, href)
        if absolute is None or _looks_like_file(label, href):
            return
        if _page_key(absolute) == _page_key(page_url):
            return
        if not turn and not (folder and _is_catalog_path(absolute)):
            return
        if not turn and _REPLACED.search(label):
            return
        key = _page_key(absolute)
        if key in seen:
            return
        seen.add(key)
        found.append((absolute, label))

    for match in _LINK.finditer(page):
        if _covered(match.start(), chrome):
            continue
        href = _href_of(match)
        label = _plain(match.group(4))
        status = _link_status(page, match.start(), match.end(), label)
        turn = _is_page_turn(label, _join_on_page(page_url, href), page_url)
        inside = False
        has_file = False
        for start, end, block_has_file in blocks:
            if start <= match.start() < end:
                inside = True
                has_file = block_has_file
                break
        folder = inside and (has_file or _is_catalog_path(_join_on_page(page_url, href)))
        if _REPLACED.search(status) and not turn:
            continue
        add(href, label, turn=turn, folder=folder)
    for tag in _LINK_TAG.finditer(page):
        if not _REL_NEXT.search(tag.group(0)):
            continue
        href_match = _HREF_ATTR.search(tag.group(0))
        if href_match is None:
            continue
        href = html.unescape(next(part for part in href_match.groups() if part is not None))
        add(href.strip(), "", turn=True, folder=False)
    return found


def _remember_file(ordered: list[CatalogFile], by_url: dict[str, CatalogFile], item: CatalogFile) -> None:
    current = by_url.get(item.url)
    if current is None:
        by_url[item.url] = item
        ordered.append(item)
        return
    if item.replaced:
        current.replaced = True


def _fetch_page(url: str) -> tuple[str, bytes, str]:
    return _http_get(url, 20.0, _PAGE_BYTES)


def _fetch_json(url: str) -> tuple[str, bytes, str]:
    """检索接口按 JSON 来要。页面壳仍会返回 HTML，这里只改变 Accept。"""
    return _http_get(url, 20.0, _PAGE_BYTES, accept="application/json, text/plain, */*")


def _attr(tag: str, name: str) -> str:
    want = name.lower()
    for match in _ATTR.finditer(tag or ""):
        if match.group(1).lower() != want:
            continue
        raw = next((part for part in match.groups()[1:] if part is not None), "")
        return html.unescape(raw).strip()
    return ""


def _input_hint(tag: str) -> str:
    return " ".join(
        (
            _attr(tag, "placeholder"),
            _attr(tag, "id"),
            _attr(tag, "name"),
            _attr(tag, "class"),
            _attr(tag, "aria-label"),
            _attr(tag, "title"),
        )
    )


def _query_field(tag: str) -> str:
    name = _attr(tag, "name")
    if name and not _SECRET_FIELD.search(name):
        return name
    ident = _attr(tag, "id")
    if ident and not _SECRET_FIELD.search(ident):
        return ident
    return "keyword"


def _loose_search_input(
    page_html: str, page_url: str
) -> tuple[str, str, str, list[tuple[str, str]]] | None:
    """不在 form 里的搜索栏。占位、类型或旁边的搜索按钮都能认出。"""
    page = page_html or ""
    tags = [(item.start(), item.end(), item.group(0)) for item in _INPUT.finditer(page)]
    tags.extend((item.start(), item.end(), item.group(0)) for item in _WIDGET.finditer(page))
    best: tuple[int, str] | None = None
    for start, end, tag in tags:
        kind = (_attr(tag, "type") or "text").lower()
        if kind in {"hidden", "password", "submit", "button", "checkbox", "radio", "file", "image"}:
            continue
        if kind not in {"text", "search", ""} and not tag.lower().startswith("<textarea"):
            continue
        name = _attr(tag, "name")
        if name and _SECRET_FIELD.search(name):
            continue
        hint = _input_hint(tag)
        nearby = page[max(0, start - 300):end + 500]
        if kind != "search" and not _SEARCH_HINT.search(f"{hint} {nearby}") and not _SEARCH_BUTTON.search(nearby):
            continue
        score = 3 if kind == "search" else (2 if _SEARCH_HINT.search(hint) else 1)
        if best is None or score > best[0]:
            best = (score, _query_field(tag))
    if best is None:
        return None
    try:
        action_url = public_http_url(page_url)
    except ValueError:
        return None
    return action_url, best[1], "get", []


def _login_page(page_html: str) -> bool:
    """页面上是密码框、没有检索框时，登录还没完成。"""
    for tag in _INPUT.finditer(page_html or ""):
        if (_attr(tag.group(0), "type") or "").lower() == "password":
            return True
    return False


def _edge_path() -> str:
    names = (
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    )
    for root in names:
        if not root:
            continue
        path = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if path.is_file():
            return str(path)
    return ""


def _browser_path() -> str:
    edge = _edge_path()
    if edge:
        return edge
    names = (
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    )
    for root in names:
        if not root:
            continue
        path = Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
        if path.is_file():
            return str(path)
    return ""


def _clip(text: str, limit: int = 40) -> str:
    return " ".join((text or "").split())[:limit]


def _page_facts(page_html: str, label: str) -> list[str]:
    """给检测日志的页面事实。不写输入框里的值，方便事后改检索判断。"""
    text = page_html or ""
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    title = _clip(_plain(title_match.group(1)) if title_match else "无标题")
    shell = "是空壳" if _page_is_shell(text) else "不是空壳"
    password = "有密码框" if _login_page(text) else "没有密码框"
    plain = _plain(text)
    words = [word for word in ("标准号", "文件名称", "文件名", "搜索", "检索", "查询", "请登录", "登录", "密码") if word in plain]
    lines = [
        (
            f"{label}：标题「{title}」，正文 {len(text)} 字，{shell}，{password}。"
            f"页面文字里出现：{'、'.join(words) if words else '这些词都没有'}。"
        )
    ]
    inputs: list[str] = []
    for index, tag in enumerate(_INPUT.finditer(text), 1):
        raw = tag.group(0)
        kind = (_attr(raw, "type") or "text").lower()
        if kind == "password":
            inputs.append(f"{index}. type=password")
            continue
        inputs.append(
            f"{index}. type={kind}，占位={_clip(_attr(raw, 'placeholder')) or '无'}，"
            f"name={_clip(_attr(raw, 'name')) or '无'}，id={_clip(_attr(raw, 'id')) or '无'}，"
            f"class={_clip(_attr(raw, 'class')) or '无'}"
        )
    for tag in re.finditer(r"(?is)<textarea\b[^>]*>", text):
        raw = tag.group(0)
        inputs.append(
            f"textarea，占位={_clip(_attr(raw, 'placeholder')) or '无'}，name={_clip(_attr(raw, 'name')) or '无'}"
        )
    if not inputs:
        lines.append(f"{label}的输入框：没有。")
    else:
        current = f"{label}的输入框共 {len(inputs)} 个。"
        for item in inputs:
            piece = item + "。"
            if len(current) + len(piece) > 650:
                lines.append(current if current.endswith("。") else current + "。")
                current = f"{label}的输入框续。"
            current += piece
        lines.append(current if current.endswith("。") else current + "。")
    frames = []
    for tag in re.finditer(r"(?is)<iframe\b[^>]*>", text):
        frames.append(_clip(_attr(tag.group(0), "src"), 80) or "无地址")
        if len(frames) >= 6:
            break
    lines.append(
        f"{label}的框架页 {len(frames)} 个：{'、'.join(frames) if frames else '没有'}。"
    )
    buttons = []
    for tag in re.finditer(r"(?is)<button\b[^>]*>.*?</button>", text):
        name = _clip(_plain(tag.group(0)), 20)
        if name and any(word in name for word in ("搜索", "检索", "查询", "登录")):
            buttons.append(name)
        if len(buttons) >= 6:
            break
    lines.append(f"{label}里相关按钮：{'、'.join(buttons) if buttons else '没有'}。")
    scripts = [
        _clip(_attr(tag.group(0), "src"), 80)
        for tag in re.finditer(r"(?is)<script\b[^>]*\bsrc\s*=[^>]*>", text)
    ]
    scripts = [item for item in scripts if item][:4]
    lines.append(
        f"{label}外链脚本 {len(scripts)} 个：{'、'.join(scripts) if scripts else '没有'}。"
    )
    return lines


def _describe_page(page_html: str) -> str:
    """写成日志能看懂的一句：标题、是不是空壳、输入框长什么样。不写输入框里的值。"""
    text = page_html or ""
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    title = _plain(title_match.group(1))[:40] if title_match else "无标题"
    samples: list[str] = []
    count = 0
    for tag in _INPUT.finditer(text):
        count += 1
        if len(samples) >= 4:
            continue
        raw = tag.group(0)
        kind = (_attr(raw, "type") or "text").lower()
        if kind == "password":
            samples.append("password")
            continue
        hint = (
            _attr(raw, "placeholder")
            or _attr(raw, "name")
            or _attr(raw, "id")
            or _attr(raw, "class")
        )
        samples.append(f"{kind}「{(hint or '无占位')[:24]}」")
    widgets = len(_WIDGET.findall(text))
    shell = "是空壳" if _page_is_shell(text) else "不是空壳"
    shown = "、".join(samples) if samples else "没有"
    return (
        f"页面标题是「{title}」，正文 {len(text)} 字，{shell}，"
        f"输入框 {count} 个：{shown}，组件 {widgets} 个。"
    )


def _page_is_shell(page_html: str) -> bool:
    """单页应用刚载入时只有空壳，检索框还没画出来。"""
    text = page_html or ""
    lowered = text.lower()
    if "<input" in lowered or "<textarea" in lowered or "<el-input" in lowered:
        return False
    return 'id="app"' in lowered or "id='app'" in lowered or len(text) < 800


def _browser_error(text: str) -> str:
    line = " ".join((text or "").split())
    line = re.sub(r"ws://\S+", "调试端口", line)
    return (line or "空")[:80]


def _dump_dom(edge: str, url: str, flags: list[str]) -> tuple[str, str]:
    mode = " ".join(flags) or "默认"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="etest-edge-") as folder:
        cmd = [
            edge,
            *flags,
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            f"--user-data-dir={folder}",
            "--virtual-time-budget=20000",
            "--dump-dom",
            url,
        ]
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=45, check=False)
        except subprocess.TimeoutExpired:
            return "", f"浏览器模式 {mode} 等待超过 45 秒，没有交出页面。"
        except OSError as exc:
            return "", f"浏览器模式 {mode} 没有启动。原因是 {_browser_error(str(exc))}。"
    elapsed = time.monotonic() - started
    text = done.stdout.decode("utf-8", errors="replace")
    err = done.stderr.decode("utf-8", errors="replace")
    if "<html" not in text.lower() and "<input" not in text.lower():
        start = err.lower().find("<html")
        if start < 0:
            start = err.lower().find("<!doctype")
        if start >= 0:
            text = err[start:]
    if "<" not in text:
        return "", (
            f"浏览器模式 {mode} 退出码 {done.returncode}，用时 {elapsed:.0f} 秒，没有页面正文。"
            f"浏览器输出：{_browser_error(err)}。"
        )
    return text, (
        f"浏览器模式 {mode} 退出码 {done.returncode}，用时 {elapsed:.0f} 秒。{_describe_page(text)}"
    )


_PAINT_SCRIPT = """
(() => {
  const found = [];
  const visit = (node) => {
    if (!node || !node.querySelectorAll) return;
    node.querySelectorAll("input,textarea").forEach((el) => {
      const kind = String(el.type || "text").replace(/"/g, "");
      const hint = String(el.placeholder || el.name || el.id || el.className || "").replace(/"/g, "'");
      found.push("<input type='" + kind + "' placeholder='" + hint.slice(0, 40) + "'>");
    });
    node.querySelectorAll("*").forEach((el) => { if (el.shadowRoot) visit(el.shadowRoot); });
  };
  visit(document);
  const html = document.documentElement ? document.documentElement.outerHTML : "";
  return html + found.join("");
})()
"""


def _ws_send(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    size = len(payload)
    if size < 126:
        header.append(0x80 | size)
    elif size < 65536:
        header.append(0x80 | 126)
        header.extend(size.to_bytes(2, "big"))
    else:
        header.append(0x80 | 127)
        header.extend(size.to_bytes(8, "big"))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _ws_recv(sock: socket.socket) -> str:
    def read(size: int) -> bytes:
        buf = b""
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise OSError("浏览器调试连接已断开。")
            buf += chunk
        return buf

    first, second = read(2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(read(2), "big")
    elif length == 127:
        length = int.from_bytes(read(8), "big")
    if second & 0x80:
        mask = read(4)
        data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(read(length)))
    else:
        data = read(length)
    if opcode == 8:
        raise OSError("浏览器调试连接已关闭。")
    if opcode != 1:
        return ""
    return data.decode("utf-8", errors="replace")


def _stop_browser(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


def _paint_until_input(edge: str, url: str) -> tuple[str, str]:
    """等页面脚本把输入框画出来再取页面。不读 Cookie，不填登录。"""
    started = time.monotonic()
    html = ""
    with tempfile.TemporaryDirectory(prefix="etest-edge-", ignore_cleanup_errors=True) as folder:
        cmd = [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-extensions",
            "--remote-debugging-port=0",
            f"--user-data-dir={folder}",
            url,
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        except OSError as exc:
            return "", f"调试端口没有启动浏览器。原因是 {_browser_error(str(exc))}。"
        port = ""
        err_lines: list[str] = []

        def read_err() -> None:
            if proc.stderr is None:
                return
            for line in proc.stderr:
                err_lines.append(line)

        threading.Thread(target=read_err, daemon=True).start()
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                err = "".join(err_lines)
                found = re.search(r"127\.0\.0\.1:(\d+)", err)
                if found and "DevTools" in err:
                    port = found.group(1)
                    break
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
            err = "".join(err_lines)
            if not port:
                return "", (
                    f"浏览器没有打开调试端口，退出码 {proc.poll()}。"
                    f"浏览器输出：{_browser_error(err)}。"
                )
            page_url = ""
            for _ in range(20):
                try:
                    with httpx.Client(trust_env=False, timeout=2) as client:
                        targets = client.get(f"http://127.0.0.1:{port}/json/list").json()
                except (httpx.HTTPError, ValueError):
                    time.sleep(0.4)
                    continue
                for item in targets if isinstance(targets, list) else []:
                    if item.get("type") == "page" and item.get("webSocketDebuggerUrl"):
                        page_url = str(item["webSocketDebuggerUrl"])
                        break
                if page_url:
                    break
                time.sleep(0.4)
            if not page_url:
                return "", f"调试端口 {port} 已打开，但没有页面目标。{_browser_error(err)}。"
            parsed = urlparse(page_url)
            sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=5)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            sock.sendall(
                (
                    f"GET {parsed.path or '/'} HTTP/1.1\r\n"
                    f"Host: {parsed.hostname}:{parsed.port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode("ascii")
            )
            shake = b""
            while b"\r\n\r\n" not in shake:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                shake += chunk
            if b" 101 " not in shake.split(b"\r\n", 1)[0]:
                sock.close()
                return "", "调试端口已打开，但页面连接没有建立。"
            msg_id = 0
            try:
                while time.monotonic() - started < 25:
                    msg_id += 1
                    sock.settimeout(8)
                    _ws_send(sock, json.dumps({
                        "id": msg_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": _PAINT_SCRIPT, "returnByValue": True},
                    }))
                    data = json.loads(_ws_recv(sock) or "{}")
                    value = ((data.get("result") or {}).get("result") or {}).get("value")
                    if isinstance(value, str) and value:
                        html = value
                        if "<input" in value.lower() or "<textarea" in value.lower():
                            break
                    time.sleep(1)
            finally:
                sock.close()
        except (OSError, TimeoutError, json.JSONDecodeError, httpx.HTTPError) as exc:
            return "", f"调试端口读取页面没有完成。原因是 {_browser_error(str(exc))}。"
        finally:
            _stop_browser(proc)
    elapsed = time.monotonic() - started
    if not html:
        return "", f"调试端口等待 {elapsed:.0f} 秒，没有读到页面正文。"
    return html, f"调试端口等待 {elapsed:.0f} 秒。{_describe_page(html)}"


def _rendered_page(url: str) -> tuple[str, list[str]]:
    """把给定网址画出来，等到脚本生成检索框。不读 Cookie，不填登录。"""
    notes: list[str] = []
    browser = _browser_path()
    if not browser:
        notes.append("脚本第 2 步没有启动浏览器。本机找不到 Edge 或 Chrome，页面脚本没有执行。")
        return "", notes
    try:
        target = public_http_url(url)
    except ValueError as exc:
        notes.append(f"脚本第 2 步没有启动浏览器。网址不能打开：{exc}")
        return "", notes
    notes.append(f"脚本第 2 步启动浏览器 {browser}。不读取已有登录状态，等待页面把检索框画出来。")
    html, line = _paint_until_input(browser, target)
    notes.append(line)
    if html and find_search_form(html, target):
        notes.append("调试端口画出的页面里找到了检索框。")
        return html, notes
    dump_html, dump_line = _dump_dom(browser, target, ["--headless=old"])
    notes.append(dump_line)
    if dump_html and find_search_form(dump_html, target):
        notes.append("旧版无头画出的页面里找到了检索框。")
        return dump_html, notes
    chosen = dump_html if len(dump_html) > len(html) else html
    if chosen and not find_search_form(chosen, target):
        notes.append(f"两次绘制之后仍然没有对上检索框。{_describe_page(chosen)}")
    return chosen, notes


def find_search_form(
    page_html: str, page_url: str
) -> tuple[str, str, str, list[tuple[str, str]]] | None:
    """返回 (提交地址, 检索字段, 方法, 隐藏字段)。含密码的表单不作为检索。"""
    best: tuple[int, str, str, str, list[tuple[str, str]]] | None = None
    for form in _FORM.finditer(page_html or ""):
        body = form.group(0)
        opening = _FORM_OPEN.match(body)
        inputs = [item.group(0) for item in _INPUT.finditer(body)]
        inputs.extend(item.group(0) for item in re.finditer(r"(?is)<textarea\b[^>]*>", body))
        if any((_attr(tag, "type") or "").lower() == "password" for tag in inputs):
            continue
        text_fields: list[tuple[int, str]] = []
        hidden: list[tuple[str, str]] = []
        for tag in inputs:
            named = _attr(tag, "name")
            if named and _SECRET_FIELD.search(named):
                continue
            kind = (_attr(tag, "type") or "text").lower()
            if kind == "hidden":
                if named:
                    hidden.append((named, _attr(tag, "value")))
                continue
            if kind not in {"text", "search", ""} and not tag.lower().startswith("<textarea"):
                continue
            hint = _input_hint(tag)
            if not named and kind != "search" and not _SEARCH_HINT.search(hint):
                continue
            field = named or _query_field(tag)
            score = 2 if _SEARCH_FIELD.search(hint) or _SEARCH_HINT.search(hint) else 1
            text_fields.append((score, field))
        if not text_fields:
            continue
        text_fields.sort(key=lambda item: item[0], reverse=True)
        action = _attr(opening.group(0) if opening else body, "action") or page_url
        method = (_attr(opening.group(0) if opening else body, "method") or "get").lower()
        if method not in {"get", "post"}:
            method = "get"
        try:
            joined = action if urlparse(action).scheme else _join_on_page(page_url, action)
            action_url = public_http_url(joined)
        except ValueError:
            continue
        rank = text_fields[0][0]
        if best is None or rank > best[0]:
            best = (rank, action_url, text_fields[0][1], method, hidden)
    if best is None:
        return _loose_search_input(page_html, page_url)
    return best[1], best[2], best[3], best[4]


def search_queries(items: list[ManualItem]) -> list[str]:
    """检索框只填标准号。这一行没有标准号时，改填文件名称。"""
    found: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        query = re.sub(r"\s+", "", text or "")
        if len(query) < 2 or query.upper() in seen:
            return
        seen.add(query.upper())
        found.append(query)

    for item in items:
        lookup_standard = getattr(item, "lookup_standard", "") or ""
        token = _STD_TOKEN.search(lookup_standard) or _STD_TOKEN.search(item.standard or "")
        if token:
            add(token.group(0))
            continue
        add(getattr(item, "lookup_file", "") or item.standard or "")
    return found


def lookup_messages(items: list[ManualItem]) -> list[dict[str, str]]:
    """把测试表交给模型，只抽要检索的标准号和文件名。"""
    lines = ["序号\t阶段\t项目编号\t试验项目\t标准号及名称"]
    for index, item in enumerate(items[:160]):
        lines.append(
            "\t".join(
                (
                    str(index),
                    item.stage,
                    item.number,
                    item.name,
                    item.standard,
                )
            )
        )
    return [
        {
            "role": "system",
            "content": (
                "你只从用户给出的测试表里抽出每一行要去标准库检索的标准号和文件名称。"
                "不要编造表里没有的标准，不要改试验项目。"
                "只输出一个 JSON 数组，每项含 i、standard_no、file_name。"
                "standard_no 是标准号，file_name 是对应文件名。没有就用空字符串。"
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]


def apply_lookup_terms(items: list[ManualItem], text: str) -> int:
    """把模型抽出的标准号和文件名写回对应行。"""
    match = re.search(r"\[\s*\{.*\}\s*\]", text or "", re.S)
    if match is None:
        return 0
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, list):
        return 0
    written = 0
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("i"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items):
            continue
        standard_no = str(row.get("standard_no") or "").strip()
        file_name = str(row.get("file_name") or "").strip()
        if standard_no:
            items[index].lookup_standard = standard_no[:80]
        if file_name:
            items[index].lookup_file = file_name[:80]
        if standard_no or file_name:
            written += 1
    return written


def _with_query(url: str, pairs: list[tuple[str, str]]) -> str:
    parsed = urlparse(url)
    replaced = {key for key, _value in pairs}
    merged = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key not in replaced]
    merged.extend(pairs)
    return parsed._replace(query=urlencode(merged)).geturl()


def crawl_catalog(
    url: str,
    *,
    fetch=None,
    max_pages: int = _MAX_PAGES,
    deadline: float | None = None,
) -> tuple[str, list[CatalogFile], str]:
    """从文件站页面往下翻目录，收集标准文件。同一页不重复读，不提交登录。"""
    start = (url or "").strip()
    if not start:
        return "", [], "网址尚未提供，未抓取网页。"
    opener = fetch or _fetch_page
    first = public_http_url(start)
    queue = [first]
    queued = {_page_key(first)}
    seen: set[str] = set()
    hints: dict[str, str] = {}
    ordered: list[CatalogFile] = []
    by_url: dict[str, CatalogFile] = {}
    landed = ""
    read_pages = 0
    stopped = False
    while queue:
        if read_pages >= max_pages or (deadline is not None and time.monotonic() > deadline):
            stopped = True
            break
        current = queue.pop(0)
        key = _page_key(current)
        if key in seen:
            continue
        seen.add(key)
        try:
            final, raw, _note = opener(current)
        except ValueError:
            if read_pages == 0 and not ordered:
                raise
            continue
        read_pages += 1
        base = final or current
        if not landed:
            landed = base
        seen.add(_page_key(base))
        body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
        suffix = _office_suffix(body)
        if suffix:
            hint = hints.get(key) or hints.get(_page_key(base)) or ""
            name = hint or Path(urlparse(base).path).name or "标准文件"
            if Path(name).suffix.lower() not in _FILE_SUFFIX:
                name = f"{name}{suffix}"
            try:
                file_url = public_http_url(base)
            except ValueError:
                continue
            _remember_file(ordered, by_url, CatalogFile(name, file_url, False))
            continue
        text = body.decode("utf-8", errors="replace")
        for item in parse_catalog(text, base):
            _remember_file(ordered, by_url, item)
        for nxt, label in continuation_urls(text, base):
            nkey = _page_key(nxt)
            if nkey in seen or nkey in queued:
                continue
            hints.setdefault(nkey, label)
            queued.add(nkey)
            queue.append(nxt)
    note = f"已读取 {read_pages} 页，列出 {len(ordered)} 个文件。"
    if stopped:
        note += "后续页没有继续读。"
    return landed, ordered, note


_SCRIPT_SRC = re.compile(
    r"(?is)<script\b[^>]*\bsrc\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"'>]+))"
)
_QUOTED_PATH = re.compile(
    r"""["']((?:https?:)?(?://[^"'\\\s]{1,80})?/[^"'\\\s]{3,160})["']"""
)
_API_HINT = re.compile(
    r"(search|query|standard|filelist|doclist|pagelist|getlist|selectpage|retrieve)",
    re.I,
)
_JS_REF = re.compile(r"""["']([^"'\\\s]{2,180}\.js(?:\?[^"'\\\s]*)?)["']""", re.I)
_PARAM_NAME = re.compile(
    r"""["'](keyword|fileName|standardNo|standardName|standardCode|searchValue|docName|fileTitle)["']""",
    re.I,
)
_SEARCH_PARAMS = ("standardNo", "fileName", "keyword")
_REQUEST_URL = re.compile(r"""\burl\s*:\s*["']([^"']+)["']""", re.I)
_BASE_API = re.compile(
    r"""["']?(?:baseURL|baseUrl|BASE_API|baseApi)["']?\s*[:=]\s*["'](/[^"'?#\s]{1,40})["']""",
    re.I,
)
_FILE_KEYS = ("fileName", "filename", "name", "title", "standardName", "docName", "fileTitle")
_URL_KEYS = ("url", "fileUrl", "downloadUrl", "path", "filePath", "href", "filePathName")


def _script_urls(page_html: str, page_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _SCRIPT_SRC.finditer(page_html or ""):
        href = html.unescape(next(part for part in match.groups() if part is not None)).strip()
        if not href or Path(urlparse(href).path).suffix.lower() != ".js":
            continue
        absolute = _resolve_link(page_url, href)
        if absolute is None or absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
    found.sort(key=_script_rank)
    return found[:8]


def _script_rank(url: str) -> int:
    low = url.lower()
    if any(word in low for word in ("vendor", "polyfill", "runtime", "echarts", "element")):
        return 2
    if any(word in low for word in ("app", "index", "standard", "search", "main")):
        return 0
    return 1


def _js_refs(text: str, page_url: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _JS_REF.finditer(text or ""):
        href = match.group(1).strip()
        if href.startswith(("data:", "blob:", "javascript:")):
            continue
        absolute = _resolve_link(page_url, href)
        if absolute is None or absolute in seen:
            continue
        low = absolute.lower()
        if any(word in low for word in ("node_modules", "/static/css", "jquery", "echarts")):
            continue
        seen.add(absolute)
        found.append(absolute)
    found.sort(key=_script_rank)
    return found


def _api_rank(path: str) -> int:
    low = path.lower().rstrip("/")
    if any(low.endswith("/" + name) or f"/{name}" in low for name in ("search", "query", "list", "page")):
        return 0
    if low.count("/") <= 1:
        return 3
    if "standard" in low:
        return 1
    return 2


def _list_paths(path: str) -> list[str]:
    """页面路由补上列表接口。/enterpriseStandard 会再试 /list、/page、/query、/search。"""
    clean = path.split("?")[0].rstrip("/")
    if not clean.startswith("/") and "://" not in clean:
        return [clean]
    tail = Path(urlparse(clean).path).name.lower()
    if tail in {"list", "page", "query", "search", "getlist", "selectpage", "pagelist"}:
        return [clean]
    segments = [part for part in urlparse(clean).path.split("/") if part]
    if len(segments) > 2 or _API_HINT.search(clean) is None:
        return [clean]
    return [clean, *[f"{clean}/{suffix}" for suffix in ("list", "page", "query", "search")]]


def _api_prefixes(texts: list[str]) -> list[str]:
    """脚本里的 baseURL。/enterpriseStandard/list 实际常在 /prod-api 后面。"""
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _BASE_API.finditer(text or ""):
            prefix = match.group(1).rstrip("/")
            if prefix in seen or prefix in {"/", "/home", "/static", "/assets"}:
                continue
            seen.add(prefix)
            found.append(prefix)
    return found[:4]


def _with_api_prefix(path: str, prefixes: list[str]) -> list[str]:
    if not path.startswith("/") or "://" in path:
        return [path]
    extra = [
        f"{prefix}{path}"
        for prefix in prefixes
        if not path.startswith(prefix + "/") and path != prefix
    ]
    return [*extra, path]


def _is_app_shell(raw: bytes | str) -> bool:
    body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
    text = body.decode("utf-8", errors="replace")[:6000].lower()
    return 'id="app"' in text or "id='app'" in text or "<div id=app" in text


def _reply_hint(raw: bytes, error: str = "") -> str:
    if error:
        return " ".join(error.split())[:80]
    if not raw:
        return "empty"
    text = raw.decode("utf-8", errors="replace").lstrip()
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return "json"
        if isinstance(data, dict):
            code = data.get("code", data.get("status", ""))
            msg = data.get("msg") or data.get("message") or ""
            return f"json code={code} msg={str(msg)[:40]}"
        return "json"
    if _is_app_shell(raw):
        return "html-shell"
    if text.startswith("<"):
        return "html"
    return "text"


def _mentions_query(raw: bytes | str, query: str) -> bool:
    body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
    text = re.sub(r"\s+", "", body.decode("utf-8", errors="replace")).upper()
    token = re.sub(r"\s+", "", query or "").upper()
    if len(token) >= 4 and token in text:
        return True
    for number in re.findall(r"J\d{4,}[A-Z0-9-]*", token):
        if number in text:
            return True
    return False


def _json_query(field: str, query: str) -> dict[str, object]:
    return {field: query, "pageNum": 1, "pageSize": 50, "page": 1, "size": 50, "current": 1}


def _discover_search(page_html: str, page_url: str, fetch) -> tuple[list[str], list[str]]:
    """检索框由脚本画出来时，从页面脚本和它引用的脚本里找接口。"""
    texts = [page_html or ""]
    queue = _script_urls(page_html, page_url)
    seen_script = set(queue)
    fetched = 0
    while queue and fetched < 16:
        url = queue.pop(0)
        try:
            _final, raw, _note = fetch(url)
        except ValueError:
            continue
        fetched += 1
        body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
        text = body.decode("utf-8", errors="replace")[:2_000_000]
        texts.append(text)
        for extra in _js_refs(text, url):
            if extra in seen_script or len(seen_script) >= 24:
                continue
            seen_script.add(extra)
            queue.append(extra)
        queue.sort(key=_script_rank)
    endpoints: list[str] = []
    params: list[str] = []
    seen_url: set[str] = set()
    seen_param: set[str] = set()
    prefixes = _api_prefixes(texts)
    ranked: list[tuple[int, int, str]] = []
    for text in texts:
        for match in _PARAM_NAME.finditer(text):
            name = match.group(1)
            if name.lower() in seen_param:
                continue
            seen_param.add(name.lower())
            params.append(name)
        for match in list(_REQUEST_URL.finditer(text)) + list(_QUOTED_PATH.finditer(text)):
            path = match.group(1).split("?")[0]
            if "{" in path or "$" in path or "*" in path:
                continue
            if Path(urlparse(path).path).suffix.lower() in _SKIP_SUFFIX | {".js", ".css", ".map", ".vue"}:
                continue
            low = path.lower()
            if any(word in low for word in ("/static/", "/assets/", "node_modules", "webpack")):
                continue
            if _API_HINT.search(path) is None:
                continue
            for item in _list_paths(path):
                for expanded in _with_api_prefix(item, prefixes):
                    prefixed = 0 if any(expanded.startswith(prefix + "/") for prefix in prefixes) else 1
                    ranked.append((prefixed, _api_rank(expanded), expanded))
    ranked.sort(key=lambda item: (item[0], item[1], len(item[2])))
    for _prefixed, _rank, path in ranked:
        absolute = _resolve_link(page_url, path)
        if absolute is None or absolute in seen_url:
            continue
        seen_url.add(absolute)
        endpoints.append(absolute)
        if len(endpoints) >= 12:
            break
    for name in _SEARCH_PARAMS:
        if name.lower() not in seen_param:
            params.append(name)
    return endpoints, params[:6]


def _json_files(node: object, page_url: str) -> list[CatalogFile]:
    found: list[CatalogFile] = []

    def walk(item: object) -> None:
        if isinstance(item, dict):
            name = next((str(item[key]).strip() for key in _FILE_KEYS if str(item.get(key) or "").strip()), "")
            number = next(
                (
                    str(item[key]).strip()
                    for key in ("standardNo", "standardCode", "stdNo", "docNo")
                    if _STD_NUM.search(str(item.get(key) or ""))
                ),
                "",
            )
            if number and not _STD_NUM.search(name):
                name = number
            url = next((str(item[key]).strip() for key in _URL_KEYS if str(item.get(key) or "").strip()), "")
            if name and url and (_looks_like_file(name, url) or _STD_NUM.search(name) or _STD_NUM.search(url)):
                absolute = _resolve_link(page_url, url)
                if absolute is not None:
                    status = " ".join(str(item.get(key) or "") for key in ("status", "state", "replaceStatus"))
                    found.append(CatalogFile(name, absolute, bool(_REPLACED.search(f"{name} {status}"))))
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return found


def _response_files(raw: bytes | str, page_url: str) -> list[CatalogFile]:
    body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
    text = body.decode("utf-8", errors="replace").strip()
    if text.startswith("{") or text.startswith("["):
        try:
            return _json_files(json.loads(text), page_url)
        except json.JSONDecodeError:
            pass
    return parse_catalog(text, page_url)


def _search_page_files(url: str, fetch, deadline: float | None) -> tuple[list[CatalogFile], str]:
    final, raw, _note = fetch(url)
    body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
    text = body.decode("utf-8", errors="replace").strip()
    page = final or url
    if text.startswith("{") or text.startswith("["):
        try:
            return _json_files(json.loads(text), page), ""
        except json.JSONDecodeError:
            pass

    def fetch_once(current: str, _body: bytes = body, _page: str = page, _url: str = url):
        if _page_key(current) == _page_key(_page) or _page_key(current) == _page_key(_url):
            return _page, _body, "已读取网址。"
        return fetch(current)

    _landed, found, note = crawl_catalog(url, fetch=fetch_once, deadline=deadline)
    return found, note


def _probe_query(queries: list[str]) -> str:
    """用最短的标准号去试接口。整句试验名称对不上时，不要拿它当第一个检索词。"""
    numbered = [query for query in queries if _STD_NUM.search(query)]
    if numbered:
        return min(numbered, key=len)
    return queries[0] if queries else ""


def _needs_login(hint: str) -> bool:
    low = hint.lower()
    if "code=401" in low or "code=403" in low:
        return True
    return any(word in hint for word in ("未登录", "认证失败", "请登录", "无效token", "token无效"))


def _probe_search(
    endpoints: list[str],
    params: list[str],
    query: str,
    fetch,
    post_json,
    deadline: float | None,
    on_step=None,
) -> tuple[str, str, str, str]:
    """先用地址参数试，再用 JSON。页面壳不算检索结果，返回里要有这个标准号。"""
    reports: list[str] = []
    for action in endpoints:
        if deadline is not None and time.monotonic() > deadline:
            return "", "", "", "；".join(reports[:3])
        tried: list[str] = []
        for field in params[:4]:
            hint = ""
            try:
                url = public_http_url(_with_query(action, [(field, query)]))
                final, raw, _note = fetch(url)
                hint = _reply_hint(raw)
            except ValueError as exc:
                final, raw, hint = "", b"", _reply_hint(b"", str(exc))
            if raw and not _is_app_shell(raw) and _mentions_query(raw, query):
                found = _response_files(raw, final or url)
                if found:
                    return action, field, "get", ""
                hint = f"{hint}，有标准号但没有文件地址"
            try:
                posted, payload, _note = post_json(action, _json_query(field, query))
                posted_hint = _reply_hint(payload)
            except ValueError as exc:
                posted, payload, posted_hint = "", b"", _reply_hint(b"", str(exc))
            if payload and not _is_app_shell(payload) and _mentions_query(payload, query) and _response_files(payload, posted or action):
                return action, field, "json", ""
            if payload and not _is_app_shell(payload) and _mentions_query(payload, query):
                posted_hint = f"{posted_hint}，有标准号但没有文件地址"
            tried.append(f"字段 {field}：GET {hint or '空'}，JSON {posted_hint or '空'}")
        path = urlparse(action).path or action
        line = f"接口 {path} 没有带回文件。" + "；".join(tried)
        reports.append(line)
        if on_step:
            on_step("search", line)
    return "", "", "", "；".join(reports[:2])


def collect_for_manual(
    page_url: str,
    manual: list[ManualItem],
    *,
    fetch=None,
    post=None,
    post_json=None,
    deadline: float | None = None,
    on_step=None,
) -> tuple[str, list[CatalogFile], str]:
    """把每个检索词和它的结果页读完。调用方给出截止时间时才提前停下。"""
    start = (page_url or "").strip()
    if not start:
        return "", [], "网址尚未提供，未抓取网页。"
    limit = deadline
    opener = fetch or _fetch_page
    poster = post or _http_post_form
    poster_json = post_json or _http_post_json
    start_url = public_http_url(start)

    def tell(step: str, sentence: str) -> None:
        if on_step:
            on_step(step, sentence)

    final, raw, _note = opener(start_url)
    body = raw.encode("utf-8") if isinstance(raw, str) else (raw or b"")
    text = body.decode("utf-8", errors="replace")
    base = final or start_url
    tell(
        "find",
        f"脚本第 1 步：打开给定网址。请求地址是 {start_url}，最终停在 {base}。页面正文约 {len(text)} 字。不带账号、密码和 Cookie。",
    )
    form = find_search_form(text, base)
    for line in _page_facts(text, "源码"):
        tell("find", line)
    tell(
        "find",
        "源码检索判断："
        + ("认出了检索框。" if form else "没有认出检索框。判断只看输入框标签、占位、名称和旁边的搜索字样，不看屏幕。"),
    )
    drawn = False
    if form is None and fetch is None:
        tell("find", "脚本第 2 步：页面源码里没有检索框。用浏览器把这个网址画出来再找，不读取浏览器里已有的登录状态。")
        rendered, notes = _rendered_page(start_url)
        for line in notes:
            tell("find", line)
        drawn = bool(rendered)
        if rendered:
            text = rendered
            form = find_search_form(text, base)
            for line in _page_facts(text, "画出的页面"):
                tell("find", line)
            tell(
                "find",
                "画出的页面检索判断："
                + ("认出了检索框。" if form else "没有认出检索框。判断只看画出的 HTML，不看屏幕。"),
            )
        else:
            tell("find", "画出的页面没有正文，所以没有输入框可以对照。")
    queries = search_queries(manual)
    if form is None or not queries:
        if not queries:
            note = "测试表里没有可检索的标准号或文件名。"
        elif _login_page(text):
            note = "登录尚未完成，未读取文件。"
        else:
            note = "给定网址上没有找到检索框。未按搜索结果取文件。"
        where = "浏览器画出的页面" if drawn else "打开后的页面"
        tell("search", f"脚本停在找检索框。{where}的结论是：{note}{_describe_page(text)}")
        return base, [], note
    action, field, method, hidden = form
    shown = "、".join(queries[:6])
    if len(queries) > 6:
        shown += f" 等 {len(queries)} 个"
    tell(
        "search",
        f"脚本第 3 步：找到检索框。提交方式是 {method}，字段是 {field}，地址是 {action}。准备填入 {len(queries)} 个标准号或文件名：{shown}。",
    )
    action, field, method, hidden = form
    ordered: list[CatalogFile] = []
    by_url: dict[str, CatalogFile] = {}
    ran = 0
    errors: list[ValueError] = []
    stopped = False
    for index, query in enumerate(queries, 1):
        tell(
            "search",
            f"脚本第 4 步：把第 {index}/{len(queries)} 个检索词填进检索框。检索词是「{query}」，字段是 {field}，方式是 {method}。",
        )
        if limit is not None and time.monotonic() > limit:
            stopped = True
            break
        try:
            if method == "post":
                posted, payload, _note = poster(action, {**dict(hidden), field: query})
            elif method == "json":
                posted, payload, _note = poster_json(action, _json_query(field, query))
            else:
                posted, payload = "", None
            if method in {"post", "json"}:
                holder: dict[str, object] = {"url": posted or action, "body": payload}

                def fetch_result(url: str, _holder: dict[str, object] = holder):
                    cached = _holder.get("body")
                    if cached is not None and _page_key(url) == _page_key(str(_holder["url"])):
                        _holder["body"] = None
                        return str(_holder["url"]), cached, "已读取网址。"
                    return opener(url)

                crawl_url = str(holder["url"])
                crawl_fetch = fetch_result
            else:
                crawl_url = public_http_url(_with_query(action, [*hidden, (field, query)]))
                crawl_fetch = opener
            found, page_note = _search_page_files(crawl_url, crawl_fetch, limit)
        except ValueError as exc:
            errors.append(exc)
            tell("search", f"检索词「{query}」没有读成搜索结果。原因是 {exc}")
            continue
        ran += 1
        if "没有继续读" in page_note:
            stopped = True
        names = "、".join(item.name for item in found[:6]) or "没有文件"
        tell(
            "search",
            f"检索词「{query}」的搜索结果页是 {crawl_url}。这一页列出 {len(found)} 个文件：{names}。",
        )
        for item in found:
            _remember_file(ordered, by_url, item)
        if stopped:
            break
    if not ordered and errors and not stopped:
        raise errors[-1]
    note = f"已在检索框填入 {ran} 个标准号或文件名，搜索结果列出 {len(ordered)} 个文件。"
    if stopped:
        note += "读取时间到了，已停下。"
    tell("search", f"脚本第 4 步结束。{note}")
    return base, ordered, note


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


def _folded(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text or "")


def files_for_table(files: list[CatalogFile], manual_text: str) -> list[CatalogFile]:
    """只取测试表里写到的标准。表里没有标准号时，用测试项名称对文件名。"""
    latest = keep_latest(files)
    numbers = {item.group(1) for item in _STD_NUM.finditer(manual_text or "")}
    if numbers:
        return [item for item in latest if item.family in numbers]
    names = [line.strip() for line in (manual_text or "").splitlines() if len(line.strip()) >= 2]
    picked = []
    for item in latest:
        folded = _folded(item.name)
        if any(_folded(name) in folded for name in names):
            picked.append(item)
    return picked


def files_for_items(files: list[CatalogFile], items: list[ManualItem]) -> list[CatalogFile]:
    """有标准号的行按标准号取文件，没有标准号的行按测试项名称取，两行互不影响。"""
    latest = keep_latest(files)
    numbers: set[str] = set()
    names: list[str] = []
    for item in items:
        found = {match.group(1) for match in _STD_NUM.finditer(item.standard or "")}
        found.update(match.group(1) for match in _STD_NUM.finditer(item.lookup_standard or ""))
        if found:
            numbers.update(found)
        else:
            name = _folded(item.name)
            if len(name) >= 2:
                names.append(name)
            standard_name = _folded(item.standard)
            if len(standard_name) >= 2:
                names.append(standard_name)
        lookup_name = _folded(item.lookup_file)
        if len(lookup_name) >= 2:
            names.append(lookup_name)
    picked = []
    for item in latest:
        folded = _folded(item.name)
        if item.family in numbers or any(name in folded for name in names):
            picked.append(item)
    return picked


def _cell_rows(sheet) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        rows.append([str(cell).strip() if cell is not None else "" for cell in row])
    return rows


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _sheet_grid(ws, cached, max_col: int = 30) -> list[list[str]]:
    """合并单元格补全后，只取前面有表头的列。跨到表外的合并不展开。"""
    raw: dict[tuple[int, int], object] = {}
    shown: dict[tuple[int, int], object] = {}
    last_row = min(ws.max_row or 1, 2000)
    for row in range(1, last_row + 1):
        for col in range(1, max_col + 1):
            formula = ws.cell(row, col).value
            value = cached.cell(row, col).value if cached is not None else formula
            if formula is not None:
                raw[(row, col)] = formula
            if value is not None:
                shown[(row, col)] = value
    for rng in ws.merged_cells.ranges:
        if rng.min_col > max_col:
            continue
        origin = (rng.min_row, rng.min_col)
        formula = raw.get(origin)
        value = shown.get(origin, formula)
        for row in range(rng.min_row, min(rng.max_row, last_row) + 1):
            for col in range(rng.min_col, min(rng.max_col, max_col) + 1):
                raw.setdefault((row, col), formula)
                shown.setdefault((row, col), value)
    rows: list[list[str]] = []
    for row in range(1, last_row + 1):
        rows.append([_cell_text(shown.get((row, col), raw.get((row, col)))) for col in range(1, max_col + 1)])
    return rows


def _catalog_text(book) -> dict[str, tuple[str, str]]:
    """TestCaseSelection：试验项目 -> (标准全文, 目标要求)。"""
    found: dict[str, tuple[str, str]] = {}
    for name in book.sheetnames:
        if name.strip().lower() != "testcaseselection":
            continue
        ws = book[name]
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 2000), max_col=4, values_only=True):
            title = _cell_text(row[1] if len(row) > 1 else "")
            spec = _cell_text(row[2] if len(row) > 2 else "")
            criteria = _cell_text(row[3] if len(row) > 3 else "")
            if not title or not spec or "序号" in title or "试验项目" in title:
                continue
            found[_compact(title)] = (spec, criteria)
    return found


def _glossary(rows: list[list[str]]) -> dict[str, list[tuple[str, str]]]:
    """工况表：工作模式、功能状态、电压定义。"""
    modes: list[tuple[str, str]] = []
    classes: list[tuple[str, str]] = []
    voltages: list[tuple[str, str]] = []
    category = ""
    for row in rows:
        if row and row[0]:
            category = row[0]
        code = row[2] if len(row) > 2 else ""
        details: list[str] = []
        for cell in row[3:9]:
            if cell and (not details or details[-1] != cell):
                details.append(cell)
        detail = "；".join(details)
        if "工作模式" in category and re.fullmatch(r"\d+\.\d+", code or ""):
            modes.append((code, f"工作模式{code}：{detail}"))
            continue
        class_match = re.fullmatch(r"Class\s*([A-E])", code or "", re.I)
        if class_match and detail:
            classes.append((class_match.group(1).upper(), f"功能状态{class_match.group(1).upper()}：{detail}"))
            continue
        if "电压" in category and code and detail:
            for symbol in re.findall(r"U[A-Za-z]+", code):
                voltages.append((symbol, f"{code}：{detail}"))
    return {"modes": modes, "classes": classes, "voltages": voltages}


def _part_name(rows: list[list[str]]) -> str:
    for row in rows[:12]:
        for index, cell in enumerate(row):
            if "零件名称" not in _compact(cell):
                continue
            for nxt in row[index + 1 : index + 6]:
                if nxt and "零件名称" not in nxt and "卖方" not in nxt and "：" not in nxt:
                    return re.sub(r"\s+", " ", nxt).strip()
    return ""


def _sheet_label(title: str, rows: list[list[str]]) -> str:
    part = _part_name(rows)
    name = title.strip()
    if part and part not in name:
        return f"{name} {part}"
    return name


def _cite(source: str, text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    return f"来源：{source}\n{body}"


def _one_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return re.sub(r"\s+", " ", lines[0]).strip() if lines else ""


def _attach_catalog(items: list[ManualItem], catalog: dict[str, tuple[str, str]]) -> None:
    for item in items:
        spec, criteria = catalog.get(_compact(item.name), ("", ""))
        lines = [line.strip() for line in spec.splitlines() if line.strip()]
        if lines and not item.standard:
            item.standard = lines[0]
        extra = [
            line
            for line in lines[1:]
            if line not in (item.standard or "") and line not in (item.condition or "")
        ]
        if extra:
            block = _cite("TestCaseSelection", "\n".join(extra))
            item.condition = f"{item.condition}\n{block}".strip() if item.condition else block
        if criteria and not item.criteria:
            item.criteria = _cite("TestCaseSelection", criteria)
        item.standard = _one_line(item.standard)


def _refresh_clauses(items: list[ManualItem]) -> None:
    for item in items:
        clauses = _clauses_near_mark(item.standard) or _clauses_near_mark(item.criteria)
        if clauses:
            item.clause_id = "、".join(clauses)


def _attach_glossary(items: list[ManualItem], glossary: dict[str, list[tuple[str, str]]]) -> None:
    if not any(glossary.values()):
        return
    for item in items:
        text = f"{item.condition}\n{item.criteria}"
        extra: list[str] = []
        for match in re.finditer(r"工作模式", text):
            window = text[match.end() : match.end() + 48]
            for code, line in glossary["modes"]:
                if re.search(rf"(?<!\d){re.escape(code)}(?!\d)", window) and line not in extra:
                    extra.append(line)
        for letter, line in glossary["classes"]:
            if re.search(rf"功能状态\s*{letter}|{letter}\s*级|Class\s*{letter}", text, re.I) and line not in extra:
                extra.append(line)
        for symbol, line in glossary["voltages"]:
            if re.search(rf"(?<![A-Za-z]){symbol}(?![A-Za-z])", text) and line not in extra:
                extra.append(line)
        fresh = [line for line in extra if line not in (item.condition or "")]
        if fresh:
            block = _cite("总成-电源平台工况定义说明", "\n".join(fresh))
            item.condition = f"{item.condition}\n{block}".strip() if item.condition else block


def _excel_items(path: Path) -> list[ManualItem]:
    from openpyxl import load_workbook

    book = load_workbook(path, data_only=False)
    cached = load_workbook(path, data_only=True)
    try:
        catalog = _catalog_text(cached)
        glossary: dict[str, list[tuple[str, str]]] = {"modes": [], "classes": [], "voltages": []}
        found: list[ManualItem] = []
        for name in book.sheetnames:
            rows = _sheet_grid(book[name], cached[name])
            if name.strip() == "总成-电源平台工况定义说明":
                glossary = _glossary(rows)
                continue
            if name.strip().lower() == "testcaseselection":
                continue
            if not any(_is_dvp_header(row) for row in rows):
                continue
            found.extend(_dvp_items(rows, sheet=_sheet_label(name, rows)))
        _resolve_references(found)
        _attach_catalog(found, catalog)
        _refresh_clauses(found)
        _attach_glossary(found, glossary)
        return found
    finally:
        book.close()
        cached.close()


def read_manual_table(path: Path) -> list[ManualItem]:
    suffix = path.suffix.lower()
    rows: list[list[str]] = []
    if suffix in {".xlsx", ".xlsm"}:
        items = _excel_items(path)
        if not items:
            raise ValueError("测试表里没有可读的测试项。")
        return items
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


def _value_text(text: str) -> str:
    """公式格在没有缓存结果时先留空，稍后按试验库补。"""
    cleaned = (text or "").strip()
    if cleaned.startswith("="):
        return ""
    return cleaned


def _dvp_items(rows: list[list[str]], sheet: str = "") -> list[ManualItem]:
    header: list[str] = []
    stage = ""
    found: list[ManualItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if _is_dvp_header(row):
            header = row
            continue
        padded = list(row) + [""] * 8
        number = ""
        if header:
            padded = list(row) + [""] * (len(header) + 2)
            number = _value_text(padded[_column_contains(header, "序号") or 0])
        if not _ITEM_NO.match(number):
            named = _stage_name(row)
            if named:
                stage = named
            continue
        if not header:
            continue
        name_at = _column_contains(header, "试验项目")
        spec_at = _column_contains(header, "试验标准")
        cond_at = _column_contains(header, "试验条件")
        crit_at = _column_contains(header, "目标要求")
        name = _value_text(padded[name_at]) if name_at is not None else ""
        standard = _value_text(padded[spec_at]) if spec_at is not None else ""
        condition = _value_text(padded[cond_at]) if cond_at is not None else ""
        criteria = _value_text(padded[crit_at]) if crit_at is not None else ""
        if not name:
            continue
        clauses = _clauses_near_mark(standard) or _clauses_near_mark(criteria)
        key = (sheet, stage, number, name)
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
                sheet=sheet,
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
    target = items.get((item.sheet, stage, match.group(2).upper()))
    if target is None or target is item:
        return text
    followed = _followed_text(target, field, items, depth + 1)
    label = " ".join(part for part in (target.sheet, target.stage, target.number) if part)
    cited = _cite(label, followed)
    if not cited or cited in text:
        return text
    return f"{text}\n{cited}"


def _resolve_references(items: list[ManualItem]) -> None:
    index = {
        (item.sheet, item.stage.upper(), item.number.upper()): item for item in items if item.number
    }
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
    try:
        return _read_pages(path)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"读不了标准文件：{path.name}") from exc


def _docx_lines(document) -> list[str]:
    lines = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                text = cell.text.strip()
                if text and (not cells or cells[-1] != text):
                    cells.append(text)
            if cells:
                lines.append(" ".join(cells))
    return lines


def _text_from_doc(data: bytes) -> str:
    """从旧版 Word 二进制里取出连续的文字。没有办公软件时也读正文。"""
    parts: list[str] = []
    current = bytearray()

    def flush() -> None:
        if len(current) < 8:
            current.clear()
            return
        text = current.decode("utf-16le", errors="ignore")
        cleaned = "".join(ch for ch in text if ch.isprintable() or ch in "\n\r\t")
        if cleaned.strip():
            parts.append(cleaned)
        current.clear()

    index = 0
    size = len(data)
    while index + 1 < size:
        code = data[index] | (data[index + 1] << 8)
        if code in {9, 10, 13} or 32 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD:
            current.extend(data[index : index + 2])
            index += 2
            continue
        flush()
        index += 1
    flush()
    return "\n".join(parts)


def _read_pages(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(str(index), page.extract_text() or "") for index, page in enumerate(reader.pages, start=1)]
    if suffix == ".docx":
        from docx import Document

        return [("", "\n".join(_docx_lines(Document(str(path)))))]
    if suffix == ".doc":
        text = _text_from_doc(path.read_bytes())
        if not text.strip():
            raise ValueError(f"读不了标准文件：{path.name}")
        return [("", text)]
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


def _input_origin(item: ManualItem) -> str:
    return " ".join(part for part in (item.sheet, item.stage, item.number) if part)


def _with_origin(origin: str, file_source: str) -> str:
    if origin and file_source:
        return f"{origin}；{file_source}"
    return origin or file_source


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


def _row_conclusion(item: ManualItem, condition: StandardCondition) -> str:
    """同一条款对得上且文字一致为对应，文字对不上为错误，缺内容为缺少。"""
    left = _folded(item.criteria or item.condition or "")
    right = _folded(condition.condition or "")
    same_clause = bool(item.clause_id) and item.clause_id == condition.clause_id
    if same_clause and left and right and left not in right and right not in left:
        return "错误"
    if left and right and (left in right or right in left):
        return "对应"
    if same_clause and (not left or not right or left in right or right in left):
        return "对应"
    if not right:
        return "缺少"
    return "错误" if left else "缺少"


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
        origin = _input_origin(item)
        hits = [index for index, condition in enumerate(conditions) if _matches(item, condition)]
        if not hits:
            compared = note or "测试表有、标准文件未返回"
            if "检索接口" in compared or "没有返回文件" in compared:
                compared = "测试表有、标准文件未返回"
            rows.append([*lead, "", "", origin, compared, "欠缺补充", "缺少"])
            continue
        for index in hits:
            used.add(index)
            condition = conditions[index]
            conclusion = _row_conclusion(item, condition)
            compared = "对应" if conclusion == "对应" else "测试表与标准不一致"
            rows.append(
                [
                    *lead,
                    condition.document,
                    condition.condition,
                    _with_origin(origin, _source(condition)),
                    compared,
                    "验证对比" if conclusion != "缺少" else "欠缺补充",
                    conclusion,
                ]
            )
    for index, condition in enumerate(conditions):
        if index in used:
            continue
        rows.append(
            [
                "",
                "",
                condition.name,
                "",
                condition.clause_id,
                "",
                "",
                condition.document,
                condition.condition,
                _source(condition),
                "标准有、测试表未列",
                "欠缺补充",
                "缺少",
            ]
        )
    return {
        "title": "对比表",
        "headers": list(COMPARE_HEADERS_OUT),
        "rows": rows,
    }


def fetch_catalog_html(url: str) -> tuple[str, str, str]:
    """返回 (落地页, 原文, 说明)。"""
    if not (url or "").strip():
        return "", "", "网址尚未提供，未抓取网页。"
    final, raw, note = _http_get(url, 20.0, _PAGE_BYTES)
    return final, raw.decode("utf-8", errors="replace"), note


def _download_name(name: str, index: int) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "").strip(" .")
    if not cleaned:
        cleaned = f"标准文件-{index}"
    return f"{index}-{cleaned}"


def _download_standard(url: str, dest: Path, timeout: float = 20.0) -> None:
    try:
        _final, raw, _note = _http_get(url, timeout, None)
    except ValueError as exc:
        raise ValueError(str(exc).replace("读取网址失败", "读取标准文件失败", 1)) from exc
    if not raw:
        raise ValueError("标准文件没有内容。")
    dest.write_bytes(raw)


def _sheet_cell(row: list[object], headers: list[object], name: str) -> str:
    try:
        index = headers.index(name)
    except ValueError:
        return ""
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _finding_line(row: list[object], headers: list[object]) -> str:
    """一条缺少或错误：写明是哪一项、条款，以及测试表和标准各自的内容。"""
    head = " ".join(
        part
        for part in (
            _sheet_cell(row, headers, "阶段"),
            _sheet_cell(row, headers, "序号"),
            _sheet_cell(row, headers, "试验项目"),
        )
        if part
    ) or "未命名试验"
    bits = [head]
    standard = _sheet_cell(row, headers, "标准号")
    clause = _sheet_cell(row, headers, "条款")
    compared = _sheet_cell(row, headers, "对比")
    if standard:
        bits.append(f"标准号 {standard}")
    if clause:
        bits.append(f"条款 {clause}")
    if compared:
        bits.append(compared)
    table_text = "；".join(
        part
        for part in (
            _sheet_cell(row, headers, "试验条件"),
            _sheet_cell(row, headers, "目标要求"),
        )
        if part
    )
    if table_text:
        bits.append(f"测试表：{table_text}")
    standard_body = "；".join(
        part
        for part in (
            _sheet_cell(row, headers, "标准文件"),
            _sheet_cell(row, headers, "标准条件"),
        )
        if part
    )
    if standard_body:
        bits.append(f"标准：{standard_body}")
    source = _sheet_cell(row, headers, "来源")
    if source:
        bits.append(f"来源：{source}")
    return "；".join(bits)


def clause_findings(sheet: dict[str, object]) -> str:
    """把缺少和错误的条款逐条写出来。没有时写无。"""
    headers = sheet.get("headers") if isinstance(sheet.get("headers"), list) else []
    rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []
    if "结论" not in headers:
        return ""
    grouped = {"错误": [], "缺少": []}
    for row in rows:
        if not isinstance(row, list):
            continue
        verdict = _sheet_cell(row, headers, "结论")
        if verdict in grouped:
            grouped[verdict].append(row)
    blocks = []
    for verdict, title in (("错误", "错误的条款"), ("缺少", "缺少的条款")):
        picked = grouped[verdict]
        if not picked:
            blocks.append(f"{title}：无")
            continue
        lines = [f"{title}："]
        for index, row in enumerate(picked, 1):
            lines.append(f"{index}. {_finding_line(row, headers)}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


_FINDING_HEADERS = (
    "结论",
    "阶段",
    "序号",
    "试验项目",
    "标准号",
    "条款",
    "测试表内容",
    "标准内容",
    "来源",
    "对比",
)


def finding_rows(sheet: dict[str, object]) -> list[list[str]]:
    """缺少和错误各成一行，带上条款和两边的原文。"""
    headers = sheet.get("headers") if isinstance(sheet.get("headers"), list) else []
    rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []
    if "结论" not in headers:
        return []
    found: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        verdict = _sheet_cell(row, headers, "结论")
        if verdict not in {"错误", "缺少"}:
            continue
        table_text = "；".join(
            part
            for part in (
                _sheet_cell(row, headers, "试验条件"),
                _sheet_cell(row, headers, "目标要求"),
            )
            if part
        )
        standard_body = "；".join(
            part
            for part in (
                _sheet_cell(row, headers, "标准文件"),
                _sheet_cell(row, headers, "标准条件"),
            )
            if part
        )
        found.append(
            [
                verdict,
                _sheet_cell(row, headers, "阶段"),
                _sheet_cell(row, headers, "序号"),
                _sheet_cell(row, headers, "试验项目"),
                _sheet_cell(row, headers, "标准号"),
                _sheet_cell(row, headers, "条款"),
                table_text,
                standard_body,
                _sheet_cell(row, headers, "来源"),
                _sheet_cell(row, headers, "对比"),
            ]
        )
    return found


def comparison_workbook(sheet: dict[str, object]) -> bytes:
    """把对比表写成 Excel。缺少和错误的条款另写一张表。"""
    import io

    from openpyxl import Workbook

    book = Workbook()
    grid = book.active
    grid.title = "对比表"
    headers = sheet.get("headers") if isinstance(sheet.get("headers"), list) else []
    grid.append([str(item) for item in headers])
    rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []
    for row in rows:
        if isinstance(row, list):
            grid.append(["" if item is None else str(item) for item in row])
    extra = book.create_sheet("缺少与错误")
    extra.append(list(_FINDING_HEADERS))
    for row in finding_rows(sheet):
        extra.append(row)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def compare_manual_file(path: Path, on_step=None, ask=None, save_dir: Path | None = None) -> dict[str, object]:
    """找到检索框，填入标准号或文件名称，下载文件交回工程，再提取测试项目并写出对比表。"""
    manual = read_manual_table(path)
    page_url = source_url()
    if ask is not None:
        if on_step:
            on_step("extract", f"{len(manual)} 行")
        try:
            written = apply_lookup_terms(manual, ask(lookup_messages(manual)))
        except Exception:
            written = 0
        if written == 0 and on_step:
            on_step("extract", "模型没有抽出检索词，改用表内标准号")
    if on_step:
        on_step(
            "open",
            f"脚本开始按给定网址爬取。地址是 {page_url}。顺序是：找到检索框，填入标准号或文件名称，从搜索结果找到文件，下载后交回工程，再由工程提取测试项目并写出对比表。",
        )
    try:
        _landed, found, note = collect_for_manual(page_url, manual, deadline=None, on_step=on_step)
    except ValueError as exc:
        found = []
        note = str(exc)
        if on_step:
            on_step("find", f"打开给定网址没有完成。{exc}脚本还没有查找检索框，也没有读取标准文件。")
    conditions: list[StandardCondition] = []
    latest = keep_latest(found) if found else []
    replaced = [item.name for item in found if item.replaced]
    chosen = files_for_items(found, manual) if found else []
    missed: list[str] = []
    if on_step and found:
        dropped = "、".join(replaced[:8]) or "没有"
        kept = "、".join(item.name for item in chosen[:8]) or "没有"
        on_step(
            "file",
            f"脚本第 5 步：搜索结果共 {len(found)} 个文件，去掉已替换后剩 {len(latest)} 个最新文件。已替换的是：{dropped}。对上测试表、准备下载的是：{kept}。",
        )
    folder: Path | None = None
    keep_files = save_dir is not None
    if chosen:
        if keep_files:
            folder = Path(save_dir)
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.iterdir():
                if old.is_file() and not old.name.startswith("~$"):
                    try:
                        old.unlink()
                    except OSError:
                        pass
        else:
            import tempfile

            folder = Path(tempfile.mkdtemp(prefix="etest-std-"))
        if on_step:
            on_step("file", f"脚本第 6 步：下载这 {len(chosen)} 个文件，下载后交回工程。")
    saved: list[tuple[Path, str]] = []
    if chosen and folder is not None:
        for index, item in enumerate(chosen):
            suffix = Path(item.name).suffix.lower()
            if suffix not in _FILE_SUFFIX:
                suffix = Path(urlparse(item.url).path).suffix.lower()
            if suffix not in _FILE_SUFFIX:
                missed.append(item.name)
                if on_step:
                    on_step("file", f"「{item.name}」不是可下载的标准文件，跳过。")
                continue
            dest = folder / _download_name(item.name, index)
            if dest.suffix.lower() not in _FILE_SUFFIX:
                dest = dest.with_suffix(suffix)
            try:
                _download_standard(item.url, dest, timeout=60.0)
            except ValueError as exc:
                missed.append(item.name)
                if on_step:
                    on_step("file", f"文件「{item.name}」没有下载成功。原因是 {exc}")
                continue
            saved.append((dest, item.name))
            if on_step:
                on_step("file", f"已下载「{item.name}」，交回工程。文件在 {dest}。")
        if on_step and saved:
            on_step("file", f"脚本第 7 步：工程从交回的 {len(saved)} 个文件里提取测试项目。")
        for dest, origin in saved:
            try:
                before = len(conditions)
                conditions.extend(conditions_from_pages(_pages_of(dest), origin))
                if on_step:
                    on_step(
                        "file",
                        f"从交回的文件「{origin}」提取出试验条款 {len(conditions) - before} 条。",
                    )
            except ValueError as exc:
                missed.append(origin)
                if on_step:
                    on_step("file", f"交回的文件「{origin}」没有提取出测试项目。原因是 {exc}")
        if not keep_files:
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
    if missed:
        failed = "这些文件没有读出：" + "、".join(missed[:8])
        note = f"{note}{failed}" if note else failed
    elif found and not chosen:
        note = "网址上没有对上的、且仍未被替换的最新文件。"
    elif found and not conditions:
        note = "文件已下载并交回工程，但没有提取出测试项目。"
    sheet = build_comparison_sheet(manual, conditions, note="" if conditions else note)
    verdict = COMPARE_HEADERS_OUT.index("结论")
    missing = sum(1 for row in sheet["rows"] if row[verdict] == "缺少")
    wrong = sum(1 for row in sheet["rows"] if row[verdict] == "错误")
    matched = sum(1 for row in sheet["rows"] if row[verdict] == "对应")
    if on_step:
        on_step(
            "write",
            f"脚本第 8 步：对比表已写出。对应 {matched} 条，错误 {wrong} 条，缺少 {missing} 条。",
        )
    reply = f"已生成对比表。对应 {matched} 条，错误 {wrong} 条，缺少 {missing} 条。\n{clause_findings(sheet)}"
    return {
        "reply": reply,
        "tables": [sheet],
        "page_note": note,
        "source_url_set": bool(page_url),
        "saved_files": [str(dest) for dest, _origin in saved] if keep_files else [],
    }
