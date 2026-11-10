# 2026-11-10 ICD 不再另出版本差异

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`、`test_previous_file_marks_add_remove_and_change`）

## 代价

版本差异和差异总结各写一遍同一批改动。打开文件要在两张表之间对。

## 反事实

继续生成版本差异，下一份出表仍多一张和差异总结重复的明细表。

## 二级依据

- 用户确认：差异总结留着，版本差异不需要。
- 两个文件名和版本号已经写在差异总结开头。新增、修改、删除的颜色也在这张表上。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：工作簿是差异总结和原连接器表，没有版本差异。差异总结开头有两个文件名和 V3.11、V3.12。
`test_previous_file_marks_add_remove_and_change`：差异总结里能看到新增、修改、删除三色。没有版本差异。
