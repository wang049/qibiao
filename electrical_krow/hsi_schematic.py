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
