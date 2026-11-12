# 2026-11-12 符号上的信号名写入 Pin Definition

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_symbol_signal_fills_empty_pin_definition`、`test_schematic_symbol_follows_body_when_header_is_swapped`）

## 代价

原理图符号写成 `P00_0/CAN10_TXD` 时，`CAN10_TXD` 进了复用列，Pin Definition 仍空。归档记录写了「按原理图归档更新」，信号名却不在引脚信号名列。

## 反事实

只把导线网络名写入 Pin Definition，符号上已有信号名、导线旁没有另写网络名时，下一份端口表的 Pin Definition 仍是空的。

## 二级依据

- 确认口径：Pin Definition 是这只脚在原理图上的信号名。已有端口名时，不用符号功能盖掉它；符号功能仍可写入复用。
- 本次归档 `HSI--20261112.xlsx`：`P00.0` 的复用是 `CAN10_TXD`，Pin Definition 为空。
- 已有端口名的例子：`P02.1` 的 Pin Definition 仍是 `PWM_M_AH_GM`，`ERAY0_RXDA2` 写在复用。

## 闸门

`test_symbol_signal_fills_empty_pin_definition`：Pin Definition 为空时，符号功能 `CAN10_TXD` 写入该列。
`test_schematic_symbol_follows_body_when_header_is_swapped`：已有 `PWM_M_AH_GM` 时不被 `ERAY0_RXDA2` 覆盖，复用列写入 `ERAY0_RXDA2`。
