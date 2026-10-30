"""HSI 端口规划规则与 LLM 语义质检。

硬件事实（球号、方向、缓冲、功能、复用、页码、原文摘录）一律来自当份芯片手册。
本模块在不触碰底表硬件事实抄录的前提下，负责：
1. 组合/别名引脚符号归一化对齐（如模板 `AN17/P40_10` 与手册 `AN17` / 复用 `P40.10`）；
2. 当份手册硬件外设复用能力（Mux）与模板 Function/端口定义冲突核查；
3. 模板主表（`2_Port Assignment`）与子表（`3_ADC Table`、`3-SPI总线` 等）跨表一致性核查；
4. 可疑行的规则检出与可选 LLM 工程语义审查（通过 `ask` 回调）；
5. P1 PWM 是否在同一 ATOM、同一相上下桥是否互补，以及三相电流是否在不同 group 的同一 channel。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from openpyxl.workbook.workbook import Workbook

from electrical_krow.mcu_pins import ChipPin, is_reserved_mux_item

Ask = Callable[[list[dict[str, str]]], str]

_PORT_PIN_RE = re.compile(r"^P(\d+)[._](\d+)$", re.I)
_MUX_PORT_RE = re.compile(r"\bP(\d+)[._](\d+)\b", re.I)
_NC_SET = frozenset({"", "NC", "N.C.", "NA", "N/A", "/", "-"})
_LLM_BATCH = 20

_LLM_QA_PROMPT = (
    "你是车规级电驱 MCU 硬件软件接口（HSI）审核专家。下面给出一组已与芯片手册引脚对齐的 HSI 端口配置候选行（JSON 数组）。"
    "每行包含：手册引脚符号、手册球号、手册支持方向、手册功能与复用摘录（mux），以及模板填写的：模板方向、模板功能分类、端口名、功能描述、高电平/上升沿定义（high）、低电平/下降沿定义（low）、初始设置（init）、子表引用（sub_sheets）。\n"
    "请逐行审查模板工程定义是否存在内部矛盾或与手册硬件能力冲突：\n"
    "1. 【方向与描述/命名矛盾】：例如模板方向填 Input，但端口名是主控发出的使能输出（如 EN_M/A_...）或功能描述写「输出...信号/使能」且非回读/检测；或端口名含两个不同模块信号（如换行写了 QSPI5_MOSI 却配成 Input）。\n"
    "2. 【高低电平/边沿列填错】：例如「低电平或下降沿(low)」列填成了 High/rising，或「高电平或上升沿(high)」列填成了 Low/falling；或同类低有效故障反馈信号（如 FLTA/DESAT）在本行被填成高电平有效（High）。\n"
    "3. 【硬件复用能力冲突】：模板要求的外设（CAN/SPI/PWM/ADC/SENT）或收发角色（TXD/RXD/MISO/MOSI/CLK）在手册 mux 中不具备对应能力。\n"
    "4. 【跨子表不一致】：子表（如 3_ADC Table、3-SPI总线）中的球号、信号名与主表或当份手册冲突。\n"
    "注意：所有指出的问题必须依据输入 JSON 中给出的当份手册字段与模板字段，严禁编造手册未出现的球号或复用通道。若某行仅为新旧网络名括号并列备注（如 `DC_SWEN1(FLT_M_LED)`）且方向与描述自洽，可归为 \"warn\" 提示确认主用网络名；若确属方向反填、电平列颠倒、硬件复用不支持或球号冲突，归为 \"conflict\"。\n"
    "只输出 JSON 数组，每个元素形如：{\"symbol\": \"P10.8\", \"level\": \"conflict\" 或 \"warn\", \"reason\": \"简明中文原因（不超过50字）\"}。没有问题的引脚不要输出。"
)


@dataclass(frozen=True)
class SubSheetEntry:
    sheet: str
    symbol: str
    ball: str = ""
    signal: str = ""
    direction: str = ""
    description: str = ""


@dataclass
class PinQaFinding:
    symbol: str
    conflict_notes: list[str] = field(default_factory=list)
    warn_notes: list[str] = field(default_factory=list)
    sub_hints: list[str] = field(default_factory=list)


def norm_symbol(raw: object) -> str:
    """将引脚符号归一化：去首尾空白、转大写，`P40_10` / `P0.1` 统一为 `P40.10` / `P00.1`。"""
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    text = re.sub(r"^TC\d+[A-Z]*_", "", text)
    matched = _PORT_PIN_RE.match(text)
    if matched:
        return f"P{int(matched.group(1)):02d}.{int(matched.group(2))}"
    return text


def split_symbol_parts(symbol: str) -> list[str]:
    """拆分模板或手册里的组合符号（如 `AN17/P40_10` -> `['AN17', 'P40.10']`）。"""
    parts: list[str] = []
    for piece in re.split(r"[/,]", str(symbol or "")):
        normed = norm_symbol(piece)
        if normed and normed not in parts:
            parts.append(normed)
    return parts


def pin_lookup_keys(pin: ChipPin) -> list[str]:
    """返回当份手册引脚可用于匹配模板符号的归一化键（主符号优先，复用里的 GPIO 端口别名次之）。"""
    keys = split_symbol_parts(pin.symbol)
    for matched in _MUX_PORT_RE.finditer(pin.mux or ""):
        alias = f"P{int(matched.group(1)):02d}.{int(matched.group(2))}"
        if alias not in keys:
            keys.append(alias)
    return keys


def _sheet_named(workbook: Workbook, suffix: str) -> str:
    for name in workbook.sheetnames:
        stripped = name.strip()
        if stripped == suffix or stripped.endswith(suffix):
            return name
    return ""


def _adc_columns(sheet) -> tuple[int, int, int, int, int, int, int]:
    """起始行、group、channel、symbol、ball、signal、desc。

    表头写着 Signal name 时，符号在它左边两列。没有这块表头时沿用旧模板的列。
    """
    for row in range(1, 8):
        for col in range(1, 20):
            text = str(sheet.cell(row, col).value or "").strip().lower()
            if text.startswith("signal name"):
                return row + 1, 2, 3, col - 2, col - 1, col, col + 1
    return 5, 2, 3, 5, 6, 7, 8


def _port_name_column(sheet) -> tuple[int, int]:
    """起始行和端口名所在列。DHTE400 的端口名在第二个 Pin Definition 之前那一列。"""
    for row in range(1, 8):
        function_col = 0
        pin_defs: list[int] = []
        for col in range(1, 25):
            text = str(sheet.cell(row, col).value or "").strip()
            if text == "Function":
                function_col = col
            elif text.startswith("Pin Definition"):
                pin_defs.append(col)
        if function_col and pin_defs:
            return row + 1, pin_defs[0]
    return 5, 10


def extract_subsheet_entries(workbook: Workbook) -> dict[str, list[SubSheetEntry]]:
    """提取模板子表（ADC、SPI）中的引脚映射，用于与主表及手册交叉核对。"""
    by_sym: dict[str, list[SubSheetEntry]] = {}

    adc_name = _sheet_named(workbook, "3_ADC Table")
    if adc_name:
        ws = workbook[adc_name]
        start, _group, _channel, symbol_col, ball_col, signal_col, desc_col = _adc_columns(ws)
        for row in range(start, (ws.max_row or start) + 1):
            raw_sym = str(ws.cell(row, symbol_col).value or "").strip()
            if not raw_sym or raw_sym in _NC_SET:
                continue
            ball = str(ws.cell(row, ball_col).value or "").strip()
            sig = str(ws.cell(row, signal_col).value or "").strip()
            desc = str(ws.cell(row, desc_col).value or "").strip()
            for sym in split_symbol_parts(raw_sym):
                by_sym.setdefault(sym, []).append(
                    SubSheetEntry(
                        sheet=adc_name.strip(),
                        symbol=sym,
                        ball="" if ball in _NC_SET else ball,
                        signal="" if sig in _NC_SET else sig,
                        description="" if desc in _NC_SET else desc,
                    )
                )

    spi_name = ""
    for name in workbook.sheetnames:
        if name.strip().endswith("SPI总线"):
            spi_name = name
            break
    if spi_name:
        ws = workbook[spi_name]
        for row in range(1, (ws.max_row or 1) + 1):
            raw_sym = str(ws.cell(row, 2).value or "").strip()
            if not raw_sym or raw_sym.upper() == "PIN" or raw_sym in _NC_SET:
                continue
            func_sig = str(ws.cell(row, 3).value or "").strip()
            io_dir = str(ws.cell(row, 4).value or "").strip()
            net_name = str(ws.cell(row, 5).value or "").strip()
            desc = str(ws.cell(row, 6).value or "").strip()
            for sym in split_symbol_parts(raw_sym):
                by_sym.setdefault(sym, []).append(
                    SubSheetEntry(
                        sheet=spi_name.strip(),
                        symbol=sym,
                        signal=f"{func_sig} ({net_name})" if func_sig and net_name and func_sig != net_name else (func_sig or net_name),
                        direction=io_dir,
                        description=desc,
                    )
                )

    return by_sym


def check_peripheral_capability(
    pin: ChipPin,
    template_function: str,
    port_name: str,
    template_direction: str,
) -> list[str]:
    """核对当份手册的 `function` + `mux` 是否支持模板要求的硬件外设类别与通道/收发角色。"""
    pdef = (port_name or "").strip()
    if pdef.upper() in _NC_SET:
        return []
    t_func = (template_function or "").strip().upper()
    blob = f"{pin.function}\n{pin.mux}".upper()
    conflicts: list[str] = []

    if t_func == "CAN":
        if "CAN" not in blob:
            conflicts.append(f"模板要求 CAN 外设（{pdef or 'CAN'}），但当份手册该引脚无 CAN 复用功能")
        else:
            if "TXD" in pdef.upper() and not re.search(r"CAN\w*TXD", blob):
                conflicts.append(f"模板端口 {pdef} 要求 CAN 发送（TXD），但当份手册该引脚仅有 CAN 接收复用")
            elif "RXD" in pdef.upper() and not re.search(r"CAN\w*RXD", blob):
                conflicts.append(f"模板端口 {pdef} 要求 CAN 接收（RXD），但当份手册该引脚仅有 CAN 发送复用")

    elif t_func == "SPI":
        if "SPI" not in blob:
            conflicts.append(f"模板要求 SPI 外设（{pdef or 'SPI'}），但当份手册该引脚无 SPI/QSPI 复用功能")
        else:
            m_qspi = re.search(r"QSPI(\d+)", pdef.upper())
            if m_qspi:
                req_ch = m_qspi.group(1)
                avail_chs = sorted(set(re.findall(r"QSPI(\d+)", blob)))
                if avail_chs and req_ch not in avail_chs:
                    avail_str = "、".join(f"QSPI{c}" for c in avail_chs)
                    conflicts.append(f"模板端口 {pdef} 要求 QSPI{req_ch}，但当份手册该引脚仅支持 {avail_str}")

    elif t_func == "SENT":
        if "SENT" not in blob:
            conflicts.append(f"模板要求 SENT 外设（{pdef or 'SENT'}），但当份手册该引脚无 SENT 复用功能")

    elif t_func == "PWM":
        if not any(k in blob for k in ("GTM", "TOM", "ATOM", "TIM", "TOUT", "PWM", "CCU", "EGU")):
            conflicts.append(f"模板要求 PWM/定时器功能（{pdef or 'PWM'}），但当份手册该引脚无 GTM/PWM/定时器复用功能")

    elif t_func == "ANALOG":
        if not any(k in blob for k in ("ADC", "ANALOG", "DSADC", "TMADC", "EVADC")):
            conflicts.append(f"模板要求 Analog 采样（{pdef or 'Analog'}），但当份手册该引脚无模拟采样/ADC 功能")

    return conflicts


def check_template_row_anomalies(
    pin: ChipPin,
    template_direction: str,
    template_function: str,
    project: tuple[object, ...],
    sub_entries: list[SubSheetEntry],
    *,
    template_ball: str = "",
) -> PinQaFinding:
    """确定性规则检查单行模板工程定义（方向与描述/命名矛盾、高低电平列填反、跨子表不一致）。"""
    finding = PinQaFinding(symbol=pin.symbol)
    name = str(project[0] if len(project) > 0 and project[0] is not None else "").strip()
    desc = str(project[1] if len(project) > 1 and project[1] is not None else "").strip()
    high = str(project[6] if len(project) > 6 and project[6] is not None else "").strip()
    low = str(project[7] if len(project) > 7 and project[7] is not None else "").strip()

    if name.upper() not in _NC_SET:
        # 1. 高/低电平列数值颠倒或相同
        if high.upper() in {"LOW", "FALLING", "↓"}:
            finding.conflict_notes.append(f"模板「高电平或上升沿」列填入了低电平/下降沿值（{high}）")
        if low.upper() in {"HIGH", "RISING", "↑"}:
            finding.conflict_notes.append(f"模板「低电平或下降沿」列填入了高电平/上升沿值（{low}）")
        if high and low and high == low and high.upper() not in _NC_SET and not high.lower().startswith("refer to"):
            finding.conflict_notes.append(f"模板高低电平列填写了完全相同的值（{high}）")

        # 2. 方向与端口名/功能描述矛盾
        t_dir = (template_direction or "").strip().upper()
        flat_name = name.replace("\n", " ").strip()
        flat_desc = desc.replace("\n", " ").strip()
        if t_dir == "INPUT":
            if re.search(r"(?:^|_)EN_M[/_\w]", flat_name.upper()) and "ENFB" not in flat_name.upper() and "MON" not in flat_name.upper():
                finding.warn_notes.append(f"模板方向为 Input，但端口名 {flat_name} 及描述「{flat_desc}」呈主控使能输出特征")
            elif ("输出" in flat_desc and not any(k in flat_desc for k in ("采样", "检测", "监控", "回读"))):
                finding.warn_notes.append(f"模板方向为 Input，但功能描述写为「{flat_desc}」，请确认信号流向")
        elif t_dir == "OUTPUT":
            if any(k in flat_desc for k in ("回读", "故障反馈", "输入")) and "使能" not in flat_desc and "控制" not in flat_desc and "复位" not in flat_desc:
                finding.warn_notes.append(f"模板方向为 Output，但功能描述写为「{flat_desc}」，请确认信号流向")

        # 3. 同一单元格换行并列两个不同外设信号（如 GPIO 与 QSPI5 复用未定）
        if "\n" in name:
            lines = [ln.strip() for ln in name.splitlines() if ln.strip()]
            if len(lines) >= 2 and not any(ln.startswith(("(", "（")) for ln in lines[1:]):
                finding.warn_notes.append("模板端口名并列多个信号（" + " / ".join(lines) + "），请确认当份方案选用哪一项")

        # 4. 故障信号极性异常（同类 FLTA/DESAT 均为 falling，唯独填了 High）
        if re.search(r"^FLT[AB]_M_|^DESAT_M_", flat_name.upper()) and high.upper() == "HIGH" and not low:
            finding.warn_notes.append(f"故障反馈信号 {flat_name} 在高电平列填为 High（同类故障反馈多为低电平/下降沿有效），请核对极性")

    # 5. 跨子表核对（3_ADC Table / 3-SPI总线）
    main_ball = (template_ball or pin.ball or "").strip()
    for sub in sub_entries:
        if "ADC Table" in sub.sheet:
            if sub.ball and main_ball and sub.ball.upper() != main_ball.upper():
                finding.warn_notes.append(f"子表《{sub.sheet}》中 {pin.symbol} 球号写为 {sub.ball}（模板主表为 {main_ball}）")
            if sub.signal and name and name.upper() not in _NC_SET and sub.signal != name:
                finding.warn_notes.append(f"子表《{sub.sheet}》信号名为 {sub.signal}（主表端口名为 {name}）")
        elif sub.sheet.endswith("SPI总线"):
            if sub.signal:
                finding.sub_hints.append(f"子表《{sub.sheet}》定义为 {sub.signal}" + (f"（{sub.description}）" if sub.description else ""))
            if sub.direction and template_direction and sub.direction.lower() != template_direction.lower():
                finding.conflict_notes.append(
                    f"子表《{sub.sheet}》方向为 {sub.direction}，与主表模板方向 {template_direction} 不一致"
                )

    return finding


_ABSENT_SIGNAL = re.compile(
    r"(?:无|没有|不具备|不支持)\s*([A-Z][A-Z0-9]*[_\d][A-Z0-9_]*)"
)
_CITED_SIGNAL = re.compile(r"仅支持\s*([A-Z][A-Z0-9]*[_\d][A-Z0-9_]*)")
_SPI_MASTER_CLAIM = re.compile(r"无SPI主发|无主发能力|无主发输出|没有主发")
_OUTPUT_CLAIM = re.compile(r"无输出能力|没有输出能力|不具备输出")
_SPI_MASTER_EVIDENCE = re.compile(
    r"QSPI\d+_SLSO\d*|QSPI\d+_MTSR(?!C)|MASTER\s+SLAVE\s+SELECT\s+OUTPUT|MASTER\s+SPI\s+DATA\s+OUTPUT"
)
_OUTPUT_EVIDENCE = re.compile(
    r"\bOUTPUT\b|TOUT\d*|QSPI\d+_SLSO\d*|MASTER\s+SLAVE\s+SELECT\s+OUTPUT"
)


def _manual_blob(pin: ChipPin) -> str:
    return f"{pin.function}\n{pin.mux}\n{pin.excerpt}".upper()


def _token_in_blob(token: str, blob: str) -> bool:
    return re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", blob) is not None


def llm_reason_contradicts_manual(pin: ChipPin, reason: str) -> bool:
    """模型说手册没有某项能力，但当份复用里已经写了这项时，这条结论不能采用。"""
    blob = _manual_blob(pin)
    upper = (reason or "").upper()
    absent = [item.upper() for item in _ABSENT_SIGNAL.findall(upper)]
    cited = {item.upper() for item in _CITED_SIGNAL.findall(upper)}
    for token in absent:
        if token in cited or _token_in_blob(token, blob):
            return True
    if _SPI_MASTER_CLAIM.search(upper) and _SPI_MASTER_EVIDENCE.search(blob):
        return True
    if _OUTPUT_CLAIM.search(upper) and _OUTPUT_EVIDENCE.search(blob):
        return True
    if re.search(r"无\s*CAN\s*复用|没有\s*CAN|无CAN功能|不具备\s*CAN", upper) and re.search(
        r"CAN\d|CANXL|CAN_", blob
    ):
        return True
    return False


def mux_for_review(mux: str, limit: int = 1600) -> str:
    """送给模型的复用去掉 Reserved，并保留后面的主发、输出项，避免只看到前几百字输入。"""
    items = [
        part.strip()
        for part in re.split(r"[；;\n]", mux or "")
        if part.strip() and not is_reserved_mux_item(part)
    ]
    if not items:
        return ""
    important = [
        item
        for item in items
        if re.search(r"output|SLSO|TOUT|RXD|TXD|Master", item, re.IGNORECASE)
    ]
    chosen: list[str] = []
    size = 0
    for item in important + [item for item in items if item not in important]:
        extra = len(item) + 1
        if item not in important and chosen and size + extra > limit:
            continue
        if item in important and size > limit * 2:
            continue
        chosen.append(item)
        size += extra
    order = {item: index for index, item in enumerate(items)}
    chosen.sort(key=lambda item: order.get(item, 0))
    return "；".join(chosen)


def _parse_json_array(raw: str) -> list[dict[str, object]]:
    text = (raw or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("LLM 未返回 JSON 数组")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("LLM 返回结果不是数组")
    return [item for item in data if isinstance(item, dict)]


def _is_llm_candidate(
    pin: ChipPin,
    template_direction: str,
    template_function: str,
    project: tuple[object, ...],
    finding: PinQaFinding,
) -> bool:
    """筛选需要送交 LLM 深度语义复核的候选行，避免对常规无异议行做无意义的批量请求。"""
    if finding.conflict_notes or finding.warn_notes or finding.sub_hints:
        return True
    name = str(project[0] if len(project) > 0 and project[0] is not None else "").strip()
    desc = str(project[1] if len(project) > 1 and project[1] is not None else "").strip()
    high = str(project[6] if len(project) > 6 and project[6] is not None else "").strip()
    low = str(project[7] if len(project) > 7 and project[7] is not None else "").strip()
    if not name or name.upper() in _NC_SET:
        return False
    if "(" in name or "（" in name or "\n" in name:
        return True
    if ("输入" in desc and template_direction.upper() == "OUTPUT") or ("输出" in desc and template_direction.upper() == "INPUT"):
        return True
    if template_function.upper() in {"PWM", "CAN", "SPI", "SENT"} and template_direction.upper() == "INPUT":
        if any(k in name.upper() for k in ("AOUT", "OUT", "TXD", "MOSI", "CLK", "SEL", "CS", "CTRL", "DRV", "EN")):
            return True
    if high and low and not high.lower().startswith("refer to"):
        return True
    return False


_PWM_DRIVE = re.compile(r"PWM_(?:M_)?([ABC])([HL])_(P\d+|GM|TM)\b", re.I)
_PHASE_CURRENT = re.compile(r"\bI([ABC])_S/M_(P\d+|GM|TM)\b", re.I)
_ATOM_CH = re.compile(r"ATOM(\d+)_CH(\d+)", re.I)
_ATOM_TOUT = re.compile(r"ATOM(\d+)_(\d+)(?=_TOUT|\b)", re.I)
_DTM = re.compile(r"DTM(\d+)_(\d+)(N)?", re.I)
_ADC_CH = re.compile(r"CH\s*(\d+)", re.I)
_ADC_GR = re.compile(r"GR\s*(\d+)", re.I)


def _atom_channel(text: str) -> tuple[str, str] | None:
    blob = re.sub(r"\s+", "", text or "").upper()
    matched = _ATOM_CH.search(blob)
    if matched:
        return matched.group(1), matched.group(2)
    matched = _ATOM_TOUT.search(blob)
    if matched:
        return matched.group(1), matched.group(2)
    return None


def _dtm_token(text: str) -> str:
    blob = re.sub(r"\s+", "", text or "").upper()
    matched = _DTM.search(blob)
    if not matched:
        return ""
    return f"{matched.group(1)}_{matched.group(2)}{matched.group(3) or ''}"


def _remember_note(found: dict[str, list[str]], symbols: list[str], text: str) -> None:
    for symbol in symbols:
        for part in split_symbol_parts(symbol) or [symbol]:
            bucket = found.setdefault(part, [])
            if text not in bucket:
                bucket.append(text)


def _pwm_allocation(workbook: Workbook, pins: tuple[ChipPin, ...], found: dict[str, list[str]]) -> None:
    """P1、GM、TM 的 PWM 应在同一个 ATOM；同一相上桥、下桥共用通道，下桥为上桥的互补 N 输出。"""
    sheet_name = _sheet_named(workbook, "2_Port Assignment")
    if not sheet_name:
        return
    by_symbol: dict[str, ChipPin] = {}
    for pin in pins:
        for key in split_symbol_parts(pin.symbol):
            by_symbol.setdefault(key, pin)
    sheet = workbook[sheet_name]
    data_start, name_col = _port_name_column(sheet)
    grouped: dict[str, dict[tuple[str, str], tuple[str, str, str, str]]] = {}
    for row in range(data_start, (sheet.max_row or data_start) + 1):
        symbol = str(sheet.cell(row, 2).value or "").strip()
        name = str(sheet.cell(row, name_col).value or "").replace("\n", " ")
        matched = _PWM_DRIVE.search(name)
        if not symbol or not matched or matched.group(3).upper() not in {"P1", "GM", "TM"}:
            continue
        motor = matched.group(3).upper()
        phase, side = matched.group(1).upper(), matched.group(2).upper()
        blobs = []
        for key in split_symbol_parts(symbol):
            pin = by_symbol.get(key)
            if pin is not None:
                blobs.append(f"{pin.function}\n{pin.mux}\n{pin.excerpt}")
        blob = "\n".join(blobs)
        atom = _atom_channel(blob)
        atom_text = "" if atom is None else f"ATOM{atom[0]} CH{atom[1]}"
        grouped.setdefault(motor, {})[(phase, side)] = (
            symbol,
            matched.group(0).upper(),
            atom_text,
            _dtm_token(blob),
        )
    for motor, phases in grouped.items():
        if len(phases) < 2:
            continue
        atoms = {item[2].split()[0] for item in phases.values() if item[2]}
        if len(atoms) > 1:
            shown = "，".join(
                f"{label} 为 {atom.split()[0]}"
                for (_phase, _side), (_symbol, label, atom, _dtm) in sorted(phases.items())
                if atom
            )
            text = f"{motor} 的 PWM 应配置在同一个 ATOM。" + shown
            _remember_note(found, [item[0] for item in phases.values()], text)
        for phase in ("A", "B", "C"):
            high = phases.get((phase, "H"))
            low = phases.get((phase, "L"))
            if high is None or low is None:
                continue
            high_sym, high_name, high_atom, high_dtm = high
            low_sym, low_name, low_atom, low_dtm = low
            if high_atom and low_atom and high_atom != low_atom:
                text = (
                    f"同一相上下桥应使用同一 ATOM 通道。{phase} 相上桥 {high_name} 为 {high_atom}，"
                    f"下桥 {low_name} 为 {low_atom}"
                )
                _remember_note(found, [high_sym, low_sym], text)
            if high_dtm and low_dtm and (high_dtm.endswith("N") or low_dtm != f"{high_dtm}N"):
                text = (
                    f"同一相上下桥应按互补输出配置。{phase} 相上桥为 DTM{high_dtm}，"
                    f"下桥应为 DTM{high_dtm.removesuffix('N')}N，手册为 DTM{low_dtm}"
                )
                _remember_note(found, [high_sym, low_sym], text)


def _adc_allocation(workbook: Workbook, found: dict[str, list[str]]) -> None:
    """三相电流（不含备份）应落在不同 ADC group 的同一个 channel。"""
    sheet_name = _sheet_named(workbook, "3_ADC Table")
    if not sheet_name:
        return
    sheet = workbook[sheet_name]
    start, group_col, channel_col, symbol_col, _ball_col, signal_col, desc_col = _adc_columns(sheet)
    group = ""
    motors: dict[str, dict[str, tuple[str, str, str, str]]] = {}
    for row in range(start, (sheet.max_row or start) + 1):
        raw_group = str(sheet.cell(row, group_col).value or "").strip()
        if raw_group:
            group = raw_group
        channel = str(sheet.cell(row, channel_col).value or "").strip()
        symbol = str(sheet.cell(row, symbol_col).value or "").strip()
        signal = str(sheet.cell(row, signal_col).value or "").strip()
        desc = str(sheet.cell(row, desc_col).value or "").strip()
        matched = _PHASE_CURRENT.search(signal.replace(" ", ""))
        if not matched or not symbol:
            continue
        if "BU" in signal.upper() or "备份" in desc:
            continue
        phase, motor = matched.group(1).upper(), matched.group(2).upper()
        ch = _ADC_CH.search(channel.upper())
        gr = _ADC_GR.search(group.upper())
        motors.setdefault(motor, {})[phase] = (
            symbol,
            gr.group(1) if gr else "",
            ch.group(1) if ch else "",
            signal,
        )
    for motor, phases in motors.items():
        if set(phases) != {"A", "B", "C"}:
            continue
        symbols = [phases[key][0] for key in ("A", "B", "C")]
        channels = [phases[key][2] for key in ("A", "B", "C")]
        groups = [phases[key][1] for key in ("A", "B", "C")]
        detail = "，".join(
            f"I{key} 为 Gr{phases[key][1] or '?'} Ch{phases[key][2] or '?'}"
            for key in ("A", "B", "C")
        )
        if all(channels) and len(set(channels)) > 1:
            text = f"三相电流应配置在不同 group 的同一 channel。{motor}：{detail}"
            _remember_note(found, symbols, text)
        if all(groups) and len(set(groups)) < 3:
            text = f"三相电流应配置在不同 group 的同一 channel。{motor}：{detail}"
            _remember_note(found, symbols, text)


def allocation_notes(workbook: Workbook, pins: tuple[ChipPin, ...]) -> dict[str, list[str]]:
    """按 IO 分配规则核对。手册复用里没有 ATOM 或 DTM 时，不把没写出来的通道当成冲突。"""
    found: dict[str, list[str]] = {}
    _pwm_allocation(workbook, pins, found)
    _adc_allocation(workbook, found)
    return found


def run_llm_pin_qa(
    candidates: list[tuple[ChipPin, str, str, tuple[object, ...], list[SubSheetEntry]]],
    ask: Ask | None,
    on_progress=None,
) -> tuple[dict[str, list[tuple[str, str]]], bool]:
    """将可疑候选行分批送给 LLM 做工程语义质检。返回 (symbol -> [(level, reason)], model_used)。

    on_progress(done, total) 按已核对的引脚数回报。某一批失败也照样前进，避免进度停在这一批。
    """
    if ask is None or not candidates:
        return {}, False
    results: dict[str, list[tuple[str, str]]] = {}
    pins_by_symbol = {pin.symbol: pin for pin, _, _, _, _ in candidates}
    model_used = False
    total = len(candidates)
    if on_progress is not None:
        on_progress(0, total)

    for start in range(0, total, _LLM_BATCH):
        batch = candidates[start : start + _LLM_BATCH]
        payload = []
        for pin, t_dir, t_func, proj, subs in batch:
            name = str(proj[0] if len(proj) > 0 and proj[0] is not None else "").strip()
            desc = str(proj[1] if len(proj) > 1 and proj[1] is not None else "").strip()
            pull = str(proj[5] if len(proj) > 5 and proj[5] is not None else "").strip()
            high = str(proj[6] if len(proj) > 6 and proj[6] is not None else "").strip()
            low = str(proj[7] if len(proj) > 7 and proj[7] is not None else "").strip()
            init = str(proj[8] if len(proj) > 8 and proj[8] is not None else "").strip()
            payload.append(
                {
                    "symbol": pin.symbol,
                    "manual_ball": pin.ball,
                    "manual_direction": pin.direction,
                    "manual_function": pin.function,
                    "manual_mux": mux_for_review(pin.mux),
                    "template_direction": t_dir,
                    "template_function": t_func,
                    "port_name": name,
                    "description": desc,
                    "reset_pull": pull,
                    "high": high,
                    "low": low,
                    "init": init,
                    "sub_sheets": [
                        f"{s.sheet}:{s.signal or ''}(ball={s.ball or '-'},dir={s.direction or '-'})"
                        for s in subs
                    ],
                }
            )
        messages = [
            {"role": "system", "content": _LLM_QA_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        try:
            items = _parse_json_array(ask(messages))
            model_used = True
        except Exception:  # noqa: BLE001
            items = []
        for item in items:
            sym = str(item.get("symbol") or "").strip()
            level = str(item.get("level") or "warn").strip().lower()
            reason = re.sub(r"\s+", " ", str(item.get("reason") or "").strip())
            pin = pins_by_symbol.get(sym)
            if pin is None or not reason or llm_reason_contradicts_manual(pin, reason):
                continue
            norm_level = "conflict" if level == "conflict" else "warn"
            results.setdefault(sym, []).append((norm_level, reason))
        if on_progress is not None:
            on_progress(start + len(batch), total)

    return results, model_used
