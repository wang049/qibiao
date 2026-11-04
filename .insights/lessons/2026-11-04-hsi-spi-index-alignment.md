# 2026-11-04 SPI 序号对齐不统一

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_spi_rows_follow_manual_qspi_pins`）

## 代价

SPI 表序号有的居中、有的靠右，看起来像两套编号。

## 反事实

写入序号时不设对齐，下一次打开 `4-SPI总线`，原示例行仍居中，原分段标题行按数字默认靠右。

## 二级依据

- 模板里编号格是居中。分段标题行没有水平对齐，Excel 对数字默认靠右。
- 新写入的序号统一居中。ADC 表序号同样处理。

## 闸门

`test_spi_rows_follow_manual_qspi_pins`：第 4 行第 1 列序号为 `1`，水平对齐为 `center`。
