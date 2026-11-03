# 2026-11-03 原理图出表不显示模板上的芯片和变更

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

按原理图生成的 HSI 仍显示模板封面修改人、变更记录，以及端口表上的 `TC499`、`MCU_TC499`、`BGA436`。功率板网表被看成上一份芯片文档。

## 反事实

封面继续留着 `殷桂来`，变更记录继续留着 `v1.3`，下一份原理图表仍像 DHTE400 已经改过的 TC499 文件。端口表头继续写 `MCU_TC499` 和 `BGA436` 时，接插件脚会显示在芯片封装下面。

## 二级依据

- 确认口径：原理图这份不显示模板上的芯片型号、封装、封面修改人和变更记录。列名保留。
- `HSI--20261103.xlsx` 封面 D 列是 `殷桂来`、`星驱`、`王宇`。变更记录为 `v1.0` 至 `v1.3`，编订人 `WY`。端口表 A1 为 `TC499 Port Assignment [Main Table]`，B2 为 `MCU_TC499`，B3 为 `BGA436\Ball`。ADC 表 B2 也是 `MCU_TC499`。
- 这些字来自模板 `DHTE400-HSI-V1.3-20261023.xlsx`，不是 `DHT160OF_PU_B3V2.EDF`。手册出表仍保留封面和变更记录。

## 闸门

`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：修改人表头还在，`殷桂来` 被清空；「需要修改内容」整列清空，目录里的表名还在；变更记录表头「版本」还在，`v1.3` 和说明被清空；端口标题去掉 `TC499`，`MCU_TC499` 为空，球号列表头为 `Ball`，「星驱原理图网络」仍在；ADC 的 `MCU_TC499` 为空。
