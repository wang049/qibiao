# 2026-11-04 SPI 的 I/O 跟功能走

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_spi_rows_follow_manual_qspi_pins`）

## 代价

SPI 表的 I/O 抄了引脚垫的方向。TC499 这些口是双向垫，整列都写成 `Input/Output`。片选、发送是输出，接收、从机时钟是输入，看不出来。

## 反事实

继续抄引脚方向时，下一次 `QSPI3_SLSO4` 仍是 `Input/Output`，`QSPI3_MRSTC` 也仍是 `Input/Output`。

## 二级依据

- 确认口径：有的脚只是 Input，有的只是 Output。不能整列写成 Input/Output。
- TC499 手册：`QSPI3_SLSO4 O6 Master slave select output`；`QSPI3_MRSTC Master SPI data input`；`QSPI3_MRST O4 Slave SPI data output`；`QSPI3_MTSRC Slave SPI data input`；`QSPI3_MTSR O4 Master SPI data output`；`QSPI3_SCLKC Slave SPI clock inputs`；`QSPI3_SCLK O4 Master SPI clock output`。
- 端口表 Direction 仍是这只垫的方向。SPI 表 I/O 只看该条 QSPI/SPI 功能说明里的 input 或 output。同一只脚有两条功能时，I/O 跟功能逐行对应。

## 闸门

`test_spi_rows_follow_manual_qspi_pins`：垫方向是 `Input/Output` 时，`QSPI3_SLSO4` 的 I/O 为 `Output`。`QSPI3_MRSTC` 为 `Input`，同一行的 `QSPI3_MRST` 为 `Output`。
