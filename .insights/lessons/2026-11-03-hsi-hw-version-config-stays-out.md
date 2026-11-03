# 2026-11-03 硬件版本页不留模板配置

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

`0_硬件版本识别` 前 8 行仍显示模板配置：`Boost`、`无Boost`、`充电升压Boost（1000V）`、`PCM1`、`PCM2`、`普通差速器`、`切分机构`，以及 `HW1=0` 到 `HW4=1`。

## 反事实

只清长说明和 `P00.8` 这类示例，下一次硬件版本页仍把 `HW1=0`、`1000V` 和锁切一体选项显示成这次的结果。

## 二级依据

- 确认口径：这一页的配置行清掉。列名 `配置项`、`配置释义`、`GPIO配置`、`备注` 留下。
- 模板 `DHTE400-HSI-V1.3-20261023.xlsx` 的 `0_硬件版本识别`：第 3 到 8 行是 Boost、控制器、锁切一体和 `HW1=0` 等。`DHT160OF_PU_B3V2.EDF` 没有这些配置。
- 第 9 行以后的版本电压已在第 9 行起清空。这次补的是仍留在前 8 行的配置。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：`配置项`、`GPIO配置` 还在；`Boost`、`HW1=0`、`充电升压Boost（1000V）`、`切分机构` 为空。
