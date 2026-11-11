# 2026-11-11 原理图归档去掉整行黄粉底

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_archive_drops_page_preview_and_row_color`）

## 代价

分页预览和列样式去掉以后，WPS 仍把端口表右边画成整片黄，中间夹着粉条。黄、粉底记在行上，一行的底色会涂满这一行的空白列。

## 反事实

继续留下行底色，下一份 `2_Port Assignment` 在 WPS 里仍是整片黄和粉条。若把这次写入的绿色一起清掉，`SIG` 这种改过的格子就看不出来。

## 二级依据

- 发布稿端口表行样式：黄底 `FFFFFF00` 274 行，粉底 `FFFF66FF` 44 行。列样式去掉、视图改成普通视图之后，这两层行底色还在。
- 有原理图时只留这次改过的绿色 `C6EFCE`。手册出表不走这一步。

## 闸门

`test_schematic_archive_drops_page_preview_and_row_color`：归档后视图是普通视图。第 4 行黄底、第 5 行粉底不再是实心色。绿色格子仍是 `C6EFCE`。
