# 2026-11-04 表头区右侧的模板数据也要清

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_header_band_drops_template_values_on_other_sheets`、`test_spi_rows_follow_manual_qspi_pins`）

## 代价

电机温度、热泵、锁切备注和死区公式还显示上一份项目的脚名和电平，像是这次手册写出来的。

## 反事实

表头区仍只扫到第 24 列，下一次 `16_EM Temp` 仍是 `TEMP_S/M_MT_GM`、`P8（AN42）`，热泵页仍是 `TEMP_T_PT2_AC_H_SIG`，锁切备注仍是「正常工作为低电平」，死区页 AA 列仍挂着 `=TEXT(J7,"0.0")&"μs"`。

## 二级依据

- 这些格子在 DHTE400 第 1 到 8 行、第 25 列以右，或是短信号名。TC499 手册没有这些网络名、球号和电平。
- 列名留下：电机温度的 `Motor`，锁切的 `Remarks`，死区的「死区时间」「μs」，油温页的 `MCU_OilTemp`。
- `4-SPI总线` 第 2 行「1. CAN模块 SPI总线」是模板分节，波特率列表头另留。

## 闸门

`test_header_band_drops_template_values_on_other_sheets`：`TEMP_S/M_MT_GM`、`T8（AN38）`、热泵信号名、锁切「正常工作」、死区 `TEXT(J7` 被清掉；`Motor`、`Remarks`、「死区时间」、`MCU_OilTemp` 还在。
`test_spi_rows_follow_manual_qspi_pins`：「1. CAN模块 SPI总线」被清掉，「SPI CLK波特率配置需求」还在。
