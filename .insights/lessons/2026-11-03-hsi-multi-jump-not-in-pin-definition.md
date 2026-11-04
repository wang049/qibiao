# 2026-11-03 一对多跳转不占端口名列

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_one_port_name_links_every_matching_row`）

## 代价

两条蓝色链接写在 Pin Definition 和观测变量里。这两列没法再填端口名。

## 反事实

跳转从第 13 列往右摊开时，下一次打开端口表，M、N 列是「3_ADC Table 第7行」这种蓝字，真正的端口名没有格子。

## 二级依据

- WPS 里点下拉项只改当前格的字，不会打开那一行。
- 多个落点时，点符号或端口名进跳转索引。格子里仍是端口名，不写成「某表第几行」。
- 端口名自己对不上后面各表时，跟这一行符号去同一处。见 `2026-11-04-hsi-pin-definition-jumps-with-symbol`。
- 第 13 列及以后不写跳转。后面各表仍引用总表名称格。

## 闸门

`test_one_port_name_links_every_matching_row`：名称格仍是 `IA_S/M_TM`。下拉挂在 `L4`。第 13 列为空。ADC、热泵、PMIC 仍引用 `L4`。
