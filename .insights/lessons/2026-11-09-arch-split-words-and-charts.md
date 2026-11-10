# 2026-11-09 按词拆开的 as、the 留在原句，上下两张曲线不合成一张

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_contrast.py`（`test_hyphen_split_number_and_table_row_labels`、`test_whole_table_excerpt_is_one_line_per_row`）；`tests/test_arch_figures.py`（`test_any_document_splits_each_chart_from_its_own_table`、`test_outlined_condition_page_excerpts_the_sentences_and_the_table`）

## 代价

`Such as the safety regulations` 被收成 `Such safety regulations`。半截译文 `项目：材料 marking` 写进整表摘录。一页两张曲线合成一张，噪声图的 8 阶、24 阶、48 阶不再分开截图。

## 反事实

`as`、`the` 仍按一两字碎片丢掉时，下一份按词拆行的要求会缺掉介词。没译完的英文单词仍跟在中文后面时，栏目对照不再是原文一行。两串曲线仍共用一个绘图外框时，上下两张图还是一张截图，阶次标题进不了各自的图。

## 二级依据

- 确认口径：`docs/knowledge/arch_kb.yaml` 卡片 `arch-chart-screenshot`。曲线图按各自分开截图。同一高度旁边的坐标和数据表可以收进这一张，不把下一张图连进来。没译完的格子不写成「原文 / 中文」。

## 闸门

`test_hyphen_split_number_and_table_row_labels`：摘录含 `Such as the safety regulations`。
`test_whole_table_excerpt_is_one_line_per_row`：`Item: Material marking` 后面直接是 `Other:`，`Related SPEC` 才带 `相关规范`。
`test_any_document_splits_each_chart_from_its_own_table`：一页两张曲线各一张，且不另写表。
`test_outlined_condition_page_excerpts_the_sentences_and_the_table`：噪声页有 3 张含 Noise 的图，8 阶在左，48 阶在右。
