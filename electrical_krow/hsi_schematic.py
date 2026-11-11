"""从 Altium EDIF 网表读原理图网络，以及接到电源或地的电阻。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_RENAME = re.compile(r'^\(rename \S+ "([^"]+)"\)')
_PORT = re.compile(r"\(PortRef &?([^\s\)]+) \(InstanceRef ([^\)]+)\)")
_VALUE = re.compile(r'\(Property Value \(String "([^"]*)"')
_TYPE = re.compile(r'\(Property Type \(String "([^"]*)"')
_SUPPLY = re.compile(r"^(?:5V|3V3|3\.3V|1V8|1V2|VCC|VDD|VDDA|VDDIO)(?:_|$)")


@dataclass(frozen=True)
class _Pull:
    kind: str
    part: str
    value: str
    other: str


@dataclass(frozen=True)
class SchematicHit:
    net: str
    pulls: tuple[_Pull, ...]


@dataclass(frozen=True)
class BoardPin:
    """功率板接插件上的一只脚。"""

    ref: str
    pin: str
    net: str
    pulls: tuple[_Pull, ...]

    @property
    def label(self) -> str:
        return f"{self.ref}.{self.pin}"


_PIN_TOKEN = re.compile(r"P\d{1,2}\.\d{1,2}|AN\d{1,3}", re.I)


def pin_key(symbol: str) -> str:
    """HSI 引脚符号。`P2.1` 与 `P02.1` 视为同一只脚。"""
    matched = re.fullmatch(r"P(\d{1,2})\.(\d{1,2})", (symbol or "").strip(), re.I)
    if matched:
        return f"P{int(matched.group(1)):02d}.{int(matched.group(2))}"
    matched = re.fullmatch(r"AN(\d{1,3})", (symbol or "").strip(), re.I)
    if matched:
        return f"AN{int(matched.group(1))}"
    return ""


def _pins_in(*parts: str) -> list[str]:
    found: list[str] = []
    for part in parts:
        for token in _PIN_TOKEN.findall(part or ""):
            key = pin_key(token)
            if key and key not in found:
                found.append(key)
    return found


def net_key(name: str) -> str:
    """同一网络的内部键。不用于和 HSI 端口名对齐。"""
    return (name or "").replace(" ", "").upper()


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace")


def _block(text: str, start: int) -> str:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _net_name(header: str) -> str:
    renamed = _RENAME.match(header.strip())
    if renamed:
        return renamed.group(1)
    return header.split()[0]


def _rail(net: str) -> str:
    if not net:
        return ""
    folded = net.upper()
    if folded == "GND" or folded.startswith("GND_") or folded.endswith("_GND"):
        return "下拉"
    if _SUPPLY.match(folded):
        return "上拉"
    return ""


def read_schematic(path: Path) -> dict[str, SchematicHit]:
    """按 MCU 引脚符号返回原理图网络。端口名相近但不含引脚符号时不返回。"""
    if path.suffix.lower() != ".edf" or not path.is_file():
        return {}
    text = _read_text(path)
    pin_net: dict[tuple[str, str], str] = {}
    net_pins: dict[str, list[str]] = {}
    net_names: dict[str, str] = {}
    for match in re.finditer(r"\(Net ", text):
        block = _block(text, match.start())
        if not block:
            continue
        head = block[len("(Net ") :].split("(Joined", 1)[0]
        name = _net_name(head)
        if not name:
            continue
        key = net_key(name)
        net_names.setdefault(key, name)
        refs = _PORT.findall(block)
        pins = _pins_in(name, *(port for port, _inst in refs), *(inst for _port, inst in refs))
        if pins:
            bucket = net_pins.setdefault(key, [])
            for pin in pins:
                if pin not in bucket:
                    bucket.append(pin)
        for port, inst in refs:
            pin_net[(inst, port)] = name
    pulls: dict[str, list[_Pull]] = {}
    for match in re.finditer(r"\(Instance ", text):
        block = _block(text, match.start())
        if not block.startswith("(Instance "):
            continue
        inst = block.split()[1].rstrip(")")
        if not inst.startswith("R"):
            continue
        kind = _TYPE.search(block)
        if kind is None or kind.group(1) != "Res":
            continue
        value = _VALUE.search(block)
        shown = value.group(1) if value else ""
        first = pin_net.get((inst, "1"))
        second = pin_net.get((inst, "2"))
        for signal, other in ((first, second), (second, first)):
            role = _rail(other or "")
            if not signal or not role:
                continue
            pulls.setdefault(net_key(signal), []).append(_Pull(role, inst, shown, other or ""))
    found: dict[str, SchematicHit] = {}
    for key, pins in net_pins.items():
        hit = SchematicHit(net_names[key], tuple(pulls.get(key, ())))
        for pin in pins:
            found.setdefault(pin, hit)
    return found


def _pin_id(token: str) -> str:
    token = (token or "").strip().strip('"')
    if token.startswith("&"):
        token = token[1:]
    return token


def _cell_ports(text: str) -> dict[str, list[str]]:
    """元件接口上声明的脚号。接插件未入网的脚也在这里。"""
    found: dict[str, list[str]] = {}
    for match in re.finditer(r"\(cell\s+", text):
        block = _block(text, match.start())
        head = block[:240]
        renamed = re.match(r'\(cell\s+\(rename\s+(\S+)\s+"([^"]+)"\)', head)
        plain = re.match(r"\(cell\s+(\S+)", head)
        if renamed:
            name = renamed.group(1)
        elif plain:
            name = plain.group(1)
        else:
            continue
        ports: list[str] = []
        for item in re.finditer(r'\(port\s+(?:\(rename\s+\S+\s+"([^"]+)"\)|(&?\S+))', block):
            shown = _pin_id(item.group(1) or item.group(2))
            if shown and shown not in ports:
                ports.append(shown)
        if ports:
            found[name] = ports
    return found


def _connector_defined_pins(text: str) -> dict[str, list[str]]:
    cells = _cell_ports(text)
    mapping: dict[str, list[str]] = {}
    for match in re.finditer(r"\(Instance ", text):
        block = _block(text, match.start())
        if not block.startswith("(Instance "):
            continue
        inst = block.split()[1].rstrip(")")
        kind = _TYPE.search(block)
        if not (_CONNECTOR.match(inst) or (kind is not None and kind.group(1) == "CON")):
            continue
        cell = re.search(r"\(cellRef\s+([^\s\)]+)", block)
        mapping[inst] = cells.get(cell.group(1), []) if cell else []
    return mapping


_CONNECTOR = re.compile(r"^J\d+", re.I)


def _connector_refs(text: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(r"\(Instance ", text):
        block = _block(text, match.start())
        if not block.startswith("(Instance "):
            continue
        inst = block.split()[1].rstrip(")")
        kind = _TYPE.search(block)
        if _CONNECTOR.match(inst) or (kind is not None and kind.group(1) == "CON"):
            found.add(inst)
    return found


def read_board_pins(path: Path) -> list[BoardPin]:
    """按接插件自己的脚返回一行。不读取 MCU 的 P02.1、AN0。"""
    if path.suffix.lower() != ".edf" or not path.is_file():
        return []
    text = _read_text(path)
    connectors = _connector_refs(text)
    if not connectors:
        return []
    pin_net: dict[tuple[str, str], str] = {}
    members: dict[str, list[tuple[str, str]]] = {}
    for match in re.finditer(r"\(Net ", text):
        block = _block(text, match.start())
        if not block:
            continue
        head = block[len("(Net ") :].split("(Joined", 1)[0]
        name = _net_name(head)
        if not name:
            continue
        refs = _PORT.findall(block)
        members[name] = refs
        for port, inst in refs:
            pin_net[(inst, port)] = name
    pulls: dict[str, list[_Pull]] = {}
    for match in re.finditer(r"\(Instance R", text):
        block = _block(text, match.start())
        if not block.startswith("(Instance "):
            continue
        inst = block.split()[1].rstrip(")")
        kind = _TYPE.search(block)
        if kind is None or kind.group(1) != "Res":
            continue
        value = _VALUE.search(block)
        shown = value.group(1) if value else ""
        first = pin_net.get((inst, "1"))
        second = pin_net.get((inst, "2"))
        for signal, other in ((first, second), (second, first)):
            role = _rail(other or "")
            if not signal or not role:
                continue
            pulls.setdefault(signal, []).append(_Pull(role, inst, shown, other or ""))
    rows: list[BoardPin] = []
    seen: set[tuple[str, str]] = set()
    for name, refs in members.items():
        attached = () if _rail(name) else tuple(pulls.get(name, ()))
        for port, inst in refs:
            if inst not in connectors:
                continue
            key = (inst, port)
            if key in seen:
                continue
            seen.add(key)
            rows.append(BoardPin(inst, port, name, attached))
    for inst, ports in _connector_defined_pins(text).items():
        for port in ports:
            key = (inst, port)
            if key in seen:
                continue
            seen.add(key)
            rows.append(BoardPin(inst, port, "", ()))
    rows.sort(key=lambda item: (item.ref, _pin_order(item.pin)))
    return rows


def _pin_order(pin: str) -> tuple[int, str]:
    if pin.isdigit():
        return int(pin), pin
    return 10**9, pin


@dataclass(frozen=True)
class SchematicSymbolPin:
    """原理图符号上认出的一只 MCU 脚。"""

    symbol: str
    ball: str
    function: str
    sheet: str
    net: str = ""


_SCH_PIN = re.compile(r"^(P\d{1,2})_(\d{1,2})(?:/(.+))?$")
_SCH_AN = re.compile(r"^(AN\d+)(?:/(P\d{1,2})_(\d{1,2}))?(?:/(.+))?$", re.I)
_SCH_BALL = re.compile(r"^[A-Z]{1,2}\d{1,2}$")
_SCH_SHEET = re.compile(r"([\w .+-]+?)\.SchDoc")
_SCH_MCU = re.compile(r"TC\d{3}")
# 球号文字比引脚文字高约 2.6 pt。上下两行距约 5.3 pt，取绝对最近会配到下一行。
# 网络名常写在导线上方，字心离导线大约 3 pt，仍小于行距的一半。
_BALL_DX = 50.0
_BALL_ABOVE = 2.64
_WIRE_BAND = 3.2
_NET_NAME = re.compile(r"[A-Za-z].*[_/].*")


def _norm_port_symbol(port: str, bit: str) -> str:
    return f"P{int(port[1:]):02d}.{int(bit)}"


def _word_y(word: tuple[float, float, float, float, str]) -> float:
    return (word[1] + word[3]) / 2


def _word_x(word: tuple[float, float, float, float, str]) -> float:
    return (word[0] + word[2]) / 2


def _net_word(text: str) -> bool:
    if not _NET_NAME.search(text) or "[" in text or " " in text:
        return False
    if text.startswith(("PO", "PI", "CB", "TP")):
        return False
    if _SCH_PIN.match(text) or _SCH_AN.match(text):
        return False
    return _SCH_BALL.match(text) is None


def _touching_wire(
    pin: tuple[float, float, float, float, str],
    lines: list[tuple[float, float, float]],
) -> tuple[str, float, float, float] | None:
    """返回脚朝向、这一侧的导线范围，以及这根导线的纵坐标。不跨过中间的空隙。"""
    py = _word_y(pin)
    segs = [(line_y, x0, x1) for line_y, x0, x1 in lines if abs(line_y - py) <= _WIRE_BAND]
    left = right = None
    for line_y, x0, x1 in segs:
        if abs(x1 - pin[0]) <= 8 and x0 < pin[0] - 8:
            gap = pin[0] - x1
            if left is None or gap < left[0]:
                left = (gap, x0, x1, line_y)
        if abs(x0 - pin[2]) <= 8 and x1 > pin[2] + 8:
            gap = x0 - pin[2]
            if right is None or gap < right[0]:
                right = (gap, x0, x1, line_y)
    if left is None and right is None:
        return None
    if right is None or (left is not None and left[0] <= right[0]):
        far = left[1]
        changed = True
        while changed:
            changed = False
            for _line_y, x0, x1 in segs:
                if abs(x1 - far) <= 2 and x0 < far:
                    far = x0
                    changed = True
        return "L", far, pin[0], left[3]
    far = right[2]
    changed = True
    while changed:
        changed = False
        for _line_y, x0, x1 in segs:
            if abs(x0 - far) <= 2 and x1 > far:
                far = x1
                changed = True
    return "R", pin[2], far, right[3]


def _net_on_wire(
    pin: tuple[float, float, float, float, str],
    labels: list[tuple[float, float, float, float, str]],
    lines: list[tuple[float, float, float]],
) -> str:
    wire = _touching_wire(pin, lines)
    if wire is None:
        return ""
    side, near, far, line_y = wire
    best: tuple[float, str] | None = None
    for label in labels:
        if abs(_word_y(label) - line_y) > _WIRE_BAND:
            continue
        if side == "L":
            if label[0] > pin[0]:
                continue
            overlap = min(label[2], far) - max(label[0], near)
            gap = near - label[2]
            dist = pin[0] - label[2]
        else:
            if label[2] < pin[2]:
                continue
            overlap = min(label[2], far) - max(label[0], near)
            gap = label[0] - far
            dist = label[0] - pin[2]
        if dist < 0 or not (overlap > 0 or 0 <= gap <= 18):
            continue
        if best is None or dist < best[0]:
            best = (dist, label[4])
    return best[1] if best else ""


def _parsed_pin(text: str) -> tuple[str, str] | None:
    """引脚符号和写在同一串里的功能。AN36/P40_6 的符号是 AN36，功能是 P40.6。"""
    matched = _SCH_PIN.match(text)
    if matched:
        function = (matched.group(3) or "").strip()
        if function.upper() == "NC":
            function = ""
        return _norm_port_symbol(matched.group(1), matched.group(2)), function
    analog = _SCH_AN.match(text)
    if analog is None:
        return None
    symbol = f"AN{int(analog.group(1)[2:])}"
    parts: list[str] = []
    if analog.group(2) and analog.group(3):
        parts.append(_norm_port_symbol(analog.group(2), analog.group(3)))
    rest = (analog.group(4) or "").strip()
    if rest and rest.upper() != "NC":
        parts.append(rest)
    return symbol, "/".join(parts)


def pins_from_schematic_words(
    words: list[tuple[float, float, float, float, str]],
    sheet: str,
    lines: list[tuple[float, float, float]] | None = None,
) -> list[SchematicSymbolPin]:
    """球号用同一行、略高于引脚的文字。网络名取这只脚朝向那一侧导线上的名字。"""
    pins = [word for word in words if _parsed_pin(word[4])]
    balls = [
        word
        for word in words
        if _SCH_BALL.match(word[4]) and _parsed_pin(word[4]) is None and not word[4].startswith("PI")
    ]
    labels = [word for word in words if _net_word(word[4])]
    claims: list[tuple[float, float, int, int]] = []
    for pin_index, pin in enumerate(pins):
        py = _word_y(pin)
        px = _word_x(pin)
        for ball_index, ball in enumerate(balls):
            dx = _word_x(ball) - px
            dy = _word_y(ball) - py
            if abs(dx) > _BALL_DX or not (-4.2 <= dy <= -1.2):
                continue
            claims.append((abs(dx), abs(dy + _BALL_ABOVE), pin_index, ball_index))
    claims.sort()
    chosen: dict[int, str] = {}
    used_balls: set[int] = set()
    for _dx, _dy, pin_index, ball_index in claims:
        if pin_index in chosen or ball_index in used_balls:
            continue
        chosen[pin_index] = balls[ball_index][4]
        used_balls.add(ball_index)
    wire_lines = lines or []
    found: list[SchematicSymbolPin] = []
    for pin_index, pin in enumerate(pins):
        parsed = _parsed_pin(pin[4])
        if parsed is None:
            continue
        symbol, function = parsed
        net = _net_on_wire(pin, labels, wire_lines)
        found.append(SchematicSymbolPin(symbol, chosen.get(pin_index, ""), function, sheet, net))
    return found


def _horizontal_lines(page) -> list[tuple[float, float, float]]:
    found: list[tuple[float, float, float]] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            start, end = item[1], item[2]
            if abs(start.y - end.y) > 0.8:
                continue
            x0, x1 = sorted((start.x, end.x))
            if x1 - x0 < 8:
                continue
            found.append(((start.y + end.y) / 2, x0, x1))


def read_schematic_pdf(path: Path) -> tuple[list[SchematicSymbolPin], str]:
    """从原理图 PDF 认出 MCU 符号上的脚、球号和图纸上写的功能。返回引脚和认出的型号。"""
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return [], ""
    import pymupdf

    doc = pymupdf.open(path)
    try:
        grouped: dict[str, SchematicSymbolPin] = {}
        mcu = ""
        for page in doc:
            text = page.get_text() or ""
            if not mcu:
                found = _SCH_MCU.search(text)
                if found:
                    mcu = found.group(0)
            title = _SCH_SHEET.search(text)
            sheet = title.group(1).strip() if title else f"第{page.number + 1}页"
            words = [
                (word[0], word[1], word[2], word[3], word[4])
                for word in page.get_text("words")
            ]
            for pin in pins_from_schematic_words(words, sheet, _horizontal_lines(page)):
                current = grouped.get(pin.symbol)
                if current is None:
                    grouped[pin.symbol] = pin
                    continue
                if (pin.function and not current.function) or (pin.ball and not current.ball) or (pin.net and not current.net):
                    grouped[pin.symbol] = SchematicSymbolPin(
                        pin.symbol,
                        pin.ball or current.ball,
                        pin.function or current.function,
                        pin.sheet if pin.ball or pin.function else current.sheet,
                        pin.net or current.net,
                    )
        pins = sorted(grouped.values(), key=lambda item: _symbol_sort(item.symbol))
        return pins, mcu
    finally:
        doc.close()


def _symbol_sort(symbol: str) -> tuple[int, int, str]:
    matched = re.fullmatch(r"P(\d+)\.(\d+)", symbol)
    if matched:
        return int(matched.group(1)), int(matched.group(2)), symbol
    return 10**9, 10**9, symbol
    analog = re.fullmatch(r"AN(\d+)", symbol, re.I)
    if analog:
        return 1000, int(analog.group(1)), symbol
