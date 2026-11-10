# 2026-11-10 ICD 恢复表下小结和差异总结

- 状态：superseded
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`、`test_long_note_row_is_tall_enough_to_show_the_text`）

## 代价

只留原表和版本差异时，每个连接器表下没有本表小结，也没有差异总结。改过的内容要到版本差异里翻。

## 反事实

不再写表下小结和差异总结，下一份出表仍要在版本差异里逐条找，连接器表底下看不到这张表新增、修改、删除了多少。

## 二级依据

- 会议仍要原表格式和一张版本差异。随后确认表下小结和差异总结还要保留。
- 小结写在原表右侧新列，不改原表已有列宽。不恢复引脚清单。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：有差异总结、版本差异和原表。打开的是差异总结。原表有「本表小结」，A 列宽仍是 14、D 列宽仍是 9。没有引脚清单和变更记录。
`test_long_note_row_is_tall_enough_to_show_the_text`：长句在版本差异、差异总结和表下小结里都能放下，行高至少 40。
