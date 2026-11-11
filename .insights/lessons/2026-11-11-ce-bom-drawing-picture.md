# 2026-11-11 2 级件图片格放入本图视图

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_drawing_view_png_stops_before_the_notes`、`test_level_two_picture_is_embedded`）

## 代价

图片列若截技术要求左边的整块，塞进窄格后只露出图纸左上角。外形尺寸旁边的侧视图和平面图看不清。

## 反事实

继续截技术要求左边的整块，下一张壳体图的图片格仍是左上角的局部。把左边另一张视图和右边的局部放大一起贴进去，格子里不是标了外形尺寸的那两张主视图。3 级件若也贴上这张图，就带上了本图视图。

## 二级依据

- 供应商表有图片列。2 级件的图片取外形尺寸旁边的侧视图和平面图，不取图纸左上角的另一张视图。
- 右边以「1.」开头的技术要求，以及底下的图样名称、图样代号，不放进图片格。
- 3 级件没有单独的图，不放图片。

## 闸门

`test_drawing_view_png_stops_before_the_notes`：截图是 PNG，宽度停在技术要求左边。
`test_level_two_picture_is_embedded`：2 级件那一行有一张图，行高被撑开。
