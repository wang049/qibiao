# 2026-10-30 端口表不沿用模板的黄紫行

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_board_pins_drop_template_yellow_and_purple_rows`）

## 代价

DHTE400 端口表用整行黄底、紫底标过原来的 TC499 引脚。按功率板接插件脚重写以后，这些底色还挂在行上，看起来像另一种分类。

## 反事实

仍留下行样式，下一次 `J402.20` 写进去，空单元格还是黄的或紫的。颜色不表示接插件、网络或上下拉。

## 二级依据

- `2_Port Assignment` 的行样式：多数数据行是黄底 `FFFFFF00`，另一些行是紫底 `FFFF66FF`。这是模板原来的标色。
- 分页预览会在表上印出「第 N 页」。接插件脚出表后改回普通视图。
- 底色不是当份网表里的量，不表示脚的类型。

## 闸门

`test_board_pins_drop_template_yellow_and_purple_rows`：写进接插件脚之后，第 4 行和第 22 行不再带模板行样式，工作表视图是普通视图。
