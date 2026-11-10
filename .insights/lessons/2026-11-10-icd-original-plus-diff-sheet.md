# 2026-11-10 ICD 原表后只加版本差异

- 状态：superseded
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`、`test_gateway_returns_the_pin_workbook`）

## 代价

每个连接器表下再写小结，并另起差异总结、引脚清单。原表列宽和行数被拉开，出表不再是原来的 ICD。

## 反事实

继续在原表下写本表小结，或再加差异总结、引脚清单，下一份仍不是「原表加上一张版本差异」。封面式的重排会再次碰到列宽对不齐。

## 二级依据

- 会议：比对上一版和最新版，生成差异文档。输出要易读，可以用颜色、按内容调整列宽，并保持与原格式一致。
- 确认口径：分析每个 sheet 之后，加一张版本差异即可。改过的行可以涂色，不在表下再嵌一张表。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：结果只有原连接器表和「版本差异」。没有差异总结、引脚清单、变更记录，也没有「本表小结」。原表仍是 2 行，A 列宽 14、D 列宽 9。改过的信号格为黄。打开的是版本差异，前两行有两个文件名和 V3.11、V3.12。
`test_gateway_returns_the_pin_workbook`：没有上一版时，下载的是原表，没有引脚清单，也没有版本差异。
