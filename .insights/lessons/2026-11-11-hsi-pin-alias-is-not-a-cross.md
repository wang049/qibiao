# 2026-11-11 脚号别名不算和端口名交叉

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_alias_pin_does_not_append_a_second_row`、`test_template_highlight_clears_and_written_cell_is_green`、`test_schematic_symbol_follows_body_when_header_is_swapped`）

## 代价

原理图符号上的 `AN17/P40.10` 把 `P40.10` 放进功能字段。拿它和端口名 `6V6_P_LDO_AI` 比，字一定不同。没改网络名的行也被标成待人工复核，符号和球号涂绿。

## 反事实

继续把脚号当功能去比端口名，下一份 `AN17/P40_10` 仍会写「交叉：端口名 6V6_P_LDO_AI，符号功能 P40.10」，核对状态仍是待人工复核。导线上的网络名 `NET_A` 若不再写入交叉说明，端口名 `PWM_M_AH_GM` 和网络名不一致时就没有这句话。

## 二级依据

- 流程图：对上的行只更新引脚和信号名；端口名和原理图网络名不一致时写交叉说明；没改的格子保持模板。
- `P40.10`、`AN17` 是同一只脚的另一个脚号。交叉只比较读到的导线网络名和端口名。
- 脚号不写入复用。复用只在读到的是功能名、并且这一格原来是空的时候填写。网络名和端口名都没变的行不标待人工复核，也不涂绿。

## 闸门

`test_alias_pin_does_not_append_a_second_row`：`AN17/P40_10` 的端口名仍是 `6V6_P_LDO_AI`，不写交叉，不标待人工复核，符号格不上绿，不另起一行。
`test_template_highlight_clears_and_written_cell_is_green`：网络名写成 `NET_A` 并标绿，交叉说明是「端口名 PWM_M_AH_GM，原理图 NET_A」。端口名仍是 `PWM_M_AH_GM`。
`test_schematic_symbol_follows_body_when_header_is_swapped`：空的复用写成 `ERAY0_RXDA2` 并标待人工复核。没有导线网络名时不写交叉。
