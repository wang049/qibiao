# 2026-11-03 引脚收齐后再隐藏电源地，一个名称跳到每一行

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_lqfp_numeric_pins_and_system_io_and_inline_alias`、`test_supply_pin_stays_on_the_sheet_and_is_hidden`、`test_one_port_name_links_every_matching_row`、`test_other_vendor_pin_table_keeps_power_and_signal`）

## 代价

手册里的电源脚被整行跳过，端口表上的数量对不上封装球数。同名信号只跳到 ADC 或 SPI 的第一行，总表改名后后面的表不会跟着变。

## 反事实

继续跳过 `VDD` 这类脚，下一次 BGA436 的清单里仍然没有电源和地，筛选也无行可藏。同名信号只保留第一次出现的行时，第二行和 PMIC 页仍然点不回去。名称格的链接若指向用 IF 算出来的定义名称，Excel 会报「引用无效」。

## 二级依据

- 手册把同一颗 `VSS`、`VDD` 写成多行球号。只按「一行一个球」抽，BGA436 只会得到 355 行，电源和地的球被整组丢掉。
- 端口表同一信号名可以在 `3_ADC Table` 出现多行，也可以出现在后续页的 Signal name 列。
- 关联格写成对总表单元格的引用。总表那一格改字，引用它的格子一起变。
- 电源、地用行隐藏收起来，格子还在。ADC 中文列不自动翻译。电压、电流余量系数尚未写成确认过的换算标准，最大最小值不按举例系数填。

## 闸门

`test_lqfp_numeric_pins_and_system_io_and_inline_alias`：`VDD` 单独成脚，不写进 `ESR0` 的复用。
`test_supply_pin_stays_on_the_sheet_and_is_hidden`：`VDD` 写在端口表里并且该行隐藏，`AN0` 不隐藏。
`test_one_port_name_links_every_matching_row`：同一名称对应多页时，点名称按所选标签打开对应行，不指向用 IF 算出来的定义名称。
`test_other_vendor_pin_table_keeps_power_and_signal`：非 TC 的球号表同时留下电源脚和 GPIO。
