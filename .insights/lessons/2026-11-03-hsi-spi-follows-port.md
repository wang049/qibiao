# 2026-11-03 SPI 表对应端口表里的 QSPI 脚

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_spi_rows_follow_manual_qspi_pins`）

## 代价

端口表里已经有手册复用 `QSPI3_SLSO4`，SPI 表仍是空表头，引脚符号不能跳过去。

## 反事实

SPI 表继续只留表头，下一次 `P00.8` 的片选只出现在端口表的复用列。把模板网络名 `CSN3_M/T_SPI3` 或波特率 `2M` 写进 SPI 表，会把上一份项目的片选说明当成这次手册的结果。

## 二级依据

- 确认口径：SPI 表只列手册复用里有 `QSPI` 或 `SPI` 的脚。写入引脚符号、复用功能和方向。项目网络名、功能说明和波特率留空。
- 模板 `4-SPI总线` 第 4 行原是 `P00.8`、`QSPI3_M_SEL6`、`Output`、`CSN3_M/T_SPI3`、「底盘CAN2片选」、`2M`、`4M`。
- 只有 `QSPI`、`SPI` 开头的复用项算 SPI。`CAN10_RXDA` 不进这张表。

## 闸门

`test_spi_rows_follow_manual_qspi_pins`：`P00.8` 的功能是 `QSPI3_SLSO4`，方向是 `Output`，网络名和波特率为空。功能说明引用端口表名称格。`P00.1` 只有 CAN，不进 SPI 表。端口表 `P00.8` 的符号格链到 SPI。
