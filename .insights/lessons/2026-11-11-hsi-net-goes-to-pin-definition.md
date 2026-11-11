# 2026-11-11 原理图网络名写入引脚信号名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`、`test_template_highlight_clears_and_written_cell_is_green`）、`tests/test_hsi_dead_time.py`（`test_schematic_archive_keeps_dead_time_text`）

## 代价

星驱原理图网络是星驱项目专有列。先把导线名写进这一列再删掉，删完后原理图名字不在表里，Pin Definition 仍是模板原名。有原理图时再改死区时间和 3041，工程师打开的就不是原来那本表。

## 反事实

继续写进星驱列再删除，下一份 `P02.1` 的 Pin Definition 仍是 `PWM_M_AH_GM`，原理图上的 `PWM_M/D_AH_GM` 不出现。有原理图时若仍把死区页改成可编辑公式，`C4` 不再是模板原句。

## 二级依据

- 确认口径：星驱原理图网络不进入输出。导线网络名写入 Pin Definition。和模板原名不同时，标记说明留下原名。同一只脚在 ADC 的 Signal name、SPI 和 CAN 已有行的 Net Name 上一起改。封面、死区时间、3041 保持模板。
- 删列发生在写入之后。Pin Definition 左移一列。跳转挂在删列以后的信号名上。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：删列后第 11 列是 Pin Definition，值为 `PWM_M/D_AH_GM`，标记含端口名 `PWM_M_AH_GM`。`AN0` 仍是 `IA_S/M_TM`。
`test_template_highlight_clears_and_written_cell_is_green`：`NET_A` 写在 Pin Definition 并标绿，星驱列不写。
`test_schematic_archive_keeps_dead_time_text`：死区页原句还在，不写成 `J7` 公式。
