# 2026-11-10 连接器表下的差异改回表格

- 状态：superseded
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_same_signal_without_pin_number_is_not_a_new_pin`、`test_different_sheet_name_and_plain_pin_still_compare`）

## 代价

本表小结把一条差异写成居中的一段话。上一版和当版叠在上下，引脚定义连在一起，对不上看哪一项改了。

## 反事实

继续用一段居中文字，下一份高压接口表下仍是「修改、上一版、当版」竖排，引脚定义对不上列。若为了做表格去加宽原表的型号列、镀层列，连接器本体又会被撑开。

## 二级依据

- 出表后的高压接口表：小结是居中文字块，用户要求改回表格。
- 原表列宽要留着。列够宽时按现有列切成差异、对象、字段、上一版、当版；列不够时表格接到右侧，不改前面的列宽。

## 闸门

`test_same_signal_without_pin_number_is_not_a_new_pin`：小结里「修改」和「引脚号」各是一格，当版格含信号，表头有「上一版」，没有单独一格等于「新增」。本表小结水平居中。
`test_different_sheet_name_and_plain_pin_still_compare`：原表 A 列宽 14、D 列宽 9 不变。表头有「上一版」和「当版」。
