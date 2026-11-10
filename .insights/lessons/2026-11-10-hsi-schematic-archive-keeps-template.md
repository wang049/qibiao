# 2026-11-10 有原理图时按模板归档，只改对上的格子

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`、`test_schematic_symbol_follows_body_when_header_is_swapped`）

## 代价

按 EDIF 出表会删掉模板端口行，改成接插件脚，并清掉封面修改人、变更记录和其他页。工程师不能直接拿原格式归档。

## 反事实

若继续整表重写，下一份网表仍丢掉未出现在接插件上的 `AN0`，端口名 `PWM_M_AH_GM` 被网络名盖掉，封面修改说明和 v1.3 也被清掉。

## 二级依据

- 会议口径：有原理图时与现有模板一致。不用改的内容直接复制，要改的由原理图更新，并做交叉验证。格式保持原表，工程师直接使用。
- 网表网络 `PWM_M/D_AH_GM` 对模板端口名 `PWM_M_AH_GM`。网络写进「星驱原理图网络」，端口名留下，标记写明两边不一致。接到地的电阻才写下拉。对不上模板端口的网络不新增行。
- 无原理图仍先认 MCU，再数脚、按手册归类，再写复用。分类不进 Function 列。电子件 CE BOM 仍默认 4 级；与上一版只做校核。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：`P02.1` 与 `AN0` 都在；网络列是 `PWM_M/D_AH_GM`，端口名仍是 `PWM_M_AH_GM`；说明含「交叉」和 `R822A`；`AN0` 的网络名不动。
`test_schematic_symbol_follows_body_when_header_is_swapped`：表头写球号在 B、符号在 C，正文却是 `P02.1` 在 B、`F5` 在 C。对上后不另起一行，K 列网络名和端口名留下。
`test_alias_pin_does_not_append_a_second_row`：模板已有 `AN17/P40_10` 时，原理图再出现 `P40.10` 和 `AN17` 仍落在同一行，不追加。
