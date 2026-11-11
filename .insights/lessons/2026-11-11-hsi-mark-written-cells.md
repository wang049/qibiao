# 2026-11-11 去掉模板黄紫底，本次写入标绿

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_template_highlight_clears_and_written_cell_is_green`、`test_adc_group_stays_empty_when_converters_differ`、`test_manual_ports_drop_template_yellow_and_purple_rows`）

## 代价

端口表整行是黄底或紫底。这次改过的球号、网络名落在同一层颜色上，打开后分不出哪些格子是这次写入的。

## 反事实

留下模板黄、紫行底，下一份原理图归档里 `P02.1` 的球号即使改成 `E19`，整行仍是黄的。手册写出的 ADC 通道若不上绿色，`EVADC_G9CH11` 和没写过的空格一样没有标记。组号列若被绿色盖住，同一组的浅蓝 `BDD7EE` 会消失。

## 二级依据

- 模板端口表行底是黄 `FFFFFF00`、紫 `FFFF66FF`。单元格 theme 0 在 WPS 里也是黄底。这些不是这次读出来的内容。
- 这次写入的格子用绿色 `C6EFCE`。没改的格子去掉黄、紫，不上绿。改过的那一行，引脚符号和球号也标绿，避免只标在最右边的复用列。
- 按原理图归档时，整本里的黄、紫和会画成黄底的主题色都去掉。电路图自己的绿色、蓝色留下。
- ADC 组号仍用浅蓝 `BDD7EE`。两路转换器的组号留空，不上色。

## 闸门

`test_template_highlight_clears_and_written_cell_is_green`：黄行底去掉。球号和网络名是绿色。端口名 `PWM_M_AH_GM` 还在，不是绿色，也不是黄色。
`test_adc_group_stays_empty_when_converters_differ`：通道格是绿色，组号格仍是 `BDD7EE`，空组号不上色。
`test_manual_ports_drop_template_yellow_and_purple_rows`：手册出表后行底不再是整行黄、紫。
