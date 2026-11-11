# 2026-11-11 原理图归档回到普通视图

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_archive_drops_page_preview_and_keeps_row_color`）

## 代价

模板端口表的查看方式是分页预览，列样式用主题色铺开。WPS 按这个方式打开，空列被画成整片黄，上面还盖着「第 41 页」。Excel 用普通视图打开同一份模板时，这些通常不出现。数据行上的黄、粉底是模板原来的行标记。

## 反事实

继续留下分页预览和列样式，下一份 `HSI--` 在 WPS 里仍是整片黄，页码仍是「第 41 页」。若把数据行的黄、粉底也清掉，模板里原来标过的行就没有了。

## 二级依据

- 发布稿 `DHTE400_HSI_V1.3_20261023_release.xlsx` 的 `2_Port Assignment`：视图是 `pageBreakPreview`，左上角 `A94`。列 A–M 的列样式是实心主题色。行样式里黄底 `FFFFFF00` 有 274 行，粉底 `FFFF66FF` 有 44 行。
- 出表只去掉列样式和分页预览。行底色保留。

## 闸门

`test_schematic_archive_drops_page_preview_and_keeps_row_color`：归档后视图是普通视图，左上角是 `A1`，列填充不再是实心色，列范围不超过 200。第 4 行的黄底还在。
