# 2026-10-26 跳转要选中整行

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_port_names_link_to_adc_and_spi`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

从端口名跳到 ADC 或 SPI 之后，只落在一个格子上。表很宽，看不出刚落到第几行。

## 反事实

链接仍指向单个单元格，下一次点开 `IA_S/M_TM` 还是只亮一个信号名，左侧行号不会整行亮起。悬停不写「第几行」，点之前也不知道落点。

## 二级依据

- 复核口径：跳过去要能看出是哪一行。
- 落点用整行名称，例如 `HSI_ADC_5` 指向 `'3_ADC Table'!$5:$5`。悬停文字为 `第5行 IA_S/M_TM`。
- 返回端口表同样选中整行，例如 `HSI_PORT_4` 指向 `'2_Port Assignment '!$4:$4`。

## 闸门

`test_port_names_link_to_adc_and_spi`：ADC 链接位置是 `HSI_ADC_5`，名称覆盖第 5 行整行，悬停含行号和信号名；SPI、返回端口表同样选中整行。
`test_dhte400_keeps_atom_port_name_cover_and_history`：AN0 的端口名链接指向 ADC 整行名称，悬停含 `IA_S/M_TM` 和行号。
