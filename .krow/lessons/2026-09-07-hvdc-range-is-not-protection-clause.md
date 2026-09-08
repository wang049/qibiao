# 2026-09-07 HVDC 电压表不是 6.4.2.4 Protection

- 状态：active
- 条目：#5 直流工作电压范围；#6 满功率(电流)工作电压；#7 降额工作电压范围
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hvdc_voltage_clause_not_protection`、`test_printed_hvdc_range_clause_is_kept`）；`electrical/extract.py` `_clause_for_index`、`_lock_field_semantics`

## 代价

#5/#6/#7 抽出值来自 `HVDC Voltage Range 高压范围` 表，条款列却写成 `6.4.2.4`。现场按条款号打开 Protection 节，看不到电压表。

## 反事实

不拦更近的未印号 PEI 标题、不把 `6.4.2.x` 从高压电压格清掉，下次仍会把上一节 Protection 条款号挂到高压范围表上；也不得把未印号的标题臆造成 6.5.3。

## 二级依据

- 用户格子：#5/#6/#7 条款 `6.4.2.4`，现场在该节对不上电压表。
- 当份 Word：`6.4.2.4` 正文是 Protection 保护；高压范围标题是 `HVDC Voltage Range 高压范围`，未印条款号。修订记录只写了 6.5.2 低压功耗、6.5.4 BOOST。
- 既有复盘：`2026-09-07-ripple-lv-unnumbered-headings`（低压表同样抄 Protection）。印在标题上的 `6.5.3 HVDC Voltage Range` 仍应保留。

## 闸门

- `_clause_for_index`：上一节号与命中点之间若有未印号的 PEI 分节标题（HVDC/LVDC Voltage Range、低压功耗、HV Booster、Cooling connections 等），或命中点就在该标题行上，条款列留空，不沿用 Protection / Guiding pins。
- `_pick_clause` / `_lock_field_semantics`：#5/#6/#7 摘录是高压范围表时，拒绝 `6.4.2.x` 和低压功耗的 `6.5.2`（扩句带上未唤醒行时也不改挂）。
- `_working_v_score` / `_derate_score`：HVDC Voltage Range（冷启动、限制最高 1125）压过 PCM 母线 530–1150 / 1150 线性降额。
- 回归：前文 `6.4.2.4 Protection`、后接未印号高压范围表 → 三格条款空、不得为 6.4.2.4；标题印了 `6.5.3 HVDC Voltage Range` → 仍为 6.5.3；SuperEvo 同时有母线表和高压范围表时取冷启动/1125。印在标题上的 `6.5.3 HVDC Voltage Range` 仍应保留。

