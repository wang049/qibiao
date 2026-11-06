# 2026-11-05 原理图 ADC 组号按手册球号填写

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_adc_group_follows_the_manual_ball`、`test_schematic_adc_group_reads_the_tc499_manual`）

## 代价

原理图符号上的模拟脚只写着 `P40.6` 或单独的 `AN0`。ADC 表因此有引脚和球号，`Gr`、`channel` 是空的。手册出表会把该球号复用里的 `ADC_TMADCnCHx` 写入这两列。

## 反事实

只把符号上的 `P40.6` 写进复用，下一次 `3_ADC Table` 的 `Gr` 和 `channel` 仍空。球号对不上时若改按引脚符号去拿手册通道，会把另一只脚的组号写到这一行。`EDSADC`、`FC` 若也算成一组，组号就不再和手册出表一致。

## 二级依据

- 确认口径：原理图生成的 `Gr`、`channel` 与按芯片手册生成相同。组号只取该球号复用里唯一的 `EVADC_Gn` 或 `TMADCn`。`EDSADC`、`FC` 不另算一组。两路 `EVADC` 留空。对不上手册球号的行留空。
- `infineon-sak-tc499pp-20mf400ms-ab-datasheet-en.pdf` 的 BGA436：`W13` 是 `AN0`，复用含 `ADC_TMADC0CH0`；`T7` 是 `AN36`，复用含 `P40.6` 和 `ADC_TMADC3CH8`。

## 闸门

`test_schematic_adc_group_follows_the_manual_ball`：`AN36` 球号 `T7` 的组号是 `TMADC3`，通道含 `ADC_TMADC3CH8`，符号上的 `P40.6` 仍留在复用里。`AN0` 球号 `W13` 的组号是 `TMADC0`。`P00.1` 不进 ADC 表。
`test_schematic_adc_group_reads_the_tc499_manual`：本机有这本手册时，`W13` 的通道含 `ADC_TMADC0CH0`，`T7` 的组号是 `TMADC3`。
