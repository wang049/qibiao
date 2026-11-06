# 2026-11-04 原理图网络名取脚朝向那一侧的线

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_net_follows_the_wire_on_the_pin_side`、`test_jump_index_keeps_the_rows_under_each_net`）

## 代价

黄标签是导线上的项目网络名。按距离最近去配，会把符号对面那只脚的名字配过来。`P00.0` 会写成 `CSN3_M/T_SPI3`，而这根线接的是右边的 `P00.8`。

## 反事实

不看脚朝向，或顺着同一行一直找到远处的名字，下一次 `P14.8` 会写成 `P33.1` 那根线上的 `FLTA_M_H_TM`。把 `CB18_P1_GM_Driver` 或 `PO…` 位号写进网络列，页码和隐藏位号会当成网络名。写进「星驱原理图网络」列，Pin Definition 仍空着。M 列继续叫 Pin Definition，功能描述和端口名分不开。跳转索引若跟其他页一起清示例，`FLTA_M_H_TM（2 处）` 下面的「第几行」会被删掉，只剩一个标题。

## 二级依据

- 确认口径：网络名写入第一列 Pin Definition。星驱原理图网络这一列不展示。后一列 Pin Definition 的表头改为 Pin Function Description。只取这只脚朝向那一侧、同一行导线上最近的名字。页间端口 `CB…` 和 `PO…` 位号不写。复用列仍是符号上的功能。
- `DHT160-OF_BOOST_CU_A1V1.pdf` 第 2 页同一行从左到右：`RDY_M_H_GM`、`P00_0/CAN10_TXD`、`P00_8`、`CSN3_M/T_SPI3`。左边的线接到 `P00.0`，右边的线接到 `P00.8`。
- 再往外的 `CB18_P1_GM_Driver`、`CB11_RRO_CHASSIS` 是页间端口。

## 闸门

`test_schematic_net_follows_the_wire_on_the_pin_side`：`P00.0` 的网络名是 `RDY_M_H_GM`，复用仍是 `CAN10_TXD`。`P00.8` 的网络名是 `CSN3_M/T_SPI3`。两边的 `CB…` 都不进网络列。
`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：网络名 `SIG` 写在 Pin Definition。星驱原理图网络列藏起、表头清空。后一列 Pin Definition 改为 Pin Function Description。
`test_jump_index_keeps_the_rows_under_each_net`：清模板示例后，`跳转索引` 里分组标题和「第几行」都还在。
