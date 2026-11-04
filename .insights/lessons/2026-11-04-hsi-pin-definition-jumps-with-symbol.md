# 2026-11-04 端口名跟符号跳到同一处

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_pin_definition_follows_symbol_when_name_has_no_row`、`test_port_names_link_to_adc_and_spi`）

## 代价

Pin Definition 已经写入模板端口名，但蓝字只挂在引脚符号上。点 `FLTB_M_H_GM` 不会打开 SPI 或 ADC 那一行。

## 反事实

端口名仍不加链接时，下一次 `FLTB_M_H_GM` 只在 L 列，点不开 `4-SPI总线` 第 4 行。`DO_ASC_PRI_H_P1` 同时在 ADC 和 SPI 时，L 列也不会进跳转索引。若把落点写成「3_ADC Table 第5行」摊到 M 列，端口中文说明就没了。

## 二级依据

- 确认口径：L 列端口名也要能一对一、一对多跳转。字留在格子里，不对的由人改。
- 端口名在后面各表对得上时，仍按名称自己的落点跳。对不上时，跟这一行符号去同一处：一处直达整行，多处进同一条跳转索引。
- 中文说明列和观测变量不挂跳转。不另起索引分组。

## 闸门

`test_pin_definition_follows_symbol_when_name_has_no_row`：`FLTB_M_H_GM` 与 `P00.8` 都到 `HSI_SPI_4`；`DO_ASC_PRI_H_P1` 与 `P02.1` 进同一条跳转索引。两行的中文说明都没有链接。
`test_port_names_link_to_adc_and_spi`：`QSPI3` 跟 `P00.8` 到 SPI 第 4 行。名称自己对得上 ADC 时，仍进 ADC，不改成符号的落点。
