"""从当份 MCU 数据手册抽出引脚。只收手册里写明的球号、符号、缓冲和功能。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PIN_START = re.compile(
    r"^(?P<ball>[A-Z]{1,2}\d{1,2})\s+"
    r"(?P<symbol>P\d{2}\.\d{1,2}|AN\d+)\s+"
    r"(?P<ctrl>[IO])(?P<idx>\d+)?"
    r"\s*(?P<rest>.*)$"
)
# 手册把方向拆到下一行：`T1 AN67 /` 换行后才是 `I S / PU1 /`。
_PIN_BARE = re.compile(
    r"^(?P<ball>[A-Z]{1,2}\d{1,2})\s+(?P<symbol>P\d{2}\.\d{1,2}|AN\d+)\s*/\s*$"
)
_PIN_ALIAS = re.compile(r"^(?P<symbol>P\d{2}\.\d{1,2}|AN\d+)$")
_PIN_DIR = re.compile(r"^(?P<ctrl>[IO])(?P<idx>\d+)?\s*(?P<rest>.*)$")
_BUFFER = re.compile(r"^(?P<tok>[A-Z][A-Z0-9]*)\s*/\s*$|^(?P<es>ES\d*)$")
# 缓冲被拆成单独一行：`/ FAST /`、`X / FAST /`、`/ ES5`。不是功能描述。
_BUFFER_LINE = re.compile(
    r"^/?(?:\s*(?:[A-Z][A-Z0-9]*|ES\d*))(?:\s*/\s*(?:[A-Z][A-Z0-9]*|ES\d*))*\s*/?\s*$"
)
_PAGE_BANNER = re.compile(r"^TC\d+[A-Za-z0-9]*\s+AD/AE-Step$", re.IGNORECASE)
_MUX = re.compile(
    r"^(?P<name>[—\-–A-Z][A-Z0-9_]*)\s+(?P<ctrl>[IO]\d+)\s*(?P<desc>.*)$"
)
_OUTPUT = re.compile(
    r"^(?P<symbol>P\d{2}\.\d{1,2}|AN\d+)\s+O0\s*(?P<desc>.*)$"
)
_PACKAGE = re.compile(r"(?P<kind>LFBGA|BGA)[\s\-_]*(?P<num>\d{3})", re.IGNORECASE)
_MCU_FILE = (
    ("tc499", "TC499"),
    ("tc49", "TC499"),
    ("tc38", "TC38x"),
    ("tc39", "TC39x"),
)


@dataclass(frozen=True)
class ChipPin:
    package: str
    ball: str
    symbol: str
    direction: str
    buffer: str
    function: str
    mux: str
    page: str
    excerpt: str


def mcu_name(filename: str) -> str:
    low = Path(filename).name.lower().replace("_", "").replace("-", "")
    for needle, name in _MCU_FILE:
        if needle in low:
            return name
    raise ValueError("文件名里看不出 MCU 型号。请使用含 TC499、TC38x 或 TC39x 的手册。")


def _package_name(line: str) -> str:
    found = _PACKAGE.search(line)
    if not found:
        return ""
    kind = found.group("kind").upper()
    if kind == "LFBGA":
        return f"LFBGA{found.group('num')}"
    return f"BGA{found.group('num')}"


def _looks_like_pin_page(text: str) -> bool:
    head = text[:500].lower()
    return (
        "pin configuration" in head
        or "port " in head
        or "pin definition" in head
        or "ball symbol" in text.lower()
    )


def _is_noise(line: str) -> bool:
    low = line.lower()
    if line in {"Function", "Type", "Buffer", "type", "Ctrl."}:
        return True
    if line.startswith("Table ") or line.startswith("(table"):
        return True
    if _PAGE_BANNER.match(line.strip()):
        return True
    return any(
        mark in low
        for mark in (
            "data sheet",
            "datasheet",
            "aurix",
            "pin definition and functions",
            "ball symbol",
            "open market",
            "table continues",
        )
    )


def _slash_buffer(line: str) -> list[str] | None:
    text = line.strip()
    if "/" not in text or _BUFFER_LINE.fullmatch(text) is None:
        return None
    parts = [part.strip(" /") for part in re.split(r"\s*/\s*", text) if part.strip(" /")]
    return parts or None


def _buffer_token(line: str) -> str:
    matched = _BUFFER.match(line.strip())
    if not matched:
        return ""
    return matched.group("tok") or matched.group("es") or ""


class _OpenPin:
    def __init__(self, package: str, ball: str, symbol: str, page: int, header: str) -> None:
        self.package = package
        self.ball = ball
        self.symbol = symbol
        self.page = page
        self.header = header.strip()
        self.buffers: list[str] = []
        self.function = ""
        self.mux: list[str] = []
        self.has_input = False
        self.has_output = False
        self.expect_buffer = False
        self.await_io = False
        self.lines: list[str] = [self.header]

    def add_buffer_rest(self, rest: str) -> None:
        self.expect_buffer = rest.rstrip().endswith("/")
        for part in re.split(r"\s*/\s*", rest.strip()):
            token = part.strip(" /")
            if token:
                self.buffers.append(token)

    def add_line(self, line: str) -> None:
        text = line.strip()
        if not text or _is_noise(text):
            return
        slash = _slash_buffer(text)
        if slash is not None:
            self.buffers.extend(slash)
            self.expect_buffer = text.rstrip().endswith("/")
            self.lines.append(text)
            return
        token = _buffer_token(text)
        if token or (self.expect_buffer and " " not in text and not text.startswith("—")):
            self.buffers.append(token or text.strip(" /"))
            self.expect_buffer = text.rstrip().endswith("/")
            self.lines.append(text)
            return
        self.expect_buffer = False
        output = _OUTPUT.match(text)
        if output and output.group("symbol") == self.symbol:
            self.has_output = True
            desc = output.group("desc").strip()
            if desc and not self.function:
                self.function = desc
            self.lines.append(text)
            return
        mux = _MUX.match(text)
        if mux:
            desc = mux.group("desc").strip()
            piece = mux.group("name")
            if desc:
                piece = f"{piece} {desc}"
            self.mux.append(piece)
            self.lines.append(text)
            return
        if not self.function:
            self.function = text
        else:
            self.mux.append(text)
        self.lines.append(text)

    def finish(self) -> ChipPin | None:
        if not self.ball or not self.symbol or not self.header:
            return None
        if self.has_input and self.has_output:
            direction = "Input/Output"
        elif self.has_output:
            direction = "Output"
        elif self.has_input:
            direction = "Input"
        else:
            direction = ""
        excerpt = " ".join(self.lines)
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        mux = "；".join(dict.fromkeys(item for item in self.mux if item))
        if len(mux) > 2000:
            mux = mux[:2000].rstrip()
        return ChipPin(
            package=self.package,
            ball=self.ball,
            symbol=self.symbol,
            direction=direction,
            buffer=" / ".join(dict.fromkeys(self.buffers)),
            function=self.function,
            mux=mux,
            page=str(self.page),
            excerpt=excerpt,
        )


def parse_pin_pages(pages: list[tuple[int, str]]) -> tuple[str, ...]:
    """返回手册里出现过的封装名，按出现顺序。"""
    found: list[str] = []
    for _, text in pages:
        if not _looks_like_pin_page(text):
            continue
        for line in text.splitlines():
            name = _package_on_section(line)
            if name and name not in found:
                found.append(name)
    return tuple(found)


def _package_on_section(line: str) -> str:
    low = line.lower()
    if "on page" in low:
        return ""
    if not any(mark in low for mark in ("package", "pin configuration", "port ")):
        return ""
    return _package_name(line)


def parse_pins(pages: list[tuple[int, str]], package: str) -> tuple[ChipPin, ...]:
    want = package.strip().upper().replace("-", "").replace(" ", "")
    current = ""
    open_pin: _OpenPin | None = None
    rows: list[ChipPin] = []
    seen: set[tuple[str, str]] = set()

    def close() -> None:
        nonlocal open_pin
        if open_pin is None:
            return
        pin = open_pin.finish()
        open_pin = None
        if pin is None:
            return
        key = (pin.package, pin.symbol)
        if key in seen:
            return
        seen.add(key)
        rows.append(pin)

    for number, text in pages:
        if not _looks_like_pin_page(text):
            close()
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            named = _package_on_section(line)
            if named:
                if named != current:
                    close()
                current = named
                continue
            if current.upper().replace("-", "").replace(" ", "") != want:
                continue
            bare = _PIN_BARE.match(line)
            if bare:
                close()
                open_pin = _OpenPin(
                    current,
                    bare.group("ball"),
                    bare.group("symbol"),
                    number,
                    line,
                )
                open_pin.await_io = True
                continue
            if open_pin is not None and open_pin.await_io:
                alias = _PIN_ALIAS.match(line)
                if alias and alias.group("symbol") != open_pin.symbol:
                    open_pin.mux.append(alias.group("symbol"))
                    open_pin.lines.append(line)
                    continue
                direction = _PIN_DIR.match(line)
                if direction:
                    open_pin.await_io = False
                    if direction.group("ctrl") == "I":
                        open_pin.has_input = True
                    else:
                        open_pin.has_output = True
                    open_pin.lines.append(line)
                    open_pin.add_buffer_rest(direction.group("rest") or "")
                    continue
                open_pin.await_io = False
            started = _PIN_START.match(line)
            if started:
                close()
                open_pin = _OpenPin(
                    current,
                    started.group("ball"),
                    started.group("symbol"),
                    number,
                    line,
                )
                ctrl = started.group("ctrl")
                if ctrl == "I":
                    open_pin.has_input = True
                else:
                    open_pin.has_output = True
                open_pin.add_buffer_rest(started.group("rest") or "")
                continue
            if open_pin is not None:
                open_pin.add_line(line)
    close()
    return tuple(rows)


def read_pdf_pages(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append((index, page.extract_text() or ""))
    return pages


def packages_in_titles(titles: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """从目录标题里取封装。机械外形「Package Outline」不算引脚表。"""
    found: list[str] = []
    for title in titles:
        low = title.lower()
        if "pin configuration" not in low and "package variant" not in low:
            continue
        name = _package_name(title)
        if name and name not in found:
            found.append(name)
    return tuple(found)


def _outline_titles(path: Path) -> tuple[str, ...]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    titles: list[str] = []

    def walk(items: object) -> None:
        for item in items or []:
            if isinstance(item, list):
                walk(item)
                continue
            title = getattr(item, "title", None)
            if title:
                titles.append(str(title))

    walk(getattr(reader, "outline", None))
    return tuple(titles)


def packages_in_pdf(path: Path) -> tuple[str, ...]:
    try:
        found = packages_in_titles(_outline_titles(path))
    except Exception:
        found = ()
    if found:
        return found
    return parse_pin_pages(read_pdf_pages(path))


def pins_in_pdf(path: Path, package: str) -> tuple[ChipPin, ...]:
    pins = parse_pins(read_pdf_pages(path), package)
    if not pins:
        raise ValueError(f"手册中没有读到 {package} 的引脚表。")
    return pins
