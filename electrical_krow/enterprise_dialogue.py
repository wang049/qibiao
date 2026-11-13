"""企标对话：先整理问题，再读网址，最后用本地企标关键行出结果。

网址由 ENTERPRISE_TEST_SOURCE_URL 指定，未给时不发起抓取。
本地企标目录默认是已核对过的那份测试材料，也可用 ENTERPRISE_STD_DIR 换。
"""
from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

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


def public_http_url(url: str) -> str:
    """只接受公网 http(s)。不跟随到内网。"""
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
    for raw in addresses:
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        ):
            raise ValueError("不读取内网网址。")
    return parsed.geturl()


def fetch_source_page(url: str) -> tuple[str, str]:
    """返回 (正文, 说明)。未配置网址时不访问网络。"""
    if not (url or "").strip():
        return "", "网址尚未提供，未抓取网页。"
    target = public_http_url(url)
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False) as client:
            response = client.get(target, headers={"User-Agent": "electrical-krow"})
    except httpx.HTTPError as exc:
        raise ValueError(f"读取网址失败：{exc}") from exc
    if 300 <= response.status_code < 400:
        raise ValueError("网址发生跳转，已停止读取。")
    if response.status_code >= 400:
        raise ValueError(f"网址返回 {response.status_code}。")
    raw = response.content[:_FETCH_BYTES]
    text = raw.decode(response.encoding or "utf-8", errors="replace")
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
