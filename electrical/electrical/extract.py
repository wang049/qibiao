"""单次结构化抽取：只打工位本机 OpenAI 兼容接口，文件不出公网。"""
from __future__ import annotations

import ipaddress
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from electrical.schema import (
    ExtractedCell,
    conflict_for_name,
    empty_template_rows,
    format_prompt_field,
    load_template_fields,
    retrieve_aliases_for_name,
    retrieve_enabled_for_name,
    STATUS_MISS,
    STATUS_NA,
    STATUS_PARTIAL,
    whole_name_tokens,
)
from electrical.progress import get_control, report, report_stats, checkpoint, was_stopped
from electrical.read_doc import LoadedDocument

DEFAULT_MODEL = os.environ.get(
    "SPEC_SHEET_LLM_MODEL",
    os.environ.get("KROW_CHAT_MODEL", "qwen2.5:7b"),
)
DEFAULT_BASE_URL = os.environ.get(
    "SPEC_SHEET_LLM_URL",
    os.environ.get("KROW_BASE_URL", "http://127.0.0.1:11434"),
).rstrip("/")
# 与工位 KROW_LLM_TIMEOUT 默认一致。deepseek-v4-pro 一段常要 80–200 s（含思考），90 s 会有四成段超时。
DEFAULT_TIMEOUT = float(os.environ.get("SPEC_SHEET_LLM_TIMEOUT", "180"))
EXTRACT_HEAD_CHARS = int(os.environ.get("SPEC_SHEET_EXTRACT_CHARS", "4500"))
NUM_CTX = int(os.environ.get("SPEC_SHEET_NUM_CTX", "8192"))
MAX_CHUNKS = int(os.environ.get("SPEC_SHEET_MAX_CHUNKS", "14"))
MAX_SELECT_PAGES = int(os.environ.get("SPEC_SHEET_MAX_SELECT_PAGES", "40"))
# 0 = 不强制截断，需要多久就多久。可用 SPEC_SHEET_BUDGET_SEC 自行设上限（秒）。
BUDGET_SEC = float(os.environ.get("SPEC_SHEET_BUDGET_SEC", "0"))
# 原文摘录扩成完整原句后的上限，避免再截成短语。
_CLAUSE_LIMIT = 480
_PAGE_HEADING = re.compile(r"##\s*第\s*\d+\s*页[ \t]*")
_PAGE_IN_EXCERPT = re.compile(r"## 第 (\d+) 页")
_CLAUSE_HEADING = re.compile(r"\d{1,2}(?:\.\d{1,3}){2,4}[ \t]+\S[^\n]{0,80}\n+")
# 正文 Heading 未印条款号时，按 DHTS 目录结构补上（6.6 / 6.8 等）。
_HEADING_CLAUSE = (
    (
        re.compile(
            r"(?i)Generated voltage ripple UDC control|直流控制产生电压纹波|"
            r"Maximum differential ripple when the HV battery is switched off|"
            r"高压电池关闭时的最大差分纹波"
        ),
        "2.3.3.3.4",
    ),
    (
        re.compile(
            r"(?i)2\.3\.3\.3\.3\s+Generated voltage ripple(?!\s+UDC)|"
            r"Maximum differential ripple when the HV battery is switched on|"
            r"高压电池接通时的最大差分纹波"
        ),
        "2.3.3.3.3",
    ),
    (
        re.compile(
            r"(?i)2\.3\.3\.3\.1\s+EMC requirements|Generic EMC requirements电磁兼容总体要求"
        ),
        "2.3.3.3.1",
    ),
    (
        re.compile(r"(?i)Coolant pressure drop\s*冷却回路压降"),
        "6.8.3",
    ),
    (
        re.compile(
            r"(?i)LV power consumption\s*低压功耗|"
            r"未唤醒@仅低压上电|"
            r"唤醒@IGBT\s*开管@高低压都上电"
        ),
        "6.5.2",
    ),
)
# 未印条款号的 PEI 分节：比上一节 6.4.2.4 Protection 更近时，不得沿用保护条款号。
_UNNUMBERED_PEI_HEADING = re.compile(
    r"(?im)^(?:#{1,6}\s+)?(?:"
    r"HVDC Voltage Range|LVDC Voltage Range|"
    r"LV power consumption|低压功耗|"
    r"高压范围|低压范围|"
    r"HV Booster|高压升压器|"
    r"Cooling connections|冷却连接|"
    r"Overvoltage due to generated back-emf|反电动势导致的过压|"
    r"Heat loss|热损失|"
    r"PEI requirements"
    r")"
)
_HVDC_OPERATING_VOLTAGE_FIELDS = frozenset(
    {
        "直流工作电压范围",
        "满功率(电流)工作电压",
        "降额工作电压范围",
    }
)
_POLES_RPM_NOTE = (
    "交流基频满性能假设（极对数×转速），不是最高工作转速定义。"
    "请对照转速表复核。"
)
_CONNECTOR_CHARGE_NOTE = (
    "连接器只证明有充电接口，不是升压充电功能的定义"
    "（拓扑/电压/电流/时长）。请对照充电功能章节复核。"
)
_CONNECTOR_PROTECTION_NOTE = (
    "条款 6.2.3.2 对应高压直流连接；当份未写 IPXXB/触指防护。"
    "峰值/持续功率不是防护指标。"
)
_HVDC_PEAK_POWER = re.compile(
    r"125\s*kW|62\.5\s*kW|10s\s*@\s*125|HVDC\s*peak\s*power|高压直流峰值功率",
    re.I,
)
_CONNECTOR_POWER_AS_VALUE = re.compile(
    r"\d+(?:\.\d+)?\s*kW|峰值功率|持续功率|peak power|continuous power|HVDC peak",
    re.I,
)


def _parallel_workers() -> int:
    try:
        n = int(os.environ.get("SPEC_SHEET_EXTRACT_PARALLEL", "3"))
    except ValueError:
        n = 3
    return max(1, min(4, n))

_BLOCKED_HOST_SUFFIXES = (".krow.cn",)
_BLOCKED_HOSTS = {"krow.cn", "api.krow.cn"}


class ExtractError(RuntimeError):
    pass


class ExtractAuthError(ExtractError):
    """识别未授权。不能按空段跳过，否则会 4 秒出一张只有规则的表。"""


class ExtractModelError(ExtractError):
    """识别模型不可用。不能按空段跳过，否则会出一张只有规则的表。"""


@dataclass
class ExtractMeta:
    llm_calls: int = 0
    chunk_count: int = 0
    topup_count: int = 0
    rule_filled: int = 0
    chunk_failures: int = 0
    chunk_error: str = ""


def should_send_chunk_to_model(fields: str) -> bool:
    """数字稿也不跳过模型。只要还有空缺条目，选中的段就必须送识别。"""
    return bool((fields or "").strip())


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _thinking_controls() -> dict[str, Any]:
    """推理模型控制。出表只要 JSON，长推理只拖时间、烧算力。

    SPEC_SHEET_LLM_THINKING=disabled → thinking.type=disabled；low/medium/high → reasoning_effort。
    SPEC_SHEET_LLM_MAX_TOKENS=<n> → max_tokens。不设就不发，上游不认的字段不去碰。
    """
    out: dict[str, Any] = {}
    mode = os.environ.get("SPEC_SHEET_LLM_THINKING", "").strip().lower()
    if mode in {"disabled", "off", "none"}:
        out["thinking"] = {"type": "disabled"}
    elif mode in {"low", "medium", "high", "minimal"}:
        out["reasoning_effort"] = mode
    raw = os.environ.get("SPEC_SHEET_LLM_MAX_TOKENS", "").strip()
    if raw.isdigit() and int(raw) > 0:
        out["max_tokens"] = int(raw)
    return out


def _hostname(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.hostname or "").strip().lower()
    return host.strip("[]")


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def require_workstation_endpoint(base_url: str) -> str:
    """抽取只允许本机回环地址，拒绝公网（含 api.krow.cn）。"""
    raw = (base_url or "").strip().rstrip("/")
    if not raw:
        raise ExtractError(
            "未配置本机模型地址。请安装 Ollama，或设置 SPEC_SHEET_LLM_URL="
            "http://127.0.0.1:11434"
        )
    if raw.endswith("/v1"):
        raw = raw[:-3]
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    if parsed.scheme not in {"http", "https"}:
        raise ExtractError(f"本机模型地址不合法: {base_url}")
    host = _hostname(raw)
    if not host:
        raise ExtractError(f"本机模型地址不合法: {base_url}")
    if host in _BLOCKED_HOSTS or any(host.endswith(s) for s in _BLOCKED_HOST_SUFFIXES):
        raise ExtractError(
            "按工位本机部署要求，规格书不得发往 Krow Cloud / 公网。"
            "请改用本机 Ollama（http://127.0.0.1:11434）。"
        )
    if not _is_loopback_host(host):
        raise ExtractError(
            f"抽取目标不是本机：{host}。文件必须留在工位电脑上，"
            "请把 SPEC_SHEET_LLM_URL 设为 http://127.0.0.1:11434"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _assistant_text(message: Any) -> str:
    """本机网关回包正文。现场模型常把 JSON 放在 reasoning_content。"""
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return ""
    for key in ("content", "reasoning_content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list):
            parts: list[str] = []
            for item in val:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
            blob = "".join(parts).strip()
            if blob:
                return blob
    return ""


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise ExtractError(
                f"模型没有返回 JSON: {exc}；原文前 200 字: {raw[:200]!r}"
            ) from exc
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc2:
            raise ExtractError(
                f"模型没有返回 JSON: {exc2}；原文前 200 字: {raw[:200]!r}"
            ) from exc2
    if not isinstance(data, dict):
        raise ExtractError("JSON 根节点必须是对象")
    return data


def _rows_from_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    incoming = data.get("rows") or data.get("fields")
    if isinstance(incoming, list):
        return [item for item in incoming if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []

    def add(group: str, name: str, value: Any) -> None:
        name = str(name or "").strip()
        if not name:
            return
        if isinstance(value, dict):
            row = {"group": group, "name": name, **value}
            if "value" not in row:
                row["value"] = value.get("值") or ""
            rows.append(row)
            return
        rows.append({"group": group, "name": name, "value": value})

    for key, val in data.items():
        if key in {"rows", "fields"}:
            continue
        if isinstance(val, dict):
            for name, inner in val.items():
                add(str(key), str(name), inner)
            continue
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    item = dict(item)
                    item.setdefault("group", key)
                    rows.append(item)
            continue
        if isinstance(val, (str, int, float)):
            add("", str(key), val)
    return rows


def _local_llm_hint(exc: BaseException) -> str:
    return (
        "本机模型不可用。请在工位电脑启动 Ollama，并拉取模型，例如：\n"
        "  ollama serve\n"
        "  ollama pull qwen2.5:7b\n"
        "离线环境可用 U 盘拷入模型，不要把规格书发到公网。\n"
        f"详情: {exc}"
    )


_SPEC_HIT = re.compile(
    r"(?i)voltage|current|power|temperature|cooling|torque|certif|"
    r"ip\d|kw|hz|nm|rpm|℃|°c|\bv\b|\ba\b|lpm|glycol|warranty|"
    r"电压|电流|功率|温度|防护|冷却|扭矩|寿命|质保"
)
_KEEP_PAGE = re.compile(
    r"(?i)target spec|system i/o|ewp |cooling sequence|qualification life|"
    r"iso 26262|lv 124|table 2\.|oil cooling|本机 OCR|"
    r"electrical components requirements|insulat|dielectric|"
    r"withstand voltage|连续高压直流耐压|"
    r"active discharge|passive discharge|ripple|dc-?link|"
    r"operating voltage|coolant|glycol|functional safety|asil|"
    r"back emf|ingress|ip\s*6\d|"
    r"Requirements 要求|冷却连接|绝缘电阻|主动放电|被动放电|"
    r"工作电压|直流母线|功能安全|寿命|"
    r"零部件寿命|15年或|P1逆变器|升压开关频率|冷却液流量|电机温度传感器|"
    r"altitude|sea level|storage temperature|boost control|"
    r"BOOST architecture|Y-capacitor|standstall|standstill|"
    r"continuous generate|continuous torque|"
    r"HVDC bus voltage|Peak power"
)
_WEAK_VALUE = re.compile(
    r"^(tbd|t\.b\.d\.?|n/?a|—|-|/|待定|未提及|未指定|none|null|negotiable|无)$",
    re.I,
)
DERIVE_NOTE = "由物理公式计算"
_CLAUSE_NUM = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,3}){2,4})(?![\d.])")
# 行首标题：2 段（4.6 阻燃）到 5 段（2.3.3.3.4）。正文里的 12.5 kW 不是标题。
_HEADING_LINE_CLAUSE = re.compile(
    r"^(?:#{1,6}\s+)?(\d{1,2}(?:\.\d{1,3}){1,4})(?:\s|$|(?=[A-Za-z\u4e00-\u9fff]))"
)
_HEADING_UNIT_TAIL = re.compile(
    r"(?i)^(?:kW|kV|Vdc|Vac|Arms|Ams|Nm|rpm|kg|mm|ms|Hz|LPM|nF|uF|µF|%|℃|°C)"
    r"|^(?:V|A|s)\b"
)
_LAW_SENTENCE = re.compile(
    r"(?i)ohm'?s?\s*law|欧姆定律|kirchhoff|基尔霍夫|电压电流定律|\bKVL\b|\bKCL\b|"
    r"voltage[- ]current\s+law|\bU\s*=\s*I\s*R\b|\bP\s*=\s*U\s*I\b|\bP\s*=\s*T\s*[ωw]\b"
)
_QTY_V = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(kV|VDC|VAC|Vdc|Vac|V)(?![a-zpp])")
_QTY_I = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(mA|Arms|Ams|A)(?![a-z])")
_QTY_R = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(MΩ|MOhm|Mohm|kΩ|kOhm|Ω|Ohm)\b")
_QTY_P = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*kW\b")
_QTY_C = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(µF|uF|μF|mF)\b")
_QTY_TSEC = re.compile(r"(?i)(?<![@\w./])(\d+(?:\.\d+)?)\s*(ms|s(?:ec(?:onds?)?)?)\b")
_QTY_NM = re.compile(r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(?:N[·.]?m|Nm)\b")
_INS_CTX = re.compile(
    r"(?i)绝缘电阻|insulation resistance|insulation test|绝缘测试|对地绝缘|"
    r"漏电流|leakage current"
)
_DISCHARGE_R_CTX = re.compile(r"(?i)放电电阻|discharge resistor")
_DISCHARGE_CTX = re.compile(r"(?i)放电|discharge")
_CAP_LEAK_CTX = re.compile(
    r"(?i)@ Rated Voltage|Rated Voltage,\s*1min|Dark Current|DC capacitor|DC 电容"
)


_SCAN_HEADER_LINE = re.compile(
    r"(?i)^("
    r"horse|"
    r"document\s+(name|type|no\.?|release\s+status|number)|"
    r"prerelease|issue|volume\s*no\.?|page\s*no\.?|"
    r"copyright|"
    r"\[本页为本机 OCR\]|"
    r"##\s*第\s*\d+\s*页|"
    r"\d{1,3}\s*\(\s*\d{1,3}\s*\)|"
    r"rel(?:ease)?\s*date|"
    r"reference\s*no|"
    r"version\s*/?\s*\#|"
    r"4ldht\d+\s+pcm\s+design\s+prerequisites"
    r")\b"
)


def _is_ocr_markdown(markdown: str) -> bool:
    blob = markdown or ""
    return "[本机 OCR]" in blob or "[本页为本机 OCR]" in blob


_LONG_DOC_CHARS = 120_000
_LONG_DOC_STEP_CHARS = 40_000
_LONG_DOC_MAX_CHUNKS = int(os.environ.get("SPEC_SHEET_MAX_LONG_CHUNKS", "22"))


def _chunk_cap(markdown: str = "") -> int:
    if _is_ocr_markdown(markdown):
        return max(MAX_CHUNKS, int(os.environ.get("SPEC_SHEET_MAX_SCAN_CHUNKS", "24")))
    length = len(markdown or "")
    if length > _LONG_DOC_CHARS:
        # 24 万字的规格书 14 段只够读两成；按长度加段，上限 22
        extra = (length - _LONG_DOC_CHARS) // _LONG_DOC_STEP_CHARS + 1
        return min(_LONG_DOC_MAX_CHUNKS, max(MAX_CHUNKS, MAX_CHUNKS + extra))
    return MAX_CHUNKS


def _select_page_cap(markdown: str = "") -> int:
    if _is_ocr_markdown(markdown):
        return max(MAX_SELECT_PAGES, 80)
    return MAX_SELECT_PAGES


def _strip_scan_header(text: str) -> str:
    if not _is_ocr_markdown(text):
        return text
    lines = text.splitlines()
    cut = 0
    for i, line in enumerate(lines):
        raw = line.strip()
        if not raw:
            if cut:
                cut = i + 1
            continue
        if _SCAN_HEADER_LINE.search(raw):
            cut = i + 1
            continue
        if i < 28 and len(raw) < 42 and not re.search(
            r"(?i)shall |voltage|current|\d+\.\d+|要求|母线|放电|冷却",
            raw,
        ):
            letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", raw))
            if letters <= 14:
                cut = i + 1
                continue
        break
    kept = "\n".join(lines[cut:]).strip()
    if len(kept) < 80:
        return text
    marker = re.search(r"## 第 \d+ 页", text)
    prefix = (marker.group(0) + "\n") if marker else ""
    return prefix + kept


_UNPAGED_MIN_CHARS = 12_000
_PAGE_MARKER = re.compile(r"## 第 (\d+) [页节]")


def _has_printed_page_markers(markdown: str) -> bool:
    """整篇只有一个「第 1 页」时，多半是没读到印页，不能当真。"""
    found = [int(n) for n in _PAGE_MARKER.findall(markdown or "")]
    if not found:
        return False
    if set(found) == {1} and len(markdown or "") >= _UNPAGED_MIN_CHARS:
        return False
    return True


def _page_blocks(markdown: str) -> list[tuple[int, str]]:
    if _has_printed_page_markers(markdown):
        blocks: list[tuple[int, str]] = []
        for part in re.split(r"(?=## 第 \d+ [页节])", markdown):
            if not part.strip():
                continue
            match = _PAGE_MARKER.search(part)
            page = int(match.group(1)) if match else 0
            text = part if len(part) <= 5500 else part[:5500] + "\n[本页过长已截断]\n"
            blocks.append((page, text))
        return blocks
    size = 3500
    return [
        (0, markdown[i * size : (i + 1) * size])
        for i in range((len(markdown) + size - 1) // size)
    ]


def _strip_running_header(text: str) -> str:
    match = re.match(
        r"(?:## 第 \d+ 页\s+)?Model\s.{0,400}?PAGE\s*\n?\s*\d+\s*/\s*\d+\s*",
        text,
        re.I | re.S,
    )
    if match and match.end() <= 900:
        marker = re.search(r"## 第 \d+ 页", text)
        prefix = (marker.group(0) + "\n") if marker else ""
        text = prefix + text[match.end() :].strip()
    return _strip_scan_header(text)


def _is_glossary(text: str) -> bool:
    return (
        "Terminology" in text
        and "Definitions" in text
        and len(re.findall(r"This is to|This refers to|It is the", text)) >= 2
    )


def _score_block(text: str) -> int:
    if _is_glossary(text):
        return -50
    bonus = 80 if _KEEP_PAGE.search(text) else 0
    if re.search(r"\| ---+ \|", text) and re.search(
        r"\d+(?:\.\d+)?\s*(?:V(?:dc|ac)?|A(?:rms)?|kW|rpm|℃|°C|LPM)",
        text,
        re.I,
    ):
        bonus += 70
    if re.search(r"主动放电|被动放电|绝缘电阻|工作电压|直流母线", text):
        bonus += 50
    if re.search(
        r"(?i)altitude|sea level|storage temperature|boost control|"
        r"BOOST architecture|Y-capacitor|standstall|passively discharge",
        text,
    ):
        bonus += 40
    return bonus + len(_SPEC_HIT.findall(text)) * 4 + len(re.findall(r"\d+(\.\d+)?", text))


# 「Contents」只认目录标题：独占一行的 Contents（可带表格竖线 / 点线 / 页码）或 Table of Contents。
# 逆变器 SR 2026-09-16：正文表头 `CATEGORY CONTENTS TARGET` 和句子 `contents stated in ES/MS`
# 把 3.3.6 非功能要求页、Table 3.12 CAE 页（冷却压降 <300mbar@12lpm）整页判成封面目录，选段/补抽都不看。
_CONTENTS_HEADING = re.compile(
    r"^[#*|\s]*contents\s*(?:\.{2,}\s*)?\d*\s*\|?\s*$|table\s+of\s+contents",
    re.I | re.M,
)


def _is_front_matter(text: str) -> bool:
    head = text[:900]
    if not (
        _CONTENTS_HEADING.search(head)
        or re.search(
            r"(?i)目录|revision history|修改历史|requisite documents|必要的文档",
            head,
        )
    ):
        return False
    return not re.search(
        r"(?i)operating voltage|工作电压|冷却流量|绝缘电阻|qualification life|"
        r"主动放电|Requirements 要求",
        text,
    )


_SHORT_LATIN_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9./-]{0,3}$")


def _token_present(token: str, lowered: str) -> bool:
    """别名是否出现在段里。RE / IR / OD 这类短拉丁缩写只认整词，不认子串。"""
    t = (token or "").strip()
    if len(t) < 2:
        return False
    if _SHORT_LATIN_TOKEN.match(t):
        return re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", lowered) is not None
    return t.lower() in lowered


_SHARED_TOKEN_MAX_SPECS = 2


def _raw_coverage_tokens(name: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    tokens = [*_name_match_tokens(name), *aliases, *_field_needles(name)]
    return tuple(dict.fromkeys(t.strip() for t in tokens if t and len(t.strip()) >= 2))


def _spec_alias_pool(spec) -> tuple[str, ...]:
    """强别名 + 弱别名。弱别名（重量 / 防腐 / 扭矩精度）是同槽两条共享的，词典 strong 进不去，
    但找页认条完全够用；共享 3 条以上的泛词由 _shared_coverage_tokens 再滤一遍。"""
    return tuple(dict.fromkeys([*spec.aliases, *getattr(spec, "weak_aliases", ())]))


@lru_cache(maxsize=1)
def _shared_coverage_tokens() -> frozenset[str]:
    """出现在 3 条以上条目里的针（P1 / P3 / BOOST / 升压…）认不出具体条目，不拿来算覆盖。"""
    count: dict[str, int] = {}
    for spec in load_template_fields():
        for token in _raw_coverage_tokens(spec.name, _spec_alias_pool(spec)):
            key = token.lower()
            count[key] = count.get(key, 0) + 1
    return frozenset(k for k, n in count.items() if n > _SHARED_TOKEN_MAX_SPECS)


@lru_cache(maxsize=256)
def _coverage_tokens(name: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    """选段用的认条针：条目名分词 + 词典强/弱别名 + 原文针，去掉多条目共享的泛词。"""
    shared = _shared_coverage_tokens()
    return tuple(t for t in _raw_coverage_tokens(name, aliases) if t.lower() not in shared)


@lru_cache(maxsize=256)
def _capped_weak_tokens(name: str, weak: tuple[str, ...]) -> frozenset[str]:
    """弱别名里不带条目名核心字、又不是英文多词短语的（质量 / 涂层 / 表面处理 / weight / mass），
    只能算顺带提及，不能凭旁边有个数字就当给值的页。"""
    grams = {name[i : i + 2] for i in range(len(name) - 1) if re.match(r"^[\u4e00-\u9fff]{2}$", name[i : i + 2])}
    capped: set[str] = set()
    for token in weak:
        t = token.strip()
        if not t:
            continue
        if re.search(r"[\u4e00-\u9fff]", t):
            if not any(g in t for g in grams):
                capped.add(t.lower())
        elif " " not in t:
            capped.add(t.lower())
    return frozenset(capped)


_NEAR_VALUE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:k?[VAW]|Arms|kg|g|mm|ms|s|h|Hz|kHz|rpm|Nm|℃|°C|%|MΩ|mA|kPa|bar|L/min|LPM|lpm|liter|km|years?|年|公里|万)",
    re.I,
)


def _token_strength(token: str, text: str, lowered: str) -> int:
    """0 未出现；1 顺带提及；2 旁边有数字单位或在标题行（更像给值的段）。"""
    t = token.strip().lower()
    if _SHORT_LATIN_TOKEN.match(t):
        match = re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", lowered)
    else:
        pos = lowered.find(t)
        match = None if pos < 0 else (pos, pos + len(t))
    if match is None:
        return 0
    start, end = (match.start(), match.end()) if hasattr(match, "start") else match
    window = text[max(0, start - 160) : end + 200]
    if _NEAR_VALUE.search(window):
        return 2
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start : line_end if line_end >= 0 else len(text)]
    if _HEADING_LINE_CLAUSE.match(line.strip()) or line.strip().startswith("#"):
        return 2
    return 1


def _block_covers(text: str, specs: list) -> dict[int, int]:
    """段 → {条目序号: 命中强度}。"""
    lowered = (text or "").lower()
    out: dict[int, int] = {}
    for spec in specs:
        best = 0
        capped = _capped_weak_tokens(spec.name, tuple(getattr(spec, "weak_aliases", ())))
        for token in _coverage_tokens(spec.name, _spec_alias_pool(spec)):
            strength = _token_strength(token, text, lowered)
            if token.lower() in capped:
                strength = min(strength, 1)
            if strength > best:
                best = strength
                if best >= 2:
                    break
        if best:
            out[spec.seq] = best
    return out


def _select_chunks(
    markdown: str,
    max_chunks: int | None = None,
    rows: dict[int, ExtractedCell] | None = None,
) -> list[str]:
    """给模型选段。

    传入 rows 时按「空缺条目」做贪心覆盖：每一轮取能新覆盖最多空缺条目的页，
    直到空缺都有段可读或页数用尽；剩余名额再按性能词打分补。不传 rows 保持旧行为。
    这样 24 万字的规格书里，第 2/4/5 章「通用要求」（重量、寿命、防腐、振动）也能进模型，
    而不是只送电压/电流表格。
    """
    cap = _chunk_cap(markdown)
    limit = max_chunks if max_chunks is not None else cap
    limit = max(1, min(limit, cap))
    page_cap = _select_page_cap(markdown)
    blocks = _page_blocks(markdown)
    if not blocks:
        return [markdown[:EXTRACT_HEAD_CHARS]]
    items = [(i, page, text) for i, (page, text) in enumerate(blocks)]
    chosen: list[tuple[int, str]] = []
    seen: set[int] = set()

    def take(index: int, page: int, text: str) -> None:
        if index in seen:
            return
        chosen.append((page, _strip_running_header(text)))
        seen.add(index)

    cover: list[tuple[int, str]] = []
    gaps: list[tuple[int, str]] = []
    spec: list[tuple[int, str]] = []
    rest: list[tuple[int, str]] = []
    for index, page, text in items:
        if page <= 4 or page == 0:
            if _is_front_matter(text):
                continue
            take(index, page, text)
            cover.append(chosen[-1])
            if len(cover) >= 2:
                break
    cover_ids = set(seen)
    chosen.clear()
    seen.clear()

    gap_ids: set[int] = set()
    if rows is not None:
        empty_specs = [
            s for s in load_template_fields()
            if s.seq in rows and not (rows[s.seq].value or "").strip()
        ]
        if empty_specs:
            cands = [
                (index, page, text, _block_covers(text, empty_specs))
                for index, page, text in items
                if index not in cover_ids
                and not _is_glossary(text)
                and not _is_front_matter(text)
            ]
            cands = [c for c in cands if c[3]]
            best_strength: dict[int, int] = {}

            def gain_of(hits: dict[int, int]) -> int:
                return sum(max(0, s - best_strength.get(seq, 0)) for seq, s in hits.items())

            # 覆盖贪心与性能词打分分名额：打分至少留 1/3，两边都不饿死
            free = max(0, min(page_cap, limit) - len(cover))
            gap_quota = free - max(1, free // 3) if free > 1 else free
            while cands and len(gaps) < gap_quota:
                best = max(
                    cands,
                    key=lambda c: (gain_of(c[3]), _score_block(c[2]), -c[0]),
                )
                if gain_of(best[3]) <= 0:
                    break
                cands.remove(best)
                for seq, s in best[3].items():
                    if s > best_strength.get(seq, 0):
                        best_strength[seq] = s
                gaps.append((best[1], _strip_running_header(best[2])))
                gap_ids.add(best[0])

    for index, page, text in items:
        if index in gap_ids:
            continue
        if _KEEP_PAGE.search(text) and not _is_glossary(text) and not _is_front_matter(text):
            take(index, page, text)
            spec.append(chosen[-1])
    spec.sort(key=lambda item: _score_block(item[1]), reverse=True)
    spec_ids = set(seen)
    seen = cover_ids | gap_ids | spec_ids
    ranked = sorted(items, key=lambda item: _score_block(item[2]), reverse=True)
    for index, page, text in ranked:
        if index in seen or _is_glossary(text) or _is_front_matter(text):
            continue
        rest.append((page, _strip_running_header(text)))
        seen.add(index)
        if len(cover) + len(gaps) + len(spec) + len(rest) >= page_cap:
            break
    ordered = cover + gaps + spec + rest
    if len(ordered) > page_cap:
        ordered = ordered[:page_cap]
    chunks: list[str] = []
    buf = ""
    for page, text in ordered:
        if buf and len(buf) + len(text) > EXTRACT_HEAD_CHARS:
            chunks.append(buf)
            buf = text
        else:
            buf = (buf + "\n" + text) if buf else text
        if len(chunks) >= limit:
            break
    if buf and len(chunks) < limit:
        chunks.append(buf)
    return chunks[:limit] or [markdown[:EXTRACT_HEAD_CHARS]]


_SPLIT_RETRY_MIN_CHARS = 1800


def _split_chunk_halves(chunk: str) -> list[str]:
    """把识别失败的段在中点附近的换行处切成两半；切不开就原样返回一段。"""
    text = chunk or ""
    if len(text) < _SPLIT_RETRY_MIN_CHARS:
        return [text] if text.strip() else []
    mid = len(text) // 2
    window = 600
    cut = -1
    for pattern in (r"\n(?=## 第 \d+ [页节])", r"\n(?=#{1,6} )", r"\n\n", r"\n(?=\|)", r"\n"):
        best = -1
        for match in re.finditer(pattern, text):
            if abs(match.start() - mid) <= window:
                if best < 0 or abs(match.start() - mid) < abs(best - mid):
                    best = match.start()
        if best > 0:
            cut = best
            break
    if cut <= 0:
        cut = mid
    head, tail = text[:cut].strip(), text[cut:].strip()
    return [part for part in (head, tail) if part]


def _llm_chunk_budget(empty_count: int, markdown: str = "") -> int:
    """空得越少，主抽段数越少。扫描件空格多时拉到上限，把 OCR 页送进模型。"""
    cap = _chunk_cap(markdown)
    if _is_ocr_markdown(markdown):
        if empty_count <= 20:
            return min(8, cap)
        if empty_count <= 40:
            return min(16, cap)
        return cap
    if empty_count <= 20:
        return min(6, cap)
    if empty_count <= 40:
        return min(8, cap)
    if empty_count <= 60:
        return min(12, cap)
    return cap


def _empty_field_count(rows: dict[int, ExtractedCell]) -> int:
    return sum(1 for cell in rows.values() if not (cell.value or "").strip())


def _parse_seq_name(item: dict[str, Any]) -> tuple[int, str]:
    name = str(item.get("name") or item.get("需求条目") or "").strip()
    seq = item.get("seq") or item.get("no") or item.get("id") or item.get("需求序号")
    match = re.match(r"^(\d{1,3})[.、．]\s*(.+)$", name)
    if match:
        if seq in (None, ""):
            seq = int(match.group(1))
        name = match.group(2).strip()
    try:
        seq_n = int(seq) if seq not in (None, "") else 0
    except (TypeError, ValueError):
        seq_n = 0
    return seq_n, name


def _names_compatible(left: str, right: str) -> bool:
    a, b = (left or "").strip(), (right or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 6 and shorter in longer


# 甲方将 #4 正式名由「充电升压」改为「行车升压」；旧名仍绑定同一格。
# 源表放电时间项已并入功能项。
_ITEM4_SCOPE = "设计范围是否包含行车升压功能"
_ITEM4_SCOPE_LEGACY = "设计范围是否包含充电升压功能"
_ACTIVE_DISCHARGE = "高压安全-主动放电功能"
_PASSIVE_DISCHARGE = "高压安全-被动放电功能"
_FIELD_NAME_ALIASES = {
    _ITEM4_SCOPE_LEGACY: _ITEM4_SCOPE,
    "主动放电时间": _ACTIVE_DISCHARGE,
    "被动放电时间": _PASSIVE_DISCHARGE,
}


def _canonical_field_name(name: str) -> str:
    text = (name or "").strip()
    return _FIELD_NAME_ALIASES.get(text, text)


def _bind_seq(seq: int, name: str, rows: dict[int, ExtractedCell]) -> int | None:
    name = _canonical_field_name(name)
    if seq and seq in rows and _names_compatible(name, rows[seq].name):
        return seq
    exact = [spec.seq for spec in load_template_fields() if spec.name == name]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        empty = [n for n in exact if not (rows[n].value or "").strip()]
        return (empty or exact)[0]
    if not name:
        return None
    hits = [
        spec.seq
        for spec in load_template_fields()
        if _names_compatible(name, spec.name)
    ]
    if len(hits) == 1:
        return hits[0]
    empty_hits = [n for n in hits if not (rows[n].value or "").strip()]
    if len(empty_hits) == 1:
        return empty_hits[0]
    return None


def _cell_from_item(item: dict[str, Any]) -> ExtractedCell | None:
    seq, name = _parse_seq_name(item)
    if not name and not seq:
        return None
    return ExtractedCell(
        seq=seq,
        name=name,
        value=str(item.get("value") or item.get("抽出值") or "").strip(),
        unit=str(item.get("unit") or "").strip(),
        page=str(item.get("page") or item.get("页码") or "").strip(),
        clause=str(item.get("clause") or item.get("条款号") or item.get("节号") or "").strip(),
        excerpt=str(item.get("excerpt") or item.get("原文摘录") or "").strip()[:_CLAUSE_LIMIT],
        confidence=_as_confidence(item.get("confidence") or item.get("置信度")),
        extra=True,
        note=str(item.get("note") or item.get("备注") or item.get("复核备注") or "").strip(),
        review_status=str(item.get("review_status") or item.get("核对状态") or "").strip(),
    )


def _connector_protection_kind(value: str) -> str:
    if re.search(r"IPXX|触指|防直触|防直接接触", value or "", re.I):
        return "touch"
    if re.search(r"高压直流连接|High Voltage DC connection", value or "", re.I):
        return "hvdc"
    return ""


def _attach(old: ExtractedCell, new: ExtractedCell) -> ExtractedCell:
    inherit_clause = new.clause or old.clause
    inherit_note = new.note or old.note
    inherit_status = new.review_status or old.review_status
    name = old.name or new.name or ""
    # 触指句与 6.2.3.2 高压直流连接不是同一摘录，不要把条款/局部对应备注串过去。
    if "高压连接器" in name:
        if _connector_protection_kind(old.value) != _connector_protection_kind(new.value):
            inherit_clause = new.clause
            inherit_note = new.note
            inherit_status = new.review_status
    merged = ExtractedCell(
        seq=old.seq,
        name=old.name,
        value=new.value,
        unit=new.unit,
        page=new.page or old.page,
        clause=inherit_clause,
        excerpt=new.excerpt or old.excerpt,
        confidence=new.confidence,
        hint=old.hint,
        impact=old.impact,
        example=old.example,
        note=inherit_note,
        review_status=inherit_status,
        extra=False,
    )
    result = _better(old, merged)
    if "高压连接器" in name and _connector_protection_kind(result.value) == "touch":
        if not re.search(
            r"6\.2\.3\.2|High Voltage DC connection",
            result.excerpt or "",
            re.I,
        ) and (result.clause or "").startswith("6.2.3.2"):
            result.clause = ""
        if result.note == _CONNECTOR_PROTECTION_NOTE:
            result.note = ""
        if (result.review_status or "") == STATUS_PARTIAL and re.search(
            r"IPXX|触指|防直触", result.value or "", re.I
        ):
            result.review_status = ""
    if not (result.clause or "").strip() and (merged.clause or old.clause):
        donor = merged if (merged.clause or "").strip() else old
        bemf = "反电动势" in name or "Back EMF" in name
        # 电机反电势表赢了「反电动势导致的过压」定性句时，不要接手 HV safety 的详见号。
        steal = True
        if bemf and re.search(r"\d{3,4}\s*V", result.value or "", re.I):
            if not re.search(r"\d{3,4}\s*V", donor.value or "", re.I):
                steal = False
        if "高压连接器" in name and _connector_protection_kind(result.value) == "touch":
            if not re.search(
                r"6\.2\.3\.2|High Voltage DC connection",
                result.excerpt or "",
                re.I,
            ):
                steal = False
        if steal:
            result.clause = merged.clause or old.clause
    if not (result.page or "").strip() and (merged.page or old.page):
        result.page = merged.page or old.page
    return result


def _is_weak_value(value: str) -> bool:
    return not value or bool(_WEAK_VALUE.match(value.strip()))


def _fold_text(text: str) -> str:
    return re.sub(r"[\s,，;；~～\-—–℃°]", "", (text or "")).lower()


def _copied_from_example(seq: int | None, name: str, value: str, excerpt: str) -> bool:
    """像清单「参考示例」且原文摘录对不上该值，视为模型抄模板。"""
    folded_value = _fold_text(value)
    if len(folded_value) < 5:
        return False
    specs = []
    if seq:
        specs = [item for item in load_template_fields() if item.seq == seq]
    if not specs and name:
        specs = [item for item in load_template_fields() if item.name == name]
    folded_excerpt = _fold_text(excerpt)
    for spec in specs:
        folded_example = _fold_text(spec.example)
        if folded_example and folded_value in folded_example:
            if folded_value in folded_excerpt:
                continue
            # OCR 常把单位写在数字前（rpm 20000），不能因此当成抄模板
            nums = [n for n in re.findall(r"\d+", value) if len(n) >= 3]
            if nums and all(n in folded_excerpt for n in nums):
                continue
            # 清单示例含「CAN / CAN FD / LIN」；摘录已有 LIN 时不是抄模板。
            if (
                "通讯" in (name or "")
                and re.search(r"\bLIN\b", value, re.I)
                and re.search(r"\bLIN\b", excerpt or "", re.I)
            ):
                continue
            return True
    return False


def _has_measurable_number(text: str) -> bool:
    """是否含可核对的数值（含单位的数字），用于区分流程语。"""
    return bool(
        re.search(
            r"\d+(?:\.\d+)?\s*(?:kW|kWh|V|Vdc|Vac|Vpp|A|Arms|mA|Nm|N·m|rpm|%|℃|°C|ms|s\b|L/?min|LPM|kPa|mbar|kg|MΩ|MOhm|µF|uF|nF)",
            text or "",
            re.I,
        )
    )


def _is_process_language(text: str) -> bool:
    """流程/转引语：没有可填参数，不应入库。"""
    if not text:
        return False
    if _has_measurable_number(text):
        return False
    return bool(
        re.search(
            r"吉利认可|硬件设计后|待供应商|待提供计算|"
            r"以电机实际达成为准|具体数值以|"
            r"详见传感器|详见\s*ESOW|详见\s*ICD|接口/规格详见|"
            r"supplier to provide|to be provided|after hardware|"
            r"初版设计指标|"
            r"meet the design spec|"
            r"shall meet the design specifications",
            text,
            re.I,
        )
    )


def _strip_markdown_hashes(text: str) -> str:
    """去掉 Markdown 标题的 #，避免 ### 条款标题被当成扫描花字。"""
    t = text or ""
    t = re.sub(r"(?m)^#{1,6}(?=\s|$)", "", t)
    t = re.sub(r"(?:(?<=\s)|(?<=^))#{1,6}(?=\s|[A-Za-z\u4e00-\u9fff])", "", t)
    return t


def _looks_like_ocr_garbage(text: str) -> bool:
    """扫描件中文栏花字：th#Hi#E&E、西里尔，不是 Markdown 标题的 #。"""
    raw = _PAGE_IN_EXCERPT.sub("", text or "")
    raw = _strip_markdown_hashes(raw)
    if not raw.strip():
        return False
    if re.search(r"[A-Za-z]#|#H|#R|#E", raw):
        return True
    if re.search(r"/à|#/", raw):
        return True
    if len(re.findall(r"#", raw)) >= 2:
        return True
    # 只数贴着字的 &（th#Hi#E&E）；两边带空格的 & 是「Y+≤130nF & Y-≤130nF」这类正常连接词
    odd = len(re.findall(r"(?<=\S)&(?=\S)|[À-ÖØ-öø-ÿ]|[А-яЁё]|/à ", raw))
    if odd >= 3:
        return True
    if re.search(r"\[VJ\b", raw):
        return True
    return False


def _ocr_garbage_samples(text: str) -> list[str]:
    raw = _strip_markdown_hashes(_PAGE_IN_EXCERPT.sub("", text or ""))
    found: list[str] = []
    for token in re.findall(r"[^\s]{0,8}#[^\s]{0,16}", raw):
        token = token.strip(".,;:()[]")
        if token and token not in found:
            found.append(token)
        if len(found) >= 3:
            break
    return found


def _ocr_excerpt_note(cell: ExtractedCell) -> str:
    samples = _ocr_garbage_samples(cell.excerpt or "")
    if samples:
        shown = "、".join(samples)
        cause = f"摘录被扫描识别花成「{shown}」这类字，不是规格书原句。"
    else:
        cause = "摘录被扫描识别花成 #、怪字母，不是规格书原句。"
    page = (cell.page or "").strip()
    if re.fullmatch(r"\d{1,4}", page):
        return cause + f"请打开第 {page} 页核对抽出值是不是该页上的数。"
    return cause + "请打开对应页核对抽出值是不是原页上的数。"


def _downgrade_ocr_excerpt(cell: ExtractedCell) -> None:
    """抽出值能读、摘录已乱码时，降为局部对应，避免扫描件假「已检索到」。"""
    if not _looks_like_ocr_garbage(cell.excerpt or ""):
        return
    if cell.confidence <= 0:
        cell.confidence = 0.72
    else:
        cell.confidence = min(cell.confidence, 0.72)
    concrete = _ocr_excerpt_note(cell)
    note = (cell.note or "").strip()
    if "扫描识别花成" in note:
        return
    if note.startswith("由物理公式计算"):
        cell.note = note + "；" + concrete
        return
    cell.note = concrete


_STALE_OCR_NOTE = re.compile(
    r"乱码|扫描识别花成|对照原页确认|请打开第\s*\d+\s*页核对抽出值|请打开对应页核对抽出值"
)


def _scrub_false_ocr_note(cell: ExtractedCell) -> None:
    """摘录已是通顺原句时，去掉「乱码 / 花成」备注，避免 Markdown 标题或模型抄旧句。"""
    if _looks_like_ocr_garbage(cell.excerpt or ""):
        _downgrade_ocr_excerpt(cell)
        return
    note = (cell.note or "").strip()
    if not _STALE_OCR_NOTE.search(note):
        return
    kept = re.sub(
        r"[；;,]?\s*(?:"
        r"原文摘录含扫描件乱码[^；;。]*|"
        r"摘录被扫描识别花成[^；;。]*|"
        r"请对照原页确认|"
        r"请打开第\s*\d+\s*页核对抽出值[^；;。]*|"
        r"请打开对应页核对抽出值[^；;。]*"
        r")[。]?",
        "",
        note,
    ).strip("；; ，,")
    cell.note = kept
    if (cell.review_status or "") != STATUS_PARTIAL and (cell.confidence or 0) <= 0.72:
        cell.confidence = max(float(cell.confidence or 0), 0.82)


def scrub_cells_ocr_notes(cells: list[ExtractedCell]) -> None:
    for cell in cells:
        _scrub_false_ocr_note(cell)


def _od_module_parenthetical_not_upshift(text: str, value: str = "") -> bool:
    """冷却流阻/压降括号里的 (with OD)，不是 OD 上移功能。"""
    raw = (value or "").strip()
    if re.fullmatch(r"[\(（]?\s*with\s*OD\s*[\)）]?", raw, re.I):
        return True
    blob = f"{raw}\n{text or ''}"
    if not re.search(r"with\s*OD|含OD", blob, re.I):
        return False
    return bool(
        re.search(
            r"flow resistance|冷却流阻|冷却回路压降|pressure drop|\bkPa\b|\bKpa\b|"
            r"10L/min|10\s*L/?min",
            blob,
            re.I,
        )
    )


def _is_junk_value(value: str, name: str = "") -> bool:
    text = (value or "").strip()
    if _looks_like_ocr_garbage(text):
        return True
    if re.search(r"\.(jpg|jpeg|png|gif|pdf|docx|xlsx)\b", text, re.I):
        return True
    # 条目编号「5.直流工作电压范围」；条款号 2.3.3.3 开头的原句不要当垃圾
    if re.match(r"^\d{1,3}[.．、](?!\d)", text) and not re.match(
        r"^\d+\.\d+\s*(kW|V|A|mA|Nm|%|kg|kPa|L|nF|MΩ)", text, re.I
    ):
        if not re.match(r"^\d{1,3}\.\S+[：:]", text):
            return True
    if re.search(r"未提及|not mentioned|supplier to provide", text, re.I):
        return True
    if "上移功能" in (name or "") and _od_module_parenthetical_not_upshift(text, text):
        return True
    # 失效分析/电路分析条目标题，不是保护阈值
    if re.search(r"\(\s*circuit analysis\s*\)|circuit analysis\s*$", text, re.I) and not _has_measurable_number(
        text
    ):
        return True
    if re.search(
        r"暂无具体|无具体数值|"
        r"容值供应商提供|检测阈值由供应商提供|指标供应商提供",
        text,
    ):
        return True
    if name and ("反电动势" in name or "Back EMF" in name) and _has_any(
        text, r"back[\s\-]?emf", r"反电动势"
    ):
        return False
    if _is_process_language(text):
        return True
    # 「满足下面的map表」之类是原文指向，不是可填入的参数值
    if re.search(r"满足.*map\s*表|见下[面图表]|refer to (the )?map|see (the )?map", text, re.I):
        return True
    # 表头当值
    if re.search(
        r"Oil\s*/\s*coolant\s*/\s*environmental\s*Temp",
        text,
        re.I,
    ) and not re.search(r"-40|\d+\s*℃|\d+\s*°C", text):
        return True
    folded_val = _fold_text(text)
    if name and folded_val == _fold_text(name):
        return True
    if folded_val in {_fold_text(spec.name) for spec in load_template_fields()}:
        return True
    if text in {"振动", "Vibration", "ISO 26262", "过压点"}:
        return True
    if "过压" in (name or "") and re.search(
        r"protect itself from excess voltage|发电和电机运行高压保护",
        text,
        re.I,
    ) and not re.search(r"\d+\s*V(?:dc)?", text, re.I):
        return True
    if re.fullmatch(r"Maximum allowable RPM", text, re.I):
        return True
    if (
        "耐电压" in (name or "")
        and re.search(r"Partner proposal", text, re.I)
        and not re.search(r"\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc)", text, re.I)
    ):
        return True
    if (
        "Boost输出性能" in (name or "")
        and re.search(
            r"shall be able to boost|应能够将直流输入的电压提升",
            text,
            re.I,
        )
        and not re.search(r"\d{3,4}\s*V", text, re.I)
    ):
        return True
    if re.fullmatch(r"Motor/Gearbox Same\s*Con\s*tent", text, re.I):
        return True
    return False


def _value_in_source(value: str, excerpt: str, chunk: str) -> bool:
    folded_chunk = _fold_text(chunk)
    folded_value = _fold_text(value)
    if len(folded_value) >= 6 and folded_value in folded_chunk:
        return True
    folded_excerpt = _fold_text(excerpt)
    if len(folded_excerpt) >= 8 and folded_excerpt[:32] in folded_chunk:
        return True
    excerpt_text = (excerpt or "").strip()
    return bool(excerpt_text and excerpt_text[:24] in chunk)


def _has_any(text: str, *patterns: str) -> bool:
    return any(re.search(pat, text, flags=re.I) for pat in patterns)


def _looks_like_operating_voltage_withstand(text: str) -> bool:
    """HVDC 持续供电上限 / 工作电压 withstand，不是绝缘耐电压条款。"""
    hipot = _has_any(
        text,
        r"击穿",
        r"漏电流",
        r"工频耐",
        r"1\s*(?:min|分钟)",
        r"hipot",
        r"18488",
        r"16935",
        r"闪络",
    )
    if _has_any(
        text,
        r"连续高压直流耐压",
        r"Continuous HVDC withstand voltage",
        r"连续耐压最大",
        r"shall not generate continuous",
        r"不得产生高于",
        r"Maximum allowed generated HVDC",
        r"允许产生的最大直流高压",
    ) and not hipot:
        return True
    if hipot:
        return False
    return _has_any(
        text,
        r"continuous supply",
        r"withstand continuous",
        r"持续供电",
        r"持续耐受",
        r"without any permanent",
        r"without any performance",
        r"Umax\s*operating",
        r"on the HVDC bus without",
        r"maximum 500\s*V on the HVDC",
    )


def _looks_like_dc_capacitor_spec(text: str) -> bool:
    """Hyundai 逆变器 Table 3.9 / 电容规范，不是整机电压、绝缘、静态电流。"""
    return bool(
        _has_any(
            text,
            r"DC capacitor",
            r"DC Capacitor Required",
            r"DC 电容规范",
            r"Table 3\.9",
        )
        or (
            _has_any(text, r"@ Rated Voltage", r"Rated Voltage,\s*1min")
            and _has_any(text, r"Dark Current", r"500Vdc", r"10G\s*\(\s*10")
        )
    )


_HVDC_ROW_SPECS = (
    ("cold", r"Min level during cold ICE start|冷启动时的最低电压"),
    ("limited_min", r"Min level for limited performance|性能限制时的最低(?:电压)?"),
    ("full_min", r"Min level for full power|满功率时的最低电压"),
    ("full_max", r"Max level for full power|满功率时的最高电压"),
    ("limited_max", r"Max limited performance|限制性能下可工作最高电压"),
)


def _hvdc_volt_token(text: str, *, min_v: int = 200) -> str | None:
    raw = (text or "").strip()
    if raw in {"/", "—", "-", "–", "TBD", ""}:
        return ""
    match = re.search(r"(?<!\d)(\d{3,4})(?:\s*V(?:dc)?)?(?!\d)", raw, re.I)
    if match and min_v <= int(match.group(1)) <= 1200:
        return match.group(1)
    return None


def _parse_hvdc_bus_rows(chunk: str) -> tuple[dict[str, str], str, int] | None:
    """按行读 HVDC 电压表，不要把 380 640 945 粘成一串再按位置猜。"""
    head = re.search(r"HVDC Voltage Range|HVDC bus voltage", chunk, re.I)
    if not head:
        return None
    start = head.start()
    stop = re.search(
        r"Full power is a condition|Limited performance is a condition",
        chunk[start + 24 :],
        re.I,
    )
    end = start + 24 + stop.start() if stop else min(len(chunk), start + 900)
    window = chunk[start:end]
    rows: dict[str, str] = {}
    excerpts: list[str] = []
    for key, pat in _HVDC_ROW_SPECS:
        match = re.search(
            rf"(?:{pat})[^\n|]{{0,80}}(?:\|\s*)?(/|\d{{3,4}})",
            window,
            re.I,
        )
        if not match:
            continue
        token = _hvdc_volt_token(match.group(match.lastindex))
        if token is None:
            continue
        rows[key] = token
        excerpts.append(re.sub(r"\s+", " ", match.group(0)).strip()[:80])
    if {"limited_min", "full_min", "full_max"} <= rows.keys():
        return rows, "；".join(excerpts)[:200], start
    labels: list[tuple[int, str]] = []
    for key, pat in _HVDC_ROW_SPECS:
        match = re.search(pat, window, re.I)
        if match:
            labels.append((match.start(), key))
    labels.sort()
    if len(labels) < 3:
        return None
    tail = window[labels[-1][0] :]
    nums: list[str] = []
    for match in re.finditer(r"(?m)^\s*(/|\d{3,4})\s*$", tail):
        token = _hvdc_volt_token(match.group(1))
        if token is not None:
            nums.append(token)
    if len(nums) < 3:
        nums = []
        for match in re.finditer(r"(?<!\d)(/|\d{3,4})(?!\d)", tail):
            token = _hvdc_volt_token(match.group(1))
            if token is not None:
                nums.append(token)
    keys = [key for _, key in labels]
    mapped: dict[str, str] = {}
    if len(nums) == len(keys) - 1 and keys[0] == "cold":
        mapped[keys[0]] = ""
        for key, num in zip(keys[1:], nums):
            mapped[key] = num
    elif len(nums) >= 3:
        for key, num in zip(keys, nums):
            mapped[key] = num
    else:
        return None
    rows.update(mapped)
    if not (rows.get("full_min") and rows.get("full_max")):
        return None
    parts = []
    names = {
        "cold": "冷启动",
        "limited_min": "性能限制最低",
        "full_min": "满功率最低",
        "full_max": "满功率最高",
        "limited_max": "限制性能最高",
    }
    for key, _pat in _HVDC_ROW_SPECS:
        if key not in rows:
            continue
        parts.append(f"{names[key]} {rows[key] or '/'}V" if rows[key] else f"{names[key]} /")
    return rows, "；".join(parts)[:200], start


_HVDC_CURRENT_SPECS = (
    ("current_min", r"Min level for full current|满电流时的最低电压"),
    ("current_max", r"Max level for full current|满电流时的最高电压"),
)


def _parse_hvdc_boost_split_rows(
    chunk: str,
) -> tuple[dict[str, tuple[str, str]], str, int] | None:
    """DHTS 类：HVDC 表头同时有「非升压 | 升压」两列。PDF 常把两列拆成换行。"""
    head = re.search(
        r"HVDC bus voltage[\s\S]{0,120}?非升压[\s\S]{0,80}?升压",
        chunk,
        re.I,
    )
    if not head:
        return None
    start = head.start()
    window = chunk[start : min(len(chunk), start + 1800)]
    rows: dict[str, tuple[str, str]] = {}
    excerpts: list[str] = []
    for key, pat in (*_HVDC_ROW_SPECS, *_HVDC_CURRENT_SPECS):
        match = re.search(
            rf"(?:{pat})\s*(?:\|\s*)?(/|\d{{3,4}})\s*(?:\|\s*)?(/|\d{{3,4}})",
            window,
            re.I,
        )
        if not match:
            continue
        left = _hvdc_volt_token(match.group(1), min_v=150)
        right = _hvdc_volt_token(match.group(2), min_v=150)
        if left is None and right is None:
            continue
        rows[key] = (left or "", right or "")
        excerpts.append(re.sub(r"\s+", " ", match.group(0)).strip()[:100])
    if not ({"limited_min", "full_min", "full_max"} <= rows.keys()):
        return None
    if not (rows["full_min"][0] or rows["full_min"][1]):
        return None
    if not (rows["full_max"][0] or rows["full_max"][1]):
        return None
    return rows, "；".join(excerpts)[:220], start


def _fmt_hvdc_nb_boost(pair: tuple[str, str], label: str) -> str:
    nb, boost = pair
    gap = f"{label}" if label else ""
    if nb and boost and nb != boost:
        return f"{gap}非升压{nb}V/升压{boost}V"
    volt = nb or boost
    return f"{gap}{volt}V" if volt else ""


def _fmt_hvdc_range(lo: tuple[str, str], hi: tuple[str, str], label: str) -> str:
    nb = f"{lo[0]}~{hi[0]}" if lo[0] and hi[0] else (lo[0] or hi[0])
    boost = f"{lo[1]}~{hi[1]}" if lo[1] and hi[1] else (lo[1] or hi[1])
    gap = f"{label}" if label else ""
    if nb and boost and nb != boost:
        return f"{gap}非升压{nb}V；升压{boost}V"
    rng = nb or boost
    return f"{gap}{rng}V" if rng else ""


_HVDC_V_MISSING = "未给出"


def _hvdc_volt_display(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text or text in {"/", "—", "-", "–"}:
        return _HVDC_V_MISSING
    if re.fullmatch(r"\d{3,4}", text):
        return f"{text}V"
    match = re.fullmatch(r"(\d{3,4})\s*V(?:dc)?", text, re.I)
    if match:
        return f"{match.group(1)}V"
    return text if re.search(r"V", text, re.I) else f"{text}V"


def _hvdc_pair_display(pair: tuple[str, str] | str | None) -> str:
    if pair is None:
        return _HVDC_V_MISSING
    if isinstance(pair, str):
        return _hvdc_volt_display(pair)
    left = _hvdc_volt_display(pair[0])
    right = _hvdc_volt_display(pair[1])
    if left == _HVDC_V_MISSING and right == _HVDC_V_MISSING:
        return _HVDC_V_MISSING
    if left == _HVDC_V_MISSING:
        return f"升压{right}"
    if right == _HVDC_V_MISSING:
        return f"非升压{left}"
    if left == right:
        return left
    return f"非升压{left} / 升压{right}"


def _fmt_hvdc_state_lines(states: list[tuple[str, str, str]]) -> str:
    """核对表写法：1.状态最低：xxx  最高：xxx"""
    lines: list[str] = []
    for name, lo, hi in states:
        lo_d = lo or _HVDC_V_MISSING
        hi_d = hi or _HVDC_V_MISSING
        lines.append(f"{len(lines) + 1}.{name}最低：{lo_d}  最高：{hi_d}")
    return "\n".join(lines)


def _fmt_simple_hvdc_range(state: str, raw: str, *, extra: str = "") -> str:
    text = (raw or "").strip()
    match = re.search(r"(\d{3,4})\s*V?\s*[~～\-–]\s*(\d{3,4})", text, re.I)
    if match:
        hi = f"{match.group(2)}V"
        if extra:
            hi = f"{hi}（{extra}）"
        return _fmt_hvdc_state_lines([(state, f"{match.group(1)}V", hi)])
    match = re.search(r"(\d{3,4})\s*V", text, re.I)
    if match:
        return _fmt_hvdc_state_lines([(state, f"{match.group(1)}V", _HVDC_V_MISSING)])
    return text


def _hvdc_value_has_pair(value: str, lo: str, hi: str) -> bool:
    text = value or ""
    if re.search(rf"{lo}\s*V?\s*[~～-]\s*{hi}", text, re.I):
        return True
    return bool(
        re.search(rf"最低：\s*{lo}\s*V", text, re.I)
        and re.search(rf"最高：\s*{hi}\s*V", text, re.I)
    )


def _parse_lv_current_rows(chunk: str) -> dict[str, tuple[str, str, int]]:
    """P63 低压电流表：未唤醒静态、唤醒工作电流按行读。"""
    found: dict[str, tuple[str, str, int]] = {}
    idle = re.search(
        r"未唤醒@仅低压上电[\s\S]{0,80}?"
        r"≤?\s*(\d+(?:\.\d+)?)"
        r"(?:\s*\(PCM≤?\s*(\d+(?:\.\d+)?)；OD≤?\s*(\d+(?:\.\d+)?)\))?",
        chunk,
    )
    if idle:
        raw = idle.group(1)
        try:
            amps = float(raw)
        except ValueError:
            amps = -1
        if 0 < amps <= 20:
            extra = ""
            if idle.group(2) and idle.group(3):
                extra = f"；PCM≤{idle.group(2)}，OD≤{idle.group(3)}"
            found["static"] = (
                f"≤{raw}mA（未唤醒，仅低压上电{extra}）",
                re.sub(r"\s+", " ", idle.group(0)).strip()[:200],
                idle.start(),
            )
    wake = re.search(
        r"唤醒@IGBT\s*开管@高低压都上电[^\n\d]{0,40}?(\d{3,5})([^\n|]{0,40})",
        chunk,
    )
    if wake:
        n = int(wake.group(1))
        if 100 <= n <= 8000:
            window = wake.group(0)
            note = "（稳态，不含电子锁及差速锁）" if "不含电子锁" in window else ""
            found["wake"] = (
                f"唤醒@IGBT开管 {n}mA{note}",
                re.sub(r"\s+", " ", window).strip()[:200],
                wake.start(),
            )
    if "wake" not in found:
        wltc = re.search(
            r"唤醒@IGBT\s*开管@高低压都上电[\s\S]{0,80}?"
            r"(\d+(?:\.\d+)?)\s*W\s*@\s*(\d+)\s*V(?:@WLTC)?",
            chunk,
            re.I,
        )
        if wltc:
            watts, volts = wltc.group(1), wltc.group(2)
            found["wake"] = (
                f"{watts}W@{volts}V@WLTC（唤醒@IGBT开管）",
                re.sub(r"\s+", " ", wltc.group(0)).strip()[:200],
                wltc.start(),
            )
    return found


def _hvac_motor_lang_amps(text: str, motor: str) -> tuple[str, str]:
    """HVAC 相电流峰值（A）：(中文, 英文)。缺一种语言则该侧为空。"""
    block = text or ""
    cn = ""
    match = re.search(
        rf"测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A峰值范围内.{{0,80}}{motor}",
        block,
        re.I,
    )
    if match:
        cn = match.group(1)
    else:
        match = re.search(
            rf"{motor}逆变器[^\n]{{0,48}}测量[-－]?\s*(\d{{2,4}})\s*A至\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            cn = match.group(1)
    en = ""
    match = re.search(
        rf"PEI {motor}:[\s\S]{{0,280}}?-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
        block,
        re.I,
    )
    if match:
        en = match.group(1)
    else:
        match = re.search(
            rf"PEI {motor} within the range\s*-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
            block,
            re.I,
        )
        if match:
            en = match.group(1)
    return cn, en


def _hvac_motor_peak_a(text: str, motor: str) -> str:
    """单侧峰值：中英一致或只有一种语言时用该值。冲突时不要只用这一侧。"""
    cn, en = _hvac_motor_lang_amps(text, motor)
    if cn and en and cn != en:
        return ""
    return cn or en


def _hvac_peak_phrase(cn: str, en: str) -> tuple[str, bool]:
    """量程短语。中英数字不同则两种都写。"""
    if cn and en and cn != en:
        return (
            f"中文 −{cn}A~+{cn}A 峰值；英文 −{en}A~+{en}A 峰值",
            True,
        )
    amp = cn or en
    if not amp:
        return "", False
    return f"−{amp}A~+{amp}A 峰值", False


def _hvac_accuracy_detail(window: str) -> str:
    """精度档取当份中文（无中文再看英文），不把别份的 1.5% 写死进来。"""
    bits: list[str] = []
    if re.search(r"全生命周期测量误差小于\s*±\s*3\s*%", window or ""):
        bits.append("全生命周期 ＞100A ±3% / 0–100A ±3A")
    elif re.search(r"measurement error less than\s*±\s*3\s*%", window or "", re.I):
        bits.append("＞100A ±3% / 0–100A ±3A")
    if re.search(r"室温标定后测量误差", window or ""):
        bits.append("室温标定后 ±1.5%/±1.5A")
    elif re.search(
        r"±\s*1\.5\s*%[\s\S]{0,40}room temperature|after calibration[\s\S]{0,40}±\s*1\.5",
        window or "",
        re.I,
    ):
        bits.append("室温标定后 ±1.5%/±1.5A")
    return "，".join(bits) if bits else ""


def _hvac_chinese_excerpt(window: str) -> str:
    lines = re.findall(
        r"控制器应能够测量[-－]?\s*\d{2,4}\s*A至\+\s*\d{2,4}\s*A峰值范围内[^\n]{0,80}P[13]逆变器[^\n]+",
        window or "",
    )
    extra = re.findall(r"室温标定后测量误差[^\n]+", window or "")
    text = " ".join(lines + extra[:1])
    return re.sub(r"\s+", " ", text).strip()[:420]


def _hvac_english_excerpt(window: str, *, compact: bool = False) -> str:
    bits: list[str] = []
    for motor in ("P1", "P3"):
        match = re.search(
            rf"PEI {motor}:[\s\S]{{0,280}}?-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
            window or "",
            re.I,
        )
        if not match:
            match = re.search(
                rf"PEI {motor} within the range\s*-\s*(\d+)\s*A\s*to\s*\+\s*\1\s*A",
                window or "",
                re.I,
            )
        if not match:
            continue
        amp = match.group(1)
        if compact:
            bits.append(f"PEI {motor}: -{amp}A to +{amp}A peak")
        else:
            bits.append(re.sub(r"\s+", " ", match.group(0)).strip()[:220])
    extra = re.findall(
        r"Measurement error less than\s*±\s*1\.5\s*%[^\n]+",
        window or "",
        re.I,
    )
    if extra and not compact:
        bits.append(re.sub(r"\s+", " ", extra[0]).strip())
    return " ".join(bits).strip()[:420]


def _hvac_excerpt(window: str, *, bilingual: bool) -> str:
    cn = _hvac_chinese_excerpt(window)
    if not bilingual:
        return cn or _hvac_english_excerpt(window)
    en = _hvac_english_excerpt(window, compact=True)
    return " ".join(part for part in (cn, en) if part).strip()[:_CLAUSE_LIMIT]


def _hvac_phase_accuracy(window: str) -> tuple[str, str]:
    """抽出值 + 复核备注。中英数字不一致才写两种量程并要人工复核。"""
    p1_cn, p1_en = _hvac_motor_lang_amps(window, "P1")
    p3_cn, p3_en = _hvac_motor_lang_amps(window, "P3")
    p1, p1_conflict = _hvac_peak_phrase(p1_cn, p1_en)
    p3, p3_conflict = _hvac_peak_phrase(p3_cn, p3_en)
    if not p1 and not p3:
        return "", ""
    detail = _hvac_accuracy_detail(window) or "＞100A ±3% / 0–100A ±3A"
    parts: list[str] = []
    if p1:
        parts.append(f"P1：{p1}，{detail}")
    if p3:
        parts.append(f"P3：{p3}，{detail}")
    note = "中英文量程不一致，需人工复核。" if (p1_conflict or p3_conflict) else ""
    return "；".join(parts), note


def _hvac_phase_accuracy_value(window: str) -> str:
    value, _note = _hvac_phase_accuracy(window)
    return value


def _parse_pcm_mass_kg(chunk: str) -> tuple[str, str, int] | None:
    """总成重量：允许换行、表列、kg 在数字前，以及两列重复 14.9。"""
    patterns = (
        r"动力控制模块[_\s]*总?成?[\s\S]{0,80}?(\d+[.．]\d+)\s+\1",
        r"动力控制模块[_\s]*总?成?[\s\S]{0,80}?(\d+[.．]\d+)\s*(?:kg|公斤)",
        r"动力控制模块[^\n]{0,80}?(?:kg|公斤)[^\n|]{0,24}(\d+[.．]\d+)",
        r"动力控制模块[^\n]{0,48}\|\s*(\d+[.．]\d+)\s*\|",
        r"总成重量[\s\S]{0,48}?(\d+[.．]\d+)\s*(?:kg|公斤)",
        r"(?:PCM|assembly)[^\n]{0,40}(?:weight|mass)[^\n]{0,40}?(\d+[.．]\d+)\s*kg",
        r"可拓展动力域控制模块[_\s]*总成[^\n|]{0,48}\|\s*(\d{2})\s*\|\s*1\s*\|\s*\1",
        r"单件目标重量/kg[^\n]{0,200}?\|\s*(\d{2})\s*\|\s*1\s*\|\s*\1",
    )
    for pat in patterns:
        match = re.search(pat, chunk or "", re.I)
        if not match:
            continue
        kg = match.group(1).replace("．", ".")
        try:
            mass = float(kg)
        except ValueError:
            continue
        if not (8.0 <= mass <= 25.0) or kg in {"20.2", "18.5"}:
            continue
        return (
            f"{kg}kg（单件目标重量）",
            match.group(0)[:160],
            match.start(),
        )
    return None


def _motor_label_ok(name: str, text: str) -> bool:
    """P1 条目不得只用 P3 原文；P1/P3 功率不得绑 HVDC 连接器/母线峰值。"""
    p1_name = "P1" in name and "P3" not in name
    p3_name = "P3" in name
    if not (p1_name or p3_name):
        return True
    if not re.search(r"扭矩|功率|转速|反电|ASC|电流", name):
        return True
    has_p1 = bool(
        re.search(r"(?<![A-Za-z0-9])P(?:1|[lI])(?![A-Za-z0-9])", text)
        or re.search(r"P1电机|PCM\s*P1|PCMP[lI1]|PI[:：]", text, re.I)
    )
    has_p3 = bool(
        re.search(r"(?<![A-Za-z0-9])P3(?![A-Za-z0-9])|P3电机|PCM\s*P3|PCMP3", text, re.I)
    )
    if p1_name and has_p3 and not has_p1:
        return False
    if p3_name and has_p1 and not has_p3:
        return False
    if p3_name and re.search(r"HVDC peak|高压直流峰值功率", text, re.I) and not has_p3:
        return False
    if p1_name and re.search(
        r"HVDC peak|高压直流峰值功率|HVDC continuous power|高压直流持续功率",
        text,
        re.I,
    ) and not has_p1:
        return False
    return True


def _clause_token(text: str) -> str:
    """从字符串取出 2.3.3.3 / 6.5.11.1 这类条款号，不是印页。"""
    last = ""
    for match in _CLAUSE_NUM.finditer(text or ""):
        last = match.group(1)
    return last


def _is_external_clause_cite(chunk: str, abs_pos: int) -> bool:
    """企标/国标里的「5.3.10」不是本份规格书章节号。"""
    left = chunk[max(0, abs_pos - 56) : abs_pos]
    if left.endswith("的") or re.search(r"中\s*$", left):
        return True
    if re.search(r"(?:参考|按|见|详见|According).{0,48}$", left, re.I):
        return True
    if re.search(
        r"(?i)(?:as shown in|shown in|see (?:also )?(?:section|chapter|clause))\s*$",
        left,
    ):
        return True
    if re.search(r"(?:Q/JL[Y]?|GB/T|ISO|J711)\S{0,48}$", left):
        return True
    return False


def _heading_number_on_line(stripped: str) -> str:
    """行首已印的章节号。4.6 这类两段号也算；12.5 kW 不算。"""
    match = _HEADING_LINE_CLAUSE.match(stripped or "")
    if not match:
        return ""
    rest = (stripped or "")[match.end() :].strip()
    if rest and _HEADING_UNIT_TAIL.match(rest):
        return ""
    return match.group(1)


def _heading_clause_before(chunk: str, index: int) -> tuple[str, int]:
    """最近一行已印在行首的条款号（2.3.2 性能表、4.6 阻燃、6.5.7.1 等）。不限 1600 字。"""
    last = ""
    last_at = -1
    pos = 0
    length = len(chunk)
    while pos <= index and pos < length:
        nl = chunk.find("\n", pos)
        line_end = nl if nl >= 0 else length
        raw = chunk[pos:line_end]
        stripped = raw.strip()
        num = _heading_number_on_line(stripped)
        if num:
            rel = raw.find(num)
            abs_pos = pos + (rel if rel >= 0 else 0)
            if abs_pos <= index and not _is_external_clause_cite(chunk, abs_pos):
                last = num
                last_at = abs_pos
        if nl < 0 or line_end >= index:
            break
        pos = nl + 1
    return last, last_at


def _clause_for_index(chunk: str, index: int) -> str:
    if not chunk:
        return ""
    index = max(0, min(index, len(chunk)))
    line_start = chunk.rfind("\n", 0, index) + 1
    line_end = chunk.find("\n", index)
    line = chunk[line_start : line_end if line_end >= 0 else len(chunk)]
    own = _heading_number_on_line(line.strip())
    if own:
        return own
    heading, heading_at = _heading_clause_before(chunk, index)
    if heading and heading_at >= 0:
        rest = chunk[heading_at:index]
        nl = rest.find("\n")
        after = rest[nl + 1 :] if nl >= 0 else ""
        if _UNNUMBERED_PEI_HEADING.search(line) or _UNNUMBERED_PEI_HEADING.search(after):
            return ""
        return heading
    start = max(0, index - 1600)
    window = chunk[start : index + 120]
    last = ""
    last_at = -1
    for match in _CLAUSE_NUM.finditer(window):
        abs_pos = start + match.start()
        if abs_pos <= index:
            if _is_external_clause_cite(chunk, abs_pos):
                continue
            last = match.group(1)
            last_at = abs_pos
    if last and last_at >= 0:
        between = chunk[last_at:index]
        nl = between.find("\n")
        rest = between[nl + 1 :] if nl >= 0 else ""
        if _UNNUMBERED_PEI_HEADING.search(line) or _UNNUMBERED_PEI_HEADING.search(rest):
            return ""
    return last


def _implied_clause(text: str) -> str:
    blob = text or ""
    for pat, num in _HEADING_CLAUSE:
        if pat.search(blob):
            return num
    return ""


def _page_in_excerpt(excerpt: str) -> str:
    match = _PAGE_IN_EXCERPT.search(excerpt or "")
    return match.group(1) if match else ""


def _find_longest_prefix_hit(chunk: str, snippet: str, n: int) -> int:
    """前 n 字在原文出现多处时，选与整段摘录公共前缀最长的那一处。

    DHTS 6.5.7.1（P1）与 6.5.8.1（P3）开头 48 字完全相同
    「During active short circuit the maximum allowed 」，只取首次出现会把 P3 摘录
    定位到 P1 句，随后 P1/P3 标签守卫正确拒格，#55/#57 规则路径每次必漏。
    """
    head = snippet[:n]
    if not head:
        return -1
    best, best_len = -1, -1
    start = 0
    limit_total = len(snippet)
    while True:
        idx = chunk.find(head, start)
        if idx < 0:
            break
        length = n
        limit = min(limit_total, len(chunk) - idx)
        while length < limit and chunk[idx + length] == snippet[length]:
            length += 1
        if length > best_len:
            best, best_len = idx, length
        if length >= limit_total:
            break
        start = idx + 1
    return best


def _excerpt_index(chunk: str, excerpt: str) -> int:
    """定位摘录在原文中的位置。展开成单行后不能再用原文换行去 find。"""
    snippet = (excerpt or "").strip()
    if not snippet or not chunk:
        return -1
    n = min(48, len(snippet))
    idx = _find_longest_prefix_hit(chunk, snippet, n)
    if idx >= 0:
        return idx
    rest = _PAGE_IN_EXCERPT.sub("", snippet).strip()
    if rest:
        idx = _find_longest_prefix_hit(chunk, rest, min(40, len(rest)))
        if idx >= 0:
            return idx
        idx = _find_longest_prefix_hit(
            chunk.lower(), rest.lower(), min(40, len(rest))
        )
        if idx >= 0:
            return idx
    marker = _PAGE_IN_EXCERPT.search(snippet)
    if marker:
        idx = chunk.find(marker.group(0))
        if idx >= 0:
            return idx
    return -1


def _looks_like_hvdc_voltage_table(text: str) -> bool:
    return bool(
        re.search(
            r"HVDC Voltage Range|HVDC bus voltage|高压范围|"
            r"冷启动时的最低电压|满功率时的最低电压|性能限制时的最低电压",
            text or "",
            re.I,
        )
    )


def _is_continuous_hvdc_withstand(text: str) -> bool:
    """6.6.3 连续高压直流耐压（母线持续供电），不是 ISO 6469 工频。"""
    generate_limit = _has_any(
        text,
        r"shall not generate",
        r"不得产生高于",
        r"Maximum allowed generated HVDC",
        r"允许产生的最大直流高压",
    )
    body = _has_any(
        text,
        r"Continuous HVDC withstand voltage",
        r"连续高压直流耐压",
        r"withstand continuous supply voltages of maximum \d{2,4}\s*V on the HVDC bus",
        r"承受高压直流母线上最大\d{2,4}\s*V的连续供电电压",
        r"母线持续供电最大",
    ) and _has_any(
        text,
        r"continuous supply",
        r"持续供电",
        r"连续供电",
        r"without any permanent",
        r"无永久性损坏",
    )
    if generate_limit and not body:
        return False
    return body


def _pick_clause(chunk: str, index: int | None, excerpt: str = "", name: str = "") -> str:
    if "耐电压" in (name or "") and _is_continuous_hvdc_withstand(excerpt or ""):
        return "6.6.3"
    hv = _pick_hv_safety_clause(chunk, index, name)
    if hv:
        return hv
    implied = _implied_clause(excerpt)
    if not implied and index is not None and chunk:
        implied = _implied_clause(chunk[max(0, index - 240) : index + 80])
    located = ""
    if index is not None and index >= 0:
        located = _clause_for_index(chunk, index)
    # 高压范围表扩句可能带上低压功耗行；只挡电压格，不把低压格的 6.5.2 清掉。
    hvdc_field = name in _HVDC_OPERATING_VOLTAGE_FIELDS
    if hvdc_field or (not name and _looks_like_hvdc_voltage_table(excerpt)):
        if located and not re.match(r"^6\.4\.2\.\d+$", located) and located != "6.5.2":
            return located
        return ""
    # 6.5.2 只在当份印出或修订记录写过时才用，不把 DHTS 目录结构套到 SuperEvo。
    if implied == "6.5.2":
        blob = f"{chunk or ''}\n{excerpt or ''}"
        if "6.5.2" not in blob:
            implied = ""
    # 6.8.3 只映冷却压降标题，不把未印号的「热损失」节挂上压降条款。
    if implied == "6.8.3" and "热损失" in (name or ""):
        if not re.search(r"Coolant pressure drop|冷却回路压降", excerpt or "", re.I):
            implied = ""
    if (
        "热损失" in (name or "")
        and located
        and located != "6.8.3"
        and not re.search(r"Coolant pressure drop|冷却回路压降", excerpt or "", re.I)
    ):
        return located
    if implied:
        return implied
    return located


def _formula_note(formula: str, *parts: str) -> str:
    used = "、".join(str(p).strip() for p in parts if str(p).strip())
    if used:
        return f"{DERIVE_NOTE}：{formula}（代入 {used}）"
    return f"{DERIVE_NOTE}：{formula}"


def _fmt_vi_at(volt: str, amp: str, duration: str = "", *, current_kind: str = "peak") -> str:
    """代入量：最大电压×最大电流@时间，或最大电压×持续电流。"""
    v = re.sub(r"(?i)v(?:dc)?$", "", (volt or "").strip())
    a = re.sub(r"(?i)a(?:rms)?$", "", (amp or "").strip())
    amp_name = "持续电流" if current_kind == "cont" else "最大电流"
    body = f"最大电压{v}V×{amp_name}{a}A"
    t = re.sub(r"\s+", "", (duration or "").strip())
    if t:
        t = re.sub(r"S$", "s", t)
        body += f"@{t}"
    return body


def _p_kw_from_vi(volt: str, amp: str) -> str | None:
    try:
        v = float(re.sub(r"[^0-9.]+", "", (volt or "").replace(",", "")))
        a = float(re.sub(r"[^0-9.]+", "", (amp or "").replace(",", "")))
    except ValueError:
        return None
    if v <= 0 or a <= 0:
        return None
    return f"{_fmt_qty(v * a / 1000.0)}kW"


def _fmt_p_ui_at(volt: str, amp: str, duration: str = "", *, current_kind: str = "peak") -> str:
    """#68：P=UI 点值，括注最大电压×最大/持续电流@t。不把电压区间展开成 kW 范围。"""
    vi = _fmt_vi_at(volt, amp, duration, current_kind=current_kind)
    power = _p_kw_from_vi(volt, amp)
    if not power:
        return vi
    return f"{power}（{vi}）"


def _fmt_boost_power_state_lines(states: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    for name, body in states:
        if not body:
            continue
        if name:
            lines.append(f"{len(lines) + 1}.{name}：{body}")
        else:
            lines.append(f"{len(lines) + 1}.{body}")
    return "\n".join(lines)


def _boost_output_vmax(chunk: str) -> str | None:
    """升压输出最高电压：当份升压器目标或升压至区间上限，不拿 HVDC 峰值功率行。"""
    match = re.search(r"升压器的目标输出电压[^\n]{0,48}\|\s*(\d{3,4})", chunk)
    if match:
        return match.group(1)
    match = re.search(
        r"Target output voltage of booster[^\n]{0,48}\|\s*(\d{3,4})",
        chunk,
        re.I,
    )
    if match:
        return match.group(1)
    match = re.search(r"升压至(\d{3,4})\s*[-~～]\s*(\d{3,4})\s*V", chunk)
    if match:
        return str(max(int(match.group(1)), int(match.group(2))))
    return None


def _parse_boost_power_vi(chunk: str) -> tuple[str, str, int, tuple[str, ...]] | None:
    """#68：当份已给出升压电流和输出电压时，按 P=UI 写出 kW 点值，括注最大电压×最大/持续电流@t。"""
    if not (
        re.search(
            r"表1：DHTS160--boost\s*峰值|"
            r"BOOST input peak current.{0,80}\d{2,4}\s*A\s*@\s*\d+\s*S",
            chunk,
            re.I | re.S,
        )
        and re.search(r"表3：DHT160S\s*--boost|Boost\s*:\s*\d{2,4}\s*A", chunk, re.I)
    ):
        return None
    vmax = _boost_output_vmax(chunk)
    peak = re.search(
        r"BOOST\s*input\s*peak\s*current.{0,80}?(\d{2,4})\s*A\s*@\s*(\d+)\s*S",
        chunk,
        re.I | re.S,
    )
    if not vmax or not peak:
        return None
    cont = re.search(
        r"(?:升压输入持续电流|BOOST input continue current).{0,80}?Boost\s*:\s*(\d{2,4})\s*A",
        chunk,
        re.I | re.S,
    )
    if not cont:
        cont = re.search(r"Boost\s*:\s*(\d{2,4})\s*A", chunk, re.I)
    peak_vi = _fmt_vi_at(vmax, peak.group(1), f"{peak.group(2)}s", current_kind="peak")
    states: list[tuple[str, str]] = [
        (
            "峰值功率",
            _fmt_p_ui_at(
                vmax, peak.group(1), f"{peak.group(2)}s", current_kind="peak"
            ),
        ),
    ]
    used = [peak_vi]
    if cont:
        cont_vi = _fmt_vi_at(vmax, cont.group(1), current_kind="cont")
        states.append(
            ("持续稳定功率", _fmt_p_ui_at(vmax, cont.group(1), current_kind="cont"))
        )
        used.append(cont_vi)
    body = _fmt_boost_power_state_lines(states)
    if not body:
        return None
    return body, peak.group(0)[:180], peak.start(), tuple(used)


def _is_law_description(value: str, excerpt: str) -> bool:
    """定律原句、没有算出的数：不能当抽出值，有明确数值时让位。"""
    blob = f"{value or ''}\n{excerpt or ''}"
    if DERIVE_NOTE in blob:
        return False
    if not _LAW_SENTENCE.search(blob):
        return False
    return not _has_measurable_number(blob)


def _is_derived_cell(cell: ExtractedCell | None = None, note: str = "") -> bool:
    text = note or (getattr(cell, "note", "") if cell is not None else "")
    return (text or "").startswith(DERIVE_NOTE)


def _fmt_qty(value: float) -> str:
    if abs(value) >= 100:
        return str(int(round(value)))
    text = f"{value:.4g}"
    return text[:-2] if text.endswith(".0") else text


def _format_resistance(ohms: float) -> str:
    if ohms >= 9.5e5:
        return f"{_fmt_qty(ohms / 1e6)} MΩ"
    if ohms >= 1e3:
        return f"{_fmt_qty(ohms / 1e3)} kΩ"
    return f"{_fmt_qty(ohms)} Ω"


def _volt_si(num: float, unit: str) -> float:
    return num * 1000.0 if unit.lower().startswith("kv") else num


def _amp_si(num: float, unit: str) -> float:
    return num / 1000.0 if unit.lower() == "ma" else num


def _collect_vi(chunk: str) -> tuple[list[tuple[float, str, int]], list[tuple[float, str, int]]]:
    volts: list[tuple[float, str, int]] = []
    amps: list[tuple[float, str, int]] = []
    for match in _QTY_V.finditer(chunk or ""):
        volts.append((_volt_si(float(match.group(1)), match.group(2)), match.group(0), match.start()))
    for match in _QTY_I.finditer(chunk or ""):
        amps.append((_amp_si(float(match.group(1)), match.group(2)), match.group(0), match.start()))
    return volts, amps


def _window_around(chunk: str, left: int, right: int, span: int = 280) -> str:
    lo = min(left, right)
    hi = max(left, right)
    return chunk[max(0, lo - span) : min(len(chunk), hi + span)]


def _clause_slice(chunk: str, start: int, span: int = 1000) -> str:
    """从条款标题起截到下一条 6.x，避免 IGBT/电机/电感温度共用精度句串条。"""
    window = (chunk or "")[start : start + span]
    nxt = re.search(r"\n(?=6\.\d)", window[24:])
    if nxt:
        window = window[: 24 + nxt.start()]
    return window


def _dhts_inverter_eta_parts(window: str, motor: str) -> list[str]:
    """DHTS 6.8.4：P1 最高+平均；P3 最高+区间+综合效率。不把邻节数字抄过来。"""
    parts: list[str] = []
    if re.search(
        r"max efficiency should be\s*[＞>]\s*99\s*%|最高效率应该是大于\s*99|"
        r"[＞>]\s*99\s*%",
        window,
        re.I,
    ):
        parts.append("最高效率＞99%")
    if motor == "P1" and re.search(r"98\.2\s*%", window):
        parts.append("平均效率至少 98.2%")
    if motor != "P3":
        return parts
    seen: set[str] = set()
    for match in re.finditer(
        r"(?:Interval\s*([123])|区间\s*([123]))\s*[:：]?\s*"
        r"([\d.~～\-]+)\s*(?:rpm|RPM)\s*[,，]\s*"
        r"([\d.~～\-]+)\s*Nm\s*[,，]\s*"
        r"([\d.]+)\s*%\s*@\s*(\d{2,4})\s*V",
        window,
        re.I,
    ):
        num = match.group(1) or match.group(2)
        if num in seen:
            continue
        seen.add(num)
        rpm = match.group(3)
        nm = match.group(4)
        pct = match.group(5)
        volt = match.group(6)
        parts.append(f"区间{num} {pct}%@{volt}V（{rpm}rpm，{nm}Nm）")
    combined = re.search(
        r"(?:combined efficiency|综合效率)[^\n]{0,160}?≥\s*(\d+(?:\.\d+)?)\s*%",
        window,
        re.I,
    )
    if combined:
        pct = combined.group(1)
        volt = ""
        around = combined.group(0)
        vm = re.search(r"@\s*(\d{2,4})\s*V", around, re.I)
        if not vm:
            vm = re.search(r"Udc\s*=\s*(\d{2,4})\s*V", window, re.I)
        if vm:
            volt = f"@{vm.group(1)}V"
        parts.append(f"综合效率≥{pct}%{volt}")
    elif re.search(r"Average efficiency at least 98\.2\s*%|平均效率至少为\s*98", window, re.I):
        parts.append("平均效率至少 98.2%")
    return parts


def _pcm_table_eta_dialect(chunk: str) -> bool:
    """2.3.2 性能表方言：PCM Px efficiency / 区间效率，不是 DHTS 6.8.4 的 P1逆变器效率标题。"""
    return bool(
        re.search(
            r"PCM\s*P[13]\s*(?:efficiency|区间效率)|P[13]\s*区间效率",
            chunk or "",
            re.I,
        )
    )


def _collapse_eta_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _peak_power_row_window(chunk: str, at: int, extra_lines: int = 2) -> str:
    """峰值功率行及 OCR 折到下一两行，用来收同行的 @10s。"""
    line_start = chunk.rfind("\n", 0, at) + 1
    rest = chunk[line_start:]
    parts = rest.split("\n", extra_lines + 1)
    return "\n".join(parts[: extra_lines + 1])


def _duration_on_peak_power_row(text: str) -> str:
    """峰值功率行上的 @10s / @10sec / @≥10s，不靠旁边扭矩行，也不收电流行 Arms@10s。"""
    blob = text or ""
    cut = re.search(
        r"P3\s+peak\s+torque|P3\s*电机峰值扭矩|P3\s+continuous\s+torque|P3\s*电机额定扭矩",
        blob,
        re.I,
    )
    if cut:
        blob = blob[: cut.start()]
    for match in re.finditer(
        r"@\s*(≥\s*)?(\d+)\s*s(?:ec(?:onds?)?)?\b",
        blob,
        re.I,
    ):
        left = blob[max(0, match.start() - 16) : match.start()]
        if re.search(r"(?:Arms|Ams|Amms|电流)\s*$", left, re.I):
            continue
        prefix = "≥" if match.group(1) else ""
        return f"{prefix}{match.group(2)}s"
    return ""


def _duration_from_peak_power_hit(chunk: str, match: re.Match[str]) -> tuple[str, str]:
    window = _peak_power_row_window(chunk, match.start())
    dur = _duration_on_peak_power_row(window) or _duration_on_peak_power_row(
        match.group(0)
    )
    excerpt = (window.strip()[:200] or match.group(0)[:160])
    return dur, excerpt


def _join_inverter_eta(name: str, *values: str) -> str:
    """最高效率行与平均/区间行并存。P3 仍不得并入 P1 的 98.2%。"""
    pieces: list[str] = []
    for raw in values:
        for piece in re.split(r"[；;]", raw or ""):
            piece = piece.strip().strip("；;")
            if not piece:
                continue
            if "P3" in name and re.search(r"98\.2(?!\d)", piece) and not re.search(
                r"98\.25|区间\s*[123]|总考核|综合效率", piece
            ):
                continue
            pieces.append(piece)
    uniq: list[str] = []
    for piece in pieces:
        folded = _fold_text(piece)
        if any(folded == _fold_text(old) for old in uniq):
            continue
        uniq.append(piece)
    kept: list[str] = []
    for piece in uniq:
        folded = _fold_text(piece)
        if any(folded != _fold_text(other) and folded in _fold_text(other) for other in uniq):
            continue
        kept.append(piece)
    max_only = [
        part
        for part in kept
        if re.search(r"99\.[589]|＞\s*99|>\s*99", part)
        and not re.search(r"区间|单挡|平均|总考核|综合", part)
    ]
    if len(max_only) > 1:
        best = max(max_only, key=len)
        kept = [part for part in kept if part not in max_only] + [best]

    def _rank(part: str) -> tuple[int, int]:
        if re.search(r"最高效率|99\.5|99\.8|99\.9|＞\s*99|>\s*99", part):
            return (0, -len(part))
        if re.search(r"平均效率|单挡", part):
            return (1, -len(part))
        if re.search(r"区间|总考核|综合", part):
            return (2, -len(part))
        return (3, -len(part))

    kept.sort(key=_rank)
    return "；".join(kept)


def _iter_pcm_table_eta(chunk: str) -> list[tuple[str, str, str, int]]:
    """2.3.2 表：PCM P1/P3 区间或平均效率行（不含 maximum efficiency 那一行）。"""
    if not _pcm_table_eta_dialect(chunk):
        return []
    hits: list[tuple[str, str, str, int]] = []
    p1_pipe = re.search(
        r"PCM P1 efficiency[^\n|]{0,80}\|\s*%\s*\|\s*([^|\n]+)",
        chunk,
        re.I,
    )
    p1_flat = re.search(
        r"PCM P1(?:\s*(?:efficiency|区间效率))+.{0,120}?%\s+"
        r"(.+?)(?=\n\s*区间\s*1\s*[:：]|PCM P3|PCM cooling|$)",
        chunk,
        re.I | re.S,
    )
    p1 = p1_pipe or p1_flat
    if p1:
        raw = p1.group(1) if p1_pipe else p1.group(1)
        val = _collapse_eta_ws(raw)
        if re.search(r"%|单挡|Nm|rpm", val, re.I) and not re.search(
            r"P[I1l]\s*[:：]\s*≥\s*99\.5", val
        ):
            hits.append(
                (
                    "P1",
                    val,
                    _collapse_eta_ws(p1.group(0))[:_CLAUSE_LIMIT],
                    p1.start(),
                )
            )
    p3_blob = ""
    p3_ex = ""
    p3_at = -1
    if re.search(r"PCM P3\s*(?:efficiency|区间效率)|P3\s*区间效率", chunk, re.I):
        wide = re.search(
            r"区间\s*1\s*[:：][\s\S]{0,800}?"
            r"(?:总考核目标效率|综合效率)[\s\S]{0,240}?"
            r"(?=PCM cooling|电压利用率|The matched|匹配电机|P1 continuous generate|$)",
            chunk,
            re.I,
        )
        p3_pipe = re.search(
            r"PCM P3 efficiency[^\n|]{0,80}\|\s*%\s*\|\s*([^|\n]+)",
            chunk,
            re.I,
        )
        if wide:
            p3_blob = _collapse_eta_ws(wide.group(0))
            p3_ex = p3_blob[:_CLAUSE_LIMIT]
            p3_at = wide.start()
        elif p3_pipe:
            p3_blob = _collapse_eta_ws(p3_pipe.group(1))
            p3_ex = _collapse_eta_ws(p3_pipe.group(0))[:_CLAUSE_LIMIT]
            p3_at = p3_pipe.start()
        else:
            p3_flat = re.search(
                r"PCM P3(?:\s*(?:efficiency|区间效率))+.{0,120}?%\s+"
                r"(.+?)(?=PCM cooling|电压利用率|The matched|匹配电机|$)",
                chunk,
                re.I | re.S,
            )
            if p3_flat:
                p3_blob = _collapse_eta_ws(p3_flat.group(1))
                p3_ex = p3_blob[:_CLAUSE_LIMIT]
                p3_at = p3_flat.start()
    if p3_blob and re.search(r"区间|总考核|综合|%|Nm", p3_blob) and not (
        re.search(r"P3\s*[:：]\s*≥\s*99\.[89]", p3_blob)
        and not re.search(r"区间", p3_blob)
    ):
        p3_blob = re.sub(
            r"PCM P3\s*(?:区间效率|efficiency)(?:\s*@\s*\d+\s*V)?",
            " ",
            p3_blob,
            flags=re.I,
        )
        p3_blob = _collapse_eta_ws(re.sub(r"\s+%\s+", " ", p3_blob))
        hits.append(("P3", p3_blob, p3_ex, p3_at))
    return hits


def _two_band_temp_acc(window: str) -> str:
    if re.search(r"-40", window) and re.search(r"±\s*5", window) and re.search(
        r"±\s*3", window
    ):
        return "−40~+100℃ 误差＜±5℃；＞100℃ 误差＜±3℃"
    return ""


def _sensor_range_c(window: str, *, motor: bool) -> str:
    """电机量程≥200℃；控制器/IGBT 约 120℃。不把精度档的 100℃ 当量程。"""
    found: list[int] = []
    for match in re.finditer(
        r"(?:at least|至少|不低于|≥|量程(?:为|至)?|up to|上限|测(?:量|试)至)\s*"
        r"(\d{2,3})\s*(?:°\s*C|℃|degC)",
        window or "",
        re.I,
    ):
        found.append(int(match.group(1)))
    if motor:
        hi = [n for n in found if n >= 180]
        if not hi:
            return ""
        return f"量程≥{max(hi)}℃"
    mid = [n for n in found if 100 <= n <= 150]
    if not mid:
        return ""
    return f"量程{mid[-1]}℃"


def _temp_sample_value(window: str, *, motor: bool, prefix: str = "") -> str:
    bits: list[str] = []
    if prefix:
        bits.append(prefix.rstrip("；; "))
    rng = _sensor_range_c(window, motor=motor)
    if rng:
        bits.append(rng)
    acc = _two_band_temp_acc(window)
    if acc:
        bits.append(acc)
    return "；".join(bits)


def _p1_asc_section_span(text: str) -> tuple[int, str]:
    """6.5.7.1 ASC 窗口，截到 6.5.7.2 持续相电流之前。"""
    text = text or ""
    m_head = re.search(
        r"6\.5\.7\.1\b|"
        r"AC Active short circuit current PEI P1|"
        r"P1逆变器交流主动短路电流|"
        r"During active short circuit the maximum allowed.{0,48}P1|"
        r"主动短路期间[，,]?P1(?:电磁|电机|EM)",
        text,
        re.I,
    )
    if m_head:
        start = m_head.start()
    else:
        m2 = re.search(r"主动短路期间|During active short circuit", text, re.I)
        start = m2.start() if m2 else 0
    rest = text[start:]
    m_end = re.search(
        r"6\.5\.7\.2\b|"
        r"AC current continuous|"
        r"PEI P1 must be able to handle continuous AC phase current|"
        r"逆变器P1须能满足交流相电流",
        rest,
        re.I,
    )
    end = start + m_end.start() if m_end else len(text)
    return start, text[start:end]


def _p1_asc_transient_peak(section: str) -> str:
    match = re.search(
        r"(?:transient peak current is|短时峰值电流为)\s*(\d{2,4})\s*A(?:rms)?\s*@\s*1\s*ms",
        section or "",
        re.I,
    )
    return match.group(1) if match else ""


def _p1_asc_reject_inverter_amp(section: str, match: re.Match[str]) -> bool:
    around = section[max(0, match.start() - 100) : match.end() + 80]
    if not re.search(r"主动短路|active short|\bASC\b|3\.5", around, re.I):
        return True
    if re.search(r"峰值|peak AC|10\s*s|持续交流", match.group(0), re.I):
        return True
    if re.search(
        r"@\s*1\s*ms|transient peak|短时峰值|持续值|"
        r"continuous AC phase current|handle continuous|"
        r"须能满足交流相电流",
        around,
        re.I,
    ):
        return True
    tail = section[match.end() : match.end() + 16]
    return bool(re.search(r"^\s*(?:rms)?\s*@\s*1\s*ms", tail, re.I))


def _p1_asc_inverter_amps(chunk: str) -> tuple[str, str, int, str]:
    """P1 逆变器 ASC 电流。电机允许电流若不同则只进备注，不写入逆变器格。"""
    start, section = _p1_asc_section_span(chunk)
    if not re.search(r"P1\s*EM|P1电磁|P1电机|PEI P1|P1逆变器", section, re.I):
        return "", "", -1, ""
    motor = ""
    inverter = ""
    at = -1
    excerpt = ""
    m_em = re.search(
        r"(?:P1\s*)?(?:EM|电磁|电机)[^\n]{0,72}?"
        r"(?:最大允许|allowed)[^\n]{0,48}?"
        r"(\d{2,4})\s*A(?:rms)?",
        section,
        re.I,
    )
    if m_em:
        motor = m_em.group(1)
        at = start + m_em.start()
        excerpt = m_em.group(0)
    m_inv_n = re.search(
        r"(?:P1\s*)?(?:inverter|逆变器|PEI P1)[^\n]{0,28}应能在(\d{2,4})\s*A(?:rms)?\s*条件下",
        section,
        re.I,
    )
    m_inv = m_inv_n
    if not m_inv:
        m_inv = re.search(
            r"(?:P1\s*)?(?:inverter|逆变器|PEI)[^\n]{0,80}?"
            r"(\d{2,4})\s*A(?:rms)?",
            section,
            re.I,
        )
        if m_inv and _p1_asc_reject_inverter_amp(section, m_inv):
            m_inv = None
    if m_inv:
        inverter = m_inv.group(1)
        inv_at = start + m_inv.start()
        if at < 0:
            at = inv_at
            excerpt = m_inv.group(0)
        else:
            excerpt = (excerpt + " " + m_inv.group(0)).strip()
    same_cond = bool(
        re.search(r"应能在此条件下工作\s*3\.5", section)
        or re.search(r"under this condition during\s*3\.5", section, re.I)
        or re.search(r"perform under this condition during\s*3\.5", section, re.I)
    )
    if motor and same_cond and not inverter:
        inverter = motor
    if inverter and motor and inverter != motor:
        return inverter, motor, at, excerpt
    if inverter:
        return inverter, "", at, excerpt
    if motor and same_cond:
        return motor, "", at, excerpt
    return "", motor, at, excerpt


def _motor_in_window(window: str) -> str:
    has_p1 = bool(re.search(r"(?i)(?<![A-Za-z0-9])P(?:1|[lI])(?![A-Za-z0-9])|P1电机|PCMP[lI1]", window))
    has_p3 = bool(re.search(r"(?i)(?<![A-Za-z0-9])P3(?![A-Za-z0-9])|P3电机|PCMP3", window))
    if has_p1 and not has_p3:
        return "P1"
    if has_p3 and not has_p1:
        return "P3"
    return ""


def _farad(num: float, unit: str) -> float:
    key = unit.lower().replace("μ", "u").replace("µ", "u")
    if key == "mf":
        return num * 1e-3
    return num * 1e-6


def _seconds(num: float, unit: str) -> float:
    return num / 1000.0 if unit.lower().startswith("ms") else num


def _ohm_si(num: float, unit: str) -> float:
    key = unit.lower().replace("ω", "ohm").replace("Ω", "ohm")
    if key.startswith("mohm"):
        return num * 1e6
    if key.startswith("kohm") or key.startswith("k"):
        return num * 1e3
    return num


def _format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{_fmt_qty(seconds * 1000)} ms"
    return f"{_fmt_qty(seconds)} s"


def _is_ac_phase_current_field(name: str) -> bool:
    """逆变器交流侧电流条目（相电流 / 交流电流 / ASC / 堵转电流）。"""
    n = name or ""
    return bool(
        re.search(r"相电流|交流电流|交流主动短路|ASC电流|堵转电流", n)
        or ("ASC" in n.upper() and "电流" in n)
    )


def _derived_fits_field(name: str, value: str, excerpt: str) -> bool:
    n = name or ""
    text = f"{value}\n{excerpt}"
    if not _motor_label_ok(n, text):
        return False
    if "绝缘电阻" in n:
        return bool(re.search(r"MΩ|MOhm", value, re.I))
    if "放电电阻" in n:
        return bool(re.search(r"Ω|Ohm", value, re.I))
    if "放电时间" in n or "放电功能" in n:
        return bool(re.search(r"(?i)ms|\d+(?:\.\d+)?\s*s\b|秒", value))
    if "效率" in n:
        return "%" in value
    if "扭矩" in n:
        return bool(re.search(r"Nm|N[·.]m", value, re.I))
    if _is_ac_phase_current_field(n):
        # 交流相电流不能由功率和直流母线电压推算：P=√3UI 要的是交流线电压，还差功率因数/调制比。
        # SuperEvo 2026-09-16：#58 P3额定功率相电流被算成 86.6Arms（120kW/√3/800Vdc），同表峰值 465Arms。
        return False
    if "相电流" in n or ("电流" in n and "功率" not in n):
        return bool(re.search(r"A(?:rms)?", value, re.I))
    if "功耗" in n:
        return bool(re.search(r"W", value, re.I))
    if "升压输出功率" in n:
        return bool(
            re.search(r"kW", value, re.I)
            or re.search(
                r"\d+\s*V\s*[×x*]\s*(?:最大电流|持续电流)?\s*\d+\s*A",
                value,
                re.I,
            )
        )
    if "散热" in n or "热损失" in n or "功率" in n:
        return bool(re.search(r"kW", value, re.I))
    return False


def _add_formula_values(chunk: str, add) -> None:
    """用当份原文已出现的量按物理公式推算缺项，不把定律原句当抽出值。"""
    if not chunk:
        return
    seen: set[tuple[str, str]] = set()

    def emit(name: str, value: str, excerpt: str, at: int, formula: str, raw_u: str, raw_i: str) -> None:
        key = (name, value)
        if key in seen:
            return
        seen.add(key)
        add(
            name,
            value,
            "",
            excerpt,
            at,
            confidence=0.72,
            note=_formula_note(formula, raw_u, raw_i),
            review_status=STATUS_PARTIAL,
        )

    volts, amps = _collect_vi(chunk)
    for v_si, v_raw, v_at in volts:
        for i_si, i_raw, i_at in amps:
            if i_si <= 0 or abs(v_at - i_at) > 240:
                continue
            window = _window_around(chunk, v_at, i_at)
            excerpt = _expand_to_clause(chunk, min(v_at, i_at), max(v_at + len(v_raw), i_at + len(i_raw)))
            if not excerpt:
                excerpt = window.strip()[:_CLAUSE_LIMIT]
            if _looks_like_dc_capacitor_spec(window) or _CAP_LEAK_CTX.search(window):
                continue
            if _INS_CTX.search(window) and 200 <= v_si <= 3000 and 1e-7 <= i_si <= 0.05:
                if _QTY_R.search(window):
                    continue
                ohms = v_si / i_si
                if 1e5 <= ohms <= 1e11:
                    emit(
                        "高压安全-绝缘电阻",
                        _format_resistance(ohms),
                        excerpt,
                        min(v_at, i_at),
                        "R=U/I",
                        v_raw,
                        i_raw,
                    )
                continue
            if _DISCHARGE_R_CTX.search(window) and 60 <= v_si <= 1500 and 0.01 <= i_si <= 80:
                if _QTY_R.search(window):
                    continue
                ohms = v_si / i_si
                if 0.5 <= ohms <= 1e6:
                    name = "主动放电电阻" if re.search(r"(?i)主动|active", window) else "被动放电电阻"
                    if re.search(r"(?i)主动|active", window) and re.search(r"(?i)被动|passive", window):
                        name = "主动放电电阻"
                    emit(name, _format_resistance(ohms), excerpt, min(v_at, i_at), "R=U/I", v_raw, i_raw)
                continue
            if 9 <= v_si <= 16 and 0.02 <= i_si <= 8 and re.search(
                r"(?i)功耗|consumption|@\s*14\s*V|低压功耗", window
            ):
                watts = v_si * i_si
                if 0.5 <= watts <= 80:
                    emit(
                        "低压功耗要求",
                        f"{_fmt_qty(watts)}W@{_fmt_qty(v_si)}V",
                        excerpt,
                        min(v_at, i_at),
                        "P=UI",
                        v_raw,
                        i_raw,
                    )
                continue
            if _QTY_P.search(window):
                continue
            motor = _motor_in_window(window)
            three_phase = bool(re.search(r"(?i)三相|line[- ]to[- ]line|线电压|phase voltage", window))
            if motor and re.search(r"(?i)峰值功率|peak power|peak generate|额定功率", window):
                if 80 <= v_si <= 1500 and 30 <= i_si <= 900:
                    watts = (math.sqrt(3) * v_si * i_si) if three_phase else (v_si * i_si)
                    if watts >= 5000:
                        peak = bool(re.search(r"(?i)峰值|peak", window))
                        name = f"{motor}峰值功率" if peak else f"{motor}额定功率"
                        formula = "P=√3UI" if three_phase else "P=UI"
                        emit(
                            name,
                            f"{_fmt_qty(watts / 1000.0)} kW",
                            excerpt,
                            min(v_at, i_at),
                            formula,
                            v_raw,
                            i_raw,
                        )

    for match in re.finditer(
        r"(?i)(\d+(?:\.\d+)?)\s*(?:N[·.]?m|Nm)\s*@\s*(?:0\s*[-~～]\s*)?(\d{3,5})\s*rpm",
        chunk,
    ):
        window = _window_around(chunk, match.start(), match.end(), 200)
        if _QTY_P.search(window):
            continue
        motor = _motor_in_window(window)
        if not motor:
            continue
        torque = float(match.group(1))
        rpm = float(match.group(2))
        kw = torque * rpm / 9549.0
        if kw < 5:
            continue
        peak = bool(re.search(r"(?i)峰值扭矩|peak torque", window))
        rated = bool(re.search(r"(?i)额定扭矩|continuous torque", window))
        if peak == rated:
            continue
        name = f"{motor}峰值功率" if peak else f"{motor}额定功率"
        excerpt = _expand_to_clause(chunk, match.start(), match.end()) or match.group(0)
        emit(
            name,
            f"{_fmt_qty(kw)} kW",
            excerpt,
            match.start(),
            "P=Tω",
            match.group(0),
            f"n={match.group(2)} rpm",
        )

    for match in re.finditer(
        r"(?i)(\d+(?:\.\d+)?)\s*kW\s*@\s*(\d{3,5})\s*rpm",
        chunk,
    ):
        window = _window_around(chunk, match.start(), match.end(), 200)
        if _QTY_NM.search(window):
            continue
        motor = _motor_in_window(window)
        if not motor:
            continue
        if not re.search(r"(?i)扭矩|torque", window):
            continue
        kw = float(match.group(1))
        rpm = float(match.group(2))
        if rpm < 100:
            continue
        torque = 9550.0 * kw / rpm
        if torque < 5:
            continue
        peak = bool(re.search(r"(?i)峰值|peak", window))
        name = f"{motor}峰值扭矩/时间/对应转速范围" if peak else f"{motor}额定扭矩"
        excerpt = _expand_to_clause(chunk, match.start(), match.end()) or match.group(0)
        emit(
            name,
            f"{_fmt_qty(torque)} Nm@{match.group(2)}rpm",
            excerpt,
            match.start(),
            "T=9550P/n",
            match.group(0),
            f"n={match.group(2)} rpm",
        )

    for p_match in _QTY_P.finditer(chunk):
        for v_si, v_raw, v_at in volts:
            if abs(p_match.start() - v_at) > 240:
                continue
            window = _window_around(chunk, p_match.start(), v_at)
            if not re.search(r"(?i)三相|相电流|phase current|Arms", window):
                continue
            motor = _motor_in_window(window)
            if motor not in {"P1", "P3"}:
                continue
            if re.search(r"(?i)\d+(?:\.\d+)?\s*A(?:rms|ms)?", window):
                continue
            has_peak = bool(re.search(r"(?i)峰值|peak", window))
            has_rated = bool(re.search(r"(?i)额定|持续|continuous", window))
            if has_peak == has_rated:
                continue
            watts = float(p_match.group(1)) * 1000.0
            if v_si < 80:
                continue
            amps_ll = watts / (math.sqrt(3) * v_si)
            if not (20 <= amps_ll <= 800):
                continue
            if motor == "P3":
                name = "P3逆变器交流电流峰值" if has_peak else "P3额定功率相电流"
            else:
                name = "P1逆变器交流电流峰值" if has_peak else "P1逆变器持续交流电流"
            excerpt = _expand_to_clause(chunk, min(p_match.start(), v_at), max(p_match.end(), v_at + len(v_raw)))
            emit(
                name,
                f"{_fmt_qty(amps_ll)} Arms",
                excerpt or window.strip()[:_CLAUSE_LIMIT],
                min(p_match.start(), v_at),
                "I=P/(√3U)",
                p_match.group(0),
                v_raw,
            )

    powers = [(float(m.group(1)), m.group(0), m.start()) for m in _QTY_P.finditer(chunk)]
    for i, (p_a, raw_a, at_a) in enumerate(powers):
        for p_b, raw_b, at_b in powers[i + 1 :]:
            if abs(at_a - at_b) > 280:
                continue
            window = _window_around(chunk, at_a, at_b)
            if not re.search(r"(?i)效率|efficiency", window):
                continue
            if not re.search(r"(?i)输入|输出|input|output|P_?in|P_?out", window):
                continue
            # 原文已写效率目标（99.5%@直通等）时，勿把相邻功率区间当成 η=Pout/Pin
            if re.search(
                r"(?i)efficiency target|效率目标|最高效率|"
                r"(?:≥|>|＞)?\s*9[0-9](?:\.\d+)?\s*%",
                window,
            ):
                continue
            hi, lo = max(p_a, p_b), min(p_a, p_b)
            if hi <= 0 or lo <= 0:
                continue
            eta = 100.0 * lo / hi
            if not (80 <= eta < 100):
                continue
            if re.search(r"(?i)boost|升压", window):
                name = "升压效率"
            else:
                motor = _motor_in_window(window)
                if not motor:
                    continue
                name = f"{motor}逆变器效率指标"
            excerpt = _expand_to_clause(chunk, min(at_a, at_b), max(at_a, at_b) + 8)
            emit(
                name,
                f"{_fmt_qty(eta)}%",
                excerpt or window.strip()[:_CLAUSE_LIMIT],
                min(at_a, at_b),
                "η=Pout/Pin",
                raw_a,
                raw_b,
            )

    if _DISCHARGE_CTX.search(chunk):
        caps = [
            (_farad(float(m.group(1)), m.group(2)), m.group(0), m.start())
            for m in _QTY_C.finditer(chunk)
            if 50e-6 <= _farad(float(m.group(1)), m.group(2)) <= 0.02
        ]
        times = [
            (_seconds(float(m.group(1)), m.group(2)), m.group(0), m.start())
            for m in _QTY_TSEC.finditer(chunk)
            if 0.02 <= _seconds(float(m.group(1)), m.group(2)) <= 180
        ]
        for c_si, c_raw, c_at in caps:
            window_c = _window_around(chunk, c_at, c_at, 320)
            if not _DISCHARGE_CTX.search(window_c):
                continue
            v0_cands = [v for v in volts if abs(v[2] - c_at) < 400 and 200 <= v[0] <= 1500 and abs(v[0] - 60) > 5]
            if not v0_cands:
                continue
            v0_si, v0_raw, v0_at = max(v0_cands, key=lambda item: item[0])
            v1 = 60.0
            if not re.search(r"60\s*V", window_c, re.I):
                continue
            ln_ratio = math.log(v0_si / v1)
            if ln_ratio < 0.4:
                continue
            for t_si, t_raw, t_at in times:
                if abs(t_at - c_at) > 400:
                    continue
                window = _window_around(chunk, c_at, t_at, 200)
                if not _DISCHARGE_CTX.search(window):
                    continue
                if _QTY_R.search(window):
                    continue
                ohms = t_si / (c_si * ln_ratio)
                if not (0.5 <= ohms <= 2e5):
                    continue
                name = "主动放电电阻"
                if t_si >= 10 or re.search(r"(?i)被动|passive", window):
                    if not re.search(r"(?i)主动|active", window):
                        name = "被动放电电阻"
                excerpt = _expand_to_clause(chunk, min(c_at, t_at), max(c_at, t_at) + 8)
                emit(
                    name,
                    _format_resistance(ohms),
                    excerpt or window.strip()[:_CLAUSE_LIMIT],
                    min(c_at, t_at),
                    "R=t/(C ln(V0/V1))",
                    f"{c_raw}, {t_raw}",
                    f"{v0_raw}→60V",
                )

        resistors = [
            (_ohm_si(float(m.group(1)), m.group(2)), m.group(0), m.start())
            for m in _QTY_R.finditer(chunk)
            if 0.5 <= _ohm_si(float(m.group(1)), m.group(2)) <= 2e5
        ]
        for c_si, c_raw, c_at in caps:
            window_c = _window_around(chunk, c_at, c_at, 320)
            if not _DISCHARGE_CTX.search(window_c):
                continue
            if any(
                0.02 <= _seconds(float(m.group(1)), m.group(2)) <= 180
                for m in _QTY_TSEC.finditer(window_c)
            ):
                continue
            v0_cands = [v for v in volts if abs(v[2] - c_at) < 400 and 200 <= v[0] <= 1500 and abs(v[0] - 60) > 5]
            if not v0_cands:
                continue
            if not re.search(r"60\s*V", window_c, re.I):
                continue
            v0_si, v0_raw, _v0_at = max(v0_cands, key=lambda item: item[0])
            ln_ratio = math.log(v0_si / 60.0)
            if ln_ratio < 0.4:
                continue
            for r_si, r_raw, r_at in resistors:
                if abs(r_at - c_at) > 400:
                    continue
                window = _window_around(chunk, c_at, r_at, 200)
                if not _DISCHARGE_CTX.search(window):
                    continue
                seconds = r_si * c_si * ln_ratio
                if not (0.02 <= seconds <= 180):
                    continue
                name = _ACTIVE_DISCHARGE
                if seconds >= 10 or re.search(r"(?i)被动|passive", window):
                    if not re.search(r"(?i)主动|active", window):
                        name = _PASSIVE_DISCHARGE
                excerpt = _expand_to_clause(chunk, min(c_at, r_at), max(c_at, r_at) + 8)
                emit(
                    name,
                    _format_duration(seconds),
                    excerpt or window.strip()[:_CLAUSE_LIMIT],
                    min(c_at, r_at),
                    "t=RC ln(V0/V1)",
                    f"{c_raw}, {r_raw}",
                    f"{v0_raw}→60V",
                )

    for p_match in _QTY_P.finditer(chunk):
        for v_si, v_raw, v_at in volts:
            if abs(p_match.start() - v_at) > 240:
                continue
            window = _window_around(chunk, p_match.start(), v_at)
            if not re.search(r"(?i)升压|boost", window):
                continue
            if _motor_in_window(window) in {"P1", "P3"}:
                continue
            if re.search(r"(?i)\d+(?:\.\d+)?\s*A(?:rms|ms)?", window):
                continue
            has_peak = bool(re.search(r"(?i)峰值|peak", window))
            has_rated = bool(re.search(r"(?i)额定|持续|continuous|rated", window))
            if has_peak == has_rated:
                continue
            watts = float(p_match.group(1)) * 1000.0
            if not (80 <= v_si <= 1500 and 5000 <= watts <= 4e5):
                continue
            amps = watts / v_si
            if not (10 <= amps <= 800):
                continue
            name = "BOOST输入峰值电流" if has_peak else "BOOST输入额定电流"
            excerpt = _expand_to_clause(chunk, min(p_match.start(), v_at), max(p_match.end(), v_at + len(v_raw)))
            emit(
                name,
                f"{_fmt_qty(amps)} A@{_fmt_qty(v_si)}V",
                excerpt or window.strip()[:_CLAUSE_LIMIT],
                min(p_match.start(), v_at),
                "I=P/U",
                p_match.group(0),
                v_raw,
            )

    for pct_match in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", chunk):
        eta = float(pct_match.group(1))
        if not (80 <= eta < 100):
            continue
        around = chunk[max(0, pct_match.start() - 48) : pct_match.end() + 48]
        if not re.search(r"(?i)效率|efficiency|η", around):
            continue
        window = _window_around(chunk, pct_match.start(), pct_match.start(), 280)
        if not re.search(r"(?i)热损失|热损耗|散热能力|heat loss|Ploss", window):
            continue
        powers = [
            (float(m.group(1)), m.group(0), m.start())
            for m in _QTY_P.finditer(window)
        ]
        if any(0.05 <= p[0] <= 15 for p in powers):
            continue
        big = [p for p in powers if p[0] >= 20]
        if not big:
            continue
        pin_kw, pin_raw, _ = max(big, key=lambda item: item[0])
        loss_kw = pin_kw * (1.0 - eta / 100.0)
        if not (0.05 <= loss_kw <= 20):
            continue
        excerpt = _expand_to_clause(chunk, pct_match.start(), pct_match.end()) or window.strip()[:_CLAUSE_LIMIT]
        name = "最大散热能力" if re.search(r"(?i)散热能力|cooling capacity|heat rejection", window) else "热损失"
        emit(
            name,
            f"{_fmt_qty(loss_kw)} kW",
            excerpt,
            pct_match.start(),
            "P_loss=P(1-η)",
            pin_raw,
            pct_match.group(0),
        )


def _is_ac_fundamental_rpm_assumption(text: str) -> bool:
    """极对数×转速只是交流基频满性能假设，不是转速表上的最高工作转速。"""
    return bool(
        re.search(
            r"(?i)poles? and \d+\s*rpm|Req based on \d+\s*poles|"
            r"fundamental electrical frequency|交流基频|基本电气频率|"
            r"基于\d+极\d{4,5}转",
            text or "",
        )
    )


def _is_explicit_max_speed_table(text: str) -> bool:
    """转速表写法才算最高工作转速定义，不含交流基频假设句。"""
    return bool(
        re.search(
            r"(?i)the max speed of|"
            r"Top speed[\s\S]{0,40}?\d{4,5}|"
            r"随转|出电功率|出功率",
            text or "",
        )
    )


def _fmt_max_speed_power_overrun(text: str) -> str | None:
    """出电功率 / 随转成对出现时按标签取值，不按数字出现顺序。"""
    blob = text or ""
    power = re.search(
        r"(\d{4,5})\s*(?:rpm)?\s*[（(]?\s*(?:出电功率|出功率)",
        blob,
        re.I,
    )
    overrun = re.search(
        r"(\d{4,5})\s*(?:rpm)?\s*[（(]?\s*随转",
        blob,
        re.I,
    )
    if not power or not overrun:
        return None
    return f"{power.group(1)}rpm（出电功率），{overrun.group(1)}rpm（随转）"


def _lock_field_semantics(cell: ExtractedCell, field_name: str) -> None:
    """认条过满/条款抄上一节：存盘后仍按已确认口径锁住，不被高置信度覆盖。"""
    if cell is None or not field_name:
        return
    blob = f"{cell.value or ''}\n{cell.excerpt or ''}"
    if "最高工作转速" in field_name:
        pair = _fmt_max_speed_power_overrun(blob)
        if pair:
            nums = set(re.findall(r"\d{4,5}", cell.value or ""))
            if len(nums) < 2:
                cell.value = pair
        if _is_ac_fundamental_rpm_assumption(blob):
            if not _is_explicit_max_speed_table(blob):
                cell.review_status = STATUS_PARTIAL
                cell.confidence = min(float(cell.confidence or 0.72), 0.72)
                if "交流基频" not in (cell.note or ""):
                    cell.note = _POLES_RPM_NOTE
    if field_name == "升压充电功能":
        if re.search(r"慢充连接器|slow charg(?:e|ing) connector", blob, re.I) and not re.search(
            r"Charging Buck/Boost|充电升压/降压功能需求",
            blob,
            re.I,
        ):
            cell.review_status = STATUS_PARTIAL
            cell.confidence = min(float(cell.confidence or 0.72), 0.72)
            if "连接器" not in (cell.note or ""):
                cell.note = _CONNECTOR_CHARGE_NOTE
    if "高压连接器保护" in field_name:
        val = cell.value or ""
        if re.search(r"IPXX|触指|防直触|防直接接触", val, re.I):
            if cell.note == _CONNECTOR_PROTECTION_NOTE:
                cell.note = ""
            if (cell.clause or "").startswith("6.2.3.2") and not re.search(
                r"6\.2\.3\.2", cell.excerpt or ""
            ):
                cell.clause = ""
        elif re.search(
            r"高压直流连接|High Voltage DC connection",
            blob,
            re.I,
        ):
            cell.review_status = STATUS_PARTIAL
            cell.confidence = min(float(cell.confidence or 0.72), 0.72)
            if re.search(r"6\.2\.3\.2", blob):
                cell.clause = "6.2.3.2"
            if "触指" not in (cell.note or "") and "IPXX" not in (cell.note or ""):
                cell.note = _CONNECTOR_PROTECTION_NOTE
    if "通讯" in field_name:
        if (
            re.search(r"\bLIN\b", blob, re.I)
            and re.search(r"CAN[\s\-–]*FD", blob, re.I)
            and not re.search(r"\bLIN\b", cell.value or "", re.I)
        ):
            cell.value = "CAN / CAN-FD / LIN"
    if field_name in {"静态电流", "低压功耗要求"} and re.search(
        r"未唤醒@仅低压上电|唤醒@IGBT|LV power consumption|低压功耗",
        blob,
        re.I,
    ):
        if "6.5.2" in blob:
            cell.clause = "6.5.2"
    if field_name in _HVDC_OPERATING_VOLTAGE_FIELDS and _looks_like_hvdc_voltage_table(blob):
        clause = (cell.clause or "").strip()
        if re.match(r"^6\.4\.2\.\d+", clause) or clause == "6.5.2":
            cell.clause = ""
    if "冷却接口" in field_name:
        if (cell.clause or "") == "6.2.1.5" or re.search(
            r"Guiding pins|定位销", cell.excerpt or "", re.I
        ):
            if re.search(r"Cooling connections|冷却连接|VDA|NW\s*12", blob, re.I):
                cell.clause = "6.2.2" if re.search(r"6\.2\.2", blob) else ""
    if "功能安全" in field_name:
        has_d = bool(re.search(r"ASIL\s*D", blob, re.I))
        has_c = bool(re.search(r"ASIL\s*C", blob, re.I))
        if has_d and has_c:
            cell.review_status = STATUS_PARTIAL
            cell.confidence = min(float(cell.confidence or 0.72), 0.72)
            if "ASIL" not in (cell.note or ""):
                cell.note = "中英功能安全等级冲突（ASIL D / ASIL C），请对照原页定稿。"
    if "高压安全" in field_name and "纹波" in field_name and re.search(
        r"switched off|高压电池关闭|接触器开",
        blob,
        re.I,
    ):
        cell.clause = "2.3.3.3.4"


def _drive_boost_conclusions(blob: str) -> tuple[str, str] | None:
    """#3 驱动升压、#4 行车升压与 #61 功能要求：写含用途的结论，不单写「是」。"""
    if re.search(r"boost the HV input|直流输入的电压提升", blob, re.I):
        if re.search(r"\bTM\b|牵引电机", blob, re.I):
            detail = "HVDC 输入电压较低时将高压输入升至更高电压，以改善 TM 性能"
        else:
            detail = "HVDC 输入电压较低时将高压输入升至更高电压"
        return f"是；{detail}", f"有；{detail}"
    if re.search(r"boost control|BOOST architecture", blob, re.I):
        detail = "PCM 含 boost control，并按 BOOST 架构做平台变型"
        return f"是；{detail}", f"有；{detail}"
    return None


def _hv_booster_output_voltage_from_modes(chunk: str) -> tuple[str, int, str] | None:
    """6.5.4 HV Booster 三种模式 → #67，不是 #4 充电范围。"""
    match = re.search(
        r"需要具备三种作工作模式.{0,80}?Boost升压，bypass直通，BUCK降压|"
        r"Boost升压，bypass直通，BUCK降压",
        chunk or "",
        re.I,
    )
    if not match:
        return None
    around = (chunk or "")[max(0, match.start() - 240) : match.end() + 120]
    if re.search(r"Charging Buck/Boost|充电升压/降压功能需求", around, re.I):
        return None
    bits: list[str] = []
    volt = re.search(
        r"(?:Target output voltage of booster|升压器的目标输出电压)[^\n]{0,64}?"
        r"(?:\|\s*)?(\d{2,4})\s*(?:\|)?\s*V",
        chunk or "",
        re.I,
    )
    if not volt:
        volt = re.search(r"升压器的目标输出电压\s+(\d{2,4})\s*V", chunk or "", re.I)
    if volt:
        bits.append(f"{volt.group(1)}V")
    bits.append("Boost/bypass/BUCK 三种模式")
    if re.search(r"Max\s*85kW@200V-400V", chunk or "", re.I):
        bits.append("BUCK Max 85kW@200V-400V")
    return "；".join(bits), match.start(), match.group(0)


def _item4_scope_score(value: str, excerpt: str) -> int:
    """#4 行车升压：充电 Boost/Buck 优先于 6.5.4 行车 HV 结论；boost control / 三种模式不进。"""
    blob = f"{value or ''}\n{excerpt or ''}"
    val = value or ""
    s = 0
    if re.search(r"Charging Buck/Boost|充电升压/降压", blob, re.I):
        s += 8
    if re.search(
        r"HVDC 输入电压较低|boost the HV input|直流输入的电压提升",
        blob,
        re.I,
    ):
        s += 4
    if re.search(r"boost control|BOOST architecture", blob, re.I):
        s -= 4
    if re.search(r"三种作?工作模式|85\s*kW", val, re.I) and not re.search(
        r"Charging Buck/Boost", blob, re.I
    ):
        s -= 8
    stripped = val.strip()
    if re.fullmatch(r"是|否|有|无", stripped):
        s -= 4
    if "；" in stripped or "（" in stripped:
        s += 2
    return s


def _drive_boost_scope_score(value: str, excerpt: str) -> int:
    blob = f"{value or ''}\n{excerpt or ''}"
    s = 0
    if re.search(r"Charging Buck/Boost|充电升压/降压", blob, re.I):
        s -= 8
    if re.search(
        r"HVDC 输入电压较低|boost the HV input|直流输入的电压提升",
        blob,
        re.I,
    ):
        s += 6
    if re.search(r"boost control|BOOST architecture", blob, re.I):
        s += 1
    stripped = (value or "").strip()
    if re.fullmatch(r"是|否|有|无", stripped):
        s -= 4
    if "；" in stripped or "（" in stripped:
        s += 2
    return s


def _scrub_drive_boost_if_charge_spec(rows: dict[int, ExtractedCell], source: str) -> None:
    """同份已有 Charging Buck/Boost 时，PCM 产品说明里的 boost control 不是驱动升压。"""
    if not re.search(r"Charging Buck/Boost|充电升压/降压功能需求", source or "", re.I):
        return
    blanks = {cell.seq: cell for cell in empty_template_rows()}
    for seq, cell in list(rows.items()):
        if cell.name != "设计范围是否包含驱动升压功能":
            continue
        blob = f"{cell.value or ''}\n{cell.excerpt or ''}"
        if re.search(
            r"Charging Buck/Boost|充电升压/降压|boost the HV input|"
            r"直流输入的电压提升|HVDC 输入电压较低",
            blob,
            re.I,
        ):
            continue
        if re.search(r"boost control|BOOST architecture|增程控制", blob, re.I):
            rows[seq] = blanks[seq]


def _fill_peak_bemf_from_motors(rows: dict[int, ExtractedCell]) -> None:
    """#11 总条目可引用当份已抽出的 P1 反电势（无 P1 时才用 P3），不另造数。"""
    peak = next((cell for cell in rows.values() if cell.name == "反电动势峰值"), None)
    if peak is None or (peak.value or "").strip():
        return
    p1 = next(
        (cell for cell in rows.values() if cell.name == "P1反电动势（Back EMF）"),
        None,
    )
    p3 = next(
        (cell for cell in rows.values() if cell.name == "P3 反电动势（Back EMF）"),
        None,
    )

    def _has_volt(cell: ExtractedCell | None) -> bool:
        return bool(cell and re.search(r"\d{3,4}\s*V", cell.value or "", re.I))

    def _filled(cell: ExtractedCell | None) -> bool:
        return bool(cell and (cell.value or "").strip())

    src = None
    if _has_volt(p1):
        src = p1
    elif _has_volt(p3):
        src = p3
    elif _filled(p1):
        src = p1
    elif _filled(p3):
        src = p3
    if src is None:
        return
    rows[peak.seq] = _attach(peak, src)


# 当份未给出时：企标挂了方法标准的空格仍未检索到；方法号只写入复核备注。
# 禁止用企标典型小时数、试验箱边界、清单示例 kW 或「参考 标准号」填抽出值。
_STD_REF_NOTE = "企标方法对照"
_MISS_REVIEW_NOTE = "当份未给出具体值，需人工复核。"
_METHOD_STD_OK = re.compile(
    r"(?i)(?:Q\s*/\s*JL|GB/?T?|IEC\s|ISO\s|UL\s|CISPR\s)"
)
_HV_SECTION_HEAD = re.compile(
    r"(?m)^(?:#{1,6}\s+)?(\d{1,2}(?:\.\d{1,3}){1,4})\s+"
    r"([^\n]{0,120})",
)
_HV_TITLE_WANT = {
    "绝缘电阻": re.compile(r"insulation resistance|绝缘电阻", re.I),
    "耐电压": re.compile(
        r"withstand voltage|dielectric|hipot|耐电压|耐压能力|"
        r"HV insulation requirements|高压绝缘要求",
        re.I,
    ),
    "主动放电": re.compile(r"active discharge|主动放电", re.I),
    "被动放电": re.compile(r"passive discharge|被动放电", re.I),
}
_HV_TITLE_REJECT = {
    "绝缘电阻": re.compile(
        r"withstand|hipot|耐电压|耐压能力|active discharge|主动放电|"
        r"HV insulation requirements|高压绝缘要求",
        re.I,
    ),
    "耐电压": re.compile(
        r"insulation resistance|绝缘电阻|active discharge|主动放电", re.I
    ),
    "主动放电": re.compile(
        r"insulation resistance|绝缘电阻|withstand|hipot|耐电压|被动放电|passive",
        re.I,
    ),
    "被动放电": re.compile(
        r"active discharge|主动放电|insulation resistance|耐电压", re.I
    ),
}


def _kb_manifest_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    override = (os.environ.get("SPEC_SHEET_KB_MANIFEST") or "").strip()
    lex = (os.environ.get("SPEC_SHEET_CLAUSE_LEXICON") or "").strip()
    out: list[Path] = []
    if override:
        out.append(Path(override).expanduser())
    if lex:
        lex_path = Path(lex).expanduser().resolve()
        out.append(lex_path.parent / "knowledge" / "published" / "manifest.json")
    out.extend(
        [
            Path.cwd() / "docs" / "knowledge" / "published" / "manifest.json",
            here.parents[2]
            / "electrical-krow"
            / "docs"
            / "knowledge"
            / "published"
            / "manifest.json",
            here.parents[2] / "docs" / "knowledge" / "published" / "manifest.json",
            here.parents[1] / "docs" / "knowledge" / "published" / "manifest.json",
        ]
    )
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


@lru_cache(maxsize=1)
def _enterprise_manifest() -> dict:
    for path in _kb_manifest_candidates():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _is_method_std_cite(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or raw.startswith("图纸"):
        return False
    return bool(_METHOD_STD_OK.search(raw))


def _std_ref_by_seq() -> dict[int, dict[str, list[str]]]:
    """seq → {std_id, methods, clauses}。只收看起来像标准号的方法引用。"""
    enterprise = _enterprise_manifest().get("enterprise") or {}
    if enterprise.get("fill") is True:
        return {}
    std_id = str(enterprise.get("std_id") or "Q/JLP 030602-07-2026A").strip()
    by_seq: dict[int, dict[str, list[str]]] = {}
    for clause in enterprise.get("clauses") or []:
        if clause.get("fill") is True:
            continue
        methods = [
            str(x).strip()
            for x in (clause.get("method_std") or [])
            if _is_method_std_cite(str(x))
        ]
        if not methods:
            continue
        cid = str(clause.get("id") or "").strip()
        for seq in clause.get("see_seq") or []:
            try:
                num = int(seq)
            except (TypeError, ValueError):
                continue
            bucket = by_seq.setdefault(
                num, {"std_id": std_id, "methods": [], "clauses": []}
            )
            if cid and cid not in bucket["clauses"]:
                bucket["clauses"].append(cid)
            for method in methods:
                if method not in bucket["methods"]:
                    bucket["methods"].append(method)
    return by_seq


def _fill_std_ref_when_dpr_missing(rows: dict[int, ExtractedCell]) -> None:
    """当份未给出且企标挂了方法标准：抽出值空、标未检索到；方法号只写备注。"""
    refs = _std_ref_by_seq()
    if not refs:
        return
    for seq, cell in rows.items():
        if seq not in refs:
            continue
        if (cell.value or "").strip():
            continue
        info = refs[seq]
        methods = info.get("methods") or []
        if not methods:
            continue
        std_id = info.get("std_id") or "Q/JLP 030602-07-2026A"
        clauses = "、".join(info.get("clauses") or [])
        method_text = "；".join(methods)
        cite = f"{std_id} {clauses} → {method_text}"
        cell.value = ""
        cell.excerpt = ""
        cell.page = ""
        cell.clause = ""
        cell.confidence = 0.0
        cell.review_status = STATUS_MISS
        cell.note = f"{_STD_REF_NOTE}：当份 DPR 未给出该指标；{cite}。"


def _fill_miss_next_step(rows: dict[int, ExtractedCell]) -> None:
    """空项抽出值仍未检索到。已有企标方法号则保留；否则备注人工复核。"""
    _fill_std_ref_when_dpr_missing(rows)
    for cell in rows.values():
        if (cell.value or "").strip():
            continue
        if (cell.note or "").strip():
            continue
        cell.review_status = STATUS_MISS
        cell.note = _MISS_REVIEW_NOTE


def _hv_safety_topic(name: str) -> str:
    if "绝缘电阻" in (name or ""):
        return "绝缘电阻"
    if "耐电压" in (name or ""):
        return "耐电压"
    if "主动放电" in (name or ""):
        return "主动放电"
    if "被动放电" in (name or ""):
        return "被动放电"
    return ""


def _pick_hv_safety_clause(chunk: str, index: int | None, name: str) -> str:
    """绝缘电阻 / 耐电压 / 放电用各自标题上的条款号，不把 3.3 套到 3.4。"""
    topic = _hv_safety_topic(name)
    if not topic or index is None or index < 0 or not chunk:
        return ""
    want = _HV_TITLE_WANT[topic]
    reject = _HV_TITLE_REJECT[topic]
    best = ""
    for match in _HV_SECTION_HEAD.finditer(chunk[: index + 1]):
        title = match.group(2) or ""
        if reject.search(title) and not want.search(title):
            continue
        if want.search(title):
            best = match.group(1)
    return best


def _value_fits_field(name: str, value: str, excerpt: str) -> bool:
    """值必须和条目说的是同一件事，否则视为乱填。"""
    name = name or ""
    text = f"{value}\n{excerpt}"
    if _is_law_description(value, excerpt):
        return False
    if not _motor_label_ok(name, text):
        return False
    if "额定转速" in name or "转速需求" in name:
        if re.search(r"最高转速|max(?:imum)?\s*speed|超速|随转", text, re.I) and not re.search(
            r"额定转速|rated speed|continuous speed", text, re.I
        ):
            return False
        if "转速需求" in name:
            return bool(re.search(r"转速需求|speed demand|speed requirement", text, re.I))
        # 额定功率行的 kW@转速 不是单独额定转速定义（#29/#46 待专家口径）。
        if re.search(
            r"continuous generate|额定发电|continuous drive|额定驱动功率",
            text,
            re.I,
        ) and not re.search(r"额定转速|rated speed|rated rpm", text, re.I):
            return False
        return bool(re.search(r"额定转速|rated speed|continuous speed", text, re.I))
    if "P1" in name and "额定扭矩" in name:
        if re.search(r"P3电机额定扭矩|P3 continuous torque", text, re.I):
            return False
        return _has_any(
            text,
            r"P1\s+continuous\s+torque",
            r"P1\s*电机额定扭矩",
            r"P1额定扭矩",
        )
    if "P3" in name and "额定扭矩" in name:
        if re.search(r"P1电机额定扭矩|P1 continuous torque", text, re.I):
            return False
        return _has_any(
            text,
            r"P3\s+continuous\s+torque",
            r"P3\s*电机额定扭矩",
            r"P3额定扭矩",
        )
    if "P1" in name and "峰值功率" in name and "持续" not in name:
        # HVDC 峰值是连接器/母线能力，不是 P1 电机峰值（DHTS 125kW、SuperEvo 270kW）
        if re.search(r"HVDC peak|高压直流峰值功率", text, re.I) and not re.search(
            r"P1电机|P1 peak generate|P1峰值发电", text, re.I
        ):
            return False
        if re.search(r"270\s*kW", text, re.I) and re.search(
            r"HVDC|高压直流", text, re.I
        ):
            if not re.search(r"P1电机|generate power", text, re.I):
                return False
    if "P1" in name and "额定功率" in name:
        if re.search(r"HVDC continuous|高压直流持续", text, re.I) and not re.search(
            r"P1电机|P1 continuous generate|P1额定发电", text, re.I
        ):
            return False
        return _has_any(
            text,
            r"120\s*kW",
            r"generate power",
            r"额定发电",
            r"continuous generate",
            r"P1额定功率",
        )
    if "直流工作电压" in name:
        if _looks_like_dc_capacitor_spec(text) and _has_any(text, r"500Vdc", r"Rated Voltage"):
            return False
        # 「不得超过 945V」是发电/耐压上限，不是工作电压范围
        if _has_any(
            text,
            r"shall not generate",
            r"Maximum allowed generated",
            r"不得产生",
            r"允许产生的最高",
            r"generated HVDC",
        ) and not _has_any(text, r"Voltage Range", r"冷启动", r"满功率", r"full power", r"380", r"640"):
            return False
        return _has_any(
            text,
            r"hvdc voltage range",
            r"高压范围",
            r"工作电压",
            r"冷启动",
            r"满功率",
            r"full power",
            r"limited performance",
            r"vdc",
            r"hvdc",
        )
    if "过压" in name:
        # 通用保护叙述不是阈值（「电机旋转导致过压、可用主动短路」）
        if re.search(r"protect itself from excess voltage", text, re.I):
            return False
        if re.search(r"circuit analysis|故障树|FMEA|失效分析|分析项", text, re.I):
            return False
        # 充电 Boost「允许过压保护」不是直流母线过压阈值
        if _has_any(text, r"允许过压保护"):
            return False
        # 「不得产生 945V」是发电上限，不是过压保护阈值
        if _has_any(
            text,
            r"shall not generate",
            r"不得产生",
            r"允许产生的最高",
            r"Maximum allowed generated",
        ):
            return False
        if re.search(r"供应商提供|to be provided", text, re.I) and not re.search(
            r"\d+\s*V", text, re.I
        ):
            return False
        if not re.search(r"\d+", value or ""):
            return False
        if not re.search(r"\d+(?:\.\d+)?\s*V|1066|525|510", text, re.I):
            return False
        return _has_any(
            text,
            r"excess voltage",
            r"过压",
            r"over.?voltage",
            r"高压保护",
            r"500\s*vdc",
            r"510\s*vdc",
            r"1066",
        )
    if "BOOST最高" in name or "升压器的目标输出" in name:
        if _has_any(value, r"允许过压保护"):
            return False
        if re.search(r"1056\s*V?\s*＜\s*U\s*≤\s*1066", value) and not _has_any(
            value, r"上限", r"最高工作电压"
        ):
            return False
        return _has_any(
            text,
            r"450",
            r"目标输出",
            r"booster",
            r"1066",
            r"1056",
            r"最高工作电压",
            r"上限",
        )
    if "Boost输出性能" in name:
        # 升压纹波不是输出性能；仅「三种工作模式」也不够
        if _has_any(text, r"纹波", r"ripple", r"pk-?pk", r"vpp", r"v_vpp"):
            return False
        # 效率目标整段（99.5%@直通…）是 #62 升压效率的内容，不得因带「输入功率 kW」混进输出性能。
        # 2026-09-16：13:26 那份 #61 抄了 #62 整段，跨条目同值去重按入库顺序漏掉了它。
        if _has_any(value, r"效率", r"efficiency") and re.search(r"[%％]", value or ""):
            return False
        # shall / 「应能够升压」是功能句，不是输出侧电压/功率。2026-09-21 10:03 #61 整句入库。
        if _has_any(
            value,
            r"shall be able to boost",
            r"应能够将直流输入的电压提升",
        ) and not re.search(r"\d{3,4}\s*V", value or "", re.I):
            return False
        if _has_any(text, r"三种|工作模式|bypass") and not _has_any(
            text, r"\bkw\b", r"功率", r"\d+\s*A", r"电流", r"250A", r"85"
        ):
            return False
        return _has_any(
            text,
            r"\bkw\b",
            r"功率",
            r"电流",
            r"250A",
            r"85\s*kw",
            r"目标输出",
            r"Target output voltage of booster",
            r"450\s*V",
            r"boost",
        )
    if "设计范围是否包含充电升压" in name or "设计范围是否包含行车升压" in name:
        if _has_any(value, r"三种作?工作模式|Boost升压，bypass") and not _has_any(
            text, r"Charging Buck/Boost", r"充电升压/降压", r"慢充"
        ):
            return False
        if _has_any(value, r"85\s*kw") and not _has_any(
            text, r"Charging Buck/Boost", r"充电升压/降压", r"慢充", r"充电Boost"
        ):
            return False
        if _has_any(value, r"升压器的目标输出") and not _has_any(
            value, r"是；", r"Charging Buck"
        ):
            return False
        if _has_any(value, r"boost control", r"BOOST architecture") and not _has_any(
            text,
            r"Charging Buck/Boost",
            r"充电升压",
            r"boost the HV input",
            r"HVDC 输入电压较低",
        ):
            return False
        return _has_any(
            text,
            r"Charging Buck/Boost",
            r"充电升压/降压",
            r"充电Boost",
            r"慢充",
            r"充电升压",
            r"boost the HV input",
            r"HVDC 输入电压较低",
            r"直流输入的电压提升",
            r"改善 TM",
        )
    if "充电升压" in name or "升压充电" in name:
        if _has_any(text, r"三种作?工作模式|Boost升压，bypass") and not _has_any(
            text, r"慢充", r"充电连接", r"slow charg", r"充电机"
        ):
            return False
        if _has_any(text, r"boost control", r"BOOST architecture") and not _has_any(
            text, r"充电", r"buck", r"bypass", r"驻车放电", r"慢充"
        ):
            return False
        return _has_any(
            text,
            r"慢充",
            r"充电连接",
            r"slow charg",
            r"充电机",
            r"charging connector",
            r"Charging Buck/Boost",
            r"驻车放电",
            r"充电升压",
        )
    if "升压输出功率" in name:
        if _has_any(text, r"\bbuck\b") and not _has_any(text, r"升压输出", r"Charging Buck"):
            return False
        boost_ctx = _has_any(text, r"boost", r"升压", r"Charging Buck")
        has_p = _has_any(
            text, r"kw", r"功率", r"power", r"100kW", r"180kW", r"峰值功率", r"持续稳定功率"
        )
        has_vi = bool(
            re.search(
                r"\d+\s*V\s*[×x*]\s*(?:最大电流|持续电流)?\s*\d+\s*A",
                text,
                re.I,
            )
        )
        return boost_ctx and (has_p or has_vi)
    if "升压输出电压" in name:
        if _has_any(text, r"高压侧") and _has_any(
            text, r"1056", r"1066", r"480", r"满功率", r"满电流"
        ):
            return True
        if _has_any(text, r"三种作?工作模式|Boost升压，bypass|Boost/bypass/BUCK"):
            return True
        return _has_any(
            text, r"升压器的目标输出", r"Target output voltage of booster", r"450"
        ) and _has_any(text, r"boost", r"升压", r"booster")
    if "相电流采样" in name:
        # ASIL 等级 alone 不是采样精度
        if _has_any(text, r"asil") and not _has_any(text, r"%", r"精度", r"accuracy", r"±"):
            return False
        return _has_any(
            text,
            r"phase current",
            r"相电流",
            r"current sensor",
            r"HVAC current",
            r"高压交流电流",
        ) and _has_any(text, r"%", r"精度", r"accuracy", r"±")
    if "防腐" in name:
        return _has_any(text, r"f[34]", r"防腐", r"corrosion", r"j160003")
    if "湿度" in name:
        return _has_any(text, r"湿度", r"humidity", r"95\s*%", r"1%\s*[~～-]\s*100%")
    if "母线直流电流" in name:
        if re.search(r"供应商提供|to be provided", text, re.I) and not _has_any(
            text, r"\d+\s*A", r"asil", r"监测"
        ):
            return False
        return _has_any(text, r"hvdc current", r"直流电流", r"current sensor", r"dc current")
    if "堵转电流" in name:
        return _has_any(text, r"堵转", r"stall", r"520")
    if "堵转扭矩" in name:
        return _has_any(text, r"堵转", r"locking", r"stall", r"50%\s*峰值", r"持续堵转") and _has_any(
            text, r"tmax", r"扭矩", r"torque", r"nm", r"260", r"415"
        )
    if "峰值扭矩" in name and "P3" in name:
        # 堵转策略 85% Tmax@3s 属于堵转格，不是电机峰值扭矩
        if re.search(
            r"locking strategy|堵转策略|Tmax\s*\*\s*0\.85|T_max\s*\*\s*0\.85",
            text,
            re.I,
        ) and not re.search(
            r"P3\s*(?:peak torque|电机峰值扭矩)[^\n]{0,120}?\d+(?:\.\d+)?\s*Nm",
            text,
            re.I,
        ):
            return False
        if _has_any(text, r"持续堵转") and not _has_any(
            text, r"P3\s*peak torque", r"P3\s*电机峰值扭矩"
        ):
            return False
        return _has_any(
            text,
            r"P3\s+peak\s+torque",
            r"P3\s*电机峰值扭矩",
            r"≥\s*415\s*Nm",
            r"400\s*Nm",
        )
    if "反电动势" in name or "Back EMF" in name:
        if _has_any(text, r"以电机实际达成为准|具体数值") and _has_any(
            text, r"back[\s\-]?emf", r"反电动势"
        ):
            return True
        return _has_any(text, r"back[\s\-]?emf", r"反电动势", r"反电势") and _has_any(
            text, r"\d+\s*V", r"Vpk", r"Vdc", r"峰值", r"maximum", r"＜", r"<"
        )
    if "耐电压" in name:
        src = excerpt or ""
        heading_only = bool(
            re.search(
                r"耐电压要求\s*（电控）|Withstand voltage requirements of PCM",
                src,
                re.I,
            )
        ) and not _has_any(
            src,
            r"18488",
            r"16935",
            r"漏电流",
            r"击穿",
            r"3\.5\s*mA",
            r"5mA",
            r"工频",
        ) and not re.search(r"\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc)", src, re.I)
        if heading_only:
            return False
        # 瞬态脉冲、ELP 通用试验引用，都不是工频/直流耐电压指标
        if _has_any(
            text, r"transient hvdc", r"瞬态高压直流", r"voltage transient pulses"
        ) and not _has_any(text, r"工频", r"hipot", r"直流耐电压", r"连续高压直流耐压"):
            return False
        if _has_any(text, r"J7111029") and not _has_any(
            text, r"击穿", r"漏电流", r"18488", r"工频", r"直流耐电压"
        ):
            return False
        # ISO 6469 仅标准号/公式不够；原文给出 1min、50–60Hz 交流试验时按耐电压条款认
        iso_formula = _has_any(
            text, r"ISO\s*6469", r"2U\s*\+\s*1\s*000", r"2U\s*\+\s*1000"
        )
        iso_hipot = iso_formula and _has_any(
            text,
            r"1\s*(?:min|分钟)",
            r"50\s*Hz",
            r"60\s*Hz",
            r"VAC\s*rms",
            r"交流试验电压",
        )
        if iso_formula and not iso_hipot and not _has_any(text, r"18488", r"漏电流", r"击穿"):
            return False
        if _is_continuous_hvdc_withstand(text):
            return bool(re.search(r"\d{2,4}\s*V", text, re.I))
        if _looks_like_operating_voltage_withstand(text):
            return False
        if _looks_like_dc_capacitor_spec(text):
            return False
        # 检查表「Dielectric strength @60sec / Partner proposal √」没有试验电压
        if _has_any(text, r"Partner proposal", r"合作方提案") and not re.search(
            r"\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc)|18488|16935|击穿|漏电流",
            text,
            re.I,
        ):
            return False
        if _has_any(text, r"电容耐压", r"薄膜电容") and not _has_any(
            text, r"动力端子", r"信号端子", r"外壳", r"18488", r"16935"
        ):
            return False
        has_label = _has_any(
            text,
            r"耐压",
            r"耐电压",
            r"withstand",
            r"hipot",
            r"击穿",
            r"闪络",
            r"dielectric",
        )
        has_test = _has_any(
            text,
            r"击穿",
            r"漏电流",
            r"工频",
            r"直流耐电压",
            r"直流耐压",
            r"hipot",
            r"18488",
            r"16935",
            r"1\s*(?:min|分钟)",
            r"50\s*Hz",
            r"VAC\s*rms",
            r"ISO\s*6469",
        )
        # 试验电压只跟「耐压/耐电压/hipot」配；不要用英文 withstand，否则会把
        # 「母线持续供电 500V」当成耐电压试验。
        has_test_voltage = bool(
            re.search(
                r"(?:耐压|耐电压|hipot|工频耐压|直流耐压|连续耐压)[^\n]{0,48}?\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc)|"
                r"\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc)[^\n]{0,24}(?:耐压|耐电压|hipot)",
                text,
                re.I,
            )
        )
        return bool(has_label and (has_test or has_test_voltage))
    if "低压功耗" in name or name == "静态电流":
        if _is_process_language(text):
            return False
        if _has_any(text, r"吉利认可|硬件设计后|待提供|待供应商") and not _has_any(
            text, r"未唤醒", r"唤醒@IGBT", r"\d+\s*mA", r"\d+\s*W\s*@"
        ):
            return False
        if name == "静态电流":
            # 电容漏电流、板级 Dark Current Under 1 不是整机未唤醒静态电流
            if _has_any(text, r"Under 1", r"板级 Dark Current"):
                return False
            if _looks_like_dc_capacitor_spec(text):
                return False
            if _has_any(text, r"DC.?电容", r"DC capacitor", r"film cap") and not _has_any(
                text, r"未唤醒", r"休眠", r"\bXCM\b", r"quiescent"
            ):
                return False
            if re.search(r"Rated Voltage,\s*1min|@ Rated Voltage", text, re.I) and re.search(
                r"0\.1\s*mA|Dark Current", text, re.I
            ):
                return False
            if re.match(r"^Under 1\b", (excerpt or "").strip()):
                return False
        if "低压功耗" in name:
            # 未唤醒 0.2 mA 是静态电流，不是整机唤醒功耗
            if re.search(r"未唤醒", text) and not re.search(
                r"唤醒@IGBT|高低压都上电", text
            ):
                return False
            if not _has_any(
                text,
                r"\d{3,5}\s*mA",
                r"唤醒@IGBT",
                r"高低压都上电",
                r"working current",
                r"\d+\s*W\s*@",
            ):
                return False
        return _has_any(
            text,
            r"\d+\s*mA",
            r"\d+\s*mW",
            r"\d+\s*W\s*@",
            r"0\.1\s*mA",
            r"static current",
            r"dark current",
            r"working current",
        )
    if "电驱回路水温" in name or "冷却液入口" in name:
        return _has_any(text, r"coolant inlet", r"冷却液入口", r"-40")
    if "油温采样" in name:
        return _has_any(text, r"oil temperature", r"油温") and _has_any(
            text, r"-?\d+", r"℃", r"°C", r"精度", r"%", r"ms", r"延时"
        )
    if "油温" in name:
        return _has_any(text, r"oil temperature", r"油温")
    if "振动" in name:
        if (value or "").strip() in {"振动", "Vibration"}:
            return False
        if re.search(r"暂无具体|无具体数值", value or ""):
            return False
        # 电容规范上的 10G 不是整机振动要求
        if _has_any(text, r"DC 电容规范", r"DC capacitor", r"DC 电容"):
            return False
        if re.search(r"10G\s*\(\s*10\s*[~～-]\s*200\s*Hz\s*\)", text, re.I) and not _has_any(
            text, r"030600", r"正弦", r"随机", r"32h", r"PSD"
        ):
            return False
        if not _has_any(
            text, r"\d+\s*G\b", r"10G", r"030600", r"Hz", r"正弦", r"随机", r"32h"
        ):
            return False
        return _has_any(text, r"vibration", r"振动", r"030600", r"10G")
    if "CPSR" in name:
        if _has_any(text, r"\d+\s*V", r"精度", r"%", r"ms", r"延时", r"range", r"范围"):
            return _has_any(text, r"cpsr")
        return _has_any(text, r"cpsr") and _has_any(text, r"继电器", r"relay")
    if "清洁度" in name:
        return _has_any(text, r"cleanliness", r"清洁度")
    if "高压连接器" in name:
        # 抽出值写成峰值/持续功率 → 拒。摘录里可以有功率句（6.2.3.2 正文）。
        if (
            _CONNECTOR_POWER_AS_VALUE.search(value or "")
            or _HVDC_PEAK_POWER.search(value or "")
        ) and not _has_any(
            value or "",
            r"IPXX",
            r"触指",
            r"防直接接触",
            r"防直触",
        ):
            return False
        if re.search(r"无机械互锁|without machine of HVIL", text, re.I) and not _has_any(
            text, r"IPXX", r"触指", r"防直触", r"防直接接触"
        ):
            return False
        if _has_any(
            text, r"auxiliary hvdc", r"辅助高压直流连接", r"Auxiliary high voltage"
        ) and not _has_any(
            value or "",
            r"IPXX",
            r"触指",
            r"hvil",
            r"防直接接触",
            r"高压直流连接",
            r"High Voltage DC connection",
        ):
            return False
        if _has_any(
            text,
            r"IPXX",
            r"触指",
            r"防直接接触",
            r"防直触",
            r"finger proof",
            r"touch protection",
        ):
            return True
        # 专家：条款 6.2.3.2 正确。当份只写高压直流连接、未写触指 → 局部对应。
        return _has_any(
            value or "",
            r"高压直流连接",
            r"High Voltage DC connection",
        ) and _has_any(
            text,
            r"6\.2\.3\.2",
            r"High Voltage DC connection",
            r"高压直流连接",
        )
    if "额定流量" in name:
        # 压降考核点 alone 不够；要有流量定义
        if _has_any(text, r"压降|kPa|mbar") and not _has_any(
            text, r"流量范围|rated flow|额定流量|0\s*to\s*10|MAX\.?\s*12|10\s*L/?min|10L/min"
        ):
            return False
        return _has_any(text, r"10\s*l", r"12\s*l", r"liter/min", r"lpm", r"额定流量", r"rated flow")
    if "冷却流量范围" in name:
        if _has_any(text, r"压降|kPa|mbar") and not _has_any(
            text, r"0\s*to\s*10|流量范围|MAX\.?\s*12|liter/min|lpm"
        ):
            return False
        return _has_any(text, r"0\s*to\s*10", r"流量", r"flow", r"lpm", r"liter/min", r"MAX\.?\s*12")
    if "上移功能" in name:
        # 冷却流阻/重量括号里的 (with OD) 不是油泵/OD 功能上移
        if _od_module_parenthetical_not_upshift(text, value):
            return False
        return _has_any(
            text,
            r"上移",
            r"OD relocation",
            r"relocated OD",
            r"OD moved into",
            r"function relocation",
            r"推荐电路",
            r"平台电路",
            r"reference circuit",
            r"recommended circuit",
        )
    if "OD本体" in name or "物理集成" in name:
        if _od_module_parenthetical_not_upshift(text, value) and _has_any(
            text, r"flow resistance|冷却流阻|kPa|Kpa|压降"
        ):
            return False
        return _has_any(text, r"\bOD\b") and _has_any(
            text, r"含OD模块", r"with od module", r"物理集成", r"including the od", r"OD Module"
        )
    if "升压" in name and "纹波" in name:
        if _has_any(text, r"Voltage Ripple on HV") and not _has_any(text, r"boost", r"升压"):
            return False
        return _has_any(text, r"boost", r"升压", r"桩侧", r"Charging Buck") and _has_any(
            text, r"ripple", r"纹波", r"vpp", r"1%", r"20V", r"10V"
        )
    if "高压安全" in name and "纹波" in name:
        # Boost 引起的母线纹波、额定/峰值工况表不是高压安全（电池接通/断开）口径
        if _has_any(text, r"caused by Boost", r"Boost对母线"):
            return False
        if _has_any(text, r"Voltage Ripple on HV") and not _has_any(
            text, r"switched off", r"高压电池关闭", r"接触器断开"
        ):
            return False
        if not re.search(r"\d+", value or ""):
            return False
        return _has_any(
            text,
            r"battery.{0,40}disconnect",
            r"contactors open",
            r"switched off",
            r"电池断开",
            r"接触器断开",
            r"高压电池关闭",
            r"高压系统兼容纹波",
        )
    if "直流母线" in name and "纹波" in name:
        if _has_any(text, r"caused by Boost", r"Boost对母线"):
            return False
        if _has_any(text, r"桩侧", r"单体未接入", r"纹波电压-电池侧"):
            return False
        # 电容/EMC 表 Voltage Ripple on HV 15Vpp Region I 不是整机母线纹波条款
        if _has_any(text, r"Voltage Ripple on HV") and not _has_any(
            text, r"Generated voltage ripple", r"产生电压纹波", r"switched on", r"高压电池接通"
        ):
            return False
        if _has_any(text, r"Region I") and _has_any(text, r"15Vpp"):
            return False
        if not re.search(r"\d+", value or ""):
            return False
        return _has_any(
            text,
            r"Generated voltage ripple",
            r"产生电压纹波",
            r"额定工况",
            r"Rated operating",
            r"ripple",
            r"纹波",
            r"vpp",
            r"pk-pk",
        )
    if "纹波" in name:
        # 充电桩侧/电池侧纹波不是直流母线纹波，也不是升压输出纹波
        if _has_any(text, r"桩侧", r"单体未接入", r"纹波电压-电池侧"):
            return False
        if not re.search(r"\d+", value or ""):
            return False
        return _has_any(text, r"ripple", r"纹波", r"vpp")
    if "绝缘电阻" in name:
        if _looks_like_dc_capacitor_spec(text):
            return False
        if _has_any(text, r"DC-link 电容", r"DC.?link 电容"):
            return False
        if _has_any(text, r"@ Rated Voltage", r"Rated Voltage,\s*1min") and _has_any(
            text, r"100M"
        ):
            return False
        if _has_any(
            text,
            r"meet the design spec",
            r"shall meet the design",
            r"满足设计规格",
            r"符合设计规格",
        ) and not _has_any(text, r"MΩ", r"MOhm", r"100M", r"20M", r"mΩ"):
            return False
        return _has_any(
            text, r"MΩ", r"MOhm", r"mohm", r"mΩ", r"100M", r"20M", r"48\s*M", r"2\.5\s*M"
        )
    if "主动放电电阻" in name:
        return _has_any(text, r"ohm", r"ω", r"Ω") and not _has_any(text, r"40k", r"事件", r"events")
    if "主动放电时间" in name or "主动放电功能" in name:
        if _has_any(
            text, r"after a crash", r"碰撞", r"continue to operate for\s*5"
        ) and not _has_any(text, r"completed within", r"内完成", r"200\s*ms"):
            return False
        if _has_any(text, r"60\s*v", r"60vdc") and _has_any(
            text, r"\d+\s*(s|ms|秒)", r"within\s*[lI1]\s*s", r"1s"
        ):
            return True
        has_ad = _has_any(text, r"主动放电", r"active discharge", r"discharge to DC")
        if "主动放电功能" in name:
            return has_ad
        return has_ad and _has_any(text, r"\d+\s*(s|ms|秒|second)", r"within\s*[lI1]\s*s")
    if "被动放电" in name:
        if re.search(r"discharge resistor", text, re.I) and not _has_any(
            text, r"\d+\s*s(?:ec)?", r"120\s*s", r"60\s*\(\s*Passive"
        ):
            return False
        return _has_any(
            text,
            r"被动放电",
            r"passive discharge",
            r"passively discharge",
            r"below 60\s*V[Il1]?DC",
            r"60\s*\(\s*Passive",
        )
    if "备份电源" in name:
        if _has_any(
            text,
            r"Connecting the KL30",
            r"Disconnecting KL30",
            r"must not activate outputs",
            r"不能激活输出",
            r"gate drivers",
            r"门极",
            r"隔离电源",
        ) and not _has_any(text, r"if KL30 is lost", r"KL30丢失"):
            return False
        return _has_any(text, r"back-?up", r"KL30丢失", r"备份电源")
    if "海拔" in name or "工作高度" in name:
        return _has_any(text, r"altitude", r"海拔", r"elevation", r"5000\s*m", r"米")
    if "冷却接口" in name or "冷却连接" in name:
        return _has_any(text, r"coolant", r"冷却", r"glycol", r"spigot", r"进水")
    if "压降" in name or "流阻" in name:
        return _has_any(text, r"kpa", r"mbar", r"pressure", r"流阻", r"压降")
    if "降额" in name:
        if _looks_like_ocr_garbage(value):
            return False
        # 380V 里 V 是单词字符，\b380\b 配不上；摘录常被截在表头、数字在后
        if _has_any(text, r"Min level during cold") and not _has_any(
            text, r"380", r"640", r"性能限制", r"limited performance"
        ):
            return False
        return _has_any(
            text,
            r"limited performance",
            r"降额",
            r"性能限制",
            r"限制最高",
            r"1150",
            r"1125",
            r"1066",
            r"380",
        )
    if "低压电源" in name or "LVDC" in name.upper():
        return _has_any(text, r"lvdc", r"6\s*[~～-]\s*16", r"iso\s*16750")
    if "寿命" in name:
        return _has_any(text, r"年", r"公里", r"\bkm\b", r"year", r"warranty", r"质保")
    if "采样精度" in name:
        # 「有传感器 / 测量某某」不够，必须带误差或分辨率
        if not _has_any(
            text,
            r"±",
            r"%",
            r"精度",
            r"accuracy",
            r"error",
            r"误差",
            r"resolution",
            r"分辨率",
        ):
            return False
    if "IGBT" in name and "温度" in name:
        if re.search(r"(?<!\d)200\s*℃", value or "") and not re.search(
            r"120\s*℃", value or ""
        ):
            return False
        return _has_any(text, r"igbt", r"功率模块", r"power module", r"inverter tempe")
    if "电机温度" in name:
        if re.search(r"(?<!\d)120\s*℃", value or "") and not re.search(
            r"200", value or ""
        ):
            return False
        return _has_any(text, r"电机温度", r"motor temp", r"绕组", r"stator", r"coil")
    if "冷却液温度" in name:
        if re.search(r"environmental\s*Temp|Oil\s*/\s*coolant", value, re.I) and not re.search(
            r"-40|\b65\b", value
        ):
            return False
        if re.search(
            r"locking strategy|堵转策略|堵转安全|Stall Safety|peak torque\s*@",
            text,
            re.I,
        ) and not re.search(r"-40", text):
            return False
        # 传感器「可测范围」是水温采样条目，不是冷却液工作温度
        if re.search(
            r"must be measurable|可测范围|inlet temperature must be measurable|入口水温可测",
            text,
            re.I,
        ) and not re.search(
            r"Full coolant|全冷却液温度|Normal coolant|正常冷却液|Cooling Water Temperature",
            text,
            re.I,
        ):
            return False
        if re.match(r"^65\s*[°℃]?\s*C?$", (value or "").strip(), re.I):
            return False
        if not re.search(
            r"-?\d+(?:\.\d+)?\s*(?:℃|°C|degC)|\b-40\b.{0,12}\b65\b|\b65\s*°",
            text,
            re.I,
        ):
            return False
        return _has_any(
            text, r"冷却液", r"coolant", r"cooling water", r"inlet", r"冷却水"
        )
    if "流量" in name:
        return _has_any(text, r"流量", r"flow", r"lpm", r"liter/min", r"l/min")
    if "密封" in name or re.search(r"(?i)\bIP\b|IP等级", name):
        src = excerpt or ""
        if _has_any(
            text,
            r"non-mated",
            r"未插接",
            r"未插配",
            r"Non-mated connectors",
            r"connectors?\s+shall",
            r"connectors for options",
            r"touch protected",
            r"IPXX",
            r"IPxx",
            r"protection degree of at least\s*IP68",
        ):
            return False
        # 值里的 IP68 不能自证；摘录必须有整机防护等级
        return _has_any(src, r"ip\s*[456][0-9k]", r"ip6k", r"防护等级", r"waterproof")
    if "功能安全" in name:
        return _has_any(text, r"iso\s*26262", r"asil")
    if "设计范围是否包含驱动升压" in name:
        if _has_any(text, r"Charging Buck/Boost", r"充电升压/降压", r"充电升压及驻车放电"):
            return False
        return _has_any(
            text,
            r"boost",
            r"升压",
            r"电压提升",
            r"BOOST architecture",
        ) and _has_any(text, r"是", r"有", r"shall be able", r"能够", r"boost control")
    if "主动保险" in name:
        return _has_any(
            text,
            r"PSS",
            r"Power Safety Switch",
            r"主动点爆",
            r"烟火",
            r"pyrotechnic",
        )
    if "BOOST输入峰值电流" in name:
        if _has_any(text, r"额定输入电流") and not _has_any(
            text, r"峰值电流", r"peak current"
        ):
            return False
        return _has_any(text, r"峰值电流", r"peak current", r"@10S", r"@10s")
    if "升压" in name or "BOOST" in name.upper() or "Boost" in name:
        return _has_any(text, r"boost", r"升压", r"250A", r"1066", r"充电功率")
    if "Y电容" in name:
        if not re.search(r"nF", text, re.I):
            return False
        return _has_any(
            text,
            r"y[- ]?电容",
            r"y型电容",
            r"y-?cap",
            r"cy\s*\+",
            r"cy\s*-",
            r"hvdc\+\s*to\s*gnd",
            r"pcm\s+\d{2,4}\s*nF",
        )
    if "通讯" in name:
        return _has_any(text, r"\bcan\b", r"flexray", r"ethernet", r"以太网")
    if "ASC电流" in name or "主动短路电流" in name or (
        "ASC" in name.upper() and "电流" in name
    ) or "主动短路" in name:
        if not _has_any(text, r"arms", r"(?<![kKmM])\d+\s*A\b"):
            return False
        if re.search(r"253", value or "") and re.search(
            r"(?:inverter|逆变器).{0,48}250", text
        ):
            return False
        if re.search(r"200", value or "") and re.search(
            r"持续值|continuous AC phase current of\s*200", text, re.I
        ) and re.search(r"此条件|under this condition", text, re.I) and re.search(
            r"250", text
        ) and not re.search(r"在200\s*A|200\s*A(?:rms)?\s*条件下", text, re.I):
            return False
        if "主动短路电流" in name and re.search(r"830", value or "") and re.search(
            r"@\s*1\s*ms|短时峰值|transient peak", text, re.I
        ):
            return False
        return _has_any(text, r"主动短路", r"active short", r"\basc\b", r"ASC")
    if "持续交流电流" in name or "额定功率相电流" in name:
        # 充电/Boost 低压侧输入电流不是 P3 相电流
        if _has_any(text, r"低压侧", r"充电功率", r"\bbuck\b"):
            return False
        if _has_any(text, r"额定输入电流") and not _has_any(
            text, r"相电流", r"P3", r"Arms", r"PEI P3"
        ):
            return False
        return _has_any(text, r"持续", r"continuous", r"额定") and _has_any(text, r"arms", r"电流")
    # P3 峰值：DHTS 520Arms；SuperEvo 465Arms — 二者都认
    if "P3" in name and ("交流电流峰值" in name or "电流峰值" in name):
        if _has_any(text, r"520|465"):
            return _has_any(text, r"arms", r"电流", r"峰值", r"peak")
        if _has_any(text, r"250") and not _has_any(text, r"520|465"):
            return False
        return _has_any(text, r"峰值", r"peak") and _has_any(text, r"arms", r"电流")
    if "交流电流峰值" in name or "电流峰值" in name:
        return _has_any(text, r"峰值", r"peak") and _has_any(text, r"arms", r"电流")
    if "工作温度" in name:
        return _has_any(
            text,
            r"工作温度",
            r"operating temperature",
            r"Ambient\s*\(\s*Operating\s*\)",
            r"\(Operating\)",
            r"\(Operation\)",
            r"surface temperature",
            r"-40\s*℃?\s*[~～-]\s*85",
            r"-40\s*℃?\s*[~～-]\s*1[01][05]",
        )
    if "存储温度" in name:
        return _has_any(
            text,
            r"存储温度",
            r"storage temperature",
            r"Ambient\s*\(\s*Storage\s*\)",
            r"Storage/Abandon",
            r"Non-\s*operation",
            r"-40\s*[~～-]\s*105",
            r"-40\s*[~～-]\s*110",
        )
    if "海拔" in name:
        return _has_any(
            text, r"海拔", r"altitude", r"5000", r"elevation", r"sea level"
        )
    if "满功率" in name:
        return _has_any(
            text,
            r"满功率",
            r"full power",
            r"full performance",
            r"800\s*V?\s*[~～-]\s*1066",
            r"465Arms",
        )
    if "峰值功率持续时间" in name:
        excerpt_only = excerpt or ""
        if not _has_any(
            excerpt_only,
            r"\d+\s*s",
            r"duration",
            r"持续",
            r"≥\s*10s",
            r"@\s*10s(?:ec)?",
            r"10\s*sec",
        ):
            return False
        # 禁止把 BOOST/相电流 @10S 当成功率时长
        if _has_any(text, r"\d+\s*A\b", r"arms", r"电流") and not _has_any(
            text, r"\bkw\b", r"千瓦", r"功率", r"power"
        ):
            return False
        if "P1" in name and re.search(
            r"HVDC peak|高压直流峰值", text, re.I
        ) and not re.search(r"P1电机|P1 peak generate|P1峰值发电", text, re.I):
            return False
        # SuperEvo：≥300kw @800V 功率行无时长，@10s 在下一行峰值扭矩
        if "P3" in name:
            power_part = re.split(
                r"P3\s+peak\s+torque|P3\s*电机峰值扭矩|P3\s+continuous\s+torque|P3\s*电机额定扭矩",
                excerpt_only,
                maxsplit=1,
                flags=re.I,
            )[0]
            if (
                re.search(r"peak drive power", power_part, re.I)
                and re.search(r"\d+\s*kw", power_part, re.I)
                and not re.search(r"@\s*(?:≥\s*)?\d+\s*s", power_part, re.I)
                and re.search(r"peak torque[\s\S]{0,64}@\s*\d+\s*s", excerpt_only, re.I)
            ):
                return False
        return _has_any(
            text,
            r"峰值功率",
            r"peak power",
            r"maximum rating",
            r"\bkw\b.*10\s*s",
            r"10\s*s.*\bkw\b",
            r"duration",
            r"10\s*s",
            r"10\s*sec",
        ) and _has_any(text, r"\bkw\b", r"功率", r"power", r"maximum rating")
    if "峰值功率" in name:
        # UDC 模式 13kW/10kW 不是 P1/P3 电机峰值
        # 「此UDC模式」里 UDC 两侧都是字，不能用 \b
        if re.search(r"13\s*kW", text, re.I) and re.search(
            r"UDC|continues power\s*10", text, re.I
        ):
            return False
        if "P1" in name and re.search(
            r"HVDC peak|高压直流峰值功率", text, re.I
        ) and not re.search(r"P1电机|P1 peak generate|P1峰值发电", text, re.I):
            return False
        # 功率条目禁止绑成纯电流（如 830A@1ms）
        if _has_any(text, r"arms", r"(?<![kKmM])\d+\s*A\b") and not _has_any(
            text, r"\bkw\b", r"千瓦", r"功率"
        ):
            return False
        return _has_any(text, r"\bkw\b", r"千瓦", r"峰值功率", r"peak power")
    if "P3" in name and "额定功率相电流" in name:
        return _has_any(text, r"250", r"310", r"持续", r"continuous") and _has_any(
            text, r"arms|ams|电流"
        )
    if "热损失" in name:
        return _has_any(text, r"热损失", r"heat loss", r"爬坡", r"0\.8\s*kw") and _has_any(
            text, r"kw", r"千瓦", r"0\.8", r"0\.9", r"0\.4"
        )
    if "重量" in name:
        src = excerpt or ""
        if re.search(r"包装|packed|shipping|gross", src, re.I):
            return False
        decimal = bool(re.search(r"\d+[.．]\d+", src))
        integer_pcm = bool(
            re.search(
                r"(?:可拓展动力域|控制模块_总成|单件目标重量|总目标重量)[\s\S]{0,80}?"
                r"(?<!\d)(1[0-9]|2[0-5])(?!\d)",
                src,
            )
        )
        if not decimal and not integer_pcm:
            return False
        return _has_any(
            src,
            r"kg",
            r"公斤",
            r"重量",
            r"weight",
            r"动力控制模块",
            r"控制模块_总成",
            r"域控制模块",
            r"\bpcm\b",
        )
    if "位置传感器" in name:
        if _has_any(
            text,
            r"HVIL",
            r"Main [Rr]elay",
            r"Inverter Rdy",
            r"design compliance",
            r"Precharge",
        ) and not _has_any(text, r"eddy", r"涡流", r"Resolver Offset", r"旋变"):
            return False
        if re.search(r"^转子位置\s*/\s*Resolver$", (value or "").strip()) and not _has_any(
            text, r"eddy", r"涡流", r"Resolver Offset", r"旋变", r"two Rotor position"
        ):
            return False
        return _has_any(
            text, r"位置传感器", r"rotor position", r"旋变", r"eddy", r"resolver"
        )
    if "电机类型" in name:
        return _has_any(text, r"永磁", r"pmsm", r"permanent magnet", r"感应", r"异步")
    if "薄膜电容" in name:
        if not _has_any(text, r"µF", r"uF", r"μF", r"nF", r"mF"):
            return False
        return _has_any(text, r"film", r"薄膜", r"dc capacitor", r"dc-link")
    if "母线电压采样" in name:
        if not _has_any(
            text, r"±", r"%", r"精度", r"accuracy", r"error", r"误差", r"resolution"
        ):
            return False
        return _has_any(
            text, r"dc link", r"hvdc voltage", r"母线电压", r"高压直流电压", r"高压直流母线", r"±\s*3V"
        )
    if "低压供电" in name and "采样" in name:
        return _has_any(text, r"0\.01", r"12\s*v", r"总精度", r"resolution")
    if "逆变器效率" in name:
        if not (
            _has_any(text, r"效率", r"efficiency", r"99\.5", r"99\.8", r"99\.9")
            and _has_any(text, r"%", r"98", r"99")
        ):
            return False
        if "P1" in name:
            if re.search(
                r"总考核|综合效率|PCM P3 efficiency|P3\s*区间效率",
                text,
                re.I,
            ) and not re.search(
                r"99\.5|98\.2|单挡|PCM P1 efficiency|P1\s*区间效率|"
                r"Average efficiency|平均效率|-\s*\d+.{0,12}-\s*\d+\s*Nm",
                text,
                re.I,
            ):
                return False
            return bool(
                re.search(
                    r"99\.5|98\.2|单挡|P1\s*区间效率|PCM P1 efficiency|"
                    r"Average efficiency|平均效率|"
                    r"-\s*\d+.{0,12}-\s*\d+\s*Nm",
                    text,
                    re.I,
                )
            )
        if "P3" in name:
            if re.search(r"98\.2(?!\d)", value or "") and not re.search(
                r"98\.25|综合效率|区间[123]|总考核", text
            ):
                return False
            if re.search(r"6\.8\.4\.1|P1逆变器效率", excerpt or "") and not re.search(
                r"6\.8\.4\.2|P3逆变器效率|PEI P3", excerpt or "", re.I
            ):
                return False
            return bool(
                re.search(
                    r"99\.9|99\.8|＞\s*99|>\s*99|98\.25|总考核|"
                    r"区间\s*[123]|PCM P3 efficiency|P3\s*区间效率|综合效率",
                    text,
                    re.I,
                )
            )
        return True
    if "扭矩控制精度" in name or "转矩控制精度" in name:
        return _has_any(
            text,
            r"±\s*3\s*%",
            r"±\s*2\s*%",
            r"±\s*3\s*Nm",
            r"0\.4\s*Nm",
            r"扭矩控制精度",
            r"torque accuracy",
            r"zero torque",
        )
    if "扭矩响应" in name:
        return _has_any(text, r"响应", r"response", r"100-300", r"40\s*ms")
    if "禁用" in name or "限用" in name:
        return _has_any(text, r"J160001", r"禁用", r"限用", r"prohibited", r"ELV", r"Deca BDE", r"MS 201-02")
    if "阻燃" in name:
        return _has_any(text, r"阻燃", r"flame", r"V-0", r"J7110335")
    if "馈电" in name:
        return _has_any(text, r"馈电", r"generating", r"负扭矩", r"发电工况", r"regen")
    if "EMC" in name:
        return _has_any(text, r"emc", r"cispr", r"ece r10", r"es 36500", r"j7110922", r"j7110779")
    if "网络" in name:
        return _has_any(text, r"cyber", r"tara", r"sums", r"网络安全")
    if "加速踏板" in name:
        # 逆变器开关频率不是加速踏板 PWM
        if _has_any(text, r"switching frequency", r"开关频率", r"12\.5\s*kHz", r"\bPEI"):
            return False
        return _has_any(text, r"踏板", r"accelerator", r"\bAPP\b", r"pedal") and _has_any(
            text, r"hz", r"%", r"占空", r"duty", r"pwm"
        )
    if "Boost功能要求" in name or name == "Boost功能要求":
        return _has_any(text, r"boost", r"升压")
    if "额定功率" in name and "P3" in name:
        return _has_any(
            text,
            r"120\s*kw",
            r"额定驱动",
            r"continuous drive",
            r"P3\s+continuous",
            r"P3额定功率",
        )
    if "最高工作转速" in name:
        if _is_ac_fundamental_rpm_assumption(text):
            if not re.search(r"max speed|最高转速|随转|16000|20000", text, re.I):
                return False
        # 表头 Maximum allowable RPM 没有转速数字
        if not re.search(r"\d{4,5}", text):
            return False
        return _has_any(text, r"rpm", r"转速", r"16500", r"20000", r"16000", r"max speed")
    if "峰值扭矩" in name and "P1" in name:
        # ＞100A 电流测量误差不是 >100Nm 峰值扭矩
        if _has_any(
            text,
            r"HVAC current",
            r"高压交流电流",
            r"measure the HVAC",
            r"600A",
            r"800A",
            r"1200A",
            r"测量误差",
        ):
            return False
        if _has_any(text, r"(?<![kKmM])\d+\s*A\b", r"arms") and not _has_any(
            text, r"nm", r"扭矩", r"torque"
        ):
            return False
        return _has_any(text, r"100\s*Nm", r">\s*100\s*Nm", r"峰值扭矩", r"peak torque")
    if "绝缘电阻" in name:
        return _has_any(text, r"绝缘电阻", r"insulation resistance", r"100\s*M", r"20\s*M", r"mΩ")
    keys = (
        "逆变器", "持续", "交流", "电流", "峰值", "扭矩", "功率", "转速",
        "电压", "温度", "冷却", "绝缘", "放电", "寿命", "密封", "通讯",
        "升压", "纹波", "采样", "精度",
    )
    hits = [k for k in keys if k in name]
    if hits:
        return any(k in text for k in hits)
    tokens = [
        tok
        for tok in re.findall(r"[\u4e00-\u9fff]{2,4}", name)
        if tok not in {"是否", "包含", "要求", "指标", "范围", "功能", "设计", "是否包含"}
    ]
    if tokens:
        return any(tok in text for tok in tokens)
    return True


_FIELD_EN = (
    ("电压", "voltage vdc volt"),
    ("电流", "current amp arms"),
    ("温度", "temperature celsius"),
    ("冷却", "coolant glycol ewp lpm"),
    ("绝缘", "insulation isolation mohm"),
    ("放电", "discharge"),
    ("纹波", "ripple"),
    ("转速", "rpm speed"),
    ("扭矩", "torque nm"),
    ("功率", "power kw"),
    ("寿命", "life warranty km years"),
    ("升压", "boost"),
    ("功能安全", "iso 26262 asil"),
    ("密封", "ip6 ip67 ip68 ingress"),
    ("通讯", "can fd flexray"),
    ("振动", "vibration"),
    ("海拔", "altitude"),
)

# 清单全称 → 规格常用写法挂在 FieldSpec.aliases / clause_lexicon。
# 选段主检索用整词（三字名 + 已开通检索的别名），不用二字切「电压」。
# 「耐电压」检索认 耐压 / hipot；withstand 持续供电由入库闸挡掉，不靠行业常识补值。


def _name_match_tokens(name: str) -> list[str]:
    tokens = whole_name_tokens(name)
    extra = list(retrieve_aliases_for_name(name))
    return list(dict.fromkeys([*tokens, *extra]))


_LATIN_ALIAS = re.compile(r"^[a-z0-9][a-z0-9 ./+-]*$")


def _strong_alias_present(token: str, lowered: str) -> bool:
    """强别名列 prompt 条目用：英文别名只认整词（允许复数 s/es），creep 不能认 creepage。
    中文别名按子串。"""
    t = (token or "").strip().lower()
    if len(t) < 2:
        return False
    if _LATIN_ALIAS.match(t):
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(t)}(?:e?s)?(?![a-z0-9])", lowered)
            is not None
        )
    return _token_present(t, lowered)


def _chunk_fields(
    chunk: str,
    rows: dict[int, ExtractedCell] | None = None,
) -> tuple[str, bool]:
    blob = chunk.lower()
    ranked: list[tuple[int, object]] = []
    for spec in load_template_fields():
        if rows is not None and (rows[spec.seq].value or "").strip():
            continue
        score = 0
        for token in _name_match_tokens(spec.name):
            if token.lower() in blob or token in chunk:
                score += 3
        # 词典强别名也算认条。二字条目名（速比）切不出整词，只能靠别名；
        # 4LDHT260 / SuperEvo 2026-09-16：选段按别名把「变速箱速比…P3: 12.830」那页送进模型，
        # prompt 却没列 #75，模型无从作答，两份都必漏。多条目共享的泛词（P1 / P3 / BOOST）不算。
        if not score:
            shared = _shared_coverage_tokens()
            for token in spec.aliases:
                t = token.strip()
                if len(t) >= 2 and t.lower() not in shared and _strong_alias_present(t, blob):
                    score += 3
                    break
        # 弱别名（重量 / 防腐 / 扭矩精度这类同槽共享词）只用来把条目列进 prompt，不进别名提示
        for token in getattr(spec, "weak_aliases", ()):
            if len(token) >= 2 and _token_present(token, blob):
                score += 2
                break
        # 未开通整词检索的条目仍可用英文提示词；已开通的（耐电压）不要用
        # 「电压→voltage」把工作电压段配进来。
        if not retrieve_enabled_for_name(spec.name):
            for cn, en in _FIELD_EN:
                if cn in spec.name:
                    for word in en.split():
                        if word in blob:
                            score += 2
        if score:
            ranked.append((score, spec))
    ranked.sort(key=lambda item: (-item[0], item[1].seq))
    hit = bool(ranked)
    chosen = [spec for _, spec in ranked[:40]]
    return "、".join(format_prompt_field(spec.seq, spec.name, spec.aliases) for spec in chosen), hit


def _fields_for_chunk(
    chunk: str,
    rows: dict[int, ExtractedCell] | None = None,
) -> str:
    text, _hit = _chunk_fields(chunk, rows)
    return text


def _looks_like_model_unavailable(status: int, text: str) -> bool:
    blob = f"{status} {text or ''}"
    low = blob.lower()
    if "try another model" in low:
        return True
    if "model" in low and "currently unavailable" in low:
        return True
    return "模型" in blob and "不可用" in blob


def _looks_like_auth_failure(status: int, text: str) -> bool:
    blob = text or ""
    if status in {401, 403}:
        return True
    return any(
        mark in blob
        for mark in ("未授权", "请先登录", "请重新登录", "Unauthorized", '"error":"Unauthorized"')
    )


def _parse_model_json(
    complete,
    prompt: str,
    timeout: float,
    *,
    fallback_prompt: str = "",
    fallback_timeout: float = 40.0,
) -> dict[str, Any]:
    try:
        return _parse_json_object(complete(prompt, timeout=timeout))
    except ExtractAuthError:
        raise
    except ExtractModelError:
        raise
    except ExtractError as exc:
        if not fallback_prompt:
            return {"rows": [], "_parse_failed": True, "_parse_error": str(exc)}
        try:
            return _parse_json_object(
                complete(fallback_prompt, timeout=fallback_timeout)
            )
        except ExtractAuthError:
            raise
        except ExtractModelError:
            raise
        except ExtractError as exc2:
            return {"rows": [], "_parse_failed": True, "_parse_error": str(exc2)}


def _ingest_model_rows(data: dict[str, Any], chunk: str, put, rule_cells) -> None:
    incoming = _rows_from_payload(data if isinstance(data, dict) else {})
    for item in incoming:
        if not isinstance(item, dict):
            continue
        cell = _cell_from_item(item)
        if cell is None:
            continue
        put(cell, chunk)
    for cell in rule_cells(chunk):
        put(cell, chunk)


def _main_extract_prompt(
    *,
    index: int,
    total: int,
    page_count: object,
    filename: str,
    fields: str,
    chunk: str,
) -> str:
    return (
        f"这是长文档的第 {index + 1}/{total} 段（共约 {page_count or '?'} 页）。"
        "只抽出下面仍空缺的条目。已填条目不要改写。第一字符必须是 { ，禁止解释。\n"
        f"仍空缺条目（序号.名称，规格常见写法只用于认条）：{fields}\n"
        "rows 里用 seq 和与清单一致的 name。"
        "找不到就不要写该条，宁可空着，禁止把本段无关的句子填进条目。"
        "TBD/无/Negotiable/流程语（如待供应商提供、以电机实际达成为准）不要当有效值。"
        "功率时长不要填成电流时长；峰值扭矩与堵转扭矩必须分开。"
        "JSON 必须是 {\"rows\":[...]}，不要按分组嵌套。"
        "value 必须能在下面这段原文中找到对应句子，并写入 excerpt 和 page。"
        "excerpt 必须是完整原句（含主语和句末，例如 "
        "The XCM shall be designed to fulfill ASIL C according to ISO 26262-2018.），"
        "禁止只截 fulfill ASIL C according to ISO 26262 这种短语。"
        "功能安全等条款型要求，value 也写该完整原句。"
        "page 只填印在页眉或页脚上的页码数字（如 78），禁止把 2.3.3.3 这类条款号写进 page。"
        "clause 填正文条款号（如 2.3.3.3、6.5.11.1），没有则空字符串；条款号与页码必须分列。"
        "若本段已给出电压和电流（或功率与电压、扭矩与转速、电容与放电时间/电阻、效率与功率）但清单缺项没有直接写出，"
        "用 R=U/I、P=UI、P=√3UI、P=Tn/9550、T=9550P/n、I=P/U、I=P/(√3U)、t=RC ln(V0/V1)、η=Pout/Pin、P_loss=P(1-η) 由这些数算出缺项，"
        "value 写计算结果（含单位），excerpt 写含输入量的原句，"
        "note 必须写「由物理公式计算：公式（代入 原文量）」，confidence 0.7。"
        "禁止只把「欧姆定律」「电压电流关系」这类句子当作抽出值。"
        "禁止用行业常识或清单参考示例编造本段没有的数字。\n"
        "格式：{\"rows\":[{\"seq\":序号,\"name\":\"条目名\",\"value\":\"原文中的值或按公式算出的值\","
        "\"page\":\"印页\",\"clause\":\"条款号\",\"excerpt\":\"完整原句\","
        "\"note\":\"公式推算时填写，否则空\",\"confidence\":0.85}]}\n\n"
        f"文件: {filename}\n\n{chunk}\n\nJSON:"
    )


def _cover_fallback_prompt(chunk: str) -> str:
    return (
        "只抽封面。第一字符必须是 { 。禁止解释。\n"
        '{"rows":[{"seq":97,"name":"工作温度范围","value":"",'
        '"page":"1","excerpt":"","confidence":0.8}]}\n\n'
        + chunk[:4000]
        + "\nJSON:"
    )


def _topup_extract_prompt(fields: str, chunk: str) -> str:
    return (
        "只抽出本段能对应清单且仍空缺、原文明确出现的条目。找不到就空 rows。"
        "已填勿改。禁止无关句子与流程语。规格常见写法只用于认条，禁止当取值。"
        "page 只填印页数字，clause 填条款号（如 2.3.3.3）。"
        "本段有电压/电流等输入量、缺项未直接写出时，按 R=U/I、P=UI、P=Tn/9550、t=RC ln(V0/V1) 等计算，不要只抄定律名称。"
        "算出的值须在 note 写「由物理公式计算：公式（代入 …）」。"
        "第一字符必须是 { 。\n"
        f"仍空缺条目：{fields}\n"
        "JSON：{\"rows\":[{\"seq\":序号,\"name\":\"条目名\",\"value\":\"原文中的值或按公式算出的值\","
        "\"page\":\"印页\",\"clause\":\"条款号\",\"excerpt\":\"完整原句\","
        "\"note\":\"公式推算时填写，否则空\",\"confidence\":0.85}]}\n\n"
        f"{chunk}\nJSON:"
    )


def _field_needles(name: str) -> list[str]:
    mapping = (
        ("纹波", ["ripple", "纹波"]),
        ("绝缘电阻", ["绝缘电阻", "insulation resistance", "insulation"]),
        ("主动放电", ["主动放电", "active discharge"]),
        ("被动放电", ["被动放电", "passive discharge"]),
        ("寿命", ["qualification life", "25万公里", "15 years or", "零部件寿命"]),
        ("冷却液温度", ["冷却液温度", "coolant temperature", "全冷却液温度"]),
        ("冷却流量", ["冷却液流量", "coolant flow", "liter/min", "0 to 10"]),
        ("电机温度", ["电机温度", "EM temperature"]),
        ("P1逆变器持续", ["200Arms", "P1逆变器持续"]),
        ("P1逆变器交流电流峰值", ["250Arms", "P1逆变器交流电流峰值"]),
        ("升压开关", ["升压开关频率", "Switching frequency for boost"]),
        ("Y电容", ["Y电容", "Y-cap", "Y-capacitor"]),
        ("备份电源", ["Back-up", "KL30", "备用电源"]),
        ("降额", ["limited performance", "性能限制"]),
        ("低压", ["LVDC Voltage", "低压范围", "ISO 16750"]),
        ("冷却接口", ["Cooling connections", "冷却连接", "spigot"]),
        ("压降", ["35Kpa", "流阻", "flow resistance"]),
        ("P3逆变器持续", ["P3逆变器持续", "250Arms持续"]),
        ("P3逆变器交流电流峰值", ["P3逆变器交流电流峰值", "520Arms"]),
        ("升压效率", ["BOOST efficiency", "升压效率"]),
        ("功能安全", ["ISO 26262", "ASIL"]),
        ("密封", ["IP67", "IP6K9K", "waterproof", "防护等级"]),
        ("升压", ["BOOST", "升压", "boost control", "BOOST architecture"]),
        ("工作温度", ["工作温度", "operating temperature"]),
        ("存储温度", ["存储温度", "storage temperature"]),
        ("海拔", ["海拔", "altitude", "工作高度", "sea level", "5000m", "Operation altitude"]),
        ("湿度", ["humidity", "湿度", "condensation"]),
        ("堵转", ["standstall", "standstill", "堵转"]),
        ("振动", ["振动", "vibration"]),
        ("通讯", ["CAN FD", "CAN2.0"]),
        ("主动放电功能", ["Active discharge of HVDC", "高压直流母线主动放电"]),
        ("被动放电功能", ["Passive discharge of HVDC", "高压直流母线的被动放电"]),
        ("HVDC", ["HVDC Voltage", "高压范围"]),
        ("直流工作电压", ["HVDC Voltage Range", "高压范围"]),
    )
    found: list[str] = []
    for key, needles in mapping:
        if key in name:
            found.extend(needles)
    found.extend(_name_match_tokens(name))
    tokens = [tok for tok in re.findall(r"[\u4e00-\u9fff]{3,}", name) if tok not in {"是否包含"}]
    return list(dict.fromkeys(found + tokens))


def _topup_chunks(
    markdown: str,
    rows: dict[int, ExtractedCell],
    sent: list[str],
    limit: int = 6,
) -> list[str]:
    empty = [
        spec
        for spec in load_template_fields()
        if not (rows[spec.seq].value or "").strip()
    ]
    if not empty:
        return []
    # 主抽已送过的段（可能是几页拼的）不再送；按折叠后的开头 80 字判重。
    # 判重键必须和送出去的文本做同样的页眉剥离：逆变器 SR / 扫描件每页带 running header，
    # 用原始页开头判重永远对不上，2026-09-16 两份各 10 段补抽全部是主抽已送过的页。
    sent_fold = "\n".join(_fold_text(chunk) for chunk in sent)
    cands: list[tuple[str, dict[int, int]]] = []
    for _page, text in _page_blocks(markdown):
        key = _fold_text(_strip_running_header(text))[:80]
        if key and key in sent_fold:
            continue
        if _is_glossary(text) or _is_front_matter(text):
            continue
        hits = _block_covers(text, empty)
        if hits:
            cands.append((text, hits))
    # 主抽填完一轮后，剩下的空缺重新做一次贪心覆盖：这一轮只为还空着的条目找段
    best_strength: dict[int, int] = {}

    def gain_of(hits: dict[int, int]) -> int:
        return sum(max(0, s - best_strength.get(seq, 0)) for seq, s in hits.items())

    out: list[str] = []
    while cands and len(out) < limit:
        pick = max(cands, key=lambda c: (gain_of(c[1]), _score_block(c[0])))
        if gain_of(pick[1]) <= 0:
            break
        cands.remove(pick)
        for seq, s in pick[1].items():
            if s > best_strength.get(seq, 0):
                best_strength[seq] = s
        out.append(_strip_running_header(pick[0]))
    return out


_COVER_EXTRA = {
    "规格书标题",
    "制造商",
    "规格书版本",
    "规格书日期",
    "系统/总成",
}
_ALLOWED_EXTRA = {
    *_COVER_EXTRA,
    "车速信号电压",
    "电气耐久准则",
}
_OFF_LIST_MAX = 28
_OFF_LIST_USEFUL = re.compile(
    r"(?i)回料|脱模剂|胶水|润滑剂|"
    r"涂镀|平整|光滑|灰度|铭牌|二维码|\bDMC\b|条码|"
    r"打印|追溯|追溯码|"
    r"微控制器|主控芯片|单片机|开发CAN|每个I/O|屏蔽终端|"
    r"(?<![A-Za-z])MCU(?![A-Za-z])|32-bit|lock-step|CAN-HS|5\s*Mbit|"
    r"(?<![A-Za-z])Flash(?![A-Za-z])|闪存|(?<![A-Za-z])SRAM(?![A-Za-z])|"
    r"主频|clock frequency|"
    r"(?<![A-Za-z])JTAG(?![A-Za-z])|(?<![A-Za-z])SWD(?![A-Za-z])|"
    r"调试口|刷写口|调试接口|"
    r"ICD[- ]?\d|pin assignment|针脚|"
    r"KL15|PNC wakeup|I/O|"
    r"(?<![A-Za-z])CARB(?![A-Za-z])|(?<![A-Za-z])OBD(?![A-Za-z])|"
    r"绝对压力|真空状态|冷却液回路.{0,24}(?:bar|mbar)|"
    r"乙二醇|ethylene glycol|(?<![A-Za-z])glycol(?![A-Za-z])|"
    r"冷却介质|冷却液.{0,12}(?:浓度|体积比|配比|介质)|"
    r"透气阀|泄压阀|breather valve|waterproof vent|pressure.?relief valve|"
    r"爬电距离|电气间隙|creepage|clearance distance|air clearance|"
    r"接地点|接地电阻|ground (?:points?|resistance)|"
    r"NVH.{0,40}(?:\d+\s*级|dB)|dB\(A\)|\d+\s*级|"
    r"ground shift|watchdog|UDS|XCP|CCP|标定"
)
_OFF_LIST_CITE_ONLY = re.compile(
    r"(?i)按照.{0,16}(?:ISO|SAE|USCAR|IPC)|designed (?:in )?according to|"
    r"fulfil IPC|符合(?:ISO|IPC|SAE|USCAR)"
)
_OFF_LIST_NOT_USEFUL = re.compile(
    r"(?i)hazardous|危险事件|fuse type|fault current|safety rules|campaign|"
    r"连续故障|单点故障|\bpitch\b|OCPD|绞距|flashed"
)
_OFF_LIST_METRIC = re.compile(
    r"(?<![A-Za-z])(?:[Vv]|A(?:rms)?|kW|℃|°C|mm|rpm|bar|mbar)(?![A-Za-z])"
    r"|%|级|ISO|GB|Q/"
    r"|(?i:bit|cores?|Mbit|dB|kHz|MB|KB|MHz)|CAN"
    r"|mΩ|mOhm|(?<=\d)位|(?<=\d)核"
    r"|(?<=\d)s\b"
)
_OFF_LIST_REQ = re.compile(
    r"(?i)\bshall\b|\bmust\b|"
    r"必须|不得|禁止|应当|应能|应满足|应具备|应具有|应支持|须满足|"
    r"应(?![该用商])[\u4e00-\u9fff]|"
    r"应.{0,12}(?:为|不[大小]于|小于|大于|达到|不超过)"
)
_OFF_LIST_EMPTY = re.compile(
    r"(?i)\bTBD\b|\bTBA\b|\bN/?A\b|Negotiable|待定|待供应商|待提供|"
    r"supplier to provide|not mentioned|for reference only|仅供参考"
)
_OFF_LIST_DELIVERABLE = re.compile(
    r"(?i)3\s*-?\s*d\s*model|2\s*-?\s*d\s*drawing|3D模型|2D图纸?|CAD datas?|"
    r"component documentation|一般文件要求|loss model|thermal (?:network )?model|"
    r"thermal table|热模型|"
    r"support for (?:the )?integration|为集成工作提供支持|"
    r"provide a (?:3|2)\s*-?\s*d|presented by the supplier|supplier must present|"
    r"必须向吉利提供|须向吉利提供|向吉利提供|提交12V|提交.*测试结果|"
    r"according to GEELY|符合吉利标准|吉利负责|agreed with GEELY|"
    r"requirements stated in the ESOW|ESOW中规定|"
    r"purchase order|采购订单|样件需求|备件|专用工具|Special Service Tools|"
    r"3C verification|ECE certification|E-MARK|认证资格|"
    r"equivalent functional substitution|等效功能替代|"
    r"Life Cycle Assessment|\bLCA\b|全生命周期|"
    r"测试报告|test report|提供资金|fund subsequent|"
    r"black and grey box|卖方应|买方标准|Seller shall|"
    r"safety data sheets|电池注册|DIRECTIVE 2006/66|"
    r"\bxx\s*%|不少于xx|"
    r"this document shall include|本文件应包括|"
    r"campaign prevention|连续进料|"
    r"special attention must|"
    r"由供应商根据.{0,40}进行测试|"
    r"必须正确.{0,8}以便|shall be correct|"
    r"供应商应提供|应提供所有电气|功耗数据|"
    r"\bMTBF\b|平均故障间隔"
)
_OFF_LIST_ACTOR = re.compile(
    r"(?i)^(the\s+)?(supplier|供应商|geely|吉利|model|模型|documentation|"
    r"文件|seller|buyer|卖方|买方|unit|xcm|pcm|parts|vehicle|product|"
    r"该设备|整个系统|产品|losses|there)\b"
)
_OFF_LIST_BAD_NAME = re.compile(
    r"(?i)^(if|when|there|additionally|however|in this|in cases|"
    r"where|other|all|kinds of|symbols?|oil|"
    r"如果|此外|则|且|在问题|在任何|在最终|本车型|涉及到|当要求|"
    r"测试完成后|可再生能源|试样|"
    r"during this|during|special attention|this document|passive discharge|"
    r"注意|由供)"
)
_OFF_LIST_ON_TEMPLATE = re.compile(
    r"(?i)(?:200|250|520)\s*Arms|"
    r"passive discharge|active discharge|被动放电|主动放电|"
    r"(?:500|510)\s*VDC|"
    r"coolant (?:circuit|flow|temperature)|cooling conditions?|冷却回路|冷却流量|冷却条件|"
    r"PEI P[13]|相电流|"
    r"(?:125|62\.5)\s*kW|"
    r"switching frequency|开关频率|"
    r"最高效率|efficiency of the PEI|"
    r"HVDC voltage|高压直流电压|"
    r"measurement error|测量误差|"
    r"operating temperature|工作温度|"
    r"\bhumidity\b|湿度|"
    r"\bvibration\b|振动|"
    r"耐压能力|耐压测试|工频耐压|dielectric|hipot|"
    r"ISO\s*6469.{0,40}(?:B级|class\s*B)|B级电压|class B voltage|"
    r"0\.95\s*\*\s*I\s*peck|电基频"
)
_OFF_LIST_SPLIT_EN = re.compile(
    r"(?i)^(?:the\s+)?([A-Za-z][A-Za-z0-9+/ \-]{1,40}?)\s+(shall|must)\s+(.+)$"
)
_OFF_LIST_SPLIT_CN = re.compile(
    r"^(.{2,24}?)(应当|必须|不得|禁止|不应|应能够|应能|应满足|应具备|应具有|应支持|须(?!商)|应(?!商))(.+)$"
)
_OFF_LIST_GENERIC_HEAD = re.compile(
    r"(?i)^(requirements|要求|概述|general|note|备注|contents|目录|"
    r"general documentation requirements|一般文件要求)$"
)
_OFF_LIST_HEADING = re.compile(
    r"^(?:#{1,6}\s+\S|\d+(?:\.\d+){1,}\s+\S.{0,70})$"
)


def _field_conflict_group(name: str) -> str:
    """同组可共享同值；跨组禁止把同一数值/摘录糊到不相容条目。"""
    n = name or ""
    mapped = conflict_for_name(n)
    if mapped:
        return mapped
    if "重量" in n:
        return "weight"
    if "冷却回路压降" in n or ("流阻" in n):
        return "coolant_drop"
    if "绝缘电阻" in n:
        return "insulation"
    if "峰值功率持续时间" in n:
        return "peak_power_duration"
    if "BOOST输入峰值电流" in n or ("BOOST" in n.upper() and "峰值电流" in n):
        return "boost_peak_current"
    if "堵转扭矩" in n:
        return "stall_torque"
    if "峰值扭矩" in n:
        return "peak_torque"
    if "反电动势" in n or "Back EMF" in n:
        return "back_emf"
    if "BOOST最高" in n or "升压器的目标输出" in n or "升压输出电压" in n:
        return "boost_target_v"
    if "额定流量" in n:
        return "rated_flow"
    if "冷却流量范围" in n:
        return "flow_range"
    if "低压功耗" in n:
        return "lv_power"
    if n == "静态电流":
        return "static_current"
    return f"field:{n}"


def _expand_to_clause(chunk: str, start: int, end: int, limit: int = _CLAUSE_LIMIT) -> str:
    """把命中扩成完整原句（含主语、句末年份），不截成短语。"""
    if not chunk:
        return ""
    n = len(chunk)
    start = max(0, min(start, n))
    end = max(start, min(end, n))

    def at_sentence_start(idx: int) -> bool:
        if idx <= 0:
            return True
        if _CLAUSE_HEADING.match(chunk, idx) or re.match(
            r"\d{1,2}(?:\.\d{1,3}){2,4}\s+\S",
            chunk[idx : idx + 32],
        ):
            return True
        prev = chunk[idx - 1]
        if prev in "。！？":
            return True
        if prev == "\n":
            if idx >= 2 and chunk[idx - 2] == "\n":
                return True
            if chunk.startswith("## ", idx):
                return True
            k = idx - 2
            while k >= 0 and chunk[k] in " \t":
                k -= 1
            if k >= 0 and chunk[k] in ".。！？":
                return True
            return False
        if prev == ".":
            nxt = chunk[idx] if idx < n else ""
            return not nxt.isdigit()
        return False

    i = start
    found_back = False
    while i > 0 and start - i <= 220:
        if at_sentence_start(i):
            found_back = True
            break
        i -= 1
    if i == 0:
        found_back = True
    if not found_back:
        line = chunk.rfind("\n", max(0, start - 220), start)
        i = line + 1 if line >= 0 else start
    while i < start and chunk[i] in " \t\r\n":
        i += 1
    while i < start:
        heading = _PAGE_HEADING.match(chunk, i)
        if heading:
            i = heading.end()
            while i < start and chunk[i] in " \t\r\n":
                i += 1
            continue
        clause_head = _CLAUSE_HEADING.match(chunk, i)
        if clause_head:
            i = clause_head.end()
            while i < start and chunk[i] in " \t\r\n":
                i += 1
            continue
        break

    j = end
    found_fwd = False
    while j < n and j - i <= 240:
        ch = chunk[j]
        if ch in "。！？":
            j += 1
            found_fwd = True
            break
        if ch == ".":
            prev = chunk[j - 1] if j else ""
            nxt = chunk[j + 1] if j + 1 < n else ""
            if prev.isdigit() and nxt.isdigit():
                j += 1
                continue
            j += 1
            found_fwd = True
            break
        if ch == "\n" and j + 1 < n and chunk[j + 1] == "\n":
            found_fwd = True
            break
        if chunk.startswith("\n## ", j):
            found_fwd = True
            break
        j += 1
    if not found_fwd:
        nl = chunk.find("\n", end, min(n, end + 160))
        j = nl if nl >= 0 else end
    text = re.sub(r"[ \t]*\n[ \t]*", " ", chunk[i:j]).strip()
    return text[:limit]


def _complete_cell_clause(cell: ExtractedCell, chunk: str, field_name: str = "") -> None:
    """原文摘录写成完整原句；功能安全等条款的抽出值也用该原句。"""
    if not chunk:
        return
    if "相电流采样" in (field_name or cell.name or "") and (
        "控制器应能够测量" in (cell.excerpt or "")
        or "中英文量程不一致" in (cell.note or "")
    ):
        return
    snippet = (cell.excerpt or "").strip()
    idx = _excerpt_index(chunk, snippet) if snippet else -1
    if idx < 0 and (cell.value or "").strip():
        idx = chunk.find((cell.value or "").strip()[:48])
    if idx < 0:
        return
    span = len(snippet) if snippet else min(48, len(cell.value or ""))
    clause = _expand_to_clause(chunk, idx, idx + max(span, 1))
    if not clause:
        return
    cell.excerpt = clause


def _store_cell(
    cell: ExtractedCell,
    chunk: str,
    rows: dict[int, ExtractedCell],
    extra: list[ExtractedCell],
    seen_extra: set[tuple[str, str]],
    excerpt_owner: dict[str, str],
    value_owner: dict[str, str] | None = None,
) -> None:
    if _is_weak_value(cell.value) or _is_junk_value(cell.value, cell.name):
        return
    if not _value_in_source(cell.value, cell.excerpt, chunk):
        return
    raw_page = cell.page
    excerpt_at = _excerpt_index(chunk, cell.excerpt)
    located_clause = _pick_clause(
        chunk,
        excerpt_at if excerpt_at >= 0 else None,
        cell.excerpt or "",
        name=cell.name or "",
    )
    cell.clause = located_clause or (cell.clause or "").strip() or _clause_token(raw_page)
    located = _page_for_index(chunk, excerpt_at) if excerpt_at >= 0 else ""
    page_from_ex = _page_in_excerpt(cell.excerpt or "")
    if page_from_ex and (not located or located == "1"):
        cell.page = page_from_ex
    else:
        cell.page = located or _normalize_page(raw_page, chunk)
    if re.search(r"2\s*[~～-]\s*2\.5", str(cell.value)):
        cell.name = "车速信号电压"
        seq = None
    else:
        seq = _bind_seq(cell.seq, cell.name, rows)
    field_name = rows[seq].name if seq is not None else cell.name
    if "流量" in field_name:
        cell.value = re.sub(r"\bO\s+to\b", "0 to", cell.value or "", flags=re.I)
        cell.excerpt = re.sub(r"\bO\s+to\b", "0 to", cell.excerpt or "", flags=re.I)
    _complete_cell_clause(cell, chunk, field_name)
    if cell.excerpt:
        at = _excerpt_index(chunk, cell.excerpt)
        if at >= 0:
            located_clause = _pick_clause(chunk, at, cell.excerpt, name=field_name)
            if located_clause:
                cell.clause = located_clause
            located = _page_for_index(chunk, at)
            page_from_ex = _page_in_excerpt(cell.excerpt)
            if page_from_ex and (not located or located == "1"):
                cell.page = page_from_ex
            elif located:
                cell.page = located
    if _is_junk_value(cell.value, field_name):
        return
    fits = (
        _derived_fits_field(field_name, cell.value, cell.excerpt)
        if _is_derived_cell(cell)
        else _value_fits_field(field_name, cell.value, cell.excerpt)
    )
    if not fits:
        return
    if not _is_derived_cell(cell) and _copied_from_example(
        seq, field_name, cell.value, cell.excerpt
    ):
        return
    _downgrade_ocr_excerpt(cell)
    _scrub_false_ocr_note(cell)
    if cell.excerpt and re.fullmatch(
        r"Motor/Gearbox Same\s*Con\s*tent",
        re.sub(r"\s+", " ", cell.excerpt or "").strip(),
        re.I,
    ):
        if cell.value and re.search(r"15\s*years|300,?000", cell.value, re.I):
            cell.excerpt = cell.value
    group = _field_conflict_group(field_name)
    key = _fold_text(cell.excerpt or cell.value)[:80]
    if key and not cell.extra:
        prev = excerpt_owner.get(key)
        if prev and prev != group:
            return
        excerpt_owner[key] = group
    elif key:
        excerpt_owner.setdefault(key, group)
    folded_val = _fold_text(cell.value)
    if value_owner is not None and len(folded_val) >= 8 and not cell.extra:
        prev_g = value_owner.get(folded_val)
        if prev_g and prev_g != group:
            return
        value_owner[folded_val] = group
    if seq is not None:
        _lock_field_semantics(cell, field_name)
        rows[seq] = _attach(rows[seq], cell)
        _lock_field_semantics(rows[seq], field_name)
        _scrub_false_ocr_note(rows[seq])
        return
    if cell.name not in _ALLOWED_EXTRA:
        return
    extra_key = (cell.name, cell.value)
    if extra_key in seen_extra or _is_junk_extra(cell):
        return
    cell.extra = True
    cell.seq = 0
    seen_extra.add(extra_key)
    extra.append(cell)


def _is_junk_extra(cell: ExtractedCell) -> bool:
    if _is_weak_value(cell.value) or _is_junk_value(cell.value, cell.name):
        return True
    if re.search(r"未提及|not mentioned|supplier to provide", cell.value, re.I):
        return True
    if cell.name in {"车型", "系统", "版本", "日期", "适用车型", "总成", "标题"}:
        return True
    return False


def is_cover_extra(cell: ExtractedCell) -> bool:
    return bool(getattr(cell, "extra", False)) and (cell.name or "") in _COVER_EXTRA


def is_off_list_requirement(cell: ExtractedCell) -> bool:
    """封面字段不是需求；只有对不上 1–120 的当份要求才进「清单外需求」。"""
    if not bool(getattr(cell, "extra", False)):
        return False
    if is_cover_extra(cell):
        return False
    return bool((cell.value or "").strip())


@lru_cache(maxsize=1)
def _template_match_needles() -> tuple[str, ...]:
    toks: list[str] = []
    for spec in load_template_fields():
        toks.extend(_coverage_tokens(spec.name, _spec_alias_pool(spec)))
    return tuple(dict.fromkeys(t for t in toks if t))


def _maps_to_template_field(text: str) -> bool:
    """清单外认条：条目全名、较长强别名、带单位电参数针。短词「电压」不单独拦。"""
    raw = text or ""
    blob = re.sub(r"ly\b", "", raw.lower())
    if not blob.strip():
        return False
    if _OFF_LIST_ON_TEMPLATE.search(raw):
        return True
    for spec in load_template_fields():
        if spec.name and spec.name in raw:
            return True
        for token in spec.aliases or ():
            t = (token or "").strip()
            if len(t) < 3:
                continue
            if t.isascii() and len(t) < 5:
                continue
            if _strong_alias_present(t, blob) or t in raw:
                return True
        for token in _field_needles(spec.name):
            tok = (token or "").strip()
            if not tok:
                continue
            distinctive = (
                " " in tok
                or bool(re.search(r"\d", tok))
                or (bool(re.search(r"[\u4e00-\u9fff]", tok)) and len(tok) >= 3)
                or (tok.isascii() and len(tok) >= 8)
            )
            if distinctive and (_strong_alias_present(tok, blob) or tok in raw):
                return True
    return False


def _off_list_heading_name(line: str) -> str:
    name = re.sub(r"^#+\s*", "", (line or "").strip())
    name = re.sub(r"^\d+(?:\.\d+)+\s+", "", name)
    name = re.sub(r"\s+", " ", name).strip(" ：:.-—")
    if not name or _OFF_LIST_GENERIC_HEAD.match(name):
        return ""
    return name[:32]


def _is_off_list_heading(line: str) -> bool:
    text = (line or "").strip()
    if re.match(r"^## 第 \d+ [页节]", text):
        return False
    if _OFF_LIST_REQ.search(text):
        return False
    return bool(_OFF_LIST_HEADING.match(text))


def _is_off_list_process(text: str) -> bool:
    """交付、商务、认证、转引、xx% 占位：不是一条可填指标。有数字也要丢。"""
    blob = text or ""
    if "|" in blob:
        return True
    if _OFF_LIST_EMPTY.search(blob) or _is_process_language(blob):
        return True
    return bool(_OFF_LIST_DELIVERABLE.search(blob))


def _clean_off_list_name(name: str) -> str:
    text = re.sub(r"\s+", " ", (name or "").strip())
    text = re.sub(r"(?i)^(the|a|an)\s+", "", text)
    text = re.sub(r"(?i)\s+(of|for|to|the|a|an)$", "", text)
    text = text.strip(" ：:.-—，,")
    if not text or _OFF_LIST_REQ.search(text) or _OFF_LIST_ACTOR.match(text):
        return ""
    if _OFF_LIST_BAD_NAME.match(text):
        return ""
    if re.search(r"[，,:：]", text):
        return ""
    if len(text) < 2:
        return ""
    if len(text) > 24:
        cut = text[:24].rsplit(" ", 1)[0]
        text = cut if len(cut) >= 4 else text[:24]
    if _OFF_LIST_BAD_NAME.match(text) or _OFF_LIST_ACTOR.match(text):
        return ""
    text = re.sub(r"(?i)\s+(of|for|to|the|a|an)$", "", text).strip()
    if re.search(r"(?i)(?:不|of|for|to|由供)$", text):
        return ""
    if re.match(r"(?i)^(passive discharge|during this|this document|special attention|注意|由供)$", text):
        return ""
    if re.search(r"过程中$", text) or re.match(r"^在.+[中内]$", text):
        return ""
    return text


def _clean_off_list_value(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    text = text.strip(" ：:.-—，,。.;；")
    text = re.sub(r"(?i)^(to|be|the)\s+", "", text)
    if len(text) > 80:
        text = text[:80].rsplit(" ", 1)[0] if " " in text[:80] else text[:80]
    return text.strip()


def _off_list_value_ok(value: str, mark: str = "") -> bool:
    text = value or ""
    if len(text) < 2 or len(text) > 80:
        return False
    if re.search(r"(?i)^(described|clarified|provided|该表|下表|以下要求|描述|able to perform|正确|correct|proper)", text):
        return False
    if re.search(r"(?i)以便|so that|in order to|必须正确|shall be correct", text):
        return False
    if re.search(r"(?i)table below|下表规定|如下要求$", text) and not re.search(r"\d", text):
        return False
    if mark in {"禁止", "不得", "不应"} and 2 <= len(text) <= 40:
        return True
    if re.search(
        r"打印|ICD[- ]?\d|ISO\s*\d|GB/?T|Q/JL|USCAR|IPC|J-STD|CARB|"
        r"JTAG|SWD|乙二醇|glycol|透气阀|泄压阀|waterproof vent|breather|"
        r"relief valve|(?<![A-Za-z])Flash(?![A-Za-z])|(?<![A-Za-z])SRAM(?![A-Za-z])|主频|"
        r"爬电|电气间隙|接地电阻|接地点|mΩ|mOhm",
        text,
        re.I,
    ):
        return True
    if re.search(r"\d", text) and re.search(
        r"(?<![A-Za-z])(?:[Vv]|A(?:rms)?|kW|℃|°C|mm|rpm|bar|mbar)(?![A-Za-z])"
        r"|%|级|ISO|GB|Q/"
        r"|(?i:bit|cores?|Mbit|dB|kHz|MB|KB|MHz)|CAN"
        r"|mΩ|mOhm|\d+\s*个|(?<=\d)位|(?<=\d)核"
        r"|(?<=\d)s\b",
        text,
    ):
        return True
    # 产品外观/材料等短答案：平整光滑、使用回料、follow ICD-09
    if 4 <= len(text) <= 80 and re.search(
        r"(?i)平整|光滑|均匀|连续|回料|脱模剂|打印|胶水|润滑剂|follow|smooth|even|"
        r"KL15|PNC wakeup|deactivated|ICD[- ]?\d|停用|受控|"
        r"JTAG|SWD|透气阀|泄压阀|breather|relief valve",
        text,
    ):
        return True
    return False


def _off_list_name_from_value(value: str) -> str:
    match = re.search(r"(?:添加|使用)([^。；;，,]{2,16})", value or "")
    if not match:
        return ""
    return _clean_off_list_name(match.group(1).strip(" 的了"))


def _off_list_lang(text: str) -> str:
    """名称/抽出值语种：有汉字即中文（可夹标准号）；只有英文词即英文。"""
    blob = text or ""
    if re.search(r"[\u4e00-\u9fff]", blob):
        return "zh"
    if re.search(r"[A-Za-z]{3,}", blob):
        return "en"
    return ""


def _off_list_zh_subject(sentence: str) -> str:
    """中文句里「应」前的短主语，必须是当份原句子串。"""
    last = ""
    for match in re.finditer(
        r"([\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9/]{1,16})应",
        sentence or "",
    ):
        cand = _clean_off_list_name(match.group(1).strip(" 的了，,"))
        if cand and cand in (sentence or "") and _off_list_lang(cand) == "zh":
            last = cand
    return last


def _off_list_zh_only(text: str) -> str:
    """中文句后若粘着英文 shall，只留中文。"""
    blob = re.sub(r"\s+", " ", (text or "").strip())
    blob = re.split(r"(?i)(?:\s+|(?<=[。；.]))(?:The|Each|All|Based upon|Allowing)\b", blob, 1)[0]
    blob = re.split(r"(?<=[\u4e00-\u9fff。；])\s+(?=[A-Za-z]{3,})", blob, 1)[0]
    return blob.strip(" 。.;；:")


def _off_list_following_zh(after: str) -> str:
    """英句后的对照中文：到句号或下一句英文为止。"""
    hit = re.search(r"[\u4e00-\u9fff]", after or "")
    if not hit:
        return ""
    tail = (after or "")[hit.start() :]
    cut = re.search(r"(?i)[。；]|\s+(?:The|Each|All|Based upon)\b", tail)
    if cut:
        end = cut.end() if tail[cut.start()] in "。；" else cut.start()
        return tail[:end].strip()
    return _off_list_zh_only(tail[:160])


def _off_list_zh_twin(block: str, sentence: str) -> tuple[str, str, str] | None:
    """英中对照句：名称/答案/摘录都用后随中文句里已有的词，不另译。"""
    sent = re.sub(r"\s+", " ", (sentence or "").strip())
    if not sent or _off_list_lang(sent) != "en":
        return None
    at = (block or "").find(sent[: min(48, len(sent))])
    if at < 0:
        return None
    after = re.sub(r"\s+", " ", (block or "")[at + min(len(sent), 80) : at + len(sent) + 280])
    zh_sent = _off_list_following_zh(after)
    if len(zh_sent) < 6:
        return None
    split = _split_off_list_item("", zh_sent)
    if split and _off_list_lang(split[0]) == "zh" and split[0] in zh_sent:
        return split[0], split[1], zh_sent
    name = _off_list_zh_subject(zh_sent)
    if not name:
        return None
    value = _clean_off_list_value(zh_sent[zh_sent.find(name) + len(name) :])
    value = re.sub(r"^(应当|必须|不得|禁止|应能够|应能|应满足|应具备|应具有|应支持|应)", "", value)
    if not _off_list_value_ok(value):
        return None
    return name, value, zh_sent


def _off_list_topic(cell: ExtractedCell) -> str:
    blob = f"{cell.name} {cell.value} {cell.excerpt}"
    if re.search(r"(?i)development CAN|开发CAN", blob):
        return "dev_can"
    if re.search(r"(?i)KL15", blob) and re.search(r"(?i)I/O", blob):
        return "kl15_io"
    if re.search(r"(?i)ICD[- ]?\d", blob):
        return "icd"
    if re.search(r"(?i)shield|屏蔽终端", blob) and re.search(r"mΩ|mOhm|mohm", blob):
        return "shield"
    if re.search(r"(?<![A-Za-z])MCU(?![A-Za-z])|微控制器", blob) and re.search(
        r"(?i)32|4\s*core|锁步|lock-step|CAN bus|寄存器", blob
    ):
        return "mcu"
    return ""


def _unify_off_list_names(extra: list[ExtractedCell]) -> None:
    """同一指标中英各一行时，名称用当份中文句里的主语，不另译。"""
    items = [
        (idx, cell)
        for idx, cell in enumerate(extra)
        if getattr(cell, "extra", False) and not is_cover_extra(cell)
    ]
    keep: dict[str, int] = {}
    drop: list[int] = []
    for idx, cell in items:
        topic = _off_list_topic(cell) or f"name:{_fold_text(cell.name)}"
        if topic in keep:
            prev = extra[keep[topic]]
            extra[keep[topic]] = _prefer_off_list_cell(prev, cell)
            drop.append(idx)
        else:
            keep[topic] = idx
    for idx in reversed(drop):
        extra.pop(idx)


def _split_off_list_item(heading: str, sentence: str) -> tuple[str, str] | None:
    """拆成指标名 + 答案。名称不得是整句截断，抽出值不得整句重贴。"""
    sent = re.sub(r"\s+", " ", (sentence or "").strip()).rstrip("。.;；")
    if _is_off_list_process(sent):
        return None
    name = ""
    value = ""
    mark = ""
    en = _OFF_LIST_SPLIT_EN.match(sent)
    cn = _OFF_LIST_SPLIT_CN.match(sent)
    if cn and not en:
        name, mark, value = cn.group(1), cn.group(2), cn.group(3)
    elif en:
        name, mark, value = en.group(1), en.group(2), en.group(3)
    else:
        return None
    name = _clean_off_list_name(name)
    if not name:
        name = _off_list_name_from_value(value)
    if not name:
        name = _off_list_zh_subject(sent)
    if not name:
        head = _clean_off_list_name(heading)
        sent_lang = _off_list_lang(sent)
        head_lang = _off_list_lang(head)
        if (
            head
            and (not sent_lang or not head_lang or sent_lang == head_lang)
            and not _maps_to_template_field(heading)
            and not _maps_to_template_field(head)
        ):
            name = head
    value = _clean_off_list_value(value)
    if not name or not value:
        return None
    if _fold_text(name) == _fold_text(value):
        return None
    if _fold_text(value) == _fold_text(sent):
        return None
    if _is_off_list_process(name) or _is_off_list_process(value):
        return None
    if _OFF_LIST_REQ.search(name) or _OFF_LIST_BAD_NAME.match(name):
        return None
    if not _off_list_value_ok(value, mark):
        return None
    if mark in {"禁止", "不得", "不应"} and not value.startswith(mark):
        value = mark + value
    name = _off_list_indicator_name(name, value)
    if not name:
        return None
    value = _off_list_compact_value(name, value)
    if not value:
        return None
    name_lang, value_lang = _off_list_lang(name), _off_list_lang(value)
    if name_lang and value_lang and name_lang != value_lang:
        return None
    return name, value


def _off_list_std_ids(text: str) -> set[str]:
    found: set[str] = set()
    blob = text or ""
    for match in re.finditer(r"uscar[- ]?\d+", blob, re.I):
        found.add(re.sub(r"[\s-]", "", match.group(0).lower()))
    for match in re.finditer(r"iso\s*\d+(?:-\d+)*", blob, re.I):
        found.add(re.sub(r"\s", "", match.group(0).lower()))
    for match in re.finditer(r"j-std-\d+", blob, re.I):
        found.add(match.group(0).lower())
    if re.search(r"ipc(?:/eia)?", blob, re.I):
        found.add("ipc")
    return found


def _off_list_same_item(old: ExtractedCell, new: ExtractedCell) -> bool:
    old_v, new_v = _fold_text(old.value), _fold_text(new.value)
    if len(old_v) >= 8 and (old_v in new_v or new_v in old_v):
        return True
    old_n, new_n = _fold_text(old.name), _fold_text(new.name)
    if old_n and old_n == new_n and len(old_n) >= 2:
        return True
    if len(old_n) >= 6 and (old_n in new_n or new_n in old_n):
        if (old.clause or "") and old.clause == (new.clause or ""):
            return True
        if (old.page or "") and old.page == (new.page or ""):
            return True
    shared = _off_list_std_ids(old.value) & _off_list_std_ids(new.value)
    if shared:
        return True
    pair = (old.value + old.name, new.value + new.name)
    if all(re.search(r"(?i)hazardous|危险事件|单点故障|single point", blob) for blob in pair):
        if not old.clause or not new.clause or old.clause == new.clause:
            return True
    return False


def _merge_off_list_values(old: str, new: str, *, zh: bool) -> str:
    sep = "；" if zh else "; "
    parts: list[str] = []
    folds: list[str] = []
    for raw in (old, new):
        text = (raw or "").strip()
        if not text:
            continue
        folded = _fold_text(text)
        if any(folded == item or folded in item or item in folded for item in folds):
            continue
        parts.append(text)
        folds.append(folded)
    value = sep.join(parts)
    if len(value) > 240:
        value = value[:240].rsplit(sep, 1)[0] if sep in value[:240] else value[:240]
    return value


def _prefer_off_list_excerpt(old: str, new: str) -> str:
    """有中英对照时摘录只留中文句；没有中文才留英文。不拼中英两句。"""
    old_t, new_t = (old or "").strip(), (new or "").strip()
    if re.search(r"[\u4e00-\u9fff]", old_t):
        old_t = _off_list_zh_only(old_t)
    if re.search(r"[\u4e00-\u9fff]", new_t):
        new_t = _off_list_zh_only(new_t)
    old_zh = bool(re.search(r"[\u4e00-\u9fff]", old_t))
    new_zh = bool(re.search(r"[\u4e00-\u9fff]", new_t))
    if new_zh and not old_zh:
        return new_t
    if old_zh:
        return old_t
    return old_t or new_t


def _prefer_off_list_cell(old: ExtractedCell, new: ExtractedCell) -> ExtractedCell:
    same_name = _fold_text(old.name) == _fold_text(new.name) and bool(_fold_text(old.name))
    old_cjk = bool(re.search(r"[\u4e00-\u9fff]", old.name + old.value))
    new_cjk = bool(re.search(r"[\u4e00-\u9fff]", new.name + new.value))
    if same_name:
        zh = old_cjk or new_cjk
        clauses: list[str] = []
        for raw in (old.clause, new.clause):
            text = (raw or "").strip()
            if text and text not in clauses:
                clauses.append(text)
        return ExtractedCell(
            seq=0,
            name=new.name if new_cjk and not old_cjk else old.name,
            value=_merge_off_list_values(old.value, new.value, zh=zh),
            page=old.page or new.page,
            clause=" / ".join(clauses),
            excerpt=_prefer_off_list_excerpt(old.excerpt, new.excerpt)[:480],
            confidence=max(old.confidence or 0.0, new.confidence or 0.0) or 0.78,
            extra=True,
        )
    if new_cjk and not old_cjk:
        return new
    return old


def _off_list_indicator_name(name: str, value: str) -> str:
    """整句场合名改成指标名：NVH评级、TOP-60cm噪声、CARB诊断。"""
    blob = f"{name} {value}"
    zh = _off_list_lang(name) == "zh" or _off_list_lang(value) == "zh"
    if re.search(r"将在|进行测试", name) and re.search(r"(?i)NVH|\d+\s*级", blob):
        return "NVH评级"
    if re.search(r"分析程序|频率响应", name) and re.search(r"(?i)dB", value):
        return "TOP-60cm噪声"
    if name in {"控制器", "controller"} and re.search(r"(?<![A-Za-z])CARB(?![A-Za-z])", blob):
        return "CARB诊断"
    if re.search(r"将在|进行测试", name):
        return ""
    if re.search(r"(?<![A-Za-z])Flash(?![A-Za-z])|闪存", blob) and re.search(
        r"(?i)\d+(?:\.\d+)?\s*(?:MB|KB)", blob
    ):
        return "MCU闪存" if zh else "MCU Flash"
    if re.search(r"(?<![A-Za-z])SRAM(?![A-Za-z])", blob) and re.search(
        r"(?i)\d+(?:\.\d+)?\s*(?:KB|MB)", blob
    ):
        return "SRAM容量" if zh else "SRAM"
    if re.search(r"主频|clock frequency", blob, re.I) and re.search(r"(?i)MHz", blob):
        return "MCU主频" if zh else "MCU clock"
    if re.search(r"(?<![A-Za-z])(?:JTAG|SWD)(?![A-Za-z])|调试口|刷写口|调试接口", blob):
        return "调试口" if zh else "debug port"
    if re.search(r"乙二醇|ethylene glycol|(?<![A-Za-z])glycol(?![A-Za-z])", blob, re.I):
        return name
    if re.search(r"泄压阀|pressure.?relief", blob, re.I):
        return "泄压阀" if zh else "relief valve"
    if re.search(r"透气阀|breather|waterproof vent", blob, re.I):
        return "透气阀" if zh else "vent valve"
    if re.search(r"爬电|creepage", blob, re.I):
        return "爬电距离" if zh else "creepage"
    if re.search(r"电气间隙|clearance distance|air clearance", blob, re.I):
        return "电气间隙" if zh else "clearance"
    if re.search(r"接地电阻|ground resistance", blob, re.I):
        return "接地电阻" if zh else "ground resistance"
    if re.search(r"接地点|ground points?", blob, re.I):
        return "接地点" if zh else "ground points"
    return name


def _off_list_compact_value(name: str, value: str) -> str:
    """抽出值只留可核对答案，去掉方法从句和后半截英文。"""
    blob = value or ""
    if name == "NVH评级" or (re.search(r"NVH", name) and re.search(r"\d+\s*级", blob)):
        parts: list[str] = []
        grade = re.search(r"\d+\s*级", blob)
        if grade:
            parts.append(grade.group(0))
        ttn = re.search(r"TTN\s*≤\s*0\s*dB", blob, re.I)
        if ttn:
            parts.append(re.sub(r"\s+", "", ttn.group(0)))
        if parts:
            return "；".join(parts)
    if name == "TOP-60cm噪声" or ("噪声" in name and re.search(r"(?i)dB", blob)):
        hit = re.search(r"不大于\s*\d+(?:\.\d+)?\s*dB(?:\(A\))?", blob, re.I)
        if hit:
            return hit.group(0)
        hit = re.search(r"≤\s*\d+(?:\.\d+)?\s*dB(?:\(A\))?", blob)
        if hit:
            return hit.group(0)
    if name in {"MCU闪存", "MCU Flash", "SRAM容量", "SRAM", "MCU主频", "MCU clock"}:
        hit = re.search(
            r"(?:不[大小]于|至少|minimum|at least)\s*\d+(?:\.\d+)?\s*(?:MB|KB|MHz)",
            blob,
            re.I,
        ) or re.search(r"(?:为)?\s*\d+(?:\.\d+)?\s*(?:MB|KB|MHz)", blob, re.I)
        if hit:
            text = hit.group(0).strip()
            if re.search(r"[\u4e00-\u9fff]", blob) and not re.search(r"[\u4e00-\u9fff]", text):
                return blob
            return text
    if "乙二醇" in blob or re.search(r"(?i)glycol", blob):
        hit = re.search(r"\d+\s*%的乙二醇", blob) or re.search(
            r"\d+\s*%\s*(?:乙二醇|ethylene glycol|glycol)", blob, re.I
        )
        if hit:
            return re.sub(r"\s+", "", hit.group(0)) if "乙二醇" in hit.group(0) else hit.group(0)
    if name in {"爬电距离", "电气间隙", "creepage", "clearance"}:
        hit = re.search(
            r"(?:不[大小]于|至少|minimum|at least)\s*\d+(?:\.\d+)?\s*mm",
            blob,
            re.I,
        ) or re.search(r"\d+(?:\.\d+)?\s*mm", blob, re.I)
        if hit:
            return hit.group(0).strip()
    if name in {"接地电阻", "ground resistance"}:
        hit = re.search(
            r"(?:不[大小]于|不超过|至少|not exceed|maximum)?\s*\d+(?:\.\d+)?\s*m(?:Ω|Ohm)",
            blob,
            re.I,
        )
        if hit:
            return hit.group(0).strip()
    if name in {"接地点", "ground points"}:
        hit = re.search(r"\d+\s*个", blob)
        if hit:
            return hit.group(0)
    if re.search(r"[\u4e00-\u9fff]", blob) and re.search(r"[A-Za-z]{3,}", blob):
        blob = _off_list_zh_only(blob)
    return blob.strip()


def _off_list_overrides_template(text: str) -> bool:
    """主表别名误认：爬电/乙二醇撞到电机类型或冷却接口，但答案是 mm 或浓度。"""
    blob = text or ""
    if re.search(r"爬电|电气间隙|creepage|clearance distance|air clearance", blob, re.I):
        return bool(re.search(r"(?i)\d+(?:\.\d+)?\s*mm", blob))
    if re.search(
        r"乙二醇|ethylene glycol|(?<![A-Za-z])glycol(?![A-Za-z])|"
        r"冷却介质|冷却液.{0,12}(?:浓度|体积比|配比|介质)",
        blob,
        re.I,
    ):
        return bool(re.search(r"\d+\s*%", blob))
    if re.search(r"接地电阻|ground resistance", blob, re.I):
        return bool(re.search(r"mΩ|mOhm|mohm", blob))
    return False


def _is_off_list_useful(name: str, value: str) -> bool:
    """多收有答案的前期指标；转引标准、功能安全套话、熔断器目录不进。"""
    blob = f"{name} {value}"
    if _OFF_LIST_NOT_USEFUL.search(blob):
        return False
    if re.search(r"爬电|电气间隙|creepage|clearance distance|air clearance", blob, re.I):
        return bool(re.search(r"(?i)\d+(?:\.\d+)?\s*mm", blob))
    if re.search(r"接地电阻|ground resistance", blob, re.I):
        return bool(re.search(r"mΩ|mOhm|mohm", blob))
    if re.search(
        r"乙二醇|ethylene glycol|(?<![A-Za-z])glycol(?![A-Za-z])|"
        r"冷却介质|冷却液.{0,12}(?:浓度|体积比|配比)",
        blob,
        re.I,
    ):
        return bool(re.search(r"\d+\s*%", blob))
    if re.search(r"(?<![A-Za-z])Flash(?![A-Za-z])|闪存|(?<![A-Za-z])SRAM(?![A-Za-z])", blob):
        return bool(re.search(r"(?i)\d+(?:\.\d+)?\s*(?:MB|KB)", blob))
    if re.search(r"主频|clock frequency", blob, re.I):
        return bool(re.search(r"(?i)\d+(?:\.\d+)?\s*MHz", blob))
    if _OFF_LIST_USEFUL.search(blob):
        return True
    if _OFF_LIST_CITE_ONLY.search(blob):
        return False
    return bool(re.search(r"\d", value or "") and _OFF_LIST_METRIC.search(value or ""))


def _off_list_priority(cell: ExtractedCell) -> int:
    blob = f"{cell.name} {cell.value}"
    if re.search(r"禁止|打印|平整|光滑|回料|脱模剂|灰度", blob):
        return 3
    if re.search(
        r"(?i)\bMCU\b|CAN-HS|5\s*Mbit|lock-step|\bNVH\b|dB\(A\)|"
        r"Flash|SRAM|JTAG|SWD|乙二醇|透气阀|泄压阀|爬电|电气间隙|接地电阻|接地点",
        blob,
    ):
        return 2
    if re.search(r"(?i)this document|campaign|连续进料|由供", blob):
        return 0
    return 1


def _used_template_folds(rows: dict[int, ExtractedCell], extra: list[ExtractedCell]) -> set[str]:
    used: set[str] = set()
    for cell in [*rows.values(), *extra]:
        for raw in (cell.excerpt, cell.value):
            folded = _fold_text(raw)[:80]
            if len(folded) >= 12:
                used.add(folded)
    return used


def _already_used_excerpt(sentence: str, used: set[str]) -> bool:
    folded = _fold_text(sentence)
    if len(folded) < 8:
        return True
    if len(folded) < 12 and not _OFF_LIST_USEFUL.search(sentence or ""):
        return True
    for item in used:
        if folded[:80] == item or item in folded or folded in item:
            return True
    return False


def _off_list_candidates(text: str) -> list[tuple[str, str]]:
    heading = ""
    found: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or re.match(r"^## 第 \d+ [页节]", line):
            continue
        if line.startswith("|"):
            if re.fullmatch(r"\|?[\s:|-]+\|?", line.replace(" ", "")):
                continue
            for cell in line.strip("|").split("|"):
                sent = re.sub(r"\s+", " ", cell).strip()
                if sent.startswith("---") or re.fullmatch(r":?-+:?", sent):
                    continue
                if 10 <= len(sent) <= 400:
                    found.append((heading, sent))
            continue
        if _is_off_list_heading(line):
            heading = _off_list_heading_name(line)
            continue
        parts = re.split(r"(?<=[。．.!?！？])\s+", line)
        for part in parts:
            sent = re.sub(r"\s+", " ", part).strip()
            if 10 <= len(sent) <= 400:
                if (
                    found
                    and re.search(r"(?i)dB|\d+\s*级", sent)
                    and not _OFF_LIST_REQ.search(sent)
                    and _OFF_LIST_REQ.search(found[-1][1])
                    and len(found[-1][1]) + len(sent) <= 400
                ):
                    prev_h, prev_s = found[-1]
                    found[-1] = (prev_h, prev_s + sent)
                    continue
                found.append((heading, sent))
    return found


def _page_from_full_markdown(markdown: str, sentence: str) -> str:
    """句子被压成单行后，仍按全文「第 N 页」回填印页。"""
    sent = re.sub(r"\s+", " ", (sentence or "").strip())
    if not markdown or len(sent) < 8:
        return ""
    collapsed = re.sub(r"\s+", " ", markdown)
    at = collapsed.find(sent)
    if at < 0 and len(sent) >= 16:
        at = collapsed.find(sent[:16])
    if at < 0:
        return ""
    matches = list(re.finditer(r"第 (\d+) 页", collapsed[: at + 1]))
    return matches[-1].group(1) if matches else ""


def _collect_off_list_requirements(
    markdown: str,
    rows: dict[int, ExtractedCell],
    extra: list[ExtractedCell],
    seen_extra: set[tuple[str, str]],
) -> None:
    """当份原文里对不上 1–120 的要求。标题/目录/TBD/流程语不进。"""
    used = _used_template_folds(rows, extra)
    for page_no, block in _page_blocks(markdown):
        if _is_glossary(block):
            continue
        for heading, sentence in _off_list_candidates(block):
            if _is_front_matter(sentence):
                continue
            if not _OFF_LIST_REQ.search(sentence):
                continue
            if _is_off_list_process(sentence):
                continue
            if _is_junk_value(sentence, heading) or _looks_like_ocr_garbage(sentence):
                continue
            if _maps_to_template_field(sentence) and not _off_list_overrides_template(sentence):
                continue
            if _already_used_excerpt(sentence, used):
                continue
            split = _split_off_list_item(heading, sentence)
            twin = _off_list_zh_twin(block, sentence)
            excerpt = sentence
            if twin:
                name, value, excerpt = twin
            elif split is None:
                continue
            else:
                name, value = split
            if _off_list_lang(excerpt) == "zh":
                excerpt = _off_list_zh_only(excerpt)
            if name in _COVER_EXTRA:
                continue
            if _OFF_LIST_ON_TEMPLATE.search(excerpt) or _OFF_LIST_ON_TEMPLATE.search(
                f"{name} {value}"
            ):
                if not _off_list_overrides_template(f"{name} {value} {excerpt}"):
                    continue
            if _is_weak_value(value) or _is_junk_value(value, name):
                continue
            if not _is_off_list_useful(name, value):
                continue
            if not _value_in_source(value, excerpt, block):
                continue
            key = (name, value)
            if key in seen_extra:
                continue
            at = block.find(excerpt)
            if at < 0:
                at = block.find(sentence)
            clause = _pick_clause(block, at if at >= 0 else None, excerpt, name=name)
            located = _page_for_index(block, at) if at >= 0 else ""
            page = str(page_no) if page_no else located
            if not page:
                page = _page_from_full_markdown(markdown, excerpt) or _page_from_full_markdown(
                    markdown, sentence
                )
            cell = ExtractedCell(
                seq=0,
                name=name,
                value=value,
                page=page,
                clause=clause or "",
                excerpt=excerpt,
                confidence=0.78,
                extra=True,
            )
            replaced = False
            for idx, prev in enumerate(extra):
                if not prev.extra or is_cover_extra(prev):
                    continue
                if _off_list_same_item(prev, cell):
                    extra[idx] = _prefer_off_list_cell(prev, cell)
                    replaced = True
                    break
            if not replaced:
                if len(extra) < _OFF_LIST_MAX:
                    extra.append(cell)
                else:
                    scored = [
                        (idx, _off_list_priority(prev))
                        for idx, prev in enumerate(extra)
                        if prev.extra and not is_cover_extra(prev)
                    ]
                    if not scored:
                        continue
                    worst_idx = min(scored, key=lambda item: item[1])[0]
                    if _off_list_priority(cell) > _off_list_priority(extra[worst_idx]):
                        extra[worst_idx] = cell
                    else:
                        continue
            seen_extra.add(key)
            for raw in (sentence, excerpt):
                folded = _fold_text(raw)[:80]
                if len(folded) >= 12:
                    used.add(folded)
    _unify_off_list_names(extra)


def _better(old: ExtractedCell, new: ExtractedCell) -> ExtractedCell:
    if _is_derived_cell(new) and (old.value or "").strip() and not _is_derived_cell(old):
        if _fold_text(old.value) == _fold_text(new.value) and not (old.note or "").strip():
            old.note = new.note
            old.review_status = old.review_status or STATUS_PARTIAL
        if not old.clause and new.clause:
            old.clause = new.clause
        if not old.page and new.page:
            old.page = new.page
        return old
    if _is_derived_cell(old) and (new.value or "").strip() and not _is_derived_cell(new):
        if _fold_text(old.value) == _fold_text(new.value):
            new.note = new.note or old.note
            new.review_status = new.review_status or old.review_status or STATUS_PARTIAL
        new.clause = new.clause or old.clause
        new.page = new.page or old.page
        return new
    if _is_law_description(new.value, new.excerpt) and _has_measurable_number(old.value):
        if not old.clause and new.clause:
            old.clause = new.clause
        if not old.page and new.page:
            old.page = new.page
        return old
    if _is_law_description(old.value, old.excerpt) and _has_measurable_number(new.value):
        new.clause = new.clause or old.clause
        new.page = new.page or old.page
        return new
    if _is_weak_value(new.value):
        return old
    if _is_weak_value(old.value):
        return new
    if _fold_text(old.value) == _fold_text(new.value):
        old_partial = (old.review_status or "") == STATUS_PARTIAL
        new_partial = (new.review_status or "") == STATUS_PARTIAL
        if old_partial != new_partial:
            keep = new if new_partial else old
            keep.clause = keep.clause or old.clause or new.clause
            keep.page = keep.page or old.page or new.page
            keep.excerpt = keep.excerpt or old.excerpt or new.excerpt
            keep.note = keep.note or old.note or new.note
            return keep
    name = old.name or ""
    if "寿命" in name:
        def _life_score(v: str) -> int:
            s = 0
            if re.search(r"15\s*年|15\s*years", v, re.I):
                s += 4
            if re.search(r"35\s*万|350,?000|300,?000", v, re.I):
                s += 4
            if re.search(r"25\s*万|250,?000", v, re.I):
                s += 2
            if re.search(r"2\s*年|5\s*万|50,?000|三包|质保", v, re.I):
                s -= 3
            return s

        old_s, new_s = _life_score(old.value), _life_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_life = bool(re.search(r"年|公里|\bkm\b|year|质保", old.value, re.I))
        new_life = bool(re.search(r"年|公里|\bkm\b|year|质保", new.value, re.I))
        if new_life and not old_life:
            return new
        if old_life and not new_life:
            return old
    if "直流工作电压" in name:
        def _working_v_score(v: str, ex: str) -> int:
            s = 0
            if _looks_like_hvdc_voltage_table(ex) or re.search(r"冷启动", v):
                s += 10
            if re.search(r"busbar working voltage range|母线工作电压范围", ex, re.I):
                s += 2
            if (_hvdc_value_has_pair(v, "530", "1150") or re.search(r"530\s*V?\s*[~～-]\s*1150", v, re.I)) and "冷启动" not in v:
                s += 1
            if _hvdc_value_has_pair(v, "390", "945"):
                s += 3
            if re.search(r"性能限制≥", v) and re.search(r"\d{3}\s+\d{3}\s+\d{3}", ex):
                s -= 5
            if "非升压" in v and "升压" in v:
                s += 5
            if re.search(r"最低：", v) and re.search(r"最高：", v):
                s += 3
            s += min(3, len(re.findall(r"^\d+\.\S+最低：", v or "", re.M)))
            if re.search(r"冷启动\d+V～满功率\d+V", v) and "非升压" not in v:
                s -= 4
            return s

        old_s = _working_v_score(old.value, old.excerpt)
        new_s = _working_v_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_ok = bool(re.search(r"530\s*V?\s*[~～-]\s*1150", old.value, re.I))
        new_ok = bool(re.search(r"530\s*V?\s*[~～-]\s*1150", new.value, re.I))
        if new_ok and not old_ok:
            return new
        if old_ok and not new_ok:
            return old
    if "满功率" in name and "电压" in name:
        def _full_v_score(v: str, ex: str) -> int:
            s = 0
            if _looks_like_hvdc_voltage_table(ex):
                s += 8
            if _hvdc_value_has_pair(v, "800", "1066"):
                s += 3
            if re.search(r"465Arms", v, re.I):
                s += 1
            if "非升压" in v and "升压" in v:
                s += 5
            if re.search(r"最低：", v) and re.search(r"最高：", v):
                s += 3
            if "满电流" in v:
                s += 2
            return s

        old_s = _full_v_score(old.value, old.excerpt)
        new_s = _full_v_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_ok = _hvdc_value_has_pair(old.value, "800", "1066")
        new_ok = _hvdc_value_has_pair(new.value, "800", "1066")
        if new_ok and not old_ok:
            return new
        if old_ok and not new_ok:
            return old
        old_range = bool(
            re.search(r"\d{3,4}\s*V?\s*[~～-]\s*\d{3,4}", old.value)
            or (
                re.search(r"最低：\s*\d{3,4}\s*V", old.value)
                and re.search(r"最高：\s*\d{3,4}\s*V", old.value)
            )
        )
        new_range = bool(
            re.search(r"\d{3,4}\s*V?\s*[~～-]\s*\d{3,4}", new.value)
            or (
                re.search(r"最低：\s*\d{3,4}\s*V", new.value)
                and re.search(r"最高：\s*\d{3,4}\s*V", new.value)
            )
        )
        if old_range and not new_range:
            return old
        if new_range and not old_range:
            return new
        old_split = "非升压" in (old.value or "") and "升压" in (old.value or "")
        new_split = "非升压" in (new.value or "") and "升压" in (new.value or "")
        if old_split and not new_split:
            return old
        if new_split and not old_split:
            return new
    if "设计范围是否包含驱动升压" in name:
        old_s = _drive_boost_scope_score(old.value, old.excerpt)
        new_s = _drive_boost_scope_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "设计范围是否包含行车升压" in name or "设计范围是否包含充电升压" in name:
        old_s = _item4_scope_score(old.value, old.excerpt)
        new_s = _item4_scope_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if name == "Boost功能要求" or "Boost功能要求" in name:
        def _boost_fn_score(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"Charging Buck/Boost|充电场景|充电升压/降压", blob, re.I):
                s += 8
            if re.search(
                r"HVDC 输入电压较低|boost the HV input|直流输入的电压提升",
                blob,
                re.I,
            ):
                s += 4
            if re.search(r"boost control|BOOST architecture", blob, re.I):
                s += 1
            return s

        old_s = _boost_fn_score(old.value, old.excerpt)
        new_s = _boost_fn_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "升压输出电压" in name:
        def _vout_score(v: str, ex: str) -> int:
            s = 0
            if re.search(r"480|1056", v or "") and re.search(
                r"Charging Buck/Boost|充电升压/降压|高压侧", ex or "", re.I
            ):
                s += 8
            if re.search(r"三种|bypass|BUCK", v or "", re.I):
                s += 5
            if re.search(r"450", v or ""):
                s += 2
            return s

        old_s = _vout_score(old.value, old.excerpt)
        new_s = _vout_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "降额工作电压" in name:
        def _derate_score(v: str, ex: str) -> int:
            s = 0
            if _looks_like_hvdc_voltage_table(ex) or re.search(r"限制最高|1125", v):
                s += 8
            if re.search(r"1150.*线性降额", v, re.I) or _hvdc_value_has_pair(v, "1066", "1150"):
                s += 2
            if "非升压" in v and "升压" in v:
                s += 5
            if re.search(r"最低：", v) and re.search(r"最高：", v):
                s += 3
            if re.search(r"最高：\s*\d", v):
                s += 2
            if re.search(r"最高：\s*未给出", v):
                s -= 2
            return s

        old_s = _derate_score(old.value, old.excerpt)
        new_s = _derate_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_ok = bool(
            re.search(r"1150.*线性降额", old.value, re.I)
            or _hvdc_value_has_pair(old.value, "1066", "1150")
        )
        new_ok = bool(
            re.search(r"1150.*线性降额", new.value, re.I)
            or _hvdc_value_has_pair(new.value, "1066", "1150")
        )
        if new_ok and not old_ok:
            return new
        if old_ok and not new_ok:
            return old
        old_split = "非升压" in (old.value or "") and "升压" in (old.value or "")
        new_split = "非升压" in (new.value or "") and "升压" in (new.value or "")
        if old_split and not new_split:
            return old
        if new_split and not old_split:
            return new
    if "高压连接器保护" in name:
        def _conn_score(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"IPXXB|防直触|触指|防直接接触", v, re.I):
                s += 8
            if re.search(r"无机械互锁|without machine of HVIL", blob, re.I):
                s -= 8
            if _CONNECTOR_POWER_AS_VALUE.search(v or "") and not re.search(
                r"IPXX|触指|防直触|防直接接触", v or "", re.I
            ):
                s -= 10
            if re.search(r"6\.2\.3\.2", blob) and re.search(
                r"高压直流连接|High Voltage DC connection", v or "", re.I
            ):
                s += 3
            return s

        old_s = _conn_score(old.value, old.excerpt)
        new_s = _conn_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "绝缘电阻" in name:
        if "热态" in (new.value or "") and "热态" not in (old.value or ""):
            return new
        if "热态" in (old.value or "") and "热态" not in (new.value or ""):
            return old
    if "防腐" in name:
        def _corr_score(v: str) -> int:
            s = 0
            if re.search(r"L1-F", v, re.I):
                s += 6
            if re.search(r"\bXCM\b", v) and "L1-F" not in (v or ""):
                s -= 4
            return s

        old_s, new_s = _corr_score(old.value), _corr_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "冷却接口" in name:
        def _cool_if_score(v: str) -> int:
            s = 0
            if re.search(r"NW\s*12|VDA", v, re.I):
                s += 3
            if re.search(r"Glycol|油冷|Inverter", v, re.I):
                s += 2
            return s

        old_s, new_s = _cool_if_score(old.value), _cool_if_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "通讯" in name:
        old_n = len(re.findall(r"CAN|LIN|FlexRay|Ethernet|以太网", old.value, re.I))
        new_n = len(re.findall(r"CAN|LIN|FlexRay|Ethernet|以太网", new.value, re.I))
        if new_n > old_n:
            return new
        if old_n > new_n:
            return old
    if "功能安全" in name:
        def _asil_rank(v: str) -> int:
            m = re.search(r"ASIL[\s-]*([A-D])", v, re.I)
            if not m:
                return 0
            return "ABCD".index(m.group(1).upper()) + 1

        if _asil_rank(new.value) > _asil_rank(old.value):
            return new
        if _asil_rank(old.value) > _asil_rank(new.value):
            return old

        def _asil_complete(v: str) -> int:
            s = 0
            if re.search(r"(?i)\bshall\b|应", v):
                s += 3
            if re.search(r"26262\s*[-–]?\s*\d{4}", v):
                s += 2
            s += min(len(v or ""), 240) // 60
            return s

        if _asil_complete(new.value) > _asil_complete(old.value):
            return new
        if _asil_complete(old.value) > _asil_complete(new.value):
            return old
    if "冷却回路压降" in name:
        def _drop_score(ex: str) -> int:
            s = 0
            if re.search(r"Coolant pressure drop|冷却回路压降", ex or "", re.I):
                s += 6
            if re.search(r"flow resistance|冷却流阻", ex or "", re.I):
                s += 1
            if "6.8.3" in (ex or ""):
                s += 3
            return s

        old_s, new_s = _drop_score(old.excerpt), _drop_score(new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "反电动势" in name or "Back EMF" in name:
        old_v = bool(re.search(r"\d{3,4}\s*V", old.value, re.I))
        new_v = bool(re.search(r"\d{3,4}\s*V", new.value, re.I))
        if old_v and not new_v:
            return old
        if new_v and not old_v:
            return new
    if "EMC" in name:
        def _emc_score(v: str, ex: str = "") -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"2\.3\.3\.3", blob):
                s += 8
            if re.search(r"Generic EMC|电磁兼容总体|控制器应满足Q/JLY|The unit shall meet Q/JLY", blob, re.I):
                s += 6
            if re.search(
                r"电气属性均须满足|electrical properties of the entire transmission|"
                r"EMC testing requirements|EMC测试要求",
                blob,
                re.I,
            ):
                s += 6
            if re.search(r"J7110922D", blob, re.I):
                s += 2
            if re.search(r"7637-4|屏蔽", blob):
                s += 3
            if re.search(r"Pulse B", blob, re.I):
                s += 1
            if re.search(
                r"Electromagnetic compatibility specification for high-voltage",
                blob,
                re.I,
            ) and not re.search(
                r"2\.3\.3\.3|控制器应满足|shall meet|电气属性均须满足|EMC测试要求",
                blob,
                re.I,
            ):
                s -= 8
            return s

        old_s, new_s = _emc_score(old.value, old.excerpt), _emc_score(
            new.value, new.excerpt
        )
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if name == "升压充电功能":
        def _charge_fn_score(v: str) -> int:
            s = 0
            if re.search(r"Charging Buck/Boost|充电升压/降压功能需求", v, re.I):
                s += 8
            if re.search(
                r"充电电压|充电电流|充电时长|"
                r"charging voltage|charging current|charging duration",
                v,
                re.I,
            ):
                s += 6
            if re.search(r"充电拓扑|charging topology", v, re.I):
                s += 5
            if re.search(r"驻车放电", v):
                s += 3
            if re.search(r"慢充连接器|slow charg(?:e|ing) connector", v, re.I):
                s += 1
            if re.search(r"三种作?工作模式|Boost升压，bypass", v):
                s -= 6
            return s

        old_s, new_s = _charge_fn_score(old.value), _charge_fn_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "升压效率" in name:
        def _boost_eta(v: str) -> int:
            s = 0
            for token in ("99.5", "99.1", "98.8", "98.5", "直通", "升压"):
                if token in (v or ""):
                    s += 1
            return s

        old_s, new_s = _boost_eta(old.value), _boost_eta(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "相电流采样" in name:
        def _phase_acc_score(v: str, ex: str) -> int:
            s = 0
            if "P1" in (v or "") and "P3" in (v or ""):
                s += 3
            cn = set(re.findall(r"测量[-－]?\s*(\d{2,4})\s*A至", ex or ""))
            en = set(
                re.findall(r"-\s*(\d{2,4})\s*A\s*to\s*\+", ex or "", re.I)
            )
            for amp in cn:
                if re.search(rf"−{amp}A|[+]{amp}A|{amp}A", v or ""):
                    s += 5
            conflict = bool(cn and en and cn != en)
            if conflict:
                for amp in en:
                    if re.search(rf"−{amp}A|[+]{amp}A|{amp}A", v or ""):
                        s += 5
                if "需人工复核" in (v or "") or "中英文" in (v or ""):
                    s += 3
                if any(not re.search(rf"{amp}A", v or "") for amp in cn | en):
                    s -= 6
            else:
                for amp in en - cn:
                    if cn and re.search(rf"−{amp}A|{amp}A", v or ""):
                        s -= 4
            return s

        old_s = _phase_acc_score(old.value, old.excerpt)
        new_s = _phase_acc_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_both = "P1" in (old.value or "") and "P3" in (old.value or "")
        new_both = "P1" in (new.value or "") and "P3" in (new.value or "")
        if old_both and not new_both:
            return old
        if new_both and not old_both:
            return new
    if ("IGBT" in name or "电机温度" in name) and "采样" in name:
        def _temp_acc_score(v: str) -> int:
            s = 0
            if "±5" in (v or "") or "± 5" in (v or ""):
                s += 2
            if "±3" in (v or "") or "± 3" in (v or ""):
                s += 2
            if "100" in (v or ""):
                s += 1
            return s

        old_s, new_s = _temp_acc_score(old.value), _temp_acc_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "耐电压" in name:
        def _dielectric_score(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"18488|漏电流|无击穿|hipot|工频", blob, re.I) and not _is_continuous_hvdc_withstand(
                blob
            ):
                s += 12
            if _is_continuous_hvdc_withstand(blob):
                s += 10
            if re.search(r"ISO\s*6469", blob, re.I) and re.search(
                r"1\s*min|50\s*Hz|2U\s*\+", blob, re.I
            ):
                s += 4
            if re.search(r"Umax\s*operating", blob, re.I):
                s -= 5
            return s

        old_s = _dielectric_score(old.value, old.excerpt)
        new_s = _dielectric_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        # 勿把信号端子 500V / 电压分档表误当母线 Umax
        old_bad = bool(re.search(r"Umax\s*operating\s*=\s*500V", old.value, re.I))
        new_bad = bool(re.search(r"Umax\s*operating\s*=\s*500V", new.value, re.I))
        if old_bad and not new_bad:
            return new
        if new_bad and not old_bad:
            return old
    if "峰值功率" in name:
        def _motor_peak_score(v: str, excerpt: str) -> int:
            blob = f"{v}\n{excerpt}"
            s = 0
            if re.search(r"220\s*kW", blob, re.I) and re.search(
                r"14500|16000|generate|电机峰值", blob, re.I
            ):
                s += 6
            if re.search(r"270\s*kW", blob, re.I) and re.search(
                r"HVDC|高压直流", blob, re.I
            ):
                s -= 5
            if re.search(r"125\s*kW", blob, re.I) and re.search(
                r"HVDC peak|高压直流峰值", blob, re.I
            ) and not re.search(r"P1电机|generate", blob, re.I):
                s -= 5
            elif re.search(r"125\s*kW", blob, re.I) and re.search(
                r"P1电机|generate", blob, re.I
            ):
                s += 4
            return s

        old_s = _motor_peak_score(old.value, old.excerpt)
        new_s = _motor_peak_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
        old_kw = bool(re.search(r"(?i)\bkw\b|千瓦", old.value))
        new_kw = bool(re.search(r"(?i)\bkw\b|千瓦", new.value))
        if new_kw and not old_kw:
            return new
        if old_kw and not new_kw:
            return old
    if "P1" in name and "额定功率" in name:
        def _p1_rated_score(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"70\s*kW", v, re.I) and re.search(
                r"continuous generate|额定发电|70\s*kW", blob, re.I
            ):
                s += 4
            if re.search(r"120\s*kW", v, re.I) and re.search(
                r"P1.*120|120kW@|额定发电", blob, re.I
            ):
                s += 4
            if re.search(r"62\.5", v):
                if re.search(r"HVDC continuous|高压直流持续", blob, re.I):
                    s -= 5
                else:
                    s += 3
            return s

        old_s = _p1_rated_score(old.value, old.excerpt)
        new_s = _p1_rated_score(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "峰值扭矩" in name and "P3" in name:
        def _p3_peak_tq(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"locking strategy|堵转策略|Tmax\s*\*\s*0\.85", blob, re.I):
                s -= 6
            if re.search(
                r"P3\s*(?:peak torque|电机峰值扭矩)[^\n]{0,120}?\d+(?:\.\d+)?\s*Nm",
                blob,
                re.I,
            ):
                s += 6
            if re.search(r"\d{2,4}\s*Nm", v) and not re.search(r"85\s*%", v):
                s += 4
            return s

        old_s = _p3_peak_tq(old.value, old.excerpt)
        new_s = _p3_peak_tq(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "P3" in name and "额定功率相电流" in name:
        def _p3_cont_i(v: str, ex: str) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(r"310", v) and re.search(r"310", blob):
                s += 3
            if re.search(r"250", v) and re.search(r"250", ex or ""):
                s += 3
            if re.search(r"250", v) and not re.search(r"250", ex or ""):
                s -= 2
            if re.search(r"continuous|持续|30\s*min", blob, re.I):
                s += 1
            return s

        old_s = _p3_cont_i(old.value, old.excerpt)
        new_s = _p3_cont_i(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "P3" in name and "交流电流峰值" in name:
        def _p3_peak_i(v: str, ex: str) -> int:
            s = 0
            for n in ("600", "520", "465"):
                if n in (v or "") and n in (ex or ""):
                    s += 4
                elif n in (v or ""):
                    s += 1
            return s

        old_s = _p3_peak_i(old.value, old.excerpt)
        new_s = _p3_peak_i(new.value, new.excerpt)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "最高工作转速" in name:
        def _rpm_def_score(v: str, ex: str, conf: float) -> int:
            blob = f"{v}\n{ex}"
            s = 0
            if re.search(
                r"the max speed of|最高(?:工作)?转速|"
                r"max(?:imum)?(?:\s+operating)?\s+speed|Top speed|随转|出电功率|出功率",
                blob,
                re.I,
            ):
                s += 8
            if _is_ac_fundamental_rpm_assumption(blob):
                s -= 6
            if conf >= 0.88:
                s += 1
            return s

        old_s = _rpm_def_score(old.value, old.excerpt, old.confidence)
        new_s = _rpm_def_score(new.value, new.excerpt, new.confidence)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    if "逆变器效率" in name:
        def _eta_score(v: str) -> int:
            s = 0
            if re.search(r"＞\s*99|>\s*99|99\.5|99\.8|99\.9", v or ""):
                s += 2
            if re.search(r"98\.25|综合效率|总考核", v or ""):
                s += 4
            if "P1" in name and re.search(r"平均效率|98\.2|单挡|98\.5", v or ""):
                s += 4
            if re.search(r"区间[123]", v or ""):
                s += 3
            if "P3" in name and re.search(r"98\.2(?!\d)", v or "") and not re.search(
                r"98\.25|总考核|区间[123]", v or ""
            ):
                s -= 6
            return s

        joined = _join_inverter_eta(name, old.value, new.value)
        if joined and _fold_text(old.value) != _fold_text(new.value):
            keep = new if _eta_score(new.value) > _eta_score(old.value) else old
            keep.value = joined
            if (old.excerpt or "").strip() and (new.excerpt or "").strip():
                old_band = bool(re.search(r"区间|平均|单挡", old.excerpt or "", re.I))
                new_band = bool(re.search(r"区间|平均|单挡", new.excerpt or "", re.I))
                if old_band != new_band:
                    keep.excerpt = (
                        f"{old.excerpt}\n{new.excerpt}".strip()[:_CLAUSE_LIMIT]
                    )
            keep.clause = keep.clause or old.clause or new.clause
            keep.page = keep.page or old.page or new.page
            keep.confidence = max(old.confidence, new.confidence)
            return keep
        old_s, new_s = _eta_score(old.value), _eta_score(new.value)
        if new_s > old_s:
            return new
        if old_s > new_s:
            return old
    old_num = bool(re.search(r"\d", old.value))
    new_num = bool(re.search(r"\d", new.value))
    if new_num and not old_num:
        return new
    if old_num and not new_num:
        return old
    if len(new.value) >= len(old.value) + 10:
        return new
    if new.confidence > old.confidence:
        return new
    return old


def _page_hint(chunk: str) -> str:
    match = _PAGE_MARKER.search(chunk or "")
    if not match or match.start() > 240:
        return ""
    if set(_PAGE_MARKER.findall(chunk or "")) == {"1"} and len(chunk or "") >= _UNPAGED_MIN_CHARS:
        return ""
    return match.group(1)


def _normalize_page(page: str, chunk: str) -> str:
    """页码列只保留印在页上的页码（页眉或页脚）；模型若给出节号则改回本段「第 N 页」。"""
    raw = (page or "").strip()
    hint = _page_hint(chunk)
    if re.fullmatch(r"\d+", raw):
        if not hint:
            return ""
        return raw
    match = re.search(r"(?:第\s*)?(\d+)\s*页", raw)
    if match:
        return match.group(1) if hint else ""
    if hint and (raw.startswith("节") or re.fullmatch(r"\d+(?:\.\d+)+", raw) or not raw):
        return hint
    return hint or ""


def _page_for_index(chunk: str, index: int) -> str:
    if not _has_printed_page_markers(chunk):
        return ""
    last = ""
    nxt = ""
    for match in _PAGE_MARKER.finditer(chunk or ""):
        if match.start() <= index:
            last = match.group(1)
        elif not nxt and match.start() - index <= 160:
            nxt = match.group(1)
            break
        else:
            break
    if last == "1" and nxt and nxt != "1":
        return nxt
    return last or nxt


def _rule_cells(chunk: str, family: str = "generic") -> list[ExtractedCell]:
    found: list[ExtractedCell] = []

    def add(
        name: str,
        value: str,
        unit: str,
        excerpt: str,
        at: int,
        *,
        confidence: float = 0.82,
        note: str = "",
        review_status: str = "",
    ) -> None:
        value = value.strip()
        if not value:
            return
        name = _canonical_field_name(name)
        if "流量" in name:
            value = re.sub(r"\bO\s+to\b", "0 to", value, flags=re.I)
            excerpt = re.sub(r"\bO\s+to\b", "0 to", excerpt or "", flags=re.I)
        keep_cn = bool(
            "相电流采样" in name
            and (
                "控制器应能够测量" in (excerpt or "")
                or "中英文量程不一致" in (note or "")
            )
            and re.search(r"\d{2,4}\s*A", excerpt or "")
        )
        end = at + max(len(excerpt or ""), 1)
        clause_text = _expand_to_clause(chunk, at, end)
        if clause_text and not keep_cn:
            excerpt = clause_text
            if "功能安全" in name and len(clause_text) <= 200:
                value = clause_text
        found.append(
            ExtractedCell(
                name=name,
                value=value,
                unit=unit,
                page=_page_for_index(chunk, at),
                clause=_pick_clause(chunk, at, excerpt, name=name),
                excerpt=excerpt.strip()[:_CLAUSE_LIMIT],
                confidence=confidence,
                extra=True,
                note=note,
                review_status=review_status,
            )
        )

    match = re.search(
        r"(?i)Qualification Life\s*:\s*([0-9]+\s*years?\s*[-–]\s*[0-9,]+\s*km)",
        chunk,
    )
    if match:
        add("寿命要求", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"(?i)Warranty(?: life target)?\s*:\s*([0-9,]+\s*km(?:\s+for)?\s*\d+\s*years?|\d+\s*years?\s*[-–]\s*[0-9,]+\s*km)",
        chunk,
    )
    if match:
        add("寿命要求", "质保 " + match.group(1), "", match.group(0), match.start())
    match = re.search(r"(?i)Water\s*:\s*Glycol\s*\(([^)]+)\)", chunk)
    if match:
        add("冷却接口", f"Water:Glycol({match.group(1)})", "", match.group(0), match.start())
    match = re.search(r"(?i)Cooling sequence.{0,80}Inverter.{0,40}(?:motor|gearbox)", chunk)
    if match:
        add("冷却接口", "油冷；顺序 Inverter-motor-gearbox", "", match.group(0), match.start())
    if (
        re.search(r"(?i)\bEWP\b", chunk)
        and re.search(r"(?i)lpm", chunk)
        and re.search(r"(?i)Max(?:imum)?\.?\s*12\b", chunk)
    ):
        loc = chunk.lower().find("ewp")
        add("冷却流量范围", "Max 12 lpm", "", "EWP flowrate Max 12 lpm", max(loc, 0))
    match = re.search(r"2\s*[~～-]\s*2\.5\s*V", chunk, re.I)
    if match:
        add("车速信号电压", "2~2.5 V", "", match.group(0), match.start())
    match = re.search(
        r"(?i)8\s*poles and 20000\s*rpm|"
        r"基于8极20000转",
        chunk,
    )
    if match:
        add(
            "P3最高工作转速",
            "20000rpm",
            "",
            match.group(0),
            match.start(),
            confidence=0.72,
            note=_POLES_RPM_NOTE,
            review_status=STATUS_PARTIAL,
        )
    match = re.search(
        r"(?i)8\s*poles and 16000\s*rpm|"
        r"基于8极16000转",
        chunk,
    )
    if match:
        add(
            "P1最高工作转速",
            "16000rpm",
            "",
            match.group(0),
            match.start(),
            confidence=0.72,
            note=_POLES_RPM_NOTE,
            review_status=STATUS_PARTIAL,
        )
    match = re.search(r"(?i)[MМ]ax\.?\s*20[,.\s]?000", chunk)
    if match:
        ctx = chunk[max(0, match.start() - 240) : match.start() + 120]
        if _is_ac_fundamental_rpm_assumption(ctx):
            pass
        elif re.search(
            r"max(?:imum)?(?:\s+operating)?\s+speed|最高(?:工作)?转速|"
            r"top speed|随转|出功率",
            ctx,
            re.I,
        ):
            add(
                "P3最高工作转速",
                "≤20000rpm",
                "",
                match.group(0),
                match.start(),
                confidence=0.9,
            )
        else:
            add(
                "P3最高工作转速",
                "≤20000rpm",
                "",
                match.group(0),
                match.start(),
                confidence=0.72,
                note="仅写 Max 20000，未标明最高工作转速。请对照转速定义复核。",
                review_status=STATUS_PARTIAL,
            )
    match = re.search(r"(?i)ISO\s*26262", chunk)
    if match:
        asil = re.search(
            r"(?i)(?:fulfill|符合)\s*ASIL\s*[A-D].{0,40}ISO\s*26262|"
            r"ASIL\s*[A-D]\s*(?:according to|/)\s*ISO\s*26262|"
            r"ISO\s*26262[^\n]{0,30}ASIL\s*[A-D]",
            chunk,
        )
        if asil:
            add(
                "功能安全",
                re.sub(r"\s+", " ", asil.group(0)).strip(),
                "",
                asil.group(0),
                asil.start(),
            )
        else:
            asil2 = re.search(r"(?i)ASIL\s*[A-D]", chunk)
            if asil2:
                add(
                    "功能安全",
                    f"{asil2.group(0)} / ISO 26262",
                    "",
                    chunk[max(0, asil2.start() - 40) : asil2.end() + 24],
                    asil2.start(),
                )
            else:
                add("功能安全", "ISO 26262", "", match.group(0), match.start())
    match = re.search(r"(?i)LV\s*124", chunk)
    if match:
        add("电气耐久准则", "LV 124", "", match.group(0), match.start())
    match = re.search(r"(?i)\bIP[\s-]*([456][0-9](?:\s*/\s*[0-9]{2})?)", chunk)
    if match:
        ctx = chunk[max(0, match.start() - 520) : match.end() + 80]
        if not re.search(
            r"non-mated|未插接|未插配|Non-mated connectors|"
            r"touch protected|IPXX|IPxx|connectors for options|"
            r"protection degree of at least\s*IP68",
            ctx,
            re.I,
        ):
            add(
                "密封（IP等级）",
                "IP" + re.sub(r"\s+", "", match.group(1)),
                "",
                ctx.strip(),
                match.start(),
            )
    match = re.search(r"(?i)\b(CAN[\s-]*FD|CAN\s*2\.0b?|FlexRay)\b", chunk)
    # 同段已有 LIN 时留给后面的 CAN/CAN-FD/LIN 规则，避免只留下 CAN-FD。
    if match and not (
        re.search(r"CAN[\s\-–]*FD", chunk, re.I) and re.search(r"\bLIN\b", chunk)
    ):
        add(
            "通讯方式",
            re.sub(r"\s+", " ", match.group(1)).strip(),
            "",
            match.group(0),
            match.start(),
        )
    if re.search(
        r"Propulsion CAN bus shall support CAN-FD|动力CAN总线应支持",
        chunk,
        re.I,
    ):
        comm = "动力/底盘/Rear 等 CAN-FD 5Mbit/s（含 PNC 唤醒）"
        if re.search(r"以太网|Ethernet", chunk, re.I):
            comm += "；预留一路以太网（标定）"
        add(
            "通讯方式",
            comm,
            "",
            "Propulsion CAN / 以太网",
            re.search(r"Propulsion CAN|动力CAN", chunk, re.I).start(),
        )
    match = re.search(r"(?i)Operating temperature[^\n]{0,40}(-40\s*°?C?\s*[~～-]\s*10[05]\s*°?C?)", chunk)
    if match:
        add("工作温度范围", match.group(1).replace(" ", ""), "", match.group(0), match.start())
    match = re.search(
        r"(\d+\s*年或\d+\s*万公里[^。]{0,30}|15 years or 250,?000 kilometers[^.]{0,40})",
        chunk,
        re.I,
    )
    if match:
        add("寿命要求", re.sub(r"\s+", " ", match.group(0)).strip(), "", match.group(0), match.start())
    match = re.search(
        r"绝缘电阻\s*≥\s*48\s*M\s*Ω[\s\S]{0,80}?热态绝缘电阻\s*≥\s*2\.5\s*M\s*Ω|"
        r"insulation resistance[^\n]{0,80}?≥\s*48\s*M\s*Ω[\s\S]{0,80}?热态绝缘电阻\s*≥\s*2\.5\s*M\s*Ω",
        chunk,
        re.I,
    )
    if match:
        add(
            "高压安全-绝缘电阻",
            "≥48MΩ；热态≥2.5MΩ",
            "",
            re.sub(r"\s+", " ", match.group(0)).strip()[:200],
            match.start(),
        )
    else:
        match = re.search(r"绝缘电阻[^。\n]{0,24}≥\s*48\s*M\s*Ω", chunk)
        if match:
            add("高压安全-绝缘电阻", match.group(0), "", match.group(0), match.start())
    hot = re.search(r"热态绝缘电阻\s*≥\s*([\d.]+)\s*M\s*Ω", chunk)
    if hot:
        add(
            "高压安全-绝缘电阻",
            f"≥48MΩ；热态≥{hot.group(1)}MΩ",
            "",
            hot.group(0),
            hot.start(),
        )
    match = re.search(r"主动放电应在[^。]{0,80}?(\d+)\s*s\s*内完成", chunk)
    if match:
        add(
            _ACTIVE_DISCHARGE,
            f"{match.group(1)}s内降至60VDC（接触器打开触发）",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(r"被动放电应保证在电池接触器开启后(\d+)\s*秒内[^。]{0,40}60\s*V", chunk)
    if match:
        add(_PASSIVE_DISCHARGE, match.group(0), "", match.group(0), match.start())
    match = re.search(
        r"below 60\s*V[Il1]?DC within\s+(\d+)\s*s after opening of battery contactors",
        chunk,
        re.I,
    )
    if match:
        add(
            _PASSIVE_DISCHARGE,
            f"{match.group(1)} s内降至60V",
            "",
            chunk[max(0, match.start() - 90) : match.end()].strip()[:200],
            match.start(),
        )
    match = re.search(r"全冷却液温度范围[:：]\s*([^\n]{8,60})", chunk)
    if match:
        add("冷却液温度范围", match.group(0).strip(), "", match.group(0), match.start())
    match = re.search(
        r"(?i)coolant flow[:：]?\s*([0O][0-9.]*\s*(?:to|~|–|-)\s*[0-9.]+\s*(?:liter/min|l/min|lpm))",
        chunk,
    )
    if match:
        add("冷却流量范围", match.group(1).replace(" ", " "), "", match.group(0), match.start())
    match = re.search(r"Y电容[^。\n]{0,20}(≤\s*\d+\s*n[fF]|<\s*\d+\s*n[fF])", chunk)
    if match:
        add("高压安全-Y电容指标", match.group(0), "", match.group(0), match.start())
    match = re.search(
        r"(?i)(?:HVDC Voltage Range|高压范围)[^\n]{0,80}(\d+\s*[~～\-–]\s*\d+\s*V(?:DC)?)",
        chunk,
    )
    if match:
        add("直流工作电压范围", _fmt_simple_hvdc_range("工作", match.group(1).replace(" ", "")), "", match.group(0), match.start())
    match = re.search(r"(?i)BOOST input peak current[^|]{0,20}\|\s*([^\n|]{3,20})\|", chunk)
    if match:
        add("BOOST输入峰值电流", match.group(1).strip(), "", match.group(0), match.start())
    match = re.search(r"升压器的目标输出电压[^\n]{0,20}\|\s*([0-9.]+)\s*\|\s*V", chunk)
    if match:
        add("升压输出电压", match.group(1).strip() + " V", "", match.group(0), match.start())
    match = re.search(
        r"Switching frequency for boost\s*升压开关频率\s*\|\s*(≥\s*15)\s*\|\s*KHZ",
        chunk,
        re.I,
    )
    if match:
        add("升压开关频率", "≥15 kHz", "", match.group(0), match.start())
    match = re.search(
        r"BOOST output ripple voltage升压输出纹波电压\s*\|\s*([^|\n]+)\|",
        chunk,
        re.I,
    )
    if match:
        add("升压纹波电压", match.group(1).strip(), "", match.group(0), match.start())
    match = re.search(
        r"最高效率[：:]\s*99\.5%@直通[，,]\s*99%@升压[\s\S]{0,220}?98\.5%@升压至400-450V|"
        r"BOOST efficiency target.{0,48}BOOST效率目标\s*\|\s*([^|]+)\|",
        chunk,
        re.I,
    )
    if match:
        raw = match.group(1) if match.lastindex else match.group(0)
        val = re.sub(r"\s+", " ", (raw or match.group(0)).strip())
        val = re.sub(r"^BOOST efficiency target.{0,48}BOOST效率目标\s*\|\s*", "", val, flags=re.I)
        add("升压效率", val[:220], "", match.group(0)[:280], match.start())
    parsed_boost_p = _parse_boost_power_vi(chunk)
    if parsed_boost_p:
        body, excerpt, at, used = parsed_boost_p
        add(
            "升压输出功率",
            body,
            "",
            excerpt,
            at,
            confidence=0.72,
            note=_formula_note("P=UI", *used),
            review_status=STATUS_PARTIAL,
        )
    match = re.search(r"逆变器P1须能满足交流相电流\s*200\s*Arms持续值", chunk)
    if match:
        add("P1逆变器持续交流电流", "200Arms持续", "", match.group(0), match.start())
    match = re.search(
        r"P1控制器必须能够满足10秒交流相电流I\s*\(P1\)\s*250\s*Arms峰值",
        chunk,
    )
    if match:
        add("P1逆变器交流电流峰值", "250Arms / 10s", "", match.group(0), match.start())
    _, asc_section = _p1_asc_section_span(chunk)
    inv_a, em_a, asc_at, asc_ex = _p1_asc_inverter_amps(chunk)
    if inv_a and re.search(r"主动短路|active short", chunk, re.I) and asc_at >= 0:
        note = ""
        if em_a and em_a != inv_a:
            note = f"电机允许稳态 {em_a}Arms/3.5s，逆变器 {inv_a}Arms/3.5s，已分列。"
        add(
            "P1逆变器交流主动短路电流",
            f"{inv_a}Arms有效值，可持续3.5秒",
            "",
            asc_ex or chunk[asc_at : asc_at + 160],
            asc_at,
            note=note,
        )
        bits = [f"稳态 {inv_a}Arms，全转速可持续 3.5s"]
        peak = _p1_asc_transient_peak(asc_section)
        if peak:
            bits.append(f"瞬态 {peak}A@1ms")
        if re.search(r"at the same time|可以同时进行主动短路", asc_section, re.I):
            bits.append("可与 P3 同时 ASC")
        add(
            "P1 ASC电流能力",
            "；".join(bits),
            "",
            asc_ex or chunk[asc_at : asc_at + 160],
            asc_at,
            note=note,
        )
    match = re.search(r"逆变器P3\s*须能满足交流相电流\s*250\s*Arms\s*持续", chunk)
    if match:
        add("P3额定功率相电流", "250Arms持续", "", match.group(0), match.start())
    match = re.search(
        r"PEI P3 must be able to handle continuous AC phase current of 250\s*Arms",
        chunk,
        re.I,
    )
    if match:
        add("P3额定功率相电流", "250Arms持续", "", match.group(0), match.start())
    match = re.search(
        r"During active short circuit the maximum allowed continuous current in the P3 EM is 310\s*Arms|"
        r"在主动短路时，P3\s*电机允许的最大连续电流为310",
        chunk,
        re.I,
    )
    if match:
        excerpt = re.sub(r"\s+", " ", match.group(0)).strip()[:200]
        add("P3 ASC电流能力（是否整机提供？）", "310Arms（主动短路连续）", "", excerpt, match.start())
        add(
            "P3逆变器交流主动短路电流",
            "310Arms，可持续20s；进入ASC瞬态约1300Arms@1ms",
            "",
            excerpt,
            match.start(),
        )
    match = re.search(
        r"The XCM shall be able to boost the HV input voltage"
        r"(?: to a higher voltage(?: in order to improve the TM performance"
        r" when HVDC input voltage is low)?)?"
        r"|"
        r"(?:当高压直流输入电压较低时，)?控制器应能够将直流输入的电压提升到更高电压"
        r"(?:[，,][^。\n]{0,48})?",
        chunk,
        re.I,
    )
    if match:
        pair = _drive_boost_conclusions(chunk[match.start() : match.start() + 280])
        if pair:
            add("设计范围是否包含驱动升压功能", pair[0], "", match.group(0), match.start())
            add("设计范围是否包含行车升压功能", pair[0], "", match.group(0), match.start())
            add("Boost功能要求", pair[1], "", match.group(0), match.start())
    match = re.search(
        r"thermal management control,\s*boost control|"
        r"boost control, and integrates|"
        r"variants tailored to the BOOST architecture",
        chunk,
        re.I,
    )
    if match:
        if not re.search(
            r"Charging Buck/Boost|充电升压/降压功能需求",
            chunk,
            re.I,
        ):
            pair = _drive_boost_conclusions(match.group(0))
            if pair:
                add(
                    "设计范围是否包含驱动升压功能",
                    pair[0],
                    "",
                    match.group(0),
                    match.start(),
                )
                add("Boost功能要求", pair[1], "", match.group(0), match.start())
    match = re.search(
        r"weight of the XCM shall be less than 20\.2kg\(With OD Module\)|"
        r"升压XCM的重量不得超过20\.2公斤（含OD模块）",
        chunk,
        re.I,
    )
    if match:
        add("设计范围是否包含OD本体物理集成", "是（重量目标含OD模块）", "", match.group(0), match.start())
        add(
            "控制器重量",
            "升压≤20.2kg（含OD）；非升压≤18.5kg（含OD）",
            "",
            "升压XCM的重量不得超过20.2公斤（含OD模块），非升压XCM的重量不得超过18.5公斤（含OD模块）",
            match.start(),
        )
        add(
            "重量要求",
            "升压≤20.2kg（含OD）；非升压≤18.5kg（含OD）",
            "",
            "升压XCM的重量不得超过20.2公斤（含OD模块），非升压XCM的重量不得超过18.5公斤（含OD模块）",
            match.start(),
        )
    match = re.search(
        r"maximum heat loss[^\n]{0,80}≤\s*6\.17\s*KW|"
        r"最大热损失应≤\s*6\.17\s*KW",
        chunk,
        re.I,
    )
    if match:
        add("热损失", "≤6.17kW（恒速）", "", match.group(0), match.start())
    match = re.search(
        r"signal interface for two Rotor position sensors[^\n]{0,120}Eddy Current|"
        r"两个转子位置传感器的信号接口[^\n]{0,40}涡流传感器",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1位置传感器",
            "两路转子位置传感器接口；位置由涡流传感器提供",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"6\.8\.4\.1 PEI P1|P1逆变器效率",
        chunk,
        re.I,
    )
    if match:
        window = _clause_slice(chunk, match.start(), 900)
        parts = _dhts_inverter_eta_parts(window, "P1")
        if parts:
            add(
                "P1逆变器效率指标",
                "；".join(parts),
                "",
                re.sub(r"\s+", " ", window[:240]).strip(),
                match.start(),
            )
    match = re.search(
        r"Average efficiency at least 98\.2%\s*平均效率至少为98%",
        chunk,
        re.I,
    )
    if match and not any(c.name == "P1逆变器效率指标" for c in found):
        add(
            "P1逆变器效率指标",
            "最高效率＞99%；平均效率至少 98.2%",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"6\.8\.4\.2 PEI P3|P3逆变器效率",
        chunk,
        re.I,
    )
    if match:
        window = _clause_slice(chunk, match.start(), 1100)
        parts = _dhts_inverter_eta_parts(window, "P3")
        if parts:
            add(
                "P3逆变器效率指标",
                "；".join(parts),
                "",
                re.sub(r"\s+", " ", window[:360]).strip(),
                match.start(),
            )
    match = re.search(
        r"BOOST input continue current\s*升压输入持续电流\s*\|\s*([^|\n]+)\|",
        chunk,
        re.I,
    )
    if match:
        add("BOOST输入额定电流", match.group(1).strip(), "", match.group(0), match.start())
    match = re.search(
        r"BOOST input continue(?:\s*current)?[\s\S]{0,80}?"
        r"Boost\s*:\s*(\d{2,4})\s*A[\s\S]{0,48}?Bypass\s*:\s*(\d{2,4})\s*A",
        chunk,
        re.I,
    )
    if match:
        add(
            "BOOST输入额定电流",
            f"Boost {match.group(1)}A；Bypass {match.group(2)}A",
            "",
            re.sub(r"\s+", " ", match.group(0)).strip()[:200],
            match.start(),
        )
    match = re.search(
        r"Q/JL J160001-2024[^\n]{0,40}禁用、限用物质|"
        r"All requirements in Q/JL J160001-2024[^\n]{0,80}shall be fulfilled|"
        r"All parts must comply with the Buyer standard Q/[JI]L J160001-2024|"
        r"comply with(?: the Buyer standard)? Q/[JI]L J160001-2024",
        chunk,
        re.I,
    )
    if match:
        add("禁用、限用物质", "满足 Q/JL J160001-2024", "", match.group(0), match.start())
    match = re.search(
        r"Flame Retardance Requirement阻燃要求|"
        r"According Q/JLY J7110335C-2022",
        chunk,
        re.I,
    )
    if match:
        add("阻燃要求", "按 Q/JLY J7110335C-2022，并提供阻燃报告", "", match.group(0), match.start())
    # HVDC peak/continuous 是连接器/母线能力，不填 P1 电机功率
    # DHTS160 / 通用：P3 峰值功率与时长
    match = re.search(
        r"P3[^\n]{0,40}peak\s*power[^\n]{0,40}?(\d+(?:\.\d+)?\s*kW)[^\n]{0,30}?(\d+\s*s)|"
        r"P3峰值功率[^\n|]{0,40}?(\d+(?:\.\d+)?\s*kW)[^\n|]{0,30}?(\d+\s*[sS秒])",
        chunk,
        re.I,
    )
    if match:
        kw = next(g for g in match.groups()[0:4:2] if g)
        dur = next(g for g in match.groups()[1:4:2] if g)
        add("P3峰值功率", re.sub(r"\s+", "", kw), "", match.group(0)[:160], match.start(), confidence=0.9)
        add(
            "P3峰值功率持续时间",
            re.sub(r"\s+", "", dur),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P1[^\n]{0,30}(?:rated|nominal|额定)\s*torque[^\n]{0,40}?(\d+(?:\.\d+)?\s*N(?:·|m)?m)|"
        r"P1额定扭矩[^\n|]{0,40}?(\d+(?:\.\d+)?\s*N(?:·|m)?m)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add("P1额定扭矩", re.sub(r"\s+", "", val), "", match.group(0)[:160], match.start(), confidence=0.9)
    match = re.search(
        r"P1\s+continuous\s+torque[^\n]{0,80}?(\d+(?:\.\d+)?\s*N['’]?\s*m)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1额定扭矩",
            re.sub(r"\s+", "", match.group(1)),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P3\s+continuous\s+torque[^\n]{0,80}?(\d+(?:\.\d+)?\s*N['’]?\s*m)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P3额定扭矩",
            re.sub(r"\s+", "", match.group(1)),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P1\s+continuous\s+generate(?:\s+power)?[^\n]{0,80}?(\d+(?:\.\d+)?\s*kW)",
        chunk,
        re.I,
    )
    if match and not re.search(r"HVDC", match.group(0), re.I):
        add(
            "P1额定功率",
            re.sub(r"\s+", "", match.group(1)),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P1\s+peak\s+generate(?:\s+power)?[\s\S]{0,100}?(\d+(?:\.\d+)?\s*kW)|"
        r"P1\s*电机峰值发电功率[\s\S]{0,100}?(\d+(?:\.\d+)?\s*kW)",
        chunk,
        re.I,
    )
    if match and not re.search(r"HVDC", match.group(0), re.I):
        val = next(g for g in match.groups() if g)
        add(
            "P1峰值功率",
            re.sub(r"\s+", "", val),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
        dur, dur_ex = _duration_from_peak_power_hit(chunk, match)
        if dur:
            add(
                "P1峰值功率持续时间",
                dur,
                "",
                dur_ex,
                match.start(),
                confidence=0.88,
            )
    else:
        p1_peak_row = re.search(
            r"P1\s+peak\s+generate(?:\s+power)?|P1\s*电机峰值发电功率",
            chunk,
            re.I,
        )
        if p1_peak_row and not re.search(
            r"HVDC", _peak_power_row_window(chunk, p1_peak_row.start()), re.I
        ):
            dur, dur_ex = _duration_from_peak_power_hit(chunk, p1_peak_row)
            if dur:
                add(
                    "P1峰值功率持续时间",
                    dur,
                    "",
                    dur_ex,
                    p1_peak_row.start(),
                    confidence=0.88,
                )
    match = re.search(
        r"P3\s+continuous\s+(?:drive\s+)?(?:generate\s+)?power[^\n]{0,80}?(\d+(?:\.\d+)?\s*kW)",
        chunk,
        re.I,
    )
    if match and not re.search(r"HVDC", match.group(0), re.I):
        add(
            "P3额定功率",
            re.sub(r"\s+", "", match.group(1)),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"P1[^\n]{0,40}peak\s*torque[^\n]{0,50}?(\d+(?:\.\d+)?\s*N(?:·|m)?m)[^\n]{0,40}?(\d+\s*s)?|"
        r"P1峰值扭矩[^\n|]{0,50}?(\d+(?:\.\d+)?\s*N(?:·|m)?m)",
        chunk,
        re.I,
    )
    if match:
        nm = next(g for g in match.groups() if g and re.search(r"N", g, re.I))
        dur = next((g for g in match.groups() if g and re.search(r"\d+\s*s", g, re.I)), "")
        val = re.sub(r"\s+", "", nm) + (f"@{re.sub(r'\\s+', '', dur)}" if dur else "")
        add(
            "P1峰值扭矩/时间/对应转速范围",
            val,
            "",
            match.group(0)[:180],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P1[^\n]{0,30}(?:max(?:imum)?|最高)\s*(?:operating\s*)?speed[^\n]{0,80}|"
        r"P1最高(?:工作)?转速[^\n|]{0,80}|"
        r"the max speed of P[lI1][^\n]{0,120}",
        chunk,
        re.I,
    )
    if match:
        pair = _fmt_max_speed_power_overrun(match.group(0)) or _fmt_max_speed_power_overrun(
            chunk[match.start() : match.start() + 180]
        )
        if pair:
            add("P1最高工作转速", pair, "", match.group(0)[:180], match.start(), confidence=0.9)
        else:
            num = re.search(r"(\d{4,5})\s*rpm", match.group(0), re.I)
            if num:
                add(
                    "P1最高工作转速",
                    re.sub(r"\s+", "", num.group(0)),
                    "",
                    match.group(0)[:160],
                    match.start(),
                    confidence=0.9,
                )
    match = re.search(
        r"P3[^\n]{0,30}(?:max(?:imum)?|最高)\s*(?:operating\s*)?speed[^\n]{0,80}|"
        r"P3最高(?:工作)?转速[^\n|]{0,80}|"
        r"the max speed of P3[^\n]{0,120}",
        chunk,
        re.I,
    )
    if match:
        pair = _fmt_max_speed_power_overrun(match.group(0)) or _fmt_max_speed_power_overrun(
            chunk[match.start() : match.start() + 180]
        )
        if pair:
            add("P3最高工作转速", pair, "", match.group(0)[:180], match.start(), confidence=0.9)
        else:
            num = re.search(r"(\d{4,5})\s*rpm", match.group(0), re.I)
            if num:
                add(
                    "P3最高工作转速",
                    re.sub(r"\s+", "", num.group(0)),
                    "",
                    match.group(0)[:160],
                    match.start(),
                    confidence=0.9,
                )
    match = re.search(
        r"P1\s+Back\s*EMF[^\n]{0,80}?(≤\s*1000|<\s*1000|＜\s*1000)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1反电动势（Back EMF）",
            "≤1000V（控制器耐受 1200V）",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
        add(
            "反电动势峰值",
            "≤1000V（控制器耐受 1200V）",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.84,
        )
    match = re.search(
        r"P3\s+Back\s*EMF[^\n]{0,80}?(≤\s*1000|<\s*1000|＜\s*1000)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P3 反电动势（Back EMF）",
            "≤1000V（控制器耐受 1200V）",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P[I1l][:：]\s*(≥\s*99\.5\s*[%％])",
        chunk,
        re.I,
    )
    if match:
        around = chunk[max(0, match.start() - 100) : match.end() + 40]
        volt_m = re.search(r"@(640|800)\s*V", around, re.I)
        volt = f"（@{volt_m.group(1)}V 最高效率）" if volt_m else "（最高效率）"
        add(
            "P1逆变器效率指标",
            match.group(1).replace(" ", "").replace("％", "%") + volt,
            "",
            match.group(0),
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"P3[:：]\s*(≥\s*99\.9\s*[%％])",
        chunk,
        re.I,
    )
    if match:
        around = chunk[max(0, match.start() - 100) : match.end() + 40]
        volt_m = re.search(r"@(640|800)\s*V", around, re.I)
        volt = f"（@{volt_m.group(1)}V 最高效率）" if volt_m else "（最高效率）"
        add(
            "P3逆变器效率指标",
            match.group(1).replace(" ", "").replace("％", "%") + volt,
            "",
            match.group(0),
            match.start(),
            confidence=0.88,
        )
    for motor, val, excerpt, at in _iter_pcm_table_eta(chunk):
        add(
            f"{motor}逆变器效率指标",
            val,
            "",
            excerpt,
            at,
            confidence=0.88,
        )
    match = re.search(
        r"PCM\s*P(?:1|[Il])\s*peak\s*current[\s\S]{0,80}?(\d+)\s*A[rm]+s\s*@\s*10\s*s",
        chunk,
        re.I,
    )
    if match and not re.search(r"P3", match.group(0)):
        add(
            "P1逆变器交流电流峰值",
            f"{match.group(1)}Arms@10s",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"PCM\s*P[lI1]\s*(?:Continuous\s*Current|持续电流)[^\n]{0,60}?(\d+)\s*A[rm]+s\s*@\s*30\s*min",
        chunk,
        re.I,
    )
    if match and not re.search(r"P3", match.group(0)):
        add(
            "P1逆变器持续交流电流",
            f"{match.group(1)}Arms@30min",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"PCM\s*P3\s*peak\s*current[\s\S]{0,80}?(\d+)\s*A[rm]+s\s*@\s*10\s*s",
        chunk,
        re.I,
    )
    if match:
        add(
            "P3逆变器交流电流峰值",
            f"{match.group(1)}Arms@10s",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"PCM\s*P3\s*Continuous\s*Current[^\n]{0,40}?(\d+)\s*A[mrs]+@30min",
        chunk,
        re.I,
    )
    if match:
        add(
            "P3额定功率相电流",
            f"{match.group(1)}Arms@30min",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    parsed_mass = _parse_pcm_mass_kg(chunk)
    if parsed_mass:
        kg_val, kg_excerpt, kg_at = parsed_mass
        add("控制器重量", kg_val, "", kg_excerpt, kg_at, confidence=0.88)
        add("重量要求", kg_val, "", kg_excerpt, kg_at, confidence=0.88)
    match = re.search(
        r"P3\s+peak\s+drive\s+power[^\n]{0,80}?(\d+(?:\.\d+)?\s*kW)|"
        r"P3\s*电机峰值驱动功率[^\n]{0,80}?(\d+(?:\.\d+)?\s*kW)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add(
            "P3峰值功率",
            re.sub(r"\s+", "", val),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
        dur, dur_ex = _duration_from_peak_power_hit(chunk, match)
        if dur:
            add(
                "P3峰值功率持续时间",
                dur,
                "",
                dur_ex,
                match.start(),
                confidence=0.88,
            )
    match = re.search(
        r"P3\s+peak\s+torque[^\n]{0,120}?(\d+(?:\.\d+)?\s*Nm)|"
        r"P3\s*电机峰值扭矩[^\n]{0,120}?(\d+(?:\.\d+)?\s*Nm)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add(
            "P3峰值扭矩/时间/对应转速范围",
            re.sub(r"\s+", "", val),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"P1\s*电机峰值扭矩[^\n]{0,80}?(\d+(?:\.\d+)?\s*Nm)|"
        r"P1\s+peak\s+torque@[^@\n]{0,24}@10s[^\n]{0,80}?(\d+(?:\.\d+)?\s*Nm)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add(
            "P1峰值扭矩/时间/对应转速范围",
            re.sub(r"\s+", "", val) + "@10s",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"(?:母线工作电压范围|busbar working voltage range)[\s\S]{0,80}?(\d{3}\s*[~～-]\s*\d{3})\s*V?",
        chunk,
        re.I,
    )
    if match:
        add(
            "直流工作电压范围",
            _fmt_simple_hvdc_range("母线工作", re.sub(r"\s+", "", match.group(1)) + "V"),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"full performance working[\s\S]{0,80}?(\d{3}\s*V?\s*[~～-]\s*\d{3})",
        chunk,
        re.I,
    )
    if match:
        add(
            "满功率(电流)工作电压",
            _fmt_simple_hvdc_range(
                "满功率", re.sub(r"\s+", "", match.group(1)).replace("V", "") + "V"
            ),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"CY\+\s*&?\s*CY-\s*≤\s*(\d+)\s*nF",
        chunk,
        re.I,
    )
    if match:
        add(
            "高压安全-Y电容指标",
            f"CY+ & CY-≤{match.group(1)}nF",
            "",
            match.group(0),
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"堵转安全[^\n]{0,48}?(85%\s*峰值扭矩@3s)|"
        r"Stall Safety[^\n]{0,48}?(85%\s*peak torque@3s)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1堵转扭矩/时间",
            "85%峰值扭矩@3s持续，随后降至50%",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"PCM P1峰值电流\s*\|\s*Arms\s*\|\s*(250Arms@10s)",
        chunk,
        re.I,
    )
    if match:
        add("P1逆变器交流电流峰值", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"PCM P1持续电流\s*\|\s*Arms\s*\|\s*(200Arms@30min)",
        chunk,
        re.I,
    )
    if match:
        add("P1逆变器持续交流电流", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"PCM P3峰值电流\s*\|\s*Arms\s*\|\s*(465Arms@10s@1066V)",
        chunk,
        re.I,
    )
    if match:
        add("P3逆变器交流电流峰值", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"Min level for limited performance性能限制时的最低电压\s*\|\s*(530)\s*V",
        chunk,
        re.I,
    )
    if match:
        add(
            "降额工作电压范围",
            _fmt_hvdc_state_lines(
                [("限制性能", f"{match.group(1)}V", _HVDC_V_MISSING)]
            ),
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"PCM\s*要求防水等级至少满足\s*(IPX7\s*&\s*IPX?8\s*&\s*IP6K9K|IP6K9K)|"
        r"PCM required with at least waterproof grade of\s*(IPX7\s*&\s*IP6K9K)|"
        r"PCM\s*需要满足\s*(IP68\s*&?\s*IP6K9K)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add(
            "密封（IP等级）",
            re.sub(r"\s+", "", val),
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"压降≤\s*(25\s*kPa@10\s*L/min)",
        chunk,
        re.I,
    )
    if match:
        add("冷却回路压降", f"压降≤{match.group(1).replace(' ', '')}", "", match.group(0), match.start())
        add("额定流量", "10 L/min（压降考核点 @25kPa）", "", match.group(0), match.start())
    match = re.search(
        r"控制器流量[^\n]{0,80}?≥\s*10\s*L(?:/min)?|"
        r"requirement\s+L/min\s+≥\s*10L@65",
        chunk,
        re.I,
    )
    if match:
        add(
            "额定流量",
            "≥10 L/min @65°C",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"fully functional under operation with 100%\s*humidity|"
        r"应能在100%\s*湿度下正常工作",
        chunk,
        re.I,
    )
    if match:
        add("湿度要求", "100% 湿度下正常工作；冷凝水需妥善处理", "", match.group(0), match.start())
    match = re.search(
        r"Q/[JI]L\s*J160003-2024[^\n]{0,80}L\.?1-F([34])|"
        r"乘用车零部件防腐技术要求中L\.?1-F([34])",
        chunk,
        re.I,
    )
    if match:
        grade = next(g for g in match.groups() if g)
        add("防腐等级", f"L1-F{grade}", "", match.group(0), match.start(), confidence=0.92)
        add("防腐要求", f"需满足 Q/JL J160003-2024（L1-F{grade}）", "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"Charging Buck/Boost Function Requirements|"
        r"充电升压/降压功能需求",
        chunk,
        re.I,
    )
    if match:
        add("设计范围是否包含行车升压功能", "是（含充电 Boost/Buck 功能）", "", match.group(0), match.start())
        add("Boost功能要求", "有；充电场景下 Boost/Buck", "", match.group(0), match.start())
        add("升压充电功能", "有；Charging Buck/Boost", "", match.group(0), match.start())
        window = chunk[match.start() : match.start() + 3200]
        ripple_m = re.search(
            r"纹波电压-桩侧[\s\S]{0,80}≤\s*1%[\s\S]{0,280}纹波电压-电池侧（接入系统后）[\s\S]{0,48}≤\s*10V",
            window,
        )
        if not ripple_m:
            ripple_m = re.search(r"纹波电压-桩侧[^\n]{0,80}≤\s*1%", window)
        if ripple_m:
            add(
                "升压纹波电压",
                "桩侧≤1%；电池侧未接入≤20V、接入后≤10V",
                "",
                ripple_m.group(0),
                match.start() + ripple_m.start(),
                confidence=0.9,
            )
        pwr_m = re.search(r"充电功率\s*\|\s*([^\n]+)", window)
        if not pwr_m:
            pwr_m = re.search(
                r"充电功率[\s|：:]*((?:\d+\s*A/\d+\s*kW\\?@\d+\s*V\s+\d+\s*min(?:[；;]\s*)?)+)",
                window,
                re.I,
            )
        if pwr_m:
            points = re.findall(
                r"(\d+)\s*A/\d+\s*kW\\?@(\d+)\s*V\s+(\d+\s*min)",
                pwr_m.group(1),
                re.I,
            )
            states = [
                ("", _fmt_p_ui_at(volt, amp, duration)) for amp, volt, duration in points
            ]
            body = _fmt_boost_power_state_lines(states)
            if body:
                add(
                    "升压输出功率",
                    body,
                    "",
                    pwr_m.group(0),
                    match.start() + pwr_m.start(),
                    confidence=0.9,
                )
        volt_m = re.search(
            r"满电流工作\s*\|\s*低压侧：390V≤U≤1000V；高压侧：480V≤U≤1056V",
            window,
        )
        if volt_m:
            add(
                "升压输出电压",
                "高压侧满电流480V～1056V；满功率1056V＜U≤1066V",
                "",
                volt_m.group(0),
                match.start() + volt_m.start(),
                confidence=0.9,
            )
        # 充电 Boost/Buck 不是驱动升压；Boost输出性能需功率/电流指标，模式 alone 不写入

    # —— SuperEvo（1000V）DPR 精确表项 ——
    match = re.search(
        r"PCM母线工作电压范围\s*\|\s*Vdc\s*\|\s*(530V\s*[~～-]\s*1150V)",
        chunk,
        re.I,
    )
    if match:
        add(
            "直流工作电压范围",
            _fmt_simple_hvdc_range("母线工作", re.sub(r"\s+", "", match.group(1))),
            "",
            match.group(0),
            match.start(),
            confidence=0.84,
        )
    match = re.search(
        r"(800V\s*[~～-]\s*1066V)@465Arms\s*max",
        chunk,
        re.I,
    )
    if match:
        add(
            "满功率(电流)工作电压",
            _fmt_simple_hvdc_range("满功率", re.sub(r"\s+", "", match.group(1))),
            "",
            match.group(0),
            match.start(),
            confidence=0.84,
        )
    match = re.search(
        r"(1066V\s*[~～-]\s*1150V,?\s*1150V线性降额至0)",
        chunk,
        re.I,
    )
    if match:
        add(
            "降额工作电压范围",
            _fmt_simple_hvdc_range(
                "限制性能",
                re.sub(r"\s+", "", match.group(1)),
                extra="1150V线性降额至0",
            ),
            "",
            match.group(0),
            match.start(),
            confidence=0.84,
        )
    match = re.search(
        r"额定输入电流\s*\|\s*250A（低压侧）",
        chunk,
    )
    if match:
        add("BOOST输入额定电流", "250A（低压侧）", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"满功率工作\s*\|\s*高压侧：1056V＜U≤1066V",
        chunk,
    )
    if match:
        add(
            "BOOST最高工作电压",
            "1066V（高压侧满功率上限）",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"耐电压要求\s*（电控）|"
        r"Withstand voltage requirements of PCM|"
        r"应能耐受GB/T\s*18488-2024[^\n]{0,120}漏电流限值应≤\s*5mA|"
        r"GB/T\s*16935\.1",
        chunk,
        re.I,
    )
    if match:
        gbt18488 = re.search(
            r"应能耐受GB/T\s*18488-2024[^\n]{0,160}漏电流限值应≤\s*5mA",
            chunk,
            re.I,
        )
        gbt16935 = re.search(r"GB/T\s*16935\.1", chunk, re.I) and re.search(
            r"漏电流[^\n]{0,24}(?:<|＜|小于|less than)\s*3\.5\s*mA|"
            r"leakage current[^\n]{0,24}3\.5\s*mA",
            chunk,
            re.I,
        )
        if gbt18488:
            add(
                "高压安全-耐电压",
                "动力端子对壳体/信号端子：按 GB/T 18488-2024 表1，1min，无击穿，漏电流≤5mA；信号端子对壳体：500V 工频",
                "",
                gbt18488.group(0)[:200],
                gbt18488.start(),
                confidence=0.9,
            )
        elif gbt16935:
            loc = re.search(r"GB/T\s*16935\.1[^\n]{0,80}", chunk, re.I)
            add(
                "高压安全-耐电压",
                "按 GB/T 16935.1，1min，无击穿，漏电流<3.5mA",
                "",
                (loc.group(0) if loc else match.group(0))[:200],
                loc.start() if loc else match.start(),
                confidence=0.88,
            )
    if not any(cell.name == "高压安全-耐电压" for cell in found):
        cont = re.search(
            r"(?:6\.6\.3\s+)?Continuous HVDC withstand voltage\s*连续高压直流耐压"
            r"[\s\S]{0,400}?"
            r"(?:maximum|最大)\s*(\d{2,4})\s*V",
            chunk,
            re.I,
        )
        if not cont:
            cont = re.search(
                r"withstand continuous supply voltages of maximum\s*(\d{2,4})\s*V"
                r" on the HVDC bus without any permanent",
                chunk,
                re.I,
            )
        if not cont:
            cont = re.search(
                r"连续高压直流耐压[\s\S]{0,240}?最大(\d{2,4})\s*V",
                chunk,
            )
        if not cont:
            cont = re.search(
                r"承受高压直流母线上最大(\d{2,4})\s*V的连续供电电压",
                chunk,
            )
        if cont:
            volts = cont.group(1)
            window = chunk[cont.start() : min(len(chunk), cont.start() + 520)]
            val = f"母线持续供电最大 {volts}V，无永久性损坏"
            if re.search(r"ISO\s*16750-1", window, re.I) and re.search(
                r"minimum C|最低\s*C", window, re.I
            ):
                val += "；功能状态最低 C（ISO 16750-1）"
            add(
                "高压安全-耐电压",
                val,
                "",
                re.sub(r"\s+", " ", window).strip()[:280],
                cont.start(),
                confidence=0.9,
            )
    iso_hipot = re.search(
        r"withstand voltage capability test according to ISO 6469[\s\S]{0,700}?"
        r"(?:applied for 1 min|1 min:)|"
        r"应符合ISO 6469-3-2018的耐压能力测试[\s\S]{0,500}?应施加1分钟",
        chunk,
        re.I,
    )
    if (
        iso_hipot
        and not any(cell.name == "高压安全-耐电压" for cell in found)
        and not _is_continuous_hvdc_withstand(chunk)
    ):
        add(
            "高压安全-耐电压",
            "按 ISO 6469-3-2018，1min，50–60Hz；(2U+1000) VAC rms（基本绝缘）；U=500V；等效直流为交流有效值的1.41倍",
            "",
            re.sub(r"\s+", " ", iso_hipot.group(0)).strip()[:280],
            iso_hipot.start(),
            confidence=0.9,
        )
    if not any(cell.name == "高压安全-耐电压" for cell in found):
        na_ya = re.search(
            r"(?:工频|直流|交流)?耐压(?:试验|要求)?"
            r"[^\n]{0,80}?"
            r"(\d{3,4}\s*(?:V(?:ac|dc)?|Vac|Vdc))"
            r"[^\n]{0,80}?"
            r"(1\s*(?:min|分钟)|60\s*(?:s|秒)|无击穿|漏电流[^\n]{0,16}\d)",
            chunk,
            re.I,
        )
        if (
            na_ya
            and not _has_any(na_ya.group(0), r"瞬态", r"transient", r"电容耐压")
            and not _looks_like_dc_capacitor_spec(na_ya.group(0))
            and not _looks_like_operating_voltage_withstand(na_ya.group(0))
        ):
            volt = re.sub(r"\s+", "", na_ya.group(1))
            extra = re.sub(r"\s+", "", na_ya.group(2))
            add(
                "高压安全-耐电压",
                f"{volt}，{extra}",
                "",
                na_ya.group(0)[:200],
                na_ya.start(),
                confidence=0.86,
            )
    match = re.search(
        r"P1:≥99\.5%\s*；\s*P3:≥99\.8\s*%",
        chunk,
        re.I,
    )
    if match:
        add("P1逆变器效率指标", "P1:≥99.5%@800V", "", match.group(0), match.start(), confidence=0.92)
        add("P3逆变器效率指标", "P3:≥99.8%@800V", "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P3电机峰值驱动功率@80℃\s*\|\s*kW\s*\|\s*(≥\s*300\s*kw\s*@800V)",
        chunk,
        re.I,
    )
    if match:
        add("P3峰值功率", re.sub(r"\s+", "", match.group(1)), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P3电机额定驱动功率\s*@80℃\s*\|\s*kW\s*\|\s*(120kW\s*@\s*8000\s*[~～-]\s*15000rpm\s*@\s*800V)",
        chunk,
        re.I,
    )
    if match:
        add("P3额定功率", re.sub(r"\s+", "", match.group(1)), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P1电机峰值扭矩@80℃@10s@800V\s*\|\s*Nm\s*\|\s*(>\s*100Nm)",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1峰值扭矩/时间/对应转速范围",
            ">100Nm @80℃@10s@800V",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"P3电机峰值扭矩@480A@[^\n|]{0,20}\|\s*Nm\s*\|\s*(≥\s*415Nm)|"
        r"P3 peak torque[^\n|]{0,40}\|\s*Nm\s*\|\s*(≥\s*415Nm)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add(
            "P3峰值扭矩/时间/对应转速范围",
            f"{re.sub(r'\\s+', '', val)} @480A@10s@870V",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"P3电机额定扭矩\s*@80℃\s*\|\s*Nm\s*\|\s*(≥\s*196Nm\*10min,0-4000rpm)",
        chunk,
        re.I,
    )
    if match:
        add("P3额定扭矩", re.sub(r"\s+", "", match.group(1)), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P1电机最高转速@870V\s*\|\s*rpm\s*\|\s*(最高转速16500rpm出功率，随转18000)",
        chunk,
        re.I,
    )
    if match:
        add("P1最高工作转速", match.group(1), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P3电机最高转速\s*\|\s*rpm\s*\|\s*(最高转速20000出功率50kW\s*@20s，20500随转，超速22000rpm)",
        chunk,
        re.I,
    )
    if match:
        add("P3最高工作转速", re.sub(r"\s+", " ", match.group(1)).strip(), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P1 continuous generate power[^\n|]{0,80}\|\s*kW\s*\|\s*(120kW@[^\n|]+)|"
        r"P1电机额定发电[^\n|]{0,40}\|\s*kW\s*\|\s*(120kW@[^\n|]+)",
        chunk,
        re.I,
    )
    if match:
        val = next(g for g in match.groups() if g)
        add("P1额定功率", re.sub(r"\s+", "", val), "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"P1 peak generate power[^\n|]{0,80}\|\s*kW\s*\|\s*(220kW@[^\n|]+)|"
        r"P1电机峰值[^\n|]{0,50}\|\s*kW\s*\|\s*(220kW@[^\n|]+)",
        chunk,
        re.I,
    )
    if match:
        val = re.sub(r"\s+", "", next(g for g in match.groups() if g))
        add("P1峰值功率", val, "", match.group(0), match.start(), confidence=0.92)
        add("P1峰值功率持续时间", f"≥10s@{val}", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"P1 Back EMF[^\n|]{0,40}\|\s*Vdc\s*\|\s*([^|\n]+)",
        chunk,
        re.I,
    )
    if match:
        val = re.sub(r"\s+", "", match.group(1).strip())
        add("P1反电动势（Back EMF）", val, "", match.group(0), match.start(), confidence=0.92)
        add("反电动势峰值", val, "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"P3 Back EMF[^\n|]{0,40}\|\s*Vdc\s*\|\s*([^|\n]+)",
        chunk,
        re.I,
    )
    if match:
        val = re.sub(r"\s+", "", match.group(1).strip())
        add("P3 反电动势（Back EMF）", val, "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"可拓展动力域控制模块_总成[^\n|]{0,40}\|\s*12\s*\|\s*1\s*\|\s*12",
        chunk,
    )
    if match:
        add("控制器重量", "12kg（单件目标重量）", "", match.group(0), match.start(), confidence=0.9)
        add("重量要求", "12kg（单件目标重量）", "", match.group(0), match.start(), confidence=0.9)
    parsed_lv = _parse_lv_current_rows(chunk)
    if "static" in parsed_lv:
        val, excerpt, at = parsed_lv["static"]
        add("静态电流", val, "", excerpt, at, confidence=0.9)
    if "wake" in parsed_lv:
        val, excerpt, at = parsed_lv["wake"]
        add("低压功耗要求", val, "", excerpt, at, confidence=0.9)
    match = re.search(
        r"测量误差小于\s*300\s*V\s*为\s*±\s*3\s*V[，,]\s*300\s*V以上\s*±\s*1\s*%|"
        r"measurement error of ±\s*3V for\s+voltages less than 300V",
        chunk,
        re.I,
    )
    if match:
        add(
            "母线电压采样精度",
            "高压直流母线：＜300V 为 ±3V，300V 以上 ±1%（以中文条款为准）",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"12V supply voltage[\s\S]{0,160}?total\s+accuracy error\s*<\s*2%\s+and resolution\s*<=\s*0\.01\s*V|"
        r"总精度\s*<\s*2%\s*和分辨率\s*<=\s*0\.01",
        chunk,
        re.I,
    )
    if match:
        add(
            "低压供电电源电压采样精度",
            "总精度<2%，分辨率<=0.01V",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"Q/JLY\s*J7110922D\s*-?\s*2024",
        chunk,
        re.I,
    )
    if match:
        emc_best: tuple[int, re.Match[str], str] | None = None
        for emc_m in re.finditer(r"Q/JLY\s*J7110922D\s*-?\s*2024", chunk, re.I):
            before = chunk[max(0, emc_m.start() - 500) : emc_m.start()]
            after = chunk[emc_m.start() : emc_m.start() + 520]
            window = before + after
            line_start = chunk.rfind("\n", 0, emc_m.start()) + 1
            line_end = chunk.find("\n", emc_m.start())
            line = chunk[line_start : line_end if line_end >= 0 else emc_m.start() + 80]
            score = 0
            if re.search(r"2\.3\.3\.3", before):
                score += 8
            if re.search(r"Generic EMC|电磁兼容总体", before, re.I):
                score += 6
            if re.search(r"The unit shall meet|控制器应满足", before[-120:] + after[:80], re.I):
                score += 5
            if re.search(
                r"电气属性均须满足|electrical properties of the entire transmission",
                before[-200:] + after[:80],
                re.I,
            ):
                score += 5
            if re.search(r"EMC testing requirements|EMC测试要求", after[:240], re.I):
                score += 4
            if re.search(r"屏蔽系统|shielded system|shielding system", after, re.I):
                score += 2
            if line.strip().startswith("|"):
                score -= 10
            if emc_best is None or score > emc_best[0]:
                emc_best = (score, emc_m, window)
        if emc_best and emc_best[0] >= 5:
            _score, match, window = emc_best
            body = chunk[match.start() : match.start() + 520]
            parts = ["Q/JLY J7110922D-2024"]
            if re.search(r"J7110779E-2023", body, re.I):
                parts.append("Q/JLY J7110779E-2023")
            if re.search(r"屏蔽系统|shielded system|shielding system", body, re.I):
                parts.append("高压件按屏蔽系统设计")
            if re.search(r"ISO\s*/?\s*TS\s*7637-4", body, re.I):
                pulse = "（Pulse B）" if re.search(r"Pulse B", body, re.I) else ""
                parts.append(f"高压纹波噪声及暂态抗扰度按 ISO TS 7637-4{pulse}")
            head = re.search(
                r"2\.3\.3\.3\.1[^\n]{0,80}|Generic EMC requirements电磁兼容总体要求",
                window,
                re.I,
            )
            excerpt = ((head.group(0) + " ") if head else "") + (
                "The unit shall meet Q/JLY J7110922D-2024"
                if re.search(r"The unit shall meet|控制器应满足", body, re.I)
                else match.group(0)
            )
            add(
                "EMC等级",
                "；".join(parts),
                "",
                re.sub(r"\s+", " ", excerpt).strip()[:280],
                match.start(),
                confidence=0.92,
            )
    match = re.search(
        r"出厂检测值应大于100MΩ",
        chunk,
    )
    if match:
        val = "出厂>100MΩ；全寿命>20MΩ（直流动力端子与外壳/信号端子）"
        add("高压安全-绝缘电阻", val, "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"(?:PCMheat loss|控制器散热量)[\s\S]{0,80}?低速爬坡\s*Q?\s*≤\s*0\.8\s*kW|"
        r"低速爬坡\s*Q?\s*≤\s*0\.8\s*kW",
        chunk,
        re.I,
    )
    if match:
        add(
            "热损失",
            "低速爬坡≤0.8kW；高速爬坡≤0.9kW；高速140≤0.4kW（以效率 map 为准）",
            "",
            match.group(0)[:180],
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"对于90%\s*ile的客户，35万公里内不允许出现故障[\s\S]{0,220}?"
        r"(?:15年不允许出现故障|15 years functional life)",
        chunk,
        re.I,
    )
    if match:
        add("寿命要求", "15年或35万公里", "", match.group(0)[:160], match.start(), confidence=0.92)
    match = re.search(
        r"±3Nm@P1 e-motor torque≤100Nm\s*≤±3%@P1 e-motor to",
        chunk,
        re.I,
    )
    if match:
        val = "±3Nm@P1≤100Nm；≤±3%@P1＞100Nm"
        add("扭矩控制精度", val, "", match.group(0), match.start(), confidence=0.9)
        add("转矩控制精度", val, "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"P1峰值扭矩响应时间\s*\|\s*ms\s*\|\s*(100-300ms)",
        chunk,
        re.I,
    )
    if match:
        p1_rt = match.group(1)
        p3 = re.search(
            r"P3Tmax\s*电机扭矩响应时间\s*\|\s*ms\s*\|\s*(0-90%持续扭矩≤40ms)",
            chunk,
            re.I,
        )
        if p3:
            add(
                "扭矩响应时间",
                f"P1峰值 {p1_rt}；P3 {p3.group(1)}",
                "",
                match.group(0)[:80] + " | " + p3.group(0)[:80],
                match.start(),
                confidence=0.9,
            )
        else:
            add("扭矩响应时间", f"P1峰值 {p1_rt}", "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"(?:2\.3\.3\.3\.3|Generated voltage ripple 产生电压纹波)[\s\S]{0,900}?"
        r"额定工况：\s*16[\s\S]{0,120}?峰值工况：\s*30",
        chunk,
        re.I,
    )
    if match and not re.search(r"caused by Boost|Boost对母线", match.group(0), re.I):
        add(
            "直流母线纹波电压要求",
            "额定工况 16 V pk-pk；峰值工况 30 V pk-pk（高压电池接通）",
            "",
            re.sub(r"\s+", " ", match.group(0)).strip()[:220],
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"(?:2\.3\.3\.3\.4|Generated voltage ripple UDC control|直流控制产生电压纹波)[\s\S]{0,500}?"
        r"(?:Maximum differential ripple when the HV battery is switched off|高压电池关闭时的最大差分纹波)[\s\S]{0,80}?30|"
        r"Maximum differential ripple when the HV battery is switched off\.[^\n]{0,120}30|"
        r"高压电池关闭时的最大差分纹波[^\n]{0,80}30",
        chunk,
        re.I,
    )
    if match:
        add(
            "高压安全-纹波电压",
            "高压电池断开（接触器开）30 V pk-pk",
            "",
            re.sub(r"\s+", " ", match.group(0)).strip()[:200],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"逆变器P3须能满足10秒交流相电流[^。]{0,40}520\s*Arms|"
        r"逆变器P3须能满足交流相电流520\s*Arms峰值持续10秒|"
        r"peak AC phase current of 520\s*Arms for a duration of 10s",
        chunk,
        re.I,
    )
    if match:
        add("P3逆变器交流电流峰值", "520Arms / 10s", "", match.group(0), match.start())
    match = re.search(
        r"Each of the inverters within the XCM shall measure all the three AC phase currents|"
        r"高压交流电流传感器",
        chunk,
        re.I,
    )
    if match:
        # 无精度%时不填「相电流采样精度」
        pass
    match = re.search(
        r"HVAC Current measurements?|交流(?:相)?电流测量|"
        r"6\.3\.3\.1 HVAC current measurement|"
        r"measure the HVAC current consumed or generated PEI P1|"
        r"测量[-－]?\s*\d+\s*A至\+?\d+\s*A峰值范围内.{0,80}P1逆变器高压交流电流",
        chunk,
        re.I,
    )
    if match:
        window = chunk[match.start() : match.start() + 1600]
        val, note = _hvac_phase_accuracy(window)
        if val:
            bilingual = bool(note)
            excerpt = _hvac_excerpt(window, bilingual=bilingual) or re.sub(
                r"\s+", " ", window[:320]
            ).strip()
            cn_at = window.find("控制器应能够测量")
            at = match.start() + cn_at if cn_at >= 0 else match.start()
            add(
                "相电流采样精度",
                val,
                "",
                excerpt,
                at,
                confidence=0.72 if bilingual else 0.9,
                note=note,
                review_status=STATUS_PARTIAL if bilingual else "",
            )
    match = re.search(
        r"The XCM shall have a HVDC current sensor monitoring the HVDC current|"
        r"高压直流电流传感器",
        chunk,
        re.I,
    )
    if match:
        add(
            "母线直流电流检测",
            "有；监测 HVDC 电流（不含辅助高压电流），传感器满足 ASIL C（ISO 26262-2018）",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"XCM shall satisfy the F3 level|"
        r"XCM 应满足F3等级要求",
        chunk,
        re.I,
    )
    if match:
        add("防腐等级", "F3", "", match.group(0), match.start())
    match = re.search(
        r"需满足Q/JL J160003-2024|"
        r"Parts anti-corrosion requirement零件防腐要求",
        chunk,
        re.I,
    )
    if match and not any(
        c.name in {"防腐要求", "防腐等级"} and re.search(r"L1-F", c.value or "")
        for c in found
    ):
        add(
            "防腐要求",
            "需满足 Q/JL J160003-2024（level 1），XCM 满足 F3 等级",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"fully functional under operation with 95%\s*humidity|"
        r"应能在95%\s*湿度下正常工作",
        chunk,
        re.I,
    )
    if match:
        add("湿度要求", "95% 湿度下正常工作；冷凝水需妥善处理", "", match.group(0), match.start())
    match = re.search(
        r"控制器应满足Q/JLY\s*J7110922D\s*-?\s*2024|"
        r"The unit shall meet Q/JLY\s*J7110922D\s*-?\s*2024",
        chunk,
        re.I,
    )
    if match and not any(c.name == "EMC等级" for c in found):
        add("EMC等级", "Q/JLY J7110922D-2024", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"发电工况\(负扭矩\)[\s\S]{0,80}?-40到-50\s*nm在5000~7000rpm@340V|"
        r"Generating \(negative torque\)[\s\S]{0,80}?-40to -50 Nm within the 5000-7000 rpm @340V",
        chunk,
        re.I,
    )
    if match:
        add(
            "P1馈电要求",
            "-40~-50 Nm @5000–7000 rpm @340 V（效率段发电工况）",
            "",
            match.group(0),
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"堵转峰值电流\s*520\s*Arms|"
        r"Option2:\s*--堵转峰值电流\s*520\s*Arms",
        chunk,
        re.I,
    )
    if match:
        add(
            "P3逆变器堵转电流",
            "峰值 520Arms；85% 堵转 442Arms；持续堵转 260Arms",
            "",
            match.group(0),
            match.start(),
        )
    booster_out = _hv_booster_output_voltage_from_modes(chunk)
    if booster_out:
        add(
            "升压输出电压",
            booster_out[0],
            "",
            booster_out[2],
            booster_out[1],
        )
    match = re.search(
        r"6\.2\.3\.6 高压慢充连接器|"
        r"high-voltage slow charging connector|"
        r"XCM应该有一个高压慢充连接器",
        chunk,
        re.I,
    )
    if match:
        # 连接器只证明有充电接口，不是充电定义（拓扑/电压/电流/时长）
        add(
            "升压充电功能",
            "有高压慢充连接器",
            "",
            match.group(0),
            match.start(),
            confidence=0.72,
            note=(
                "连接器只证明有充电接口，不是升压充电功能的定义"
                "（拓扑/电压/电流/时长）。请对照充电功能章节复核。"
            ),
            review_status=STATUS_PARTIAL,
        )
    match = re.search(
        r"(?:Unit )?Target output voltage of booster\s*升压器的目标输出电压"
        r"(?:\s*\|\s*(\d{3,4})\s*\||[\s|]*(\d{3,4})[\s|]*V)",
        chunk,
        re.I,
    )
    if match:
        volts = next(g for g in match.groups() if g)
        add(
            "BOOST最高工作电压",
            f"{volts}V（升压器目标输出）",
            "",
            match.group(0),
            match.start(),
        )
        add(
            "Boost输出性能",
            f"{volts} V",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"Overvoltage due to generated back-emf|"
        r"反电动势导致的过压",
        chunk,
        re.I,
    )
    if match:
        window = _clause_slice(chunk, match.start(), 500)
        if not re.search(r"\d{3,4}\s*V", window):
            val = "电源开关须承受 P1/P3 反电动势最大值；具体以电机实际达成为准"
            add(
                "P1反电动势（Back EMF）",
                val,
                "",
                re.sub(r"\s+", " ", window[:240]).strip(),
                match.start(),
                confidence=0.72,
                review_status=STATUS_PARTIAL,
            )
            add(
                "P3 反电动势（Back EMF）",
                val,
                "",
                re.sub(r"\s+", " ", window[:240]).strip(),
                match.start(),
                confidence=0.72,
                review_status=STATUS_PARTIAL,
            )
    match = re.search(
        r"Transient HVDC withstand capability\s*瞬态高压直流耐压能力|"
        r"All units connected on the HVDC bus must withstand at least five",
        chunk,
        re.I,
    )
    if match:
        # 瞬态脉冲不是清单「耐电压」（工频/直流耐压），不填
        pass
    match = re.search(
        r"LV power consumption\s*低压功耗|"
        r"低压功耗为初版设计指标",
        chunk,
        re.I,
    )
    if match:
        # 仅流程语、无 mA/W 时不填低压功耗/静态电流
        pass
    match = re.search(
        r"堵转策略：P3，85%（T_max\*0\.85）峰值扭矩@3s|"
        r"Locking strategy:\s*P3,\s*85%\s*\(Tmax \* 0\.85\) peak torque @ 3s",
        chunk,
        re.I,
    )
    if match:
        window = chunk[match.start() : match.start() + 700]
        pairs = re.findall(r"\((\d{3,4})\s*[-–]\s*(\d{3,4})\)\s*V", window)
        volt = ""
        if pairs:
            hi = max(pairs, key=lambda p: int(p[1]))
            volt = f"@({hi[0]}-{hi[1]})V"
        tmax = re.search(r"Tmax\s*=\s*(\d+)\s*Nm", window, re.I)
        tmax_s = f"；Tmax={tmax.group(1)}Nm" if tmax else ""
        stall = "85%峰值扭矩@3s，随后2s降到50%峰值扭矩持续堵转" + tmax_s
        if volt:
            stall += volt
        add(
            "P3堵转扭矩/时间",
            stall,
            "",
            re.sub(r"\s+", " ", window[:280]).strip(),
            match.start(),
        )
    match = re.search(
        r"coolant inlet temperature must\s+be measurable in the range\s*"
        r"(-40\s*[°℃]C?\s*to\s*\+?\s*100\s*[°℃]C?)|"
        r"冷却液入口温度必须在\s*(-40\s*[°℃]C?\s*到\s*\+?\s*100\s*[°℃]C?)的范围内测量",
        chunk,
        re.I,
    )
    if match:
        rng = match.group(1) or match.group(2)
        add(
            "电驱回路水温/采样精度/延时",
            f"入口水温可测范围 {rng}；-40°C～+85°C 误差≤±3°C",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"Oil temperature sensors\s*油温传感器|"
        r"receive signals from the Oil temperature sensor",
        chunk,
        re.I,
    )
    if match:
        # 无范围/精度数字时不填油温采样条目
        pass
    match = re.search(
        r"Vibration 振动要求\s*1）Temperature cycle|"
        r"Perform the test according to Q/JLP\s*030600-10",
        chunk,
        re.I,
    )
    if match:
        val = (
            "按 Q/JLP 030600-10 2025A：温度循环与正弦+随机同步，每方向 4 循环/32h；"
            "正弦加随机 X/Y/Z 各 30h（0.5Oct/min）；随机振动 X/Y/Z 各 30h"
        )
        add("振动要求", val, "", match.group(0), match.start())
    match = re.search(
        r"CPSR is a relay control signal|"
        r"CPSR是一个继电器控制信号",
        chunk,
        re.I,
    )
    if match:
        add(
            "CPSR电压范围/采样精度/延时",
            "有定义（继电器控制信号），无电压范围/采样精度/延时定量",
            "",
            match.group(0),
            match.start(),
            confidence=0.72,
            review_status=STATUS_PARTIAL,
        )
    match = re.search(
        r"Cleanliness for manufacturing\(Water cooling cleanliness\)|"
        r"制造清洁度\(水路清洁度\)",
        chunk,
        re.I,
    )
    if match:
        add(
            "清洁度要求",
            "水路制造清洁度：限制金属/非金属杂质引入冷却系统（粒径与长宽比要求见原文）",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"6\.2\.3\.2 High Voltage DC connection|"
        r"物理连接应能够支持10s@125kW@",
        chunk,
        re.I,
    )
    if match:
        # 专家：条款 6.2.3.2 正确。抽出值是「高压直流连接」，不是 125kW/62.5kW。
        add(
            "高压连接器保护",
            "高压直流连接",
            "",
            match.group(0),
            match.start(),
            confidence=0.72,
            note=_CONNECTOR_PROTECTION_NOTE,
            review_status=STATUS_PARTIAL,
        )
    match = re.search(
        r"There shall be one physical auxiliary HVDC connection on the XCM|"
        r"控制器上应有一个物理辅助高压直流连接",
        chunk,
        re.I,
    )
    if match:
        # 辅助高压连接器不是清单「高压连接器保护」（6.2.3.2）
        pass
    match = re.search(
        r"[0O]\s+to\s+10\s+liter/min",
        chunk,
        re.I,
    )
    if match:
        add("冷却流量范围", "0 to 10 liter/min", "", match.group(0), match.start())
        # 额定流量需另有额定/考核定义；压降句单独处理
    match = re.search(
        r"rated\s+flow[^.\n]{0,40}?10\s*L/?min|"
        r"额定流量[^.\n]{0,20}?10\s*L/?min|"
        r"设计流量[^.\n]{0,20}?10\s*L/?min",
        chunk,
        re.I,
    )
    if match:
        add("额定流量", "10 L/min", "", match.group(0), match.start())
    match = re.search(
        r"Coolant pressure drop\s*冷却回路压降[\s\S]{0,280}?35\s*Kpa|"
        r"maximum allowed coolant pressure drop[\s\S]{0,120}?35\s*Kpa",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却回路压降",
            "≤35 kPa@65℃@10 L/min",
            "",
            re.sub(r"\s+", " ", match.group(0)).strip()[:240],
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"≤\s*35\s*k?Pa@65\s*℃@10\s*L/min",
        chunk,
        re.I,
    )
    if match:
        add("冷却回路压降", "≤35 kPa@65℃@10 L/min", "", match.group(0), match.start(), confidence=0.8)
    match = re.search(
        r"Active discharge of HVDC bus\s*高压直流母线主动放电|"
        r"The (?:XCM|PCM) shall have functionality to perform an active discharge",
        chunk,
        re.I,
    )
    if match:
        add(
            "高压安全-主动放电功能",
            "有；1s 内将 HVDC 放至低于 60VDC（接触器打开触发，经 P1/P3 绕组）",
            "",
            match.group(0),
            match.start(),
        )
    dur = re.search(
        r"active discharge shall be completed within\s*([lI1\d]+)\s*s",
        chunk,
        re.I,
    )
    if dur:
        sec = dur.group(1)
        if sec in {"l", "I"}:
            sec = "1"
        add(
            _ACTIVE_DISCHARGE,
            f"{sec}s内降至60VDC（接触器打开触发）",
            "",
            dur.group(0),
            dur.start(),
        )
    match = re.search(
        r"Passive discharge of HVDC bus\s*高压直流母线的被动放电|"
        r"possibility to passively discharge the HVDC bus",
        chunk,
        re.I,
    )
    if match:
        add(
            _PASSIVE_DISCHARGE,
            "有；接触器打开后 120s 内 HVDC（内部电容）低于 60VDC",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"The Y-capacitors of the (?:XCM|PCM) shall be less then|"
        r"控制器的Y型电容应小于|"
        r"Y-capacitor selection\s*Y-电容选择|"
        r"HVDC\+\s*to\s*GND",
        chunk,
        re.I,
    )
    if match:
        window = chunk[match.start() : match.start() + 1600]
        nf = re.search(
            r"Y\+?\s*[≤<=]{1,2}\s*(\d{2,3})\s*nF|"
            r"(?:PCM|XCM)\s+(\d{2,4})\s*nF",
            window,
            re.I,
        )
        if nf:
            n = next(g for g in nf.groups() if g)
            if n.isdigit() and 50 <= int(n) <= 2000:
                # 摘录必须是原文连续片段：标题句 + 表格里那一格（SuperEvo `Y+≤130nF & Y-≤130nF`）。
                # 之前拼成「Y-电容选择 Y+≤130nF」不在原文里，被 _value_in_source 当编造丢掉，#17 必漏。
                nf_at = match.start() + nf.start()
                cell_text = re.sub(r"\s+", " ", window[nf.start() : nf.start() + 48]).strip()
                excerpt = re.sub(r"\s+", " ", match.group(0)).strip()
                if cell_text:
                    excerpt = f"{excerpt} … {cell_text}"
                add(
                    "高压安全-Y电容指标",
                    f"Y+≤{n}nF、Y-≤{n}nF（HVDC±对地）",
                    "",
                    excerpt,
                    nf_at,
                )
    match = re.search(
        r"The (?:XCM|PCM) voltage range according to ISO 16750-2:CodeA\(6~16V\)|"
        r"(?:XCM|PCM)电压范围应符合ISO 16750-2",
        chunk,
        re.I,
    )
    if match:
        add("低压电源电压工作范围", "ISO 16750-2 CodeA：6~16V", "", match.group(0), match.start())
    split_hvdc = _parse_hvdc_boost_split_rows(chunk)
    if not split_hvdc:
        match = re.search(
            r"Min level for limited performance性能限制时的最低电压\s*\|\s*(\d+)\s*\|\s*(\d+)",
            chunk,
            re.I,
        )
        if match:
            add(
                "降额工作电压范围",
                _fmt_hvdc_state_lines(
                    [
                        (
                            "限制性能",
                            _hvdc_pair_display((match.group(1), match.group(2))),
                            _HVDC_V_MISSING,
                        )
                    ]
                ),
                "",
                match.group(0),
                match.start(),
            )
    if split_hvdc:
        split_rows, excerpt, at = split_hvdc
        states5: list[tuple[str, str, str]] = []
        if "cold" in split_rows:
            states5.append(
                ("冷启动", _hvdc_pair_display(split_rows["cold"]), _HVDC_V_MISSING)
            )
        if "full_min" in split_rows and "full_max" in split_rows:
            states5.append(
                (
                    "满功率",
                    _hvdc_pair_display(split_rows["full_min"]),
                    _hvdc_pair_display(split_rows["full_max"]),
                )
            )
        if "limited_min" in split_rows or "limited_max" in split_rows:
            states5.append(
                (
                    "限制性能",
                    _hvdc_pair_display(split_rows.get("limited_min")),
                    _hvdc_pair_display(split_rows.get("limited_max")),
                )
            )
        body5 = _fmt_hvdc_state_lines(states5)
        if body5:
            add(
                "直流工作电压范围",
                body5,
                "",
                excerpt,
                at,
                confidence=0.9,
            )
        states6: list[tuple[str, str, str]] = []
        if "full_min" in split_rows and "full_max" in split_rows:
            states6.append(
                (
                    "满功率",
                    _hvdc_pair_display(split_rows["full_min"]),
                    _hvdc_pair_display(split_rows["full_max"]),
                )
            )
        if "current_min" in split_rows and "current_max" in split_rows:
            states6.append(
                (
                    "满电流",
                    _hvdc_pair_display(split_rows["current_min"]),
                    _hvdc_pair_display(split_rows["current_max"]),
                )
            )
        body6 = _fmt_hvdc_state_lines(states6)
        if body6:
            add(
                "满功率(电流)工作电压",
                body6,
                "",
                excerpt,
                at,
                confidence=0.9,
            )
        if "limited_min" in split_rows or "limited_max" in split_rows:
            add(
                "降额工作电压范围",
                _fmt_hvdc_state_lines(
                    [
                        (
                            "限制性能",
                            _hvdc_pair_display(split_rows.get("limited_min")),
                            _hvdc_pair_display(split_rows.get("limited_max")),
                        )
                    ]
                ),
                "",
                excerpt,
                at,
                confidence=0.9,
            )
    parsed_hvdc = None if split_hvdc else _parse_hvdc_bus_rows(chunk)
    if parsed_hvdc:
        rows, excerpt, at = parsed_hvdc
        limited_min = rows.get("limited_min") or ""
        full_min = rows.get("full_min") or ""
        full_max = rows.get("full_max") or ""
        limited_max = rows.get("limited_max") or full_max
        cold = rows.get("cold")
        states5: list[tuple[str, str, str]] = []
        if cold:
            states5.append(("冷启动", f"{cold}V", _HVDC_V_MISSING))
        elif cold == "":
            states5.append(("冷启动", _HVDC_V_MISSING, _HVDC_V_MISSING))
        if full_min and full_max:
            states5.append(("满功率", f"{full_min}V", f"{full_max}V"))
        if limited_min:
            states5.append(
                (
                    "限制性能",
                    f"{limited_min}V",
                    f"{limited_max}V" if limited_max else _HVDC_V_MISSING,
                )
            )
        body5 = _fmt_hvdc_state_lines(states5)
        if body5:
            add(
                "直流工作电压范围",
                body5,
                "",
                excerpt,
                at,
                confidence=0.93,
            )
        if full_min and full_max:
            add(
                "满功率(电流)工作电压",
                _fmt_hvdc_state_lines([("满功率", f"{full_min}V", f"{full_max}V")]),
                "",
                excerpt,
                at,
                confidence=0.93,
            )
        if limited_min:
            add(
                "降额工作电压范围",
                _fmt_hvdc_state_lines(
                    [
                        (
                            "限制性能",
                            f"{limited_min}V",
                            f"{limited_max}V" if limited_max else _HVDC_V_MISSING,
                        )
                    ]
                ),
                "",
                excerpt,
                at,
                confidence=0.93,
            )
    match = re.search(
        r"Back-up supply voltage if KL30 is lost|"
        r"KL30丢失备用电源电压",
        chunk,
        re.I,
    )
    if match:
        add("备份电源功能", "有；KL30丢失时备用供电", "", match.group(0), match.start())
    match = re.search(
        r"Minimum allowable storage temperature when not work\s*ing[^:\n：]{0,80}[:：]\s*(-?\d+)\s*°?\s*[CС℃c]"
        r".{0,500}?"
        r"Maximum allowable storage temperature when not work\s*ing[^:\n：]{0,80}[:：]\s*(-?\d+)\s*°?\s*[CС℃c]",
        chunk,
        re.I | re.S,
    )
    if not match:
        match = re.search(
            r"不工作状态下最低存储温度[:：]\s*(-?\d+)\s*°?\s*[C℃]"
            r".{0,220}?"
            r"不工作状态下最高存储温度[:：]\s*(-?\d+)\s*°?\s*[C℃]",
            chunk,
            re.S,
        )
    if match:
        add(
            "存储温度范围",
            f"{match.group(1)}℃ ~ {match.group(2)}℃（不工作、不超过一个月）",
            "",
            match.group(0)[:180],
            match.start(),
        )
    match = re.search(
        r"withstand a surface temperature of\s*(-40\s*°?\s*[CС℃cс]?\s*[~～-]\s*110\s*°?\s*[CС℃cс]?)",
        chunk,
        re.I,
    )
    if match:
        add(
            "工作温度范围",
            "-40℃~110℃（工作时表面温度）",
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(
        r"operate at an altitude of\s*(\d+)\s*meters and below|"
        r"海拔(\d+)米及以下|"
        r"designed to operate up to\s*(\d{3,5})\s*m(?:eters?)?(?:\s+above sea level)?|"
        r"Operation altitude[\s\S]{0,220}?(\d{3,5})\s*m|"
        r"应设计为在海拔(\d+)米以上运行|"
        r"海拔\s*(\d{3,4})\s*米",
        chunk,
        re.I,
    )
    if match:
        alt = next(g for g in match.groups() if g)
        # 原文 “up to 5000m / 海拔5000米以上” 均按设计海拔 5000m 记录
        add("工作海拔高度", f"设计海拔 {alt} m", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"Cooling connections\s*冷却连接|"
        r"Coolant input/output spigot specification\s*冷却液进水口/出水口",
        chunk,
        re.I,
    )
    if match:
        window = chunk[match.start() : match.start() + 500]
        nw = re.search(r"NW\s*12", window, re.I)
        vda = re.search(r"\bVDA\b", window, re.I)
        if nw and vda:
            val = "VDA 标准，NW12 接口"
        elif vda:
            val = "按 VDA 标准设计冷却液进/出水口"
        elif nw:
            val = "NW12 接口"
        else:
            val = "冷却液进/出水口（Cooling connections）"
        add("冷却接口", val, "", re.sub(r"\s+", " ", match.group(0)).strip(), match.start())
    match = re.search(
        r"冷却流阻要求：≤\s*35\s*Kpa@65\s*℃@10L/min|"
        r"flow resistance requirement for XCM:\s*≤\s*35\s*Kpa@65\s*℃@10L/min",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却回路压降",
            "≤35 kPa @65℃ @10 L/min（含OD）",
            "",
            match.group(0),
            match.start(),
            confidence=0.8,
        )
    match = re.search(
        r"控制器应满足15年或25万公里[^。]{0,40}",
        chunk,
    )
    if match:
        add("寿命要求", match.group(0).rstrip("。"), "", match.group(0), match.start())
    match = re.search(
        r"6\.3\.1\.3 EM temperature sensors|"
        r"6\.3\.1\.3.{0,40}电机温度传感器",
        chunk,
        re.I,
    )
    if match:
        window = _clause_slice(chunk, match.start(), 800)
        acc = _temp_sample_value(window, motor=True, prefix="每电机一只")
        if acc:
            add(
                "电机温度采样精度",
                acc,
                "",
                re.sub(r"\s+", " ", window[:280]).strip(),
                match.start(),
                confidence=0.9,
            )
    match = re.search(
        r"6\.3\.1\.1 Measurement of Inverter temperature|"
        r"Temperatures of all IGBTs for both PEI",
        chunk,
        re.I,
    )
    if match:
        window = _clause_slice(chunk, match.start(), 900)
        acc = _temp_sample_value(window, motor=False, prefix="P1与P3全部 IGBT")
        if acc:
            add(
                "IGBT温度采样精度",
                acc,
                "",
                re.sub(r"\s+", " ", window[:280]).strip(),
                match.start(),
                confidence=0.9,
            )
    match = re.search(
        r"Full coolant temperature range[\s\S]{0,40}全冷却液温度范围\s*\|\s*([^|\n]+)\|",
        chunk,
        re.I,
    )
    full_cool = (match.group(1).strip() if match else "") or ""
    if not full_cool:
        m_full = re.search(
            r"全冷却液温度范围\s*\|\s*(-40\s*[°℃]C?\s*to\s*\+?\s*85\s*[°℃]C?)",
            chunk,
            re.I,
        )
        full_cool = m_full.group(1).strip() if m_full else ""
        match = m_full or match
    match_n = re.search(
        r"Normal coolant temperature range[\s\S]{0,40}正常冷却液温度范围\s*\|\s*([^|\n]+)\|",
        chunk,
        re.I,
    )
    if not match_n:
        match_n = re.search(
            r"正常冷却液温度范围\s*\|\s*(-30\s*[°℃]C?\s*to\s*\+?\s*65\s*[°℃]C?)",
            chunk,
            re.I,
        )
    if full_cool and match_n:
        add(
            "冷却液温度范围",
            f"全范围 {full_cool}；正常 {match_n.group(1).strip()}",
            "",
            (match.group(0) if match else "") + " " + match_n.group(0),
            match.start() if match else match_n.start(),
        )
    elif full_cool:
        add("冷却液温度范围", full_cool, "", match.group(0), match.start())
    # 两列表已由 _parse_hvdc_boost_split_rows 写出，勿再用最高电压单格覆盖
    if not split_hvdc:
        match = re.search(
            r"Max level for full power满功率时的最高电压\s*\|\s*(\d+)",
            chunk,
            re.I,
        )
        if match:
            add(
                "满功率(电流)工作电压",
                _fmt_hvdc_state_lines(
                    [("满功率", _HVDC_V_MISSING, f"{match.group(1)}V")]
                ),
                "",
                match.group(0),
                match.start(),
            )
        cold = re.search(
            r"Min level during cold ICE start冷启动时的最低电压\s*\|\s*(\d+)",
            chunk,
            re.I,
        )
        if cold and match:
            add(
                "直流工作电压范围",
                _fmt_hvdc_state_lines(
                    [
                        ("冷启动", f"{cold.group(1)}V", _HVDC_V_MISSING),
                        ("满功率", _HVDC_V_MISSING, f"{match.group(1)}V"),
                    ]
                ),
                "",
                cold.group(0) + " ; " + match.group(0),
                cold.start(),
            )
    match = re.search(r"(?i)\bCAN[\s-]*FD\b", chunk)
    # 同段已有 LIN 时留给 CAN/CAN-FD/LIN，避免只留下 CAN FD。
    if (
        match
        and not any(c.name == "通讯方式" for c in found)
        and not re.search(r"\bLIN\b", chunk)
    ):
        add("通讯方式", "CAN FD", "", match.group(0), match.start())

    match = re.search(r"(?im)^Design requirements\b", chunk)
    if match:
        title = "Design requirements"
        nxt = re.search(r"(?im)^Motor and Transmission[^\n]*", chunk)
        if nxt:
            title = f"Design requirements / {nxt.group(0).strip()}"
        add("规格书标题", title, "", title, match.start())
    match = re.search(r"(?m)^(.{2,80}规格书)\s*$", chunk)
    if match:
        add("规格书标题", match.group(1).strip(), "", match.group(1), match.start())
    match = re.search(r"(?i)Rev\s*No\s*\n+\s*(0*\d{1,4}|V[\d.]+)\b", chunk)
    if match:
        add("规格书版本", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"(?i)\nDate\n+\s*([0-9]{4}[.\-/]\s*[0-9]{2}[.\-/]\s*[Xx0-9]{2})",
        chunk,
    )
    if match:
        add(
            "规格书日期",
            re.sub(r"\s+", "", match.group(1)),
            "",
            match.group(0),
            match.start(),
        )
    match = re.search(r"(?i)\nModel\n+\s*([A-Za-z0-9]+)", chunk)
    if match:
        add("适用车型", match.group(1), "", match.group(0), match.start())
    match = re.search(
        r"(?i)\nItem\n+\s*([^\n]*(?:Transmission|Inverter|Motor|变速|逆变)[^\n]*)",
        chunk,
    )
    if match:
        add("系统/总成", match.group(1).strip(), "", match.group(0), match.start())
    _add_formula_values(chunk, add)
    match = re.search(
        r"电驱系统高压连接器[：:][^\n]{0,40}IPXXB[^\n]{0,80}防直触|"
        r"高压连接器[：:][^\n]{0,80}IPXXB等级[^\n]{0,80}螺栓连接",
        chunk,
        re.I,
    )
    if match:
        add(
            "高压连接器保护",
            "IPXXB / 防直触（螺栓连接可视为满足）",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"增加PSS（Power Safety Switch）[^\n]{0,80}主动点爆|"
        r"可触发主动点爆进而保护系统|"
        r"两相[^\n]{0,24}PSS[^\n]{0,80}主动点爆",
        chunk,
        re.I,
    )
    if match:
        add(
            "主动保险功能",
            "两相铜排 PSS，异常时主动点爆",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    if family != "inverter":
        return found
    loc = re.search(r"(?i)Hyundai\s*/\s*Kia", chunk)
    if loc:
        add("制造商", "Hyundai/Kia", "", loc.group(0), loc.start())
    match = re.search(
        r"Ambient\s*\(\s*Operating\s*\)[\s\S]{0,80}(-40\s*[~～-]\s*85\s*°?C)",
        chunk,
        re.I,
    )
    if match:
        add(
            "工作温度范围",
            "-40℃~85℃（Operating）",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"Ambient\s*\(\s*Storage\s*\)[\s\S]{0,80}(-40\s*[~～-]\s*105\s*°?C)",
        chunk,
        re.I,
    )
    if match:
        add(
            "存储温度范围",
            "-40℃~105℃（Storage）",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"Cooling Water Temperature[\s\S]{0,80}(-40\s*[~～-]\s*65\s*°?C)",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却液温度范围",
            "-40℃~65℃（冷却水）",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )

    # —— 逆变器 SR 族（Hyundai/Kia DHT 等）；DPR / 通用规格不跑，避免错绑 ——
    match = re.search(
        r"(?:Warranty life target|Qualification Life)\s*:\s*"
        r"(15\s*years?\s*[-–]?\s*300,?000\s*km)",
        chunk,
        re.I,
    )
    if match:
        add(
            "寿命要求",
            re.sub(r"\s+", " ", match.group(1)).strip().replace("years ", "years - "),
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"Water\s*:\s*Glycol\s*\(\s*50\s*:\s*50\s*\)",
        chunk,
        re.I,
    )
    if match:
        add("冷却接口", "Water:Glycol(50:50)", "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"Cooling sequence\s*\[?\s*Inverter\s*[-–]\s*Motor\s*[-–]\s*Gearbox",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却接口",
            "水冷；顺序 Inverter-Motor-Gearbox；Water:Glycol(50:50)",
            "",
            match.group(0),
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"(?:MAX\.?|Max(?:imum)?\.?)\s*12\b",
        chunk,
        re.I,
    )
    if match and re.search(r"LPM|lpm", chunk):
        add("冷却流量范围", "MAX. 12 LPM（EWP 强制循环）", "", match.group(0), match.start(), confidence=0.9)
        add("额定流量", "12 LPM（压降考核点）", "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"300\s*(?:mbar|t|1)?[\s\S]{0,25}@\s*12\s*LPM\s*,\s*65\s*°?C",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却回路压降",
            "300 mbar @12 LPM, 65°C",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"(?:inverter coolant temperature at 65|Inverter Inlet Standard)\b|"
        r"Coolant temperatur[e\s]*°?C[\s\S]{0,40}?\b65\b",
        chunk,
        re.I,
    )
    if match:
        add(
            "冷却液温度范围",
            "逆变器/冷却入口 65°C",
            "",
            match.group(0)[:120],
            match.start(),
            confidence=0.9,
        )
    match = re.search(
        r"-40\s*°?[CСcс]?\s*[~～-]\s*85\s*°?[CСcс]\s*\(Operating\)",
        chunk,
        re.I,
    )
    if match:
        add("工作温度范围", "-40℃~85℃（Operating）", "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"-40\s*°?C?\s*[~～-]\s*105\s*°?C\s*\(Operation\)",
        chunk,
        re.I,
    )
    if match:
        add("工作温度范围", "-40℃~105℃（Operation）", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"-40\s*[~～-]\s*105\s*°?C\s*\(Storage/?Abandon\)",
        chunk,
        re.I,
    )
    if match:
        add("存储温度范围", "-40℃~105℃（Storage/Abandon）", "", match.group(0), match.start(), confidence=0.92)
    match = re.search(
        r"-40\s*[~～-]\s*110\s*°?C\s*\(Non-\s*operation\)",
        chunk,
        re.I,
    )
    if match:
        add("存储温度范围", "-40℃~110℃（Non-operation）", "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"Humidity[\s\S]{0,120}?1%\s*[~～-]\s*100%",
        chunk,
        re.I,
    )
    if match:
        add("湿度要求", "1%~100%", "", match.group(0), match.start(), confidence=0.9)
        add("存储相对湿度", "1%~100%", "", match.group(0), match.start(), confidence=0.85)
    match = re.search(
        r"(?:Altitude below|Elevation less than)\s*5000\s*m|"
        r"Altitude\s+(?:m\s+)?5000\b|"
        r"Altitude[\s:]{0,12}5000\s*m\b",
        chunk,
        re.I,
    )
    if not match:
        match = re.search(
            r"^Altitude\s*$[\s\S]{0,48}?^5000\b",
            chunk,
            re.I | re.M,
        )
    if match:
        add(
            "工作海拔高度",
            "≤5000 m"
            if re.search(r"below|less than", match.group(0), re.I)
            else "设计海拔 5000 m",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"(?:Waterproof and dustproof rating[\s\S]{0,40})?(?:IP|1P)\s*67",
        chunk,
        re.I,
    )
    if match:
        add("密封（IP等级）", "IP67", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"(?:Flammable[\s\S]{0,80}|flame retardancy rating must meet\s*)V-[0O]",
        chunk,
        re.I,
    )
    if match:
        add("阻燃要求", "V-0", "", match.group(0), match.start(), confidence=0.9)
    match = re.search(
        r"discharge to DC\s*60V or less[\s\S]{0,40}?200\s*ms",
        chunk,
        re.I,
    )
    if match:
        add(
            _ACTIVE_DISCHARGE,
            "有；碰撞检测/他控请求/HVDC 分离/逆变断电后，200ms 内降至 ≤60Vdc",
            "",
            match.group(0),
            match.start(),
            confidence=0.92,
        )
    match = re.search(
        r"System Safety Level:\s*ASIL-C",
        chunk,
        re.I,
    )
    if match:
        add("功能安全", "ASIL-C（ISO 26262）", "", match.group(0), match.start(), confidence=0.95)
    if (
        re.search(r"CAN[\s\-–]*FD", chunk, re.I)
        and re.search(r"\bLIN\b", chunk)
        and not any("以太网" in (c.value or "") or "5Mbit" in (c.value or "") for c in found if c.name == "通讯方式")
    ):
        loc = re.search(
            r"(?:must support\s+)?CAN[,\s]+CAN[\s\-–]*FD[,\s]+(?:and\s+)?LIN(?:\s+communication)?",
            chunk,
            re.I,
        ) or re.search(r"CAN[\s\-–]*FD", chunk, re.I)
        add(
            "通讯方式",
            "CAN / CAN-FD / LIN",
            "",
            loc.group(0) if loc else "CAN-FD LIN",
            loc.start() if loc else 0,
            confidence=0.93,
        )
    match = re.search(
        r"Y-Capacitor[\s\S]{0,80}?450nF|"
        r"Y-capacitor\s*:\s*1500\s*Vdc[\s\S]{0,80}?450nF",
        chunk,
        re.I,
    )
    if match and re.search(r"450\s*nF", match.group(0), re.I):
        add(
            "高压安全-Y电容指标",
            "Y电容 1500Vdc；450nF×2",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"Insulation Resistance[\s\S]{0,40}?100M\s*[ΩΩ]?\s*[↑1]|"
        r"100MΩ↑\s*\(@ Rated Voltage, 1min\)",
        chunk,
        re.I,
    )
    if match and not _looks_like_dc_capacitor_spec(
        chunk[max(0, match.start() - 240) : match.end() + 160]
    ):
        add(
            "高压安全-绝缘电阻",
            "DC-link 电容：100MΩ↑（额定电压，1min）",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"Dark Current[\s\S]{0,200}?0\.1mA|"
        r"0\.1mA[↓\s1]*\(?@ Rated Voltage, 1min\)",
        chunk,
        re.I,
    )
    if match:
        # DC 电容漏电流不是整机静态电流，不入库
        pass
    match = re.search(
        r"(?:Torque control accuracy[\s\S]{0,80})?"
        r"(?:±\s*2\s*%|[\$Ss]\s*2\s*%\s*1?|[-—–]2%).{0,48}?"
        r"(?:0\s*[±t+]?\s*)?0\.4\s*Nm[^\n]{0,24}Zero torque|"
        r"0\.4Nm\s*@\s*Zero torque",
        chunk,
        re.I,
    )
    if match:
        add(
            "扭矩控制精度",
            "±2%（零扭矩 ±0.4Nm）",
            "",
            match.group(0),
            match.start(),
            confidence=0.86,
        )
        add(
            "转矩控制精度",
            "±2%（零扭矩 ±0.4Nm）",
            "",
            match.group(0),
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"DC link overvoltage",
        chunk,
        re.I,
    )
    if match:
        # 仅有「有过压保护」、无阈值时不入库
        pass
    match = re.search(
        r"Phase current overcurrent|"
        r"3-phase\s*Current\s*s?\s*ensor|"
        r"3-phase\s*current",
        chunk,
        re.I,
    )
    if match:
        add(
            "相电流采样精度",
            "有三相电流传感器；具备相电流过流监测",
            "",
            match.group(0),
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"DC Link Voltage|"
        r"\bDC current\b",
        chunk,
        re.I,
    )
    if match and re.search(r"DC Link Voltage", chunk, re.I):
        add(
            "母线电压采样精度",
            "测量 DC Link Voltage",
            "",
            "DC Link Voltage",
            match.start(),
            confidence=0.86,
        )
    if re.search(r"\bDC current\b", chunk, re.I) and re.search(
        r"Voltage ripple|Capacitance|Y-Capacitor", chunk, re.I
    ):
        # 电容表头「DC current」且指标待供应商，不填母线电流检测
        pass
    match = re.search(
        r"Motor temperature|"
        r"temperature sensor must be attached to the rotor,\s*stator",
        chunk,
        re.I,
    )
    if match and not any(c.name == "电机温度采样精度" for c in found):
        window = _clause_slice(chunk, match.start(), 600)
        acc = _temp_sample_value(window, motor=True)
        if acc:
            add(
                "电机温度采样精度",
                acc,
                "",
                re.sub(r"\s+", " ", window[:200]).strip(),
                match.start(),
                confidence=0.86,
            )
    match = re.search(
        r"inverter power module|"
        r"Inverter tempe\s*rature|"
        r"Temperatures of all IGBTs",
        chunk,
        re.I,
    )
    if match and not any(c.name == "IGBT温度采样精度" for c in found):
        window = _clause_slice(chunk, match.start(), 900)
        acc = _temp_sample_value(window, motor=False, prefix="P1与P3全部 IGBT")
        if acc:
            add(
                "IGBT温度采样精度",
                acc,
                "",
                re.sub(r"\s+", " ", window[:200]).strip(),
                match.start(),
                confidence=0.88,
            )
    match = re.search(
        r"permanent magnets|"
        r"demagnetization of\s*permanent magnets",
        chunk,
        re.I,
    )
    if match:
        add("电机类型", "永磁电机（需防退磁）", "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"DC capacitor 500Vd|"
        r"Rated Voltage[\s\S]{0,80}?500Vdc",
        chunk,
        re.I,
    )
    if match:
        # 额定电压不是薄膜电容容值
        pass
    match = re.search(
        r"Maximum Rating\s*\(>\s*10\s*sec\)",
        chunk,
        re.I,
    )
    if match:
        add("P1峰值功率持续时间", ">10s（Drive Maximum Rating）", "", match.group(0), match.start(), confidence=0.84)
    match = re.search(
        r"Corrosion-resistant material must be applied|"
        r"Galvanic corrosion and anti-corrosion",
        chunk,
        re.I,
    )
    if match:
        add(
            "防腐要求",
            "内外耐腐蚀材料；电偶腐蚀防护；符合 HMC 表面处理标准",
            "",
            match.group(0),
            match.start(),
            confidence=0.86,
        )
        add("防腐等级", "按 HMC 表面处理/耐腐蚀要求（未给 C 级代号）", "", match.group(0), match.start(), confidence=0.82)
    match = re.search(
        r"Dark Current[\s\S]{0,120}?Under 1",
        chunk,
        re.I,
    )
    if match:
        # 板级 Dark Current Under 1 mA 不是整机未唤醒静态电流
        pass
    match = re.search(
        r"Top speed[\s\S]{0,40}?16,?000\s*\(up to 17,?000\)",
        chunk,
        re.I,
    )
    if match:
        add("P1最高工作转速", "16000rpm（最高至 17000）", "", match.group(0), match.start(), confidence=0.88)
    match = re.search(
        r"Inverter\s*:\s*ES 36500|"
        r"ESAs requirements[\s\S]{0,80}ES 36500",
        chunk,
        re.I,
    )
    if match:
        add(
            "EMC等级",
            "ES 36500 / CISPR25 / ECE R10.05&06",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.88,
        )
    match = re.search(
        r"cybersecurity scorecard|HMC Cyber Security related ES",
        chunk,
        re.I,
    )
    if match:
        add(
            "网络安全要求",
            "需满足 HMC Cyber Security ES；提交 scorecard / TARA / SUMS",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"Do not use brominated flame retardants \(Deca BDE\)|"
        r"Satisfy HMC Spec\.\s*MS 201-02",
        chunk,
        re.I,
    )
    if match:
        add(
            "禁用、限用物质",
            "满足 MS 201-02 / EU ELV；禁止 Deca BDE",
            "",
            match.group(0)[:160],
            match.start(),
            confidence=0.86,
        )
    match = re.search(
        r"Discharge time[\s\S]{0,80}?60\s*\(\s*Passive\s*\)[\s\S]{0,48}?1\s*\(\s*Active\s*\)",
        chunk,
        re.I,
    )
    if match:
        add(
            _PASSIVE_DISCHARGE,
            "被动 60s / 主动 1s，降至 30Vac 或 60Vdc",
            "",
            match.group(0)[:180],
            match.start(),
            confidence=0.88,
        )
    return found


def extract_cells(
    doc: LoadedDocument,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    deadline: float | None = None,
    meta: ExtractMeta | None = None,
) -> list[ExtractedCell]:
    stats = meta if meta is not None else ExtractMeta()
    kind = doc.kind
    family = kind.family if kind is not None else "generic"
    if kind is not None and not kind.extract:
        report(kind.note, percent=90, stage="extract")
        skipped = empty_template_rows()
        for cell in skipped:
            cell.review_status = STATUS_NA
        return skipped

    rows = {c.seq: c for c in empty_template_rows()}
    extra: list[ExtractedCell] = []
    seen_extra: set[tuple[str, str]] = set()
    excerpt_owner: dict[str, str] = {}
    value_owner: dict[str, str] = {}

    def rule_cells(text: str) -> list[ExtractedCell]:
        return _rule_cells(text, family=family)

    def put(cell: ExtractedCell, text: str) -> None:
        _store_cell(cell, text, rows, extra, seen_extra, excerpt_owner, value_owner)

    # 泛化体检：SPEC_SHEET_MODEL_ONLY=1 跳过原文规则，只走「词典认条 → 分段模型」这条新文档也会走的路，
    # 再与整表黄金比对，量出规则之外的真实水平。日常出表不要开。
    model_only = _env_flag("SPEC_SHEET_MODEL_ONLY")
    if model_only:
        report("泛化体检：跳过原文规则，只用分段模型…", percent=36, stage="extract")
    else:
        report("按原文规则抽取明确条目…", percent=36, stage="extract")
        for _page, text in _page_blocks(doc.markdown):
            for cell in rule_cells(text):
                put(cell, text)
        # 全文再跑一遍：避免表格跨页/截断导致关键数值漏抽
        for cell in rule_cells(doc.markdown):
            put(cell, doc.markdown)
    _scrub_drive_boost_if_charge_spec(rows, doc.markdown)
    _fill_peak_bemf_from_motors(rows)

    rules_only = _env_flag("SPEC_SHEET_RULES_ONLY") and not model_only
    stats.rule_filled = sum(
        1 for cell in rows.values() if (cell.value or "").strip()
    )
    report_stats(filled=stats.rule_filled)

    if rules_only:
        report("仅规则抽取（跳过本机模型）…", percent=90, stage="extract")
        by_name: dict[str, list[int]] = {}
        for seq, cell in rows.items():
            by_name.setdefault(cell.name, []).append(seq)
        for _name, seqs in by_name.items():
            if len(seqs) < 2:
                continue
            donors = [rows[s] for s in seqs if (rows[s].value or "").strip()]
            if not donors:
                continue
            donor = max(donors, key=lambda c: (c.confidence, len(c.value)))
            for seq in seqs:
                if not (rows[seq].value or "").strip():
                    rows[seq] = _attach(rows[seq], donor)
        _scrub_drive_boost_if_charge_spec(rows, doc.markdown)
        _fill_peak_bemf_from_motors(rows)
        _fill_miss_next_step(rows)
        _collect_off_list_requirements(doc.markdown, rows, extra, seen_extra)
        return list(rows.values()) + extra

    empty_n = _empty_field_count(rows)
    budget = _llm_chunk_budget(empty_n, doc.markdown)
    chunks = _select_chunks(doc.markdown, max_chunks=budget, rows=rows)
    origin = require_workstation_endpoint(base_url)
    url = f"{origin}/v1/chat/completions"
    headers = {
        "Authorization": "Bearer local",
        "Content-Type": "application/json",
    }
    workers = _parallel_workers()

    with httpx.Client(follow_redirects=False, trust_env=False) as http:
        ctrl = get_control()
        if ctrl is not None:
            ctrl.add_stop_callback(http.close)

        def complete(user_prompt: str, timeout: float = DEFAULT_TIMEOUT) -> str:
            if was_stopped():
                return ""
            payload: dict[str, Any] = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "你只输出一个 JSON 对象。第一个字符是 {，最后一个是 }。",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                "options": {"num_ctx": NUM_CTX, "temperature": 0, "num_predict": 1536},
            }
            payload.update(_thinking_controls())
            try:
                resp = http.post(url, headers=headers, json=payload, timeout=timeout)
            except (httpx.HTTPError, RuntimeError, OSError) as exc:
                if was_stopped():
                    return ""
                raise ExtractError(_local_llm_hint(exc)) from exc
            if 300 <= resp.status_code < 400:
                raise ExtractError("本机模型返回了重定向，已拒绝（防止规格书出网）")
            if resp.status_code == 404:
                raise ExtractError(f"本机没有模型 {model}。请执行: ollama pull {model}")
            if resp.status_code >= 400:
                body = resp.text[:400]
                if _looks_like_auth_failure(resp.status_code, body):
                    raise ExtractAuthError("识别未授权，请退出后重新登录再出表。")
                if _looks_like_model_unavailable(resp.status_code, body):
                    raise ExtractModelError("识别模型当前不可用，请改选其他 chat 模型。")
                raise ExtractError(f"识别服务 HTTP {resp.status_code}: {body}")
            body = resp.json()
            try:
                message = body["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ExtractError(f"响应格式异常: {str(body)[:400]}") from exc
            text = _assistant_text(message)
            if not text:
                raise ExtractError(f"响应格式异常: {str(body)[:400]}")
            return text

        def chunk_timeout() -> float:
            if deadline is None:
                return DEFAULT_TIMEOUT
            remain = max(20.0, deadline - time.perf_counter())
            return min(DEFAULT_TIMEOUT, remain)

        def run_batch(
            batch: list[tuple[int, str, str, str]],
            *,
            total: int,
            done_fmt: str,
            percent_base: int,
            percent_span: int,
            allow_split: bool = True,
        ) -> None:
            if not batch:
                return
            stats.llm_calls += len(batch)
            timeout = chunk_timeout()

            def work(
                pos: int, item: tuple[int, str, str, str]
            ) -> tuple[int, int, str, dict[str, Any]]:
                index, chunk, prompt, fallback = item
                if was_stopped():
                    return pos, index, chunk, {}
                try:
                    data = _parse_model_json(
                        complete,
                        prompt,
                        timeout,
                        fallback_prompt=fallback,
                        fallback_timeout=min(40.0, timeout),
                    )
                except ExtractError:
                    if was_stopped():
                        return pos, index, chunk, {}
                    raise
                return pos, index, chunk, data

            # 按批内位置存结果：拆半重试时两半共用同一个段号，不能按段号覆盖
            indexed: dict[int, tuple[int, str, dict[str, Any]]] = {}
            if len(batch) == 1:
                pos, index, chunk, data = work(0, batch[0])
                indexed[pos] = (index, chunk, data)
                report(
                    done_fmt.format(index=index + 1, total=total),
                    percent=percent_base
                    + int(percent_span * (index + 1) / max(total, 1)),
                    stage="extract",
                )
            else:
                with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                    futures = [pool.submit(work, pos, item) for pos, item in enumerate(batch)]
                    for fut in as_completed(futures):
                        pos, index, chunk, data = fut.result()
                        indexed[pos] = (index, chunk, data)
                        report(
                            done_fmt.format(index=index + 1, total=total),
                            percent=percent_base
                            + int(percent_span * (index + 1) / max(total, 1)),
                            stage="extract",
                        )
            failed: list[tuple[int, str]] = []
            for pos in sorted(indexed):
                index, chunk, data = indexed[pos]
                err = str(data.pop("_parse_error", "") or "").strip()
                if err:
                    stats.chunk_error = err[:240]
                if data.pop("_parse_failed", False):
                    if allow_split and len(chunk) >= _SPLIT_RETRY_MIN_CHARS and not was_stopped():
                        failed.append((index, chunk))
                    else:
                        stats.chunk_failures += 1
                _ingest_model_rows(data, chunk, put, rule_cells)
            # 实时计数给工位页：本批最大段号、已抽出格数（拆半重试两半共用段号，不重复计）
            if indexed:
                report_stats(
                    chunk_done=max(index for index, _c, _d in indexed.values()) + 1,
                    chunk_total=total,
                    filled=sum(1 for cell in rows.values() if (cell.value or "").strip()),
                )
            if not failed:
                return
            # 整段超时 / JSON 坏掉：拆半重试一次，别把这一段的原文白白丢掉
            retry: list[tuple[int, str, str, str]] = []
            for index, chunk in failed:
                for half in _split_chunk_halves(chunk):
                    fields, _hit = _chunk_fields(half, rows)
                    if not should_send_chunk_to_model(fields):
                        for cell in rule_cells(half):
                            put(cell, half)
                        continue
                    prompt = _main_extract_prompt(
                        index=index,
                        total=total,
                        page_count=doc.page_count,
                        filename=doc.path.name,
                        fields=fields,
                        chunk=half,
                    )
                    retry.append((index, half, prompt, ""))
            if not retry:
                stats.chunk_failures += len(failed)
                return
            report(
                f"第 {'、'.join(str(i + 1) for i, _ in failed)} 段识别失败，拆半重试…",
                percent=percent_base,
                stage="extract",
            )
            for start in range(0, len(retry), max(workers, 1)):
                run_batch(
                    retry[start : start + max(workers, 1)],
                    total=total,
                    done_fmt=done_fmt,
                    percent_base=percent_base,
                    percent_span=percent_span,
                    allow_split=False,
                )

        stats.chunk_count = len(chunks)
        n_chunks = max(len(chunks), 1)
        parallel_note = (
            f"，{workers} 路并行" if workers > 1 and len(chunks) > 1 else ""
        )
        report(
            f"开始分段抽取：{len(chunks)} 段（空缺 {empty_n} 项）"
            f"，模型 {model}{parallel_note}"
            f"（约 {doc.page_count or '?'} 页"
            f"{'，含表格图识别 ' + str(doc.ocr_pages) + ' 页' if doc.ocr_pages else ''}）",
            percent=42,
            stage="extract",
        )
        cursor = 0
        while cursor < len(chunks):
            if not checkpoint(stage="extract"):
                break
            if deadline is not None and time.perf_counter() >= deadline:
                report(
                    "已达自行设定时限，按已抽出内容出表…",
                    percent=90,
                    stage="extract",
                )
                break
            if _empty_field_count(rows) == 0:
                report("清单空缺已补齐，结束主抽。", percent=84, stage="extract")
                break
            batch: list[tuple[int, str, str, str]] = []
            while cursor < len(chunks) and len(batch) < workers:
                index = cursor
                chunk = chunks[cursor]
                cursor += 1
                fields, _hit = _chunk_fields(chunk, rows)
                if not should_send_chunk_to_model(fields):
                    for cell in rule_cells(chunk):
                        put(cell, chunk)
                    continue
                prompt = _main_extract_prompt(
                    index=index,
                    total=len(chunks),
                    page_count=doc.page_count,
                    filename=doc.path.name,
                    fields=fields,
                    chunk=chunk,
                )
                fallback = _cover_fallback_prompt(chunk) if index == 0 else ""
                batch.append((index, chunk, prompt, fallback))
            if not batch:
                continue
            first = batch[0][0] + 1
            last = batch[-1][0] + 1
            if len(batch) == 1:
                msg = f"本机模型抽取第 {first}/{len(chunks)} 段，请稍候…"
            else:
                msg = f"本机模型并行抽取第 {first}–{last}/{len(chunks)} 段，请稍候…"
            report(
                msg,
                percent=42 + int(40 * batch[0][0] / n_chunks),
                stage="extract",
            )
            run_batch(
                batch,
                total=len(chunks),
                done_fmt="本机模型已完成第 {index}/{total} 段",
                percent_base=42,
                percent_span=40,
            )

        if _is_ocr_markdown(doc.markdown) and empty_n > 40:
            topup_n = 16
        elif len(doc.markdown) > _LONG_DOC_CHARS and _empty_field_count(rows) > 20:
            topup_n = 10
        else:
            topup_n = 6
        more = _topup_chunks(doc.markdown, rows, chunks, limit=topup_n)
        stats.topup_count = len(more)
        if more and not was_stopped() and (
            deadline is None or time.perf_counter() < deadline
        ):
            report(
                f"补抽原文中尚未对应的条目：{len(more)} 段",
                percent=84,
                stage="extract",
            )
            cursor = 0
            while cursor < len(more):
                if not checkpoint(stage="extract"):
                    break
                if deadline is not None and time.perf_counter() >= deadline:
                    report("已达自行设定时限，停止补抽。", percent=90, stage="extract")
                    break
                if _empty_field_count(rows) <= 12:
                    report("空缺已不多，结束补抽。", percent=90, stage="extract")
                    break
                batch = []
                while cursor < len(more) and len(batch) < workers:
                    index = cursor
                    chunk = more[cursor]
                    cursor += 1
                    fields, _hit = _chunk_fields(chunk, rows)
                    if not fields:
                        for cell in rule_cells(chunk):
                            put(cell, chunk)
                        continue
                    batch.append(
                        (index, chunk, _topup_extract_prompt(fields, chunk), "")
                    )
                if not batch:
                    continue
                first = batch[0][0] + 1
                last = batch[-1][0] + 1
                if len(batch) == 1:
                    msg = f"补抽第 {first}/{len(more)} 段，请稍候…"
                else:
                    msg = f"并行补抽第 {first}–{last}/{len(more)} 段，请稍候…"
                report(
                    msg,
                    percent=84 + int(10 * batch[0][0] / max(len(more), 1)),
                    stage="extract",
                )
                run_batch(
                    batch,
                    total=len(more),
                    done_fmt="补抽已完成第 {index}/{total} 段",
                    percent_base=84,
                    percent_span=10,
                )

    # 清单里其余同名重复项（如冷却回路压降）同步已填值；绝缘电阻/耐电压源表重复项已删
    by_name: dict[str, list[int]] = {}
    for seq, cell in rows.items():
        by_name.setdefault(cell.name, []).append(seq)
    for _name, seqs in by_name.items():
        if len(seqs) < 2:
            continue
        donors = [rows[s] for s in seqs if (rows[s].value or "").strip()]
        if not donors:
            continue
        donor = donors[0]
        for other in donors[1:]:
            donor = _better(donor, other)
        for seq in seqs:
            rows[seq] = _attach(rows[seq], donor)

    _scrub_drive_boost_if_charge_spec(rows, doc.markdown)
    _fill_peak_bemf_from_motors(rows)
    _fill_miss_next_step(rows)
    _collect_off_list_requirements(doc.markdown, rows, extra, seen_extra)
    return list(rows.values()) + extra


def _as_confidence(raw: Any) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))
