# 2026-11-12 盖住格子的图挪到文字右侧

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_empty_spi_and_can_sheets_gain_schematic_pins`）

## 代价

CAN 页的收发器框图按原来的单元格跨度铺在 PIN Function 上，引脚名被挡住。上一版把这张图直接删掉，`6_CAN` 不再显示框图。

## 反事实

图再被删掉，下一份原理图归档的 CAN 页仍只有引脚行，没有收发器框图。图若留在原位，PIN Function 继续被挡住。

## 二级依据

- 确认口径：图留着。它的单元格范围盖住已有文字时，按原来的列跨度挪到这段文字的右侧，不按位图重新放大。
- 本次 `6_CAN`：框图从第 3 行 C 列跨到第 29 行 D 列，盖住 `P00.0` 的功能列。Net Name 在 E 列，能看见 `CAN10_TXD`。

## 闸门

`test_empty_spi_and_can_sheets_gain_schematic_pins`：SPI 页的图还在，锚到 F 列。CAN 页的图还在，起始列不早于 Net Name 右侧。引脚格里的字还在。
