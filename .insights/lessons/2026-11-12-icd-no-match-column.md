# 2026-11-12 ICD 原表不再写匹配栏

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_previous_file_marks_add_remove_and_change`、`test_long_sheet_legend_is_on_the_left`）

## 代价

原表右侧再写一列匹配，和颜色、本表小结说的是同一件事。长表上这一列贴着小结，工程师还要读「修改：信号定义」。

## 反事实

继续在原表右侧写匹配栏，下一份低压连接器仍有「匹配」「修改：信号定义」「未改」。备注里若再解释匹配栏，打开第 1 列还是那段用不上的规则。

## 二级依据

- 新增、修改已经用绿色和黄色涂在改过的格子上。删除不在当版，写在本表小结。
- 原表不再加匹配栏，也不写「已从当版读出」。
- 备注只说明颜色和本表小结，不写匹配栏。

## 闸门

`test_previous_file_marks_add_remove_and_change`：原表没有「匹配」，也没有「修改：信号定义」。本表小结仍有 PIN1 修改信号定义。差异总结第 2 行含「本次出表」。
`test_long_sheet_legend_is_on_the_left`：备注里有「只涂改过的那一项」，没有「匹配栏」。
