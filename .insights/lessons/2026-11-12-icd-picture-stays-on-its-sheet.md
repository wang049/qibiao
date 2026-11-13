# 2026-11-12 每张表的图留在原表，备注列只把列号右移

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_picture_sheet_keeps_the_customer_drawing`、`test_each_sheet_keeps_its_own_picture`、`test_tall_connector_picture_sits_in_the_view_cell`）

## 代价

整车低压和变速器的备注没了。高压接口上的图出现在 12V 连接器上，低压表里的图被改到别的格子。

## 反事实

有图的表继续停在分页预览和原来的 `topLeftCell`，下一份仍从中部打开，满屏是「第 N 页」。保存后再改图纸锚点、列号和 `a:off`，或把图所跨的列宽重写成默认 13，下一份图仍被拉开。只补包里没有的图片、已有同名文件不覆盖，下一份高压的图仍会留在 12V 的文件名上。

## 二级依据

- 客户表 `超级混动项目吉利混动高低压接插件ICD_V3.12_20251202.xlsx`：高压图在 `drawing1`，12V 图在 `drawing2`，低压图在 `drawing3`（含第 3 行到第 22 行那张），变速器图在 `drawing4`。各表图片字节不能互换。
- 备注横写在表头右侧的一行，不再插入左列。有图的表不改图纸。`<cols>` 和 `<sheetFormatPr>` 用原文件那一段，小结列只加在原表内容的右边。视图改成普通，从 A1 打开。客户原表的分页预览停在低压 `I49`、变速器 `C16`。
- 低压表原文件还有 `legacyDrawing` 和 `oleObjects`。保存会丢掉这些部件，要连同 vml、emf 和 ole 文件一起写回。原表用一列区间写两列的宽度时，按区间记下每一列。不要逐列去取，否则区间里的第二列会被建成默认宽度 13。

## 闸门

`test_picture_sheet_keeps_the_customer_drawing`：源表是分页预览、停在 I49，列宽区间是第 7 到第 8 列 18.4，图是 `twoCellAnchor`。出表后图纸 XML 与源文件相同，视图是普通、停在 A1，这一段列宽不变。`test_each_sheet_keeps_its_own_picture`：高压、12V、低压各带一张不同的图，出表后仍是自己的那张图。`test_tall_connector_picture_sits_in_the_view_cell`：从第 3 行到第 22 行的图，出表后仍是这两行，宽高仍是原来的尺寸。
