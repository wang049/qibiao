# 2026-11-03 ADC 表对应端口表里的 ADC 脚

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

端口表有手册上的 ADC 脚，ADC 表仍是空表头。球号和引脚符号对不上，端口符号也不能跳到 ADC 表。

## 反事实

ADC 表继续只留表头，下一次 `AN0` 的球号 `W13` 只出现在端口表。把模板信号名 `IA_S/M_TM` 或转换公式写进 ADC 表，会把上一份项目的采样定义当成这次手册的结果。

## 二级依据

- 确认口径：ADC 表只列手册标明有 ADC 的脚。球号、引脚符号与端口表相同，并能跳转。信号名、中文说明、转换公式和诊断上下限留空。
- 模板 `3_ADC Table` 第 5 行原是 `AN0`、`W13`、`IA_S/M_TM` 和公式 `IT=(UT-2.5)/0.001511`。引脚符号在 Ball 左边一列，表头原来是空的。
- `pin_class` 把符号 `ANx` 或复用里带 ADC 的脚归为 ADC。`P02.1` 的复用是 ATOM，不进这张表。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：ADC 第 5 行是 `AN0` 和 `W13`，信号名为空，没有 `P02.1`。端口表 `AN0` 的符号格链接到 ADC。
