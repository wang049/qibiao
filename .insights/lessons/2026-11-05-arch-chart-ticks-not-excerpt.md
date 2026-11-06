# 2026-11-05 曲线刻度不写进原文摘录，表题不占掉下一条

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_figures.py`（`test_axis_ticks_do_not_stick_to_the_footnote`、`test_table_inside_a_chart_shot_is_not_excerpted_again`、`test_repeated_heading_does_not_drop_the_next_sweep_rate`）

## 代价

曲线图的转速、分贝和阶次写进「本页图表」或脚注后面。已经收进截图的噪声表再拆成一行。表题被识成新的一条标题后，下一条自己的 `②` 被后一条更长的 `②` 换掉，标题末尾还粘着 `100Nm`、`0ver`。

## 反事实

坐标刻度仍并进上一条脚注时，`*TBD` 后面还会出现 `5000` 和 `Motor 48th Noise`。噪声表的外框已经落在只留截图的曲线里时，若仍按普通表再写一行，`2500` 和 `60` 会离开截图单独成条。短句已经写完、长句只是多了一段条件时若仍当成同一条，`120rpm/s under` 会被带 `rated rpm` 的后一条换掉。表题后面又重复上一条的 `①` 时若仍另起标题，这一条自己的扫频速率进不了清单。

## 二级依据

- 确认口径：`docs/knowledge/arch_kb.yaml` 卡片 `arch-chart-screenshot`。曲线图只留整张截图。同一高度旁边的数据表收进这张图，不从格子中间裁开，也不再另写原文摘录。图里没有编号条款时，坐标和图名不写入原文摘录。

## 闸门

`test_axis_ticks_do_not_stick_to_the_footnote`：脚注仍含 `TBD`，不含 `5000` 和 `Motor 48th Noise`。
`test_table_inside_a_chart_shot_is_not_excerpted_again`：曲线截图盖住的 `2500 / 60` 不另成一条，图表行不含 `15000`。
`test_repeated_heading_does_not_drop_the_next_sweep_rate`：第 3 条标题不带上一条的 `Motor NVH TEST condition`，其下仍有 `120rpm/s under`，第 4 条才有 `rated rpm`，摘录不含 `0ver` 和 `100Nm`。
