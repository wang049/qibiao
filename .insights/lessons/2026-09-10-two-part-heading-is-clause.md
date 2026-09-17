# 2026-09-10 行首两段号也是条款，4.6 阻燃不得抄 4.3.3

- 状态：active
- 条目：#102 阻燃要求；#73 扭矩响应时间（核对表序号）；交叉 #47–#50 性能表
- 闸门：`electrical/tests/test_extract_quality.py` `test_flame_heading_4_6_not_ageing_4_3_3`、`test_drivability_table_rows_keep_printed_2_3_5`、`test_line_start_quantity_is_not_heading_clause`；`electrical/extract.py` `_heading_number_on_line`

## 代价

查其它页时：SuperEvo 2.3.2 动力经济性表、2.3.5 驾驶性表后段，和 4LDHT260 第 23–24 页一样，都是同节大表够不着标题。跨表回看修好后，阻燃「## 4.6 Flame Retardance」是两段号，原先只认三段及以上，会被挂到上一节老化 `4.3.3` / 防腐 `4.2.3`。

## 反事实

不认行首两段号，下次阻燃条款写成 4.3.3，现场打开老化章对不上阻燃正文。若把正文里的 `12.5 kW` 也当标题号，功率行会串号。

## 二级依据

- DHTS160 / SuperEvo Word：`## 4.6 Flame Retardance Requirement阻燃要求`，其下 `According Q/JLY J7110335C-2022`。
- SuperEvo：`### 2.3.5 驾驶性` 表内 P1 峰值扭矩响应 100-300ms、P3 0-90%持续扭矩≤40ms。
- 交叉 `2026-09-10-table-rows-keep-section-clause`（大表后段挂已印节号）、`2026-09-07-hvdc-range-is-not-protection-clause`（未印号 PEI 仍不得沿用上一节）。

## 闸门

- 行首已印 `x.y`～`x.y.z.a.b` 都当标题；后接 kW/V/Nm 等单位则不是标题。
- 阻燃在 `## 4.6` 下 → 条款 `4.6`，不得为 `4.3.3`。
- 2.3.5 表后段扭矩响应 → `2.3.5`。
- 未印号高压范围表仍空，不抄 Protection。
