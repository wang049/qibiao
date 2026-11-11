# 2026-11-11 ADC 信号名只改原理图对上的网络名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_adc_signal_name_uses_schematic_wire_not_template_column`、`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

ADC 的 Signal name 若整列抄端口表 K 列，`AN0` 会写成 `AI_IU_CH1_M2`，和原理图黄框里的 `IA_S/M_TM` 不是同一个字。若把没对上的信号名清空，模板里原来的字也被抹掉，工程师不能直接用这份归档。

## 反事实

继续抄 K 列，下一份 `W13` 仍是 `AI_IU_CH1_M2`。对不上的 `AN1` 若被清成空，`HW_Version_1` 不再留在表上。没有脚号的示例格若被清掉，转换公式旁边的 `IA_S/M_TM` 会消失。

## 二级依据

- 归档要求与现有模板一致。无需修改的内容直接复制，只更新原理图对上、并且脚号或球号交叉得上的格子。
- 原理图黄框里连在脚上的字才用来替换信号名。`AN0`/`W13` 对上 `IA_S/M_TM` 才改，并标绿。
- 没读到网络名的脚保持模板原文，不上绿色。K 列 `AI_IU_CH1_M2` 不整列搬进 ADC。

## 闸门

`test_adc_signal_name_uses_schematic_wire_not_template_column`：`AN0` 写成 `IA_S/M_TM` 并标绿。`AN1` 仍是 `HW_Version_1`，不上绿。端口表 K 列仍是 `AI_IU_CH1_M2`。
`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：没有脚号的示例格 `IA_S/M_TM` 和公式还在。
