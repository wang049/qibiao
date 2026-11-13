# 2026-11-12 颜色说明这一行写在最左边

- 状态：superseded
- 接上：`2026-11-12-icd-note-row-pushes-the-sheet.md`。备注不再写进原来的标题行。
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_long_sheet_legend_is_on_the_left`、`test_note_column_shifts_the_picture_with_its_sheet`、`test_different_sheet_name_and_plain_pin_still_compare`）

## 代价

整车低压和变速器的「备注：绿色为新增。黄色只涂改过的那一项。红色删除写在右侧本表小结。」写在本表小结那一列，打开后要翻到表的右侧才看得见。

## 反事实

这一行继续跟在右侧小结前面，下一份仍从第 1 列看不到绿、黄、红的意思。若为了把它放到最左边而插入一列或一行，连接器图的格子会跟着挪，图又会被拉开。

## 二级依据

- 这一行要显示在最左边。客户表「4-整车低压连接器」「5-变速器连接器」第 1 行是 A1:H1「接插件信息」，两列宽合计约 105，这一句放得下。原句挪进这一行，标题改写到紧挨着的下一格。
- 没有这条标题带、第 1 格就是「引脚号」的表，备注仍写在右侧小结那一列，避免盖住引脚号。
- 不插入列、不插入行。图片的起止格子保持客户原样。

## 闸门

`test_long_sheet_legend_is_on_the_left`：A1 是这句备注，I1 仍是「接插件信息」，A2 仍是「引脚号」。图片锚点仍是第 6 行到第 10 行。右侧小结那一列的第 1 行不是这句备注。
`test_note_column_shifts_the_picture_with_its_sheet`：A1 是这句备注，图片仍从第 3 行到第 22 行，列号不变。
`test_different_sheet_name_and_plain_pin_still_compare`：没有标题带时，这句备注仍在小结那一列的第 1 行，不盖住「引脚号」。
