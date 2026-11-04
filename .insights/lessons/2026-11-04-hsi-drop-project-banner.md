# 2026-11-04 端口表头不留项目名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_ball_and_symbol_follow_the_column_headers`、`test_schematic_lists_unconnected_connector_pin_and_clears_template_pages`）

## 代价

端口表 L2 写着 `Superevo pin Definition`。这是模板所属项目的名字，出表后会被看成这次的端口定义。

## 反事实

不删这句，下一次打开端口表，Pin Definition 上面仍是 `Superevo pin Definition`。

## 二级依据

- 确认口径：Superevo 是某个项目，出表里不应该有。
- 模板 `DHTE400-HSI-V1.3-20261023.xlsx` 端口表 L2 为 `Superevo pin Definition`，L2:M2 合并。第 3 行 L、M 列仍是 `Pin Definition`。
- 手册出表、网表出表和原理图 PDF 出表都清掉含 Superevo 的表头。列名 `Pin Definition` 留下。

## 闸门

`test_ball_and_symbol_follow_the_column_headers`：写出后 L2 为空，第 3 行仍是 `Pin Definition`。
`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`：原理图 PDF 出表同样清掉 `Superevo pin Definition`，列名还在。
