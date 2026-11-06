# 2026-11-05 矢量线框里的文字和表格按版面摘出并翻译

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_figures.py`（`test_cell_translates_headers_and_keeps_names`、`test_vector_text_and_table_are_excerpted`、`test_picture_table_without_text_is_drawn`、`test_find_figures_takes_chart_but_not_text_boxes_or_header`）

## 代价

PDF 里用线条画出的文字框和表格会被记成「本页图表（矢量图）」。原文摘录只剩这个标记和几个短标签，中文译文也不写。截图还在，但字没有按版面摘出来。

## 反事实

文字层没有字时仍只标矢量图，格线表还是画不出来。`1)` 和 `2.` 挤在同一格、模型只译了第一句就整段采用时，第 2 点和后面的子条仍然没有译文。原表左边 `100Nm` 竖向合并、下面几格为空时，若仍各写一格，摘出来的表和原表对不上。表头只有一个英文词时不译，或把 `Sanghun Han` 这类专名硬译，都不符合甲方口径。留下 `rpm` 就整格不附中文，表头和格子也会漏译。若把坐标图上的 `7V | 16V` 也当成表格来取数，曲线图会被读成一条数值要求。横轴刻度 `0、5000、10000、15000` 若写成表，会和旁边数据表的 `2500 / 60` 混成一行。

## 二级依据

- 确认口径：矢量图先整块截图。文字层有成句正文的，原文摘录写这段话并附中文。表格按原有行列画出，表头和格子里的普通词都写成「原文 / 中文」。缩写和词典里没有的专名不译。线有点斜的规格表（表题带 Table、Load、Speed rate）仍按表格摘录。只有转速、噪声这类曲线图才只留截图，旁边的数据表并进同一张图，不另写原文摘录。

## 闸门

`test_vector_text_and_table_are_excerpted`：`The supplier shall confirm every change` 的摘录含「供应商」，且不是「本页图表」。`Item`、`Unit`、`Value`、`Notes` 各占一列，下一行是 `Water cooling`、`LPM`、`MAX. 12`，格子左边有细线，表头加粗。`7V | 16V` 仍是刻度，不算表格。
`test_picture_table_without_text_is_drawn`：没有文字层的表格图片能认出 `Cooling`、`LPM` 两格。
`test_find_figures_takes_chart_but_not_text_boxes_or_header`：坐标图的摘录仍是「本页图表（矢量图）：Po (kW)」，数值列为空。
