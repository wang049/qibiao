# 2026-11-12 出表不要停在分页预览，列分页符要跟着备注列走

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_note_column_opens_in_normal_view_and_moves_the_page_break`）

## 代价

4、5 两张表打开后满屏是「第 N 页」。整车低压的竖向分页切在接插件图中间，图和引脚表被拆到不同页上。

## 反事实

原表的 `pageBreakPreview` 和 `topLeftCell` 原样留下，下一份仍从分页预览的中部打开，水印盖住表格。插入备注列后不把列分页符的 id 加 1，下一份竖线仍停在插列前的那一列，接插件信息的最后一列被切到下一页。

## 二级依据

- 客户表 `超级混动项目吉利混动高低压接插件ICD_V3.12_20251202.xlsx`：4、5 两表的 `sheetView` 都是 `pageBreakPreview`。低压表 `topLeftCell` 是 `I49`，手动列分页符 id 为 8，切在接插件信息（A:H）和引脚表之间。行分页符 id 为 83。
- 备注列插在最左边。列分页符 id 变为 9，行分页符仍是 83。这两张表改为普通视图，从 A1 打开。图的锚点仍只把列号加 1。

## 闸门

`test_note_column_opens_in_normal_view_and_moves_the_page_break`：源表是分页预览、停在 I49，列分页符 8、行分页符 83。出表后视图是 normal、停在 A1，列分页符为 9，行分页符仍是 83。
