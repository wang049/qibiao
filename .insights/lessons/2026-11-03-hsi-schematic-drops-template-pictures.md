# 2026-11-03 原理图出表不留模板图片和空表底色

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

按原理图生成的 HSI 清掉了后面各页的文字，模板嵌进去的原理图图片还在，空行的绿底、蓝底和边框也还在。看起来像这次读出了油温电路和一张空表。

## 反事实

只清格子里的字，下一次 `17_变速器油温` 仍显示模板图片「图片 2」，`18_热泵温度传感器` 仍有 5 张图。绿底 `FF92D050` 和蓝底 `FFDEEBF7` 还铺在空行上。死区页仍按模板里的 `1.6` 画出时序图。

## 二级依据

- 确认口径：这些图和空行底色不是这份 EDF 的结果，不显示。表头文字保留。
- `HSI--20261103.xlsx`：`17_变速器油温` 有 1 张图，锚在第 6 行到第 18 行，名称是「图片 2」。`18_热泵温度传感器` 有 5 张图。第 34 行是绿底空单元格，E 列向下是蓝底空单元格，并且带边框。`22_3041寄存器配置表` 有 30 条条件格式。
- 图片来自模板 `DHTE400-HSI-V1.3-20261023.xlsx`。EDF 和芯片手册里都没有这些原理图截图。按 MCU 型号新建同样去掉，见 `2026-11-03-hsi-manual-drops-template-pictures.md`。

## 闸门

`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：ADC 表头底色还在，第 5 行绿底和边框被去掉，条件格式清空，嵌图被去掉。死区页不生成 `drawing_dead_time.xml`。
