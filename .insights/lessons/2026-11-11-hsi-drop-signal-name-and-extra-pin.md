# 2026-11-11 手册出表删掉信号名列，原理图不追加模板没有的脚

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_manual_hsi_hides_adc_signal_name`、`test_schematic_symbol_follows_body_when_header_is_swapped`）

## 代价

手册出表只把 ADC 的 Signal name 列清空并隐藏，F 列和 X 列仍在表里。原理图 PDF 里模板没有的符号会在端口表末尾追加一行。

## 反事实

只隐藏不删除，下一次手册出表打开列隐藏后仍能看到 `IA_S/M_TM`。继续追加 `P99.1` 这类模板没有的脚，归档表就不再是原模板只改对上的格子。把网络名写进 L 列，会盖掉时间常数的单位。

## 二级依据

- 会议：有原理图时沿用模板，只更新认得出的引脚配置。仅手册时 ADC 的 F 列直接删除，因为信号名要等原理图才有。
- DHTE400 `3_ADC Table`：F4、X4 表头是 `Signal name`，L4 是时间常数的 `「Unit]`，J4 是电流单位。删列后 `=L5` 要变成 `=K5`，单位 `A` 仍留在表上。
- 模板没有的符号不写「已追加」。L 列不是信号名，不把网络名填进去。

## 闸门

`test_manual_hsi_hides_adc_signal_name`：删掉 Signal name 列后表头不再有这个标题，单位 `A` 仍在，公式从 `=L5` 改为 `=K5`。
`test_schematic_symbol_follows_body_when_header_is_swapped`：对上的 `P02.1` 仍更新，`P99.1` 不新增行。
