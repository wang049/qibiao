# 2026-11-11 图面括号里的三个外形尺寸写入 X Y Z

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_parenthetical_view_sizes_fill_xyz_and_skip_local_notes`、`test_structure_drawing_reads_title_and_detail_rows`）

## 代价

2 级壳体只认标题栏「外形尺寸」后面的长×宽×高。这张图没有这一栏，平面图和侧视图上括号里的外形尺寸没有写入产品尺寸，X、Y、Z 空着。

## 反事实

继续只认「外形尺寸」栏，下一张同样只在视图上标了三个括号尺寸的壳体，X、Y、Z 仍空。把旁边的 `3±0.1` 全周槽或 `25(max)` 写进产品尺寸，局部尺寸会被当成外形。明细里的摩擦焊板、固化密封胶若也写上这三个数，3 级件就有了尺寸。

## 二级依据

- 这张壳体图第 1 页视图上，括号里单独的数字是平面图横向 465.22、平面图竖向 297.1、侧视图 111。括号表示图上写出的外形参考尺寸。
- `3±0.1` 标的是全周槽，`25(max)` 是局部限制，不写入 X、Y、Z。
- 3 级件仍不提取尺寸。已有「外形尺寸 120×80×15」这种写法时，仍按这一栏，不用视图上的括号数字替换。

## 闸门

`test_parenthetical_view_sizes_fill_xyz_and_skip_local_notes`：壳体的产品尺寸是 465.22、297.1、111。
`test_structure_drawing_reads_title_and_detail_rows`：外形尺寸栏仍是 120、80、15，明细子件尺寸为空。
