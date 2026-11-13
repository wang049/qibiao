# 2026-11-12 WPS 按丢掉的行标记把连接器图拉高

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_original_row_marks_come_back`、`test_picture_sheet_keeps_the_customer_drawing`、`test_tall_connector_picture_sits_in_the_view_cell`）

## 代价

整车低压第 5、6 行被拉得很高，连接器图里的 D1、D2 和壳体分开。表头和引脚号上各出现一次「保密：一级」。

## 反事实

原表没写 `ht` 的行继续不写行高，下一份在 WPS 里第 5、6 行仍会被撑开，连接器图仍被拉开。

## 二级依据

- 客户表 `超级混动项目吉利混动高低压接插件ICD_V3.12_20251202.xlsx`「4-整车低压连接器」：行上有 `spans="1:19"` 和 `x14ac:dyDescent="0.45"`。`pageSetup` 带 `r:id`，连着打印机设置。`图片 2` 从行 3 到行 22，`editAs="oneCell"`。
- 19:59 出表的图纸 XML 与客户文件相同，但行标记和 `pageSetup` 的 `r:id` 没了，并多了 openpyxl 写入的 `sheetPr`。背景图 `image10000.png` 是 790×745 的透明图，左上角只有「保密：一级」，按页宽平铺。

## 闸门

`test_original_row_marks_come_back`：第 5 行写回 `spans`、`x14ac:dyDescent`，并写成 `ht="16.5"`。没有写死行高时，WPS 会把图所在的行撑开。
