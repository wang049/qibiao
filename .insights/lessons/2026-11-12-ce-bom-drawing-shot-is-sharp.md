# 2026-11-12 扫描图的视图要截全，并且留够像素

- 状态：active
- 条目：CE BOM 出表
- 闸门：`tests/test_ce_bom.py`（`test_scanned_sheet_picture_keeps_the_right_hand_view`、`test_drawing_view_png_stops_before_the_notes`、`test_thin_seal_view_is_not_dropped_for_the_table`、`test_seal_title_keeps_the_rubber_grade`）

## 代价

没有文字层的二维图，图片格只取页面宽度的 70%、高度的 82%，再按 0.55 倍渲染并缩到 420 像素。右侧和下方的视图被裁掉，留下来的线也看不清。

## 反事实

继续按 0.55 倍渲染并缩到 420 像素，下一份 `5501801755`、`5501801758` 的图片格仍是糊的。继续停在页面宽度的 70%，右侧轴测和标题栏左侧的下方视图仍不在格子里。有文字层的图若把技术要求一起截进去，图片格又会重新被说明文字占掉。

## 二级依据

- 用户上传的 `DHT160OF-5501801755`、`5501801758`、`5501801798` B00 图没有文字层。当时图片格是 420×346。1755 右侧轴测不在图里，1758 下方视图被底边裁掉。
- 这些图的标题栏在右下角。视图在标题栏以外。有「1.」技术要求和「图样名称」文字层的图，仍停在技术要求左边。
- `5501801802` 左边是密封圈细线，中间是清洁度表。按 0.06 倍找墨迹时细线消失，图片格只剩那张表。材料标记是 `EPDM`，质量是 `0.6g`。

## 闸门

`test_scanned_sheet_picture_keeps_the_right_hand_view`：没有文字层的页面，右侧视图留在图里，长边大于 800 像素。右下角标题栏不拿来扩大画面。
`test_drawing_view_png_stops_before_the_notes`：有技术要求文字的页面，图片仍停在说明左边，宽度小于整页。
`test_thin_seal_view_is_not_dropped_for_the_table`：细线圆和右边密表同时在一张扫描图上时，圆还在图片左半边。
`test_seal_title_keeps_the_rubber_grade`：标题栏只有一个 `EPDM` 时，材料记成 `EPDM`，名称仍是 `密封`，质量仍是 `0.6g`。
