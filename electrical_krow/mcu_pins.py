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
# 手册功能列和缓冲列抽在同一行时，供电名会粘在信号名后面，例如 `GTM_TIM2_IN3_6 VDDEXTH`。
_SUPPLY_TOKEN = re.compile(
    r"VD[A-Z0-9]+|VEXT|VEVRSB|VAREF|VFLEX|VAEXT|FAST|SLOW|PU\d*|PD\d*|HIGHZ|ES\d+|LVDS(?:_[A-Z0-9]+)?",
    re.IGNORECASE,
)
_SIGNAL_TOKEN = re.compile(r"[A-Z][A-Z0-9]*[0-9_][A-Z0-9_]*")
_RESERVED_ITEM = re.compile(r"^(?:[—\-–]\s*)?(?:O\d+\s+)?Reserved$", re.IGNORECASE)
_RESERVED_PHRASE = re.compile(
    r"(?:^|\s)[—\-–]\s+O\d+\s+Reserved\b|(?:^|\s)O\d+\s+Reserved\b|(?:^|\s)[—\-–]\s+Reserved\b",
    re.IGNORECASE,
)
_GLUED_SUPPLY = re.compile(
    r"\b([A-Z][A-Z0-9]*[0-9_][A-Z0-9_]*)\s+(?:VD[A-Z0-9]+|VEXT|VEVRSB|VAREF|VFLEX|VAEXT)\b"
)
_MUX = re.compile(
    r"^(?P<name>[—\-–A-Z][A-Z0-9_]*)\s+(?P<ctrl>[IO]\d+)\s*(?P<desc>.*)$"
)
_OUTPUT = re.compile(
    rf"^(?P<symbol>{_SYM})\s+O0\s*(?P<desc>.*)$"
)
_ONE_BALL = r"[A-Z]{1,2}\d{1,2}"
_BALL_GROUP = rf"{_ONE_BALL}(?:\s*,\s*{_ONE_BALL})*"
_BALLS_ONLY = re.compile(rf"^(?P<balls>{_BALL_GROUP})\s*,?\s*$")
_BALLS_AND_PIN = re.compile(
    rf"^(?P<balls>{_BALL_GROUP})\s+"
    rf"(?P<symbol>[A-Z][A-Z0-9_]*)\s+"
    rf"(?P<ctrl>I/O|IO|[IO])\b\s*(?P<rest>.*)$"
)
_SYMBOL_LINE = re.compile(
    rf"^(?P<symbol>[A-Z][A-Z0-9_]*)\s+"
    rf"(?P<ctrl>I/O|IO|[IO])\b\s*(?P<rest>.*)$"
)
_OTHER_PIN = re.compile(
    rf"^(?P<ball>{_BALL_ANY})\s+"
    r"(?P<symbol>VGATE\d+[NP]|XTAL\d+|DAPE\d+|THD\d+_[A-Z]|NC\d*(?:_[A-Z0-9]+)?|"
    r"PHY\d*_[A-Z0-9_]+|GND[A-Z0-9_]*|V(?:DD|SS|CC|EXT|FLEX|AREF|AGND)[A-Z0-9_]*)\s+"
    r"(?P<ctrl>I/O|IO|[IO])\b\s*(?P<rest>.*)$"
)
_SUPPLY_NAME = re.compile(
    r"^(?:VSS[A-Z0-9_]*|GND[A-Z0-9_]*|AGND[A-Z0-9_]*|VAGND[A-Z0-9_]*|VSSA[A-Z0-9_]*)$",
    re.IGNORECASE,
)
_POWER_NAME = re.compile(
    r"^(?:VDD[A-Z0-9_]*|VCC[A-Z0-9_]*|VEXT[A-Z0-9_]*|VDDM[A-Z0-9_]*|"
    r"VAREF[A-Z0-9_]*|VFLEX[A-Z0-9_]*|VAEXT[A-Z0-9_]*|VEVRSB[A-Z0-9_]*)$",
    re.IGNORECASE,
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


def _signal_start(text: str) -> bool:
    first = text.split(None, 1)[0] if text else ""
    return _SIGNAL_TOKEN.fullmatch(first) is not None


def _peel_glued_supply(text: str) -> tuple[str, list[str]] | None:
    """功能名同一行尾部若是供电或缓冲记号，拆回缓冲，不留在复用名上。"""
    parts = text.split()
    if len(parts) < 2 or _SIGNAL_TOKEN.fullmatch(parts[0]) is None:
        return None
    supplies: list[str] = []
    index = 1
    while index < len(parts) and _SUPPLY_TOKEN.fullmatch(parts[index]):
        supplies.append(parts[index])
        index += 1
    if not supplies:
        return None
    rest = " ".join(parts[index:]).strip()
    name = parts[0] if not rest else f"{parts[0]} {rest}"
    return name, supplies


def pin_supply_kind(symbol: str) -> str:
    """电源、地留在引脚表里，出表时用筛选藏起来，不从清单里删掉。"""
    name = (symbol or "").strip()
    if _SUPPLY_NAME.match(name):
        return "地"
    if _POWER_NAME.match(name):
        return "电源"
    return ""


def _general_purpose(pin: ChipPin) -> bool:
    """手册把这只脚写成通用口。复用里的 CAN、PWM 是可选功能，不改变分类。"""
    folded = (pin.function or "").upper()
    if "GENERAL-PURPOSE" in folded or "GENERAL PURPOSE" in folded:
        return True
    return folded.strip() in {"PORT", "I/O", "IO"}


def pin_class(pin: ChipPin) -> str:
    """只按当份手册的符号和功能归类。复用里的可选功能不把整脚算进专用类。

    规划路径用的名单：电源、地、IO、ADC、SPI、CAN、GPIO；其余能从手册认出的仍保留。
    没有原理图时，这些词写入端口表 Function 列。
    """
    supply = pin_supply_kind(pin.symbol)
    if supply:
        return supply
    if pin.symbol.upper().startswith("AN"):
        return "ADC"
    if _general_purpose(pin) or pin.symbol.upper().startswith("GPIO"):
        return "GPIO"
    blob = f"{pin.symbol} {pin.function}".upper()
    if re.search(r"(?<![A-Z0-9])(ADC|EVADC|DSADC|TMADC)(?![A-Z])", blob):
        return "ADC"
    if re.search(r"(?<![A-Z0-9])DAC(?![A-Z])", blob):
        return "DAC"
    if re.search(r"(?<![A-Z0-9])(?:QSPI|SPI)\d", blob):
        return "SPI"
    if re.search(r"(?<![A-Z0-9])(?:CANXL|CAN)\d", blob):
        return "CAN"
    if re.search(r"(?<![A-Z0-9])(PWM|GTM|TIM|TOM|ATOM|CCU6)(?![A-Z])", blob):
        return "PWM"
    if "寄存器" in blob or re.search(r"\bREGISTER\b", blob):
        return "寄存器"
    symbol = pin.symbol.strip()
    if re.match(r"^NC\d*", symbol, re.I):
        return "空脚"
    if re.match(r"^XTAL\d*", symbol, re.I):
        return "时钟"
    if re.match(r"^PHY\d*", symbol, re.I):
        return "以太网"
    if re.match(r"^(?:TRST|TCK|TMS|TDI|TDO)$", symbol, re.I) or re.search(r"\bDAP\d*\b", blob):
        return "调试"
    if re.match(r"^PORST", symbol, re.I) or re.search(r"\bRESET\b", blob):
        return "复位"
    if re.match(r"^P\d{1,2}[._]\d{1,2}$", symbol, re.I) or re.match(r"^PT[A-Z]\d+", symbol, re.I):
        return "GPIO"
    return ""


def is_reserved_mux_item(text: str) -> bool:
    return _RESERVED_ITEM.fullmatch(text.strip()) is not None


def present_mux(mux: str) -> str:
    """复用按功能分行，去掉只写 Reserved 的空位。"""
    items: list[str] = []
    for part in re.split(r"[；;\n]", mux or ""):
        text = part.strip()
        if not text or is_reserved_mux_item(text):
            continue
        items.append(text)
    return "\n".join(items)


def present_excerpt(excerpt: str) -> str:
    """原文摘录去掉 Reserved 空位，供电名不粘在信号名上，每个信号单独成行。"""
    text = _RESERVED_PHRASE.sub(" ", excerpt or "")
    text = _GLUED_SUPPLY.sub(r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text).strip()
    text = re.sub(r" (?=[A-Z][A-Z0-9]*_[A-Z0-9]+\b)", "\n", text)
    return text


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
        original = text
        peeled = _peel_glued_supply(text)
        if peeled:
            name, supplies = peeled
            self.buffers.extend(supplies)
            text = name
        if self.function and self.mux and not _signal_start(text):
            self.mux[-1] = f"{self.mux[-1]} {text}".strip()
            self.lines.append(original)
            return
        if not self.function:
            self.function = text
        else:
            self.mux.append(text)
        self.lines.append(original)

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
    pending: list[str] = []

    def close() -> None:
        nonlocal open_pin
        if open_pin is None:
            return
        pin = open_pin.finish()
        open_pin = None
        if pin is None:
            return
        key = (pin.package, pin.ball)
        if key in seen:
            return
        seen.add(key)
        rows.append(pin)

    def take_balls(text: str) -> list[str]:
        return re.findall(_ONE_BALL, text)

    def emit_balls(balls: list[str], symbol: str, ctrl: str, rest: str, page: int, line: str) -> None:
        nonlocal open_pin
        close()
        function = rest.strip(" —-\t")
        for ball in balls:
            if not _ball_matches_package(ball, current):
                continue
            pin = _OpenPin(current, ball, symbol, page, line)
            _apply_ctrl(pin, ctrl)
            if function:
                pin.function = function
            open_pin = pin
            close()

    for number, text in pages:
        if not _looks_like_pin_page(text):
            close()
            pending.clear()
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            named = _package_on_section(line)
            if named:
                if named != current:
                    close()
                    pending.clear()
                current = named
                continue
            if current.upper().replace("-", "").replace(" ", "") != want:
                continue
            if _STOP_SECTION.match(line):
                close()
                continue
            balls_only = _BALLS_ONLY.match(line)
            if balls_only and ("," in line or pending):
                close()
                pending.extend(take_balls(balls_only.group("balls")))
                continue
            grouped = _BALLS_AND_PIN.match(line)
            if grouped and ("," in grouped.group("balls") or pending):
                balls = pending + take_balls(grouped.group("balls"))
                pending.clear()
                emit_balls(
                    balls,
                    grouped.group("symbol"),
                    grouped.group("ctrl"),
                    grouped.group("rest") or "",
                    number,
                    line,
                )
                continue
            symbol_line = _SYMBOL_LINE.match(line)
            if pending and symbol_line and not _PIN_START.match(line):
                balls = list(pending)
                pending.clear()
                emit_balls(
                    balls,
                    symbol_line.group("symbol"),
                    symbol_line.group("ctrl"),
                    symbol_line.group("rest") or "",
                    number,
                    line,
                )
                continue
            other = _OTHER_PIN.match(line)
            if other and _ball_matches_package(other.group("ball"), current):
                close()
                open_pin = _OpenPin(
                    current,
                    other.group("ball"),
                    other.group("symbol"),
                    number,
                    line,
                )
                _apply_ctrl(open_pin, other.group("ctrl"))
                rest = other.group("rest").strip(" —-\t")
                if rest:
                    open_pin.function = rest
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


def read_pdf_pages(path: Path, on_progress=None) -> list[tuple[int, str]]:
    """on_progress(done, total) 按页回报。抽文字是读手册里最久的一段。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    total = len(reader.pages)
    if on_progress is not None:
        on_progress(0, total)
    for index, page in enumerate(reader.pages, start=1):
        pages.append((index, page.extract_text() or ""))
        if on_progress is not None:
            on_progress(index, total)
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
