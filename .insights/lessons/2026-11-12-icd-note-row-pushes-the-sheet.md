# 2026-11-12 备注独占第一行，原表下移一行

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_long_sheet_legend_is_on_the_left`、`test_picture_sheet_keeps_the_customer_drawing`、`test_note_column_opens_in_normal_view_and_moves_the_page_break`）

## 代价

颜色说明写进原来的标题行，盖住「接插件信息」，也挡住这一行上的「电器端」。

## 反事实

备注继续占用原来的第 1 行，下一份打开后标题和电器端仍被这句说明挡住。下移原表时若图纸行号不加 1，图仍停在原来的格子上，盖住下移后的表头。若同时改列号或 `a:ext`，图会被拉开。

## 二级依据

- 出表后的整车低压：备注占第 1 行，原来的标题和电器端被挡住。原表整体下移一行，备注单独留在第 1 行、从第 1 列起。
- 客户表「4-整车低压连接器」图片从行 3 到行 22。下移后行号各加 1，列号、列偏移、行偏移和 `a:ext` 保持原样。行高标记跟着原行下移，不给图所在的行另写一份更高的行高。

## 闸门

`test_long_sheet_legend_is_on_the_left`：A1 是这句备注，A2 仍是「接插件信息」，A3 仍是「引脚号」。图片列号不变，行号从 6、10 变成 7、11，列偏移和行偏移不变。
`test_picture_sheet_keeps_the_customer_drawing`：图纸与客户原件相比，只有 `<row>` 里的行号加了 1。
`test_note_column_opens_in_normal_view_and_moves_the_page_break`：行分页符从 83 变成 84，列分页符仍是 8。
