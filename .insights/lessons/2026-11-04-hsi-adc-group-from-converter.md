# 2026-11-04 ADC 组号只取手册里唯一的转换器

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_adc_drops_template_group_allocation`、`test_adc_group_stays_empty_when_converters_differ`）

## 代价

模板 `Gr` 列里的 1、2、3 是上一份项目的组号。手册功能名已经写着 `EVADC_G10CH0`，旁边的 `EDSADC` 或 `FC` 把这一行挡在组外，同一组就散在表里，也没有底色。

## 反事实

继续把组号留空，或让 `EDSADC` 挡住 `EVADC_G10`，下一次 `G10` 的脚仍不排在一起。若把模板 `Gr0` 或信号名 `IA_S/M_TM` 留在表里，会把上一份项目的分配写成这次的结果。一只脚同时有 `EVADC_G10` 和 `EVADC_G0` 时若写成其中一组，会把没选定的转换器当成已经分组。

## 二级依据

- 确认口径：组号来自当份手册复用里唯一的 `EVADC_Gn` 或 `TMADCn`。`EDSADC`、`FC` 不另算一组。同一组按通道号排在一起，`Gr` 列合并成一块，组名居中，只这一列用模板的浅蓝 `BDD7EE`。每组外框是细线，相邻组之间有横线。两路 `EVADC` 组号留空、不上色。信号名仍留空。
- TC499 Pin Mapper `Pinout_Main`：`P00_1` 球号 `K5`，`Analog_1` 为 `ADC_TMADC2CH11`，`Analog_2` 为 `ADC_DSADC5NA`。两列并存，组号不能只取第一列。
- `A2G_silicon_TC39xED.xls` 的 `pinout`：`P00_1` 在 LFBGA516 上是 `M7`，`Analog_1` 为 `EVADC_G9CH11`。模板截图的 `Gr` 1 不是这个组号。

## 闸门

`test_adc_drops_template_group_allocation`：模板 `Gr0` 和 `IA_S/M_TM` 被清掉，只有 `ADC_TMADC2CH0` 的脚组号是 `TMADC2`。
`test_adc_group_stays_empty_when_converters_differ`：`EVADC_G9` 排在 `G10` 前。同一组的 `Gr` 合并，组名只在块首，底色是 `BDD7EE`，通道列不上色。`EDSADC` 不挡住 `TMADC2`。同时有 `EVADC_G10` 和 `EVADC_G0` 的脚组号为空、不上色，并排在有组的脚后面。
