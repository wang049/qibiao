# 2026-11-03 表头区的模板示例也清掉

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

只清第 9 行以下时，写在前 8 行里的模板示例还在。`4-SPI总线` 仍显示 `P00.8` 和 `2M`，死区页仍显示 `1.6 μs`。

## 反事实

仍把前 8 行里格子最多的那一行当成表头，下一次 `P00.8`、`LPS_SIG_SENT` 的公式、`40C0` 和 `1.6` 还留在表上。这些数会看起来像这次从网表或手册读出来的。

## 二级依据

- 确认口径：列名留下。模板示例行、公式和说明清掉。两条路径都这样。
- `HSI--20261103.xlsx`：`4-SPI总线` 第 4 行是 `P00.8`、`CSN3_M/T_SPI3`、`2M`、`4M`。`7_Dead Time` 第 4 行是 `REV1` 和 `1.6 μs` 的要求，第 7 行 `J7` 为 `1.6`。`8_LPS_SIG` 第 3 行有气压公式。`22_3041寄存器配置表` 第 8 行是 `SAMPDEL` 和 `40C0`。
- 这些字来自模板 `DHTE400-HSI-V1.3-20261023.xlsx`，不是 `DHT160OF_PU_B3V2.EDF`，也不是 TC499 手册的引脚表。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：SPI 列名 `PIN` 还在，`P00.8` 和 `2M` 为空；死区表头 `Version`、`死区时间` 还在，`REV1` 和 `1.6` 为空；LPS 的 `Signal Name` 还在，公式为空；3041 的 `Name` 还在，`SAMPDEL` 为空；真值表标题、DSADC 说明、CAN 速率说明和功能安全那一行被清空。
