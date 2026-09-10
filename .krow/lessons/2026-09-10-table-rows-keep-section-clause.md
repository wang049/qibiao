# 2026-09-10 性能表行挂已印的 2.3.2，不发明条款号

- 状态：active
- 条目：#47 P3额定功率；#48 P3峰值扭矩；#49 P3额定扭矩（核对表序号 43–45）
- 闸门：`electrical/tests/test_extract_quality.py` `test_performance_table_rows_keep_printed_2_3_2`、`test_hvdc_voltage_clause_not_protection`；`electrical/extract.py` `_clause_for_index` / `_heading_clause_before`

## 代价

4LDHT260 / SuperEvo 的 2.3.2 性能表里，靠前的 P1 行条款号是 2.3.2，靠后的 P3 额定功率/扭矩条款列空。对表的人以为这些格没有条款；其实都在同一节 `2.3.2` 下。根因是条款回看只有 1600 字，大表后半截够不着标题。

## 反事实

不按「行首已印标题号」跨表回看、仍只用 1600 字窗口，下次 P3 功率扭矩条款列继续空。若为填满去套 DHTS 目录 6.5.x 或抄上一节 Protection `6.4.2.4`，高压范围表又会串号。

## 二级依据

- 当份 4LDHT260 扫描件：P3 额定 120kW、峰值扭矩 400Nm、额定扭矩 200Nm 与 P1 功率同在 2.3.2 性能表，印页约 23–24。
- 交叉 `2026-09-08-word-outline-number-and-toc-page`（写回大纲号）、`2026-09-07-hvdc-range-is-not-protection-clause`（未印号 PEI 标题仍不得沿用上一节）。

## 闸门

- 当前行已是「条款号 + 标题」→ 用该号。
- 否则用**最近一行行首已印**的 `x.y.z`；中间若出现未印号的 HVDC / 低压功耗 / 热损失等 PEI 分节 → 仍空，不抄上一节。
- 正文未出现 `2.3.2` 标题时不得发明该号。未印号高压范围表条款仍空。
