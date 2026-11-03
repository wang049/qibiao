# 2026-11-03 剩下的三句模板说明和 ADC 空框

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_drops_short_template_notes_and_empty_adc_banner`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

前 8 行里较短的模板说明还在：高压采样点、`600uA`、`待更新NTC阻值`。ADC 的 `MCU_TC499` 清掉以后，`B2:G3` 空合并框还在。

## 反事实

只按句号和 40 字来认示例，下一次高压页仍写着 U1、U2，SiC 页仍写着 `600uA`，单片机温度页仍写着待更新 NTC。先清空框、后去掉 `MCU_TC499`，ADC 的空合并框还会留下。

## 二级依据

- 确认口径：这三句清掉。列名、表名和 `MCU_OilTemp` 这类表编号留下。没有字的合并框清掉。
- `HSI--20261103.xlsx`（20:36）：`13_HVDC Overvoltage & Diag` 的 A4，`15_SiC Temp` 的 B4，`19_单片机温度` 的 B4，ADC 空合并 `B2:G3`。
- 这些字在模板 `DHTE400-HSI-V1.3-20261023.xlsx` 里，不是 `DHT160OF_PU_B3V2.EDF`。

## 闸门

`test_schematic_drops_short_template_notes_and_empty_adc_banner`：三句说明为空；高压页标题、IGBT 标题、`MCU_OilTemp`、`Signal name` 还在；`B2:G3` 不再合并。
`test_dhte400_keeps_atom_port_name_cover_and_history`：按 MCU 型号新建时这三句也为空。
