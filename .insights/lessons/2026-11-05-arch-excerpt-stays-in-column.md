# 2026-11-05 原文摘录停在自己的列里，缺字的正文改用识读结果

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_figures.py`（`test_orphan_speed_moves_back_and_excerpt_stops_before_quantity`、`test_tall_shot_still_writes_the_status_list`、`test_two_column_table_is_drawn_beside_itself`）

## 代价

线框表从「原文摘录」起按列往右写时，第二列落在「数值与单位」，第三列落在「适用条件」。转速会和表头错列。文字层缺字时仍用那串碎片，同一张图里的第 2 点、第 3 点和表下几行就不再出现。

## 反事实

不把多出来的表列插在「数值与单位」之前，下次 `Speed rate`、`200rpm/s` 仍写在「数值与单位」和「适用条件」下面。不把没有表头的最右列挪回左边，`800rpm/s` 仍比 `200rpm/s` 多偏一列。文字层已经是 `u nd n rm` 这种碎片时若仍不用截图识读，编号条款继续只剩半句。短的「④」没有单独截图就丢掉的话，同一段里的后几个子条仍然进不了清单。补截图行高时若把右移列数写成小数，状态列算不出来，生成直接报 Internal Server Error。文字层没有字、编号要求被塞进表格的一格时，若仍用那一格拼出来的半句，`Bench test sweep rate` 这类正文不会写进原文摘录。转速落在空列右边时若仍各占一列，`200rpm/s` 不会在 `Speed rate` 下面；`800rpm/s` 再往下并过下一张表，会看起来贴在 `100Nm` 旁边。已经读成两列的表若再把格子竖着堆进同一列，`2500` 和 `60` 就不会并排。和表格同一张图里的 `1)`、`2.`、`3.` 若因为没有单独截图被丢掉，左边的编号要求就不会出现在原文摘录里。左半边多识出的句子若整段接到末尾，不同条目下的 `②` 会排到一起。同一标题下若 `③` 排在 `②` 前，或把表里的扭矩格子粘进正文，摘录顺序就和原页对不上。分块识读时漏掉的 `③` 若不再从合成后的整图补回，第 2 条下面就只剩 `①` 和 `②`。同一句有截断和完整两种识读时若留短的，`engine min rpm ~ rated rpm` 会停在 `engine min r`。`④No` 和 `④ No` 若不当成同一条，表头 `Table1` 会粘在第二条上，④ 就会多一行。`③` 后面的 `(±)10,20,30` 若并进正文，电池条件会带上表里的转速。

## 二级依据

- 确认口径：任何输入文件都按同一套规则摘。编号条款按原文顺序各成一条，不同条目下的 `②` 不堆到末尾。已经读成行列的表按原列画成表。曲线图横轴刻度不写成表，只留整张截图；同一高度旁边的数据表收进这张图，不从格子中间裁开，坐标和图名不另写原文摘录。文字层缺字时用截读补上，并插回它所跟的那一条后面。缩写和专名不译，其余写成「原文 / 中文」。

## 闸门

`test_orphan_speed_moves_back_and_excerpt_stops_before_quantity`：`200rpm/s` 与 `Speed rate` 同列，并且在「数值与单位」左边。`100Nm` 仍留在左列，下面的 `(±)30Nm` 留在右列。`④ No noise` 在有文字行定位时仍写入原文摘录。
`test_tall_shot_still_writes_the_status_list`：截图把行高撑开之后，表头仍有 Currently status，状态下拉仍在。
`test_outlined_condition_page_excerpts_the_sentences_and_the_table`：轮廓字那页的原文摘录含 `Bench test sweep rate`、`Load condition`，表里仍有 `200rpm/s` 和 `100Nm`。
`test_excerpt_rules_hold_for_a_document_that_is_not_the_sample`：换一份文件时，`② Load` 仍在参照表 1 的 `②` 之前，`120rpm/s` 更靠后；`2500` 与 `60` 同一行相邻；横轴 `15000` 不进原文摘录。
