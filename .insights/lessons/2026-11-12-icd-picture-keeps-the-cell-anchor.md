# 2026-11-12 ICD 图沿用客户原来的两个格子

- 状态：superseded by 2026-11-12-icd-wps-row-marks.md
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_tall_connector_picture_sits_in_the_view_cell`、`test_picture_sheet_keeps_the_customer_drawing`）

## 代价

整车低压的连接器图被拉成竖长条，D1、D2 和壳体分开，分页预览的「第 6」盖在引脚上。

## 反事实

继续把 twoCellAnchor 改成 oneCellAnchor 并删掉 `to`，WPS 不认 `xdr:ext`，下一份仍把 535×375 的连接器图拉高。有图的表继续停在分页预览，打开后仍印着「第 N 页」。

## 二级依据

- 客户表 `超级混动项目吉利混动高低压接插件ICD_V3.12_20251202.xlsx` 的「4-整车低压连接器」：`图片 2` 是 `xl/media/image18.png`，535×375。锚点从列 1 行 3 到列 6 行 22，`a:ext` 为 5559632×3967102。
- 19:36 出表把这张图改成了 oneCell，没有 `to`。同一张表的视图仍是 `pageBreakPreview`。

## 闸门

`test_tall_connector_picture_sits_in_the_view_cell`：出表后仍是 twoCellAnchor，行号是 3 和 22，宽高仍是原图像素。`test_picture_sheet_keeps_the_customer_drawing`：图纸 XML 与客户文件一致，视图是 normal，从 A1 打开。
