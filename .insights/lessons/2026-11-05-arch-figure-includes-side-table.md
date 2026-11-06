# 2026-11-05 曲线截图要含旁边的整张数据表

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_figures.py`（`test_curve_screenshot_keeps_the_whole_side_table`、`test_outlined_condition_page_excerpts_the_sentences_and_the_table`）

## 代价

曲线图和它左边的转速–噪声表被收成一张图时，截图从表格中间切开。`rpm` 列和表头左半边不在图里，图旁再写出一串坐标碎片。

## 反事实

图框已经压进数据表、或和曲线同一高度只隔开几十点时，若仍不把整张表的外框并进截图，下次 `rpm | 8th Noise` 仍会从半格切开，只剩 `se (dBA)/TBD`。曲线和电机照片合成一张之后，若再把坐标上识出的字写进原文摘录，转速、分贝仍会变成图旁边的碎片行。

## 二级依据

- 确认口径：`docs/knowledge/arch_kb.yaml` 卡片 `arch-chart-screenshot`。任何输入文件都按同一套规则。曲线图只留整张截图，旁边同一高度的数据表收进这张图，不从格子中间裁开。图里没有编号条款时，坐标和图名不另写原文摘录。已经读成行列的规格表仍按原列画出。

## 闸门

`test_curve_screenshot_keeps_the_whole_side_table`：表线已从笔画里排除、和曲线隔开约 60 点时，截图左缘仍盖住表的左边界，右缘仍盖住曲线。
`test_outlined_condition_page_excerpts_the_sentences_and_the_table`：噪声页截图左缘不大于 40、上缘不大于 220、右缘不小于 800、下缘盖住电机照片；该图原文摘录为空。
