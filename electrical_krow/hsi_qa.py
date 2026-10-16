"""HSI 端口规划规则与 LLM 语义质检。

硬件事实（球号、方向、缓冲、功能、复用、页码、原文摘录）一律来自当份芯片手册。
本模块在不触碰底表硬件事实抄录的前提下，负责：
1. 组合/别名引脚符号归一化对齐（如模板 `AN17/P40_10` 与手册 `AN17` / 复用 `P40.10`）；
2. 当份手册硬件外设复用能力（Mux）与模板 Function/端口定义冲突核查；
3. 模板主表（`2_Port Assignment`）与子表（`3_ADC Table`、`3-SPI总线` 等）跨表一致性核查；
4. 可疑行的规则检出与可选 LLM 工程语义审查（通过 `ask` 回调）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from openpyxl.workbook.workbook import Workbook

from electrical_krow.mcu_pins import ChipPin

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


def extract_subsheet_entries(workbook: Workbook) -> dict[str, list[SubSheetEntry]]:
    """提取模板子表（`3_ADC Table`、`3-SPI总线`）中的引脚映射，用于与主表及手册交叉核对。"""
    by_sym: dict[str, list[SubSheetEntry]] = {}

    if "3_ADC Table" in workbook.sheetnames:
        ws = workbook["3_ADC Table"]
        for row in range(5, ws.max_row + 1):
            raw_sym = str(ws.cell(row, 5).value or "").strip()
            if not raw_sym or raw_sym in _NC_SET:
                continue
            ball = str(ws.cell(row, 6).value or "").strip()
            sig = str(ws.cell(row, 7).value or "").strip()
            desc = str(ws.cell(row, 8).value or "").strip()
            for sym in split_symbol_parts(raw_sym):
                by_sym.setdefault(sym, []).append(
                    SubSheetEntry(
                        sheet="3_ADC Table",
                        symbol=sym,
                        ball="" if ball in _NC_SET else ball,
                        signal="" if sig in _NC_SET else sig,
                        description="" if desc in _NC_SET else desc,
                    )
                )

    if "3-SPI总线" in workbook.sheetnames:
        ws = workbook["3-SPI总线"]
        for row in range(1, ws.max_row + 1):
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
                        sheet="3-SPI总线",
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
        if sub.sheet == "3_ADC Table":
            if sub.ball and main_ball and sub.ball.upper() != main_ball.upper():
                finding.warn_notes.append(f"子表《{sub.sheet}》中 {pin.symbol} 球号写为 {sub.ball}（模板主表为 {main_ball}）")
            if sub.signal and name and name.upper() not in _NC_SET and sub.signal != name:
                finding.warn_notes.append(f"子表《{sub.sheet}》信号名为 {sub.signal}（主表端口名为 {name}）")
        elif sub.sheet == "3-SPI总线":
            if sub.signal:
                finding.sub_hints.append(f"子表《{sub.sheet}》定义为 {sub.signal}" + (f"（{sub.description}）" if sub.description else ""))
            if sub.direction and template_direction and sub.direction.lower() != template_direction.lower():
                finding.conflict_notes.append(
                    f"子表《{sub.sheet}》方向为 {sub.direction}，与主表模板方向 {template_direction} 不一致"
                )

    return finding


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


def run_llm_pin_qa(
    candidates: list[tuple[ChipPin, str, str, tuple[object, ...], list[SubSheetEntry]]],
    ask: Ask | None,
) -> tuple[dict[str, list[tuple[str, str]]], bool]:
    """将可疑候选行分批送给 LLM 做工程语义质检。返回 (symbol -> [(level, reason)], model_used)。"""
    if ask is None or not candidates:
        return {}, False
    results: dict[str, list[tuple[str, str]]] = {}
    valid_symbols = {pin.symbol for pin, _, _, _, _ in candidates}
    model_used = False

    for start in range(0, len(candidates), _LLM_BATCH):
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
                    "manual_mux": (pin.mux or "")[:300],
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
            continue
        for item in items:
            sym = str(item.get("symbol") or "").strip()
            level = str(item.get("level") or "warn").strip().lower()
            reason = re.sub(r"\s+", " ", str(item.get("reason") or "").strip())
            if sym not in valid_symbols or not reason:
                continue
            norm_level = "conflict" if level == "conflict" else "warn"
            results.setdefault(sym, []).append((norm_level, reason))

    return results, model_used
