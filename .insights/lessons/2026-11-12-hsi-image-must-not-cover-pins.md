# 2026-11-12 原理图归档的图不能压住已写的格子

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_empty_spi_and_can_sheets_gain_schematic_pins`）

## 代价

`6_CAN` 写入 CAN10_TXD 等引脚后，模板里的框图仍锚在第 3 行到第 29 行、C 列到 D 列，PIN Fuction 被挡住。

## 反事实

这张图若留在原锚点，下一份归档的 CAN 功能名仍被框图盖住。右侧没有字的图若被一起删掉，热泵页上的电路图也会消失。

## 二级依据

- 确认口径：图跨过已经写了字的格子就去掉。锚在空白列的图留下。页本身不删。
- 本次 `output/HSI--20261112.xlsx`：`6_CAN` 有 1 张图，锚点 r3c3 → r29c4，下面是 CAN10_TXD、CAN10_RXDA。

## 闸门

`test_empty_spi_and_can_sheets_gain_schematic_pins`：压住 C3 的图被去掉，K 列空白处的图还在，CAN10_TXD 仍写在第 3 行。
