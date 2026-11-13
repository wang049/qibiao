# 2026-11-12 整车低压和变速器的本表小结写在表头右侧

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`、`test_short_sheet_summary_stays_under_the_table`）

## 代价

整车低压连接器和变速器连接器引脚很多。本表小结写在最后一行下面时，打开表先看到引脚，小结要翻到表底才出现。

## 反事实

这两张表的本表小结仍从 A 列、数据末行再往下写，下一份出表打开后仍要滚过整列 PIN 才看见新增、修改、删除。高压接口这类短表若也改到最右列，小结又离开表下，短字浮在右侧空列里。

## 二级依据

- 表名含「整车低压连接器」或「变速器连接器」时，本表小结从匹配栏右边、表头那一行起写。原表 A 到 E 的列宽不动。
- 其他原表的本表小结仍从 A 列、数据下面起写，文字靠左。
- 匹配栏仍在原表数据右侧，不写进小结占用的五列。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：「4-整车低压连接器」的本表小结在第 1 行、第 3 列以右，下一行同一列是「差异」。A 列宽仍是 14，D 列宽仍是 9。
`test_short_sheet_summary_stays_under_the_table`：「高压接口」的本表小结在第 1 列、数据下面。「5-变速器连接器」的本表小结在第 1 行、第 3 列以右，A1 仍是「引脚号」。
