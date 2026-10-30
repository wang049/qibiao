# 2026-10-26 端口名跳到 ADC、SPI，R1 和 R3 隐藏

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_port_names_link_to_adc_and_spi`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

复核时要从端口名自己翻到 ADC、SPI。ADC 表上 R1、R3 这两列电阻值还占着版面，这版不拿来对。

## 反事实

端口名不对 ADC 的 Signal name 加链接，下一次 `IA_S/M_TM` 仍要手工翻到 `3_ADC Table`。引脚符号和原理图网络不对 SPI 的 PIN、Net Name 加链接，`P00.8` 和 `CSN3_M/T_SPI3` 仍落不到 `4-SPI总线`。链接若写进 target 而不是 location，Excel 会弹出「无法打开指定的文件」。R1、R3 不按表头隐藏，生成稿里这两列仍展开；若把 C1 一并藏掉，滤波电容也会看不见。

## 二级依据

- 会议口径：信号网络名与 ADC Table、SPI 页之间要能跳转；当前项目不看的 R1、R3 列先隐藏。
- DHTE400 `3_ADC Table` 第 4 行：F 列 `Signal name`，Z 列 `R1 (kΩ)`，AA 列 `C1(nF)`，AD 列 `R3 (kΩ)`。AN0 的信号名是 `IA_S/M_TM`，R1 格已有 0.47，隐藏只收起列，不删数。
- `4-SPI总线` 第 3 行：B 列 `PIN`，E 列 `Net Name`。`P00.8` 对 `CSN3_M/T_SPI3`。
- 端口表 L 列端口名对 ADC 信号名，B 列符号对 SPI 的 PIN，K 列星驱原理图网络对 SPI 的 Net Name。对得上的两边互相跳。

## 闸门

`test_port_names_link_to_adc_and_spi`：`IA_S/M_TM` 跳到 ADC，`P00.8` 和网络名跳到 SPI，ADC 信号跳回端口表；R1、R3 隐藏，C1 不隐藏。
`test_dhte400_keeps_atom_port_name_cover_and_history`：按 DHTE400 写出后，AN0 的端口名跳到 `3_ADC Table`，Z 列和 AD 列隐藏，AA 列不隐藏。
