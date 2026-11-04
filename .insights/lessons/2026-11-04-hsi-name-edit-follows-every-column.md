# 2026-11-04 总表改名要带动后面每一列

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_renaming_port_updates_every_linked_name_and_symbol`）

## 代价

总表改了端口名或引脚符号，ADC 右侧另一列信号名、SPI 的说明仍是旧字。一对多的符号改了，关联页也不变。

## 反事实

名称公式只写到第 16 列里的第一列，下一次 `3_ADC Table` 第 24 列的 Signal name 仍是 `IA_S/M_TM`。一对多的符号如果引用隐藏列，总表 B 列改成别的脚，ADC 和 SPI 的 PIN 仍是原来的 `P00.8`。

## 二级依据

- 总表第 12 列是 Pin Definition。ADC 第 6 列和第 24 列都叫 Signal name。SPI 第 6 列是 Fuction Des。
- 这些列在生成时写成引用总表名称的公式。引脚符号引用总表 B 列。总表还空着时，关联页也显示空白。

## 闸门

`test_renaming_port_updates_every_linked_name_and_symbol`：ADC 两列信号名和 SPI 说明都含 `L4`；两处 PIN 都含 `B4`，不含隐藏列 `80`。
