"""从当份 MCU 数据手册抽出引脚。只收手册里写明的球号、符号、缓冲和功能。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SYM = (
    r"(?:P\d{1,2}[._]\d{1,2}|AN\d+|ESR\d+|PORST(?:_N)?|TCK|TMS|TRST|TDI|TDO|TESTMODE|"
    r"PT[A-Z]\d{1,2}|P[A-Z]\d{1,2}|GPIO[A-Z0-9_.\-]+|ADC\d*_(?:IN|CH)\d+)"
)
_BALL_BGA = re.compile(r"^[A-Z]{1,2}\d{1,2}$")
_BALL_ANY = r"(?:[A-Z]{1,2}\d{1,2}|\d{1,3})"

_PIN_START = re.compile(
    rf"^(?P<ball>{_BALL_ANY})\s+"
    rf"(?P<symbol>{_SYM})(?:\s*/\s*(?P<alias>{_SYM}))?\s+"
    r"(?P<ctrl>I/O|IO|[IO])(?P<idx>\d+)?"
    r"\s*(?P<rest>.*)$"
)
# 手册把方向拆到下一行：`T1 AN67 /` 换行后才是 `I S / PU1 /`。
_PIN_BARE = re.compile(
    rf"^(?P<ball>{_BALL_ANY})\s+(?P<symbol>{_SYM})\s*/\s*$"
)
_PIN_ALIAS = re.compile(rf"^(?P<symbol>{_SYM})$")
_PIN_DIR = re.compile(r"^(?P<ctrl>I/O|IO|[IO])(?P<idx>\d+)?\s*(?P<rest>.*)$")
_BUFFER = re.compile(r"^(?P<tok>[A-Z][A-Z0-9]*)\s*/\s*$|^(?P<es>ES\d*)$")
# 缓冲被拆成单独一行：`/ FAST /`、`X / FAST /`、`/ ES5`。不是功能描述。
_BUFFER_LINE = re.compile(
    r"^/?(?:\s*(?:[A-Z][A-Z0-9]*|ES\d*))(?:\s*/\s*(?:[A-Z][A-Z0-9]*|ES\d*))*\s*/?\s*$"
)
_PAGE_BANNER = re.compile(
    r"^(?:TC\d+[A-Za-z0-9]*\s+[A-Z0-9/]+-Step|\d{4}-\d{2}-\d{2})$",
    re.IGNORECASE,
)
_MUX = re.compile(
    r"^(?P<name>[—\-–A-Z][A-Z0-9_]*)\s+(?P<ctrl>[IO]\d+)\s*(?P<desc>.*)$"
)
_OUTPUT = re.compile(
    rf"^(?P<symbol>{_SYM})\s+O0\s*(?P<desc>.*)$"
)
_OTHER_BALL = re.compile(
    rf"^(?P<ball>{_BALL_ANY})\s+"
    r"(?:VGATE\d+[NP]|XTAL\d+|DAPE\d+|THD\d+_[A-Z]|NC\d*(?:_[A-Z0-9]+)?|"
    r"PHY\d*_[A-Z0-9_]+|V(?:DD|SS|EXT|FLEX|AREF|AGND)[A-Z0-9_]*)\s+"
    r"(?:I/O|IO|[IO])\b"
)
_STOP_SECTION = re.compile(
    r"^(?:Table\s+[\d\-]+\s+(?:\(continued\)\s+|\(cont.d\)\s+)?"
    r"(?:Supply|Special\s+I/O|Pad\s+List|Pad\s+Sequence)|"
    r"\d+\.\d+(?:\.\d+)?\s+\S+\s+(?:supply|special)|"
    r"3\.4\.1\s+Sequence\s+of\s+pads)",
    re.IGNORECASE,
)
_PACKAGE = re.compile(
    r"(?:PG[\s\-_]*)?(?P<kind>LFBGA|TFBGA|FBGA|LBGA|PBGA|MAPBGA|F2BGA|BGA|"
    r"HLQFP|HTQFP|LQFP|TQFP|VQFP|PQFP|QFP|"
    r"HVQFN|VQFN|WQFN|QFN|TSSOP|SSOP|SOIC|SOP|DIP)"
    r"[\s\-_]*(?P<num>\d{2,4})(?![0-9])",
    re.IGNORECASE,
)
_MCU_FILE = (
    ("tc499", "TC499"),
    ("tc49", "TC499"),
    ("tc38", "TC38x"),
    ("tc39", "TC39x"),
)
_MCU_PATTERNS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (re.compile(r"(?:sak[\s\-_]*)?(tc\d{2,3}x)(?![a-z0-9])", re.IGNORECASE), "tc_x"),
    (re.compile(r"(?:sak[\s\-_]*)?(tc\d{3})(?![0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?:sak[\s\-_]*)?(tc4[a-z0-9]{2})(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(s32[a-z]\d{2,4}[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(mpc5\d{3}[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (
        re.compile(
            r"(?<![a-z0-9])(rh850(?:[\-_](?!datasheet|manual|user|um|ds)[a-z0-9]+)?)(?![a-z0-9])",
            re.IGNORECASE,
        ),
        "rh850",
    ),
    (re.compile(r"(?<![a-z0-9])(r7f\d[a-z0-9]+)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(e3\d{3,4}[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(ytm32[a-z0-9]+)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(fc\d{4}[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(tha6\d+[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(ccfc\d+[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(gd32[a-z0-9]+)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(spc5\d+[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(stm32[a-z0-9]+)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(tms570[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(am263[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(cyt[a-z0-9]+)(?![a-z0-9])", re.IGNORECASE), "upper"),
    (re.compile(r"(?<![a-z0-9])(ac78\d{2}[a-z0-9]*)(?![a-z0-9])", re.IGNORECASE), "upper"),
)
_NOISE_STEM_TOKENS = frozenset({
    "infineon",
    "sak",
    "sal",
    "nxp",
    "renesas",
    "st",
    "ti",
    "semidrive",
    "gigadevice",
    "datasheet",
    "data",
    "sheet",
    "manual",
    "user",
    "users",
    "reference",
    "um",
    "ds",
    "en",
    "cn",
    "zh",
    "ab",
    "aa",
    "std",
})


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


def _format_mcu_token(raw: str, mode: str | None) -> str:
    if mode == "tc_x":
        return f"TC{raw[2:-1].upper()}x"
    if mode == "rh850":
        return raw.upper().replace("_", "-")
    return raw.upper()


def _match_mcu_model(text: str) -> str:
    for pattern, mode in _MCU_PATTERNS:
        found = pattern.search(text)
        if found:
            return _format_mcu_token(found.group(1), mode)
    return ""


def mcu_name(filename: str, pages: list[tuple[int, str]] | None = None) -> str:
    stem = Path(filename).stem
    low = Path(filename).name.lower().replace("_", "").replace("-", "")
    for needle, name in _MCU_FILE:
        if needle in low:
            return name
    matched = _match_mcu_model(stem)
    if matched:
        return matched
    if pages:
        for _, text in pages[:5]:
            for needle, name in _MCU_FILE:
                if needle in text.lower().replace("_", "").replace("-", ""):
                    return name
            matched = _match_mcu_model(text)
            if matched:
                return matched
    tokens: list[str] = []
    for tok in re.split(r"[\s\-_.]+", stem):
        clean = tok.strip()
        if not clean:
            continue
        tlow = clean.lower()
        if tlow in _NOISE_STEM_TOKENS:
            continue
        if re.fullmatch(r"v?\d+(?:[._]\d+)*|rev\d*|\d{6,8}", tlow):
            continue
        if _PACKAGE.fullmatch(clean):
            continue
        tokens.append(clean)
    for tok in tokens:
        if any(ch.isalpha() for ch in tok) and any(ch.isdigit() for ch in tok):
            return tok.upper()
    if tokens:
        return tokens[0].upper()
    raise ValueError("文件名里看不出 MCU 型号。")


def _package_name(line: str) -> str:
    found = _PACKAGE.search(line)
    if not found:
        return ""
    kind = found.group("kind").upper()
    if kind == "F2BGA":
        kind = "BGA"
    return f"{kind}{found.group('num')}"


def _looks_like_pin_page(text: str) -> bool:
    head = text[:600].lower()
    low = text.lower()
    return (
        "pin configuration" in head
        or "port " in head
        or "pin definition" in head
        or "pin assignment" in head
        or "pinout" in head
        or "pin description" in head
        or "ball symbol" in low
        or "pin symbol" in low
        or "pin name" in low
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
    if "on page" in low or re.search(r"\.\s*\.\s*\.\s*\d+$", line):
        return ""
    if low.startswith(("figure ", "packages type")):
        return ""
    if not any(
        mark in low
        for mark in (
            "package variant",
            "pin configuration",
            "pin assignment",
            "pin definition",
            "pinout",
            "port ",
            "analog",
            "system",
        )
    ):
        return ""
    return _package_name(line)


def _ball_matches_package(ball: str, package: str) -> bool:
    if "BGA" in package.upper():
        return _BALL_BGA.match(ball) is not None
    return True


def _apply_ctrl(open_pin: _OpenPin, ctrl: str) -> None:
    norm = ctrl.upper()
    if norm in {"I/O", "IO"}:
        open_pin.has_input = True
        open_pin.has_output = True
    elif norm == "I":
        open_pin.has_input = True
    else:
        open_pin.has_output = True


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
            if _STOP_SECTION.match(line) or _OTHER_BALL.match(line):
                close()
                continue
            bare = _PIN_BARE.match(line)
            if bare and _ball_matches_package(bare.group("ball"), current):
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
                    _apply_ctrl(open_pin, direction.group("ctrl"))
                    open_pin.lines.append(line)
                    open_pin.add_buffer_rest(direction.group("rest") or "")
                    continue
                open_pin.await_io = False
            started = _PIN_START.match(line)
            if started and _ball_matches_package(started.group("ball"), current):
                close()
                open_pin = _OpenPin(
                    current,
                    started.group("ball"),
                    started.group("symbol"),
                    number,
                    line,
                )
                alias = started.group("alias")
                if alias and alias != open_pin.symbol:
                    open_pin.mux.append(alias)
                _apply_ctrl(open_pin, started.group("ctrl"))
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
        if not any(
            mark in low
            for mark in (
                "pin configuration",
                "package variant",
                "pin assignment",
                "pinout",
                "pin definition",
            )
        ):
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
