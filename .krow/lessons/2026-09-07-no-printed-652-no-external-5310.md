# 2026-09-07 未印 6.5.2 不得套目录；5.3.10 引用不是本份条款

- 状态：active
- 条目：#21 低压功耗要求；#22 静态电流；冷却接口；#5/#6/#7 高压电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_superevo_lv_does_not_invent_6_5_2`、`test_cooling_skips_external_5_3_10_and_guiding_pins`、`test_hvdc_range_beats_pcm_busbar`、`test_lv_clause_is_6_5_2_not_protection`）；`electrical/extract.py` `_pick_clause`、`_is_external_clause_cite`、`_UNNUMBERED_PEI_HEADING`、`_scrub_drive_boost_if_charge_spec`

## 代价

把 DHTS 目录里的 `6.5.2` 套到 SuperEvo 未印号的 `LV power consumption` 上；把「参考 Q/JLY … 的 5.3.10」粘到冷却格；`Cooling connections` 抄上一节 `6.2.1.5 Guiding pins`。高压范围表（冷启动 530 / 满功率 800–1066 / 限制最高 1125）被 PCM 母线 530–1150 / 1150 线性降额压过。PCM 产品说明 `boost control` 在已有 Charging Buck/Boost 时仍把驱动升压写成「是」。

## 反事实

不要求当份字面出现 `6.5.2`、不跳过「参考…的 5.3.10」、不把 Cooling connections 当未印号分节、不让 HVDC 电压表压过母线表、不在充电规格同份时清掉 boost control→驱动升压，下次仍会条款串号、#5/#6/#7 过满、#3 把充电 Boost 当成驱动升压。

## 二级依据

- SuperEvo 全文无 `6.5.2`、无 `6.6.3`。DHTS 才因修订记录写过 6.5.2 而映低压表。交叉 `2026-09-07-ripple-lv-unnumbered-headings`。
- 「参考 Q/JLY J7110218D-2025 的 5.3.10」是扭矩精度企标引用，不是本份冷却章节。
- `6.2.1.5` 正文是定位销；下一节标题 `Cooling connections冷却连接` 未印号。
- 高压范围表优先于 PCM 母线工作电压范围。交叉 `2026-09-07-hvdc-range-is-not-protection-clause`。
- #3 驱动升压 ≠ #4 充电升压。扫描稿无充电标题时 `boost control` 仍可填驱动升压（`test_scan_env_and_boost_scope`）。

## 闸门

- `_pick_clause`：implied `6.5.2` 仅当 chunk/摘录含字面 `6.5.2`。DHTS 测试片段须带修订记录。
- `_is_external_clause_cite`：跳过「参考/Q/JLY/GB/T/的 5.3.10」。
- `_UNNUMBERED_PEI_HEADING` 含 Cooling connections；命中点在该标题行时条款留空。
- HVDC 表 `add` 置信度 0.93，母线表 0.84；`_working_v_score` / `_derate_score` 偏好冷启动与 1125。
- `_scrub_drive_boost_if_charge_spec`：同份有 Charging Buck/Boost 时清掉仅来自 boost control 的 #3。
- 回归：无 6.5.2 的低压片段条款空；冷却条款不是 5.3.10/6.2.1.5；HVDC 表压过 530–1150；充电同份时 #3 空。
