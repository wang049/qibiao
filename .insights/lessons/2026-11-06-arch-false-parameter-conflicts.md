# 2026-11-06 不同试验和同值的另一种写法不算冲突

- 状态：active
- 条目：电驱需求拆解出表
- 闸门：`tests/test_arch_params.py`（`test_consistency_compares_quantities_and_respects_conditions`）、`tests/test_arch_qa.py`（`test_detects_cross_table_vo_range_and_shock_g_and_dual_max_output`、`test_same_mechanical_shock_with_two_g_values_still_conflicts`）

## 代价

正弦半波、碰撞和概述里的机械冲击被放在一起比 G 值，整行标红。`15 years` 和 `15 years / 300,000 km`、`Region Ⅳ` 和 `Region IV`、`R10.05/06` 和分开写的两个法规号也被当成取值不一致。

## 反事实

冲击试验不按项目名分开时，`Over 40G` 仍会和 `40G / 20G / 10G`、`20G / 10G / 5G` 标成同一冲突。只比整句、不认「短的取值都包含在长的里面」时，`15 years` 仍会和多写了里程的那一处标红。罗马数字和 `R10.05/06` 不展开时，ESD 和传导发射的两种写法仍会标红。

## 二级依据

- 确认口径：同一参数、适用条件相同而取值不同才标红。试验名称不同的冲击不比。一个取值只是在另一个取值上多写了别的单位，或只是罗马数字、法规号的写法不同，不算冲突。输出电压范围前后不同、同一条机械冲击写出两个 G 值，仍然标红。
