# 2026-11-03 ADC 中文功能列出表时清空

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

`3_ADC Table` 的 Pin Function 列带着模板上一份项目的中文，看起来像已经译好。这一列约定手填，程序译不了。

## 反事实

出表时留下 `TM三相电流检测` 这类模板原文，下一份生成稿的中文功能列仍是上一份项目的句子。按信号名再译一列，会把没确认的中文写进格子。

## 二级依据

- 确认口径：ADC 中文功能说明手填，不自动翻译。电压、电流余量系数也还没确认，最大最小值不按举例系数填。
- DHTE400 `3_ADC Table` 第 4 行 G 列表头是 `Pin Function Decription`。第 5 行信号名 `IA_S/M_TM` 旁边原是 `TM三相电流检测`，这是模板里的手填内容，不是当份手册的句子。
- 表头保留，数据行清空。R1、R3 的表头仍用来隐藏这两列。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：写出后 G 列表头仍是 Pin Function，第 5 行及以下该列为空。
