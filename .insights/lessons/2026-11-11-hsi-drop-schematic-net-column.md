# 2026-11-11 删掉星驱原理图网络这一列

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

这一列只藏起来时，表里还在。`K` 列仍是 `AI_IU_CH1_M2` 这一套名字，和 Pin Definition 里的信号名不是同一列字。工程师不需要这一列。

## 反事实

继续只隐藏，下一份端口表第 3 行仍有「星驱原理图网络」。删列后若跳转还指向原来的 `L` 列，信号名公式会指到功能描述。封面修改人若被清掉，`殷桂来` 不再留在封面上。

## 二级依据

- 模板端口表 `K` 列标题是「星驱原理图网络」，`L` 列是 Pin Definition。删掉 `K` 之后，Pin Definition 在 `K` 列。
- 删列前先改本表公式，以及其他表里指向这张端口表的格子。合并区 `A1:R1` 少一列。
- 跳转在删列之后再写，用删完以后的列号。

## 闸门

`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`：端口表第 3 行没有「星驱原理图网络」，Pin Definition 在第 11 列。
`test_dhte400_keeps_atom_port_name_cover_and_history`：手册出表后这一列也不在。`P02.1` 的端口名在第 11 列，封面修改人还在。
