# 2026-11-06 拆开的脚注要拼回原句，表头词要译完

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_contrast.py`（`test_split_footnote_keeps_t_car_and_ordinal`、`test_join_lines_repairs_hyphen_breaks`、`test_quantity_keeps_rpm_per_second_and_drops_a_stuck_period`）、`tests/test_arch_figures.py`（`test_cell_translates_headers_and_keeps_names`）

## 代价

第 2 页脚注被收成 `※ TBD-vehicle evaluation and 1 Proto type bench test`。`To be determined after T-car` 没了，`1st` 变成 `1`。规格表里 `Every 10%` 写成「每项」，`Tq`、`Dyno`、`Engine` 留在英文里。测量项的短横被连成一段。

## 反事实

`T`、`-`、`car` 仍分成三行、`1` 和 `st` 先被当成碎片丢掉时，下次脚注仍是残句。`every` 一律译成「每项」、`Tq` 不进词典时，`Every 10% of max Tq` 和 `Input-Dyno (Engine) Tq.` 仍是半句中文。`of`、`max`、`Mode` 不进词典时，`of max` 和表 2 的 `Mode` 仍留在译文里。冒号后的短横若仍接在同一行，`8th/24th/48th` 那几条仍收不成原有的分行。

## 二级依据

- 确认口径：抽出值只来自当份文字层。被拆开的 `T-car`、`1st` 按原句拼回，不改写成别的数。`rpm/s` 保持原单位。规格表里的普通词写成「原文 / 中文」，`TBD`、`P1`、`P3` 不译。
