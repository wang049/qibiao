# 2026-09-21 shall 不是 Boost 输出性能；P3 10s 不在功率行；寿命摘录不是页脚

- 状态：active
- 条目：#61 Boost输出性能；#42 P3峰值功率持续时间；#64 升压输出功率；#103 寿命要求
- 闸门：`electrical/extract.py` `_value_fits_field` / `_is_junk_value`（shall 无电压拒 #61）；`_duration_on_peak_power_row` 截到峰值扭矩前；充电功率认无竖线、`kW\@`；页脚 `Motor/Gearbox Same Content` 不得当寿命摘录；`electrical/tests/test_extract_quality.py` `test_boost_output_performance_rejects_efficiency_block`、`test_booster_target_voltage_fills_output_performance`、`test_p3_duration_not_from_next_torque_row`、`test_charging_power_escaped_at_still_fills`、`test_life_excerpt_is_not_page_footer`

## 代价

`DHTS160_DPR_2026年09月21日10：03：32.xlsx` #61 把 `The XCM shall be able to boost the HV input voltage…` 标已检索到；同表 6.5.4 已有 `Target output voltage of booster | 450 | V`。`SuperEvo_1000V__DPR_2026年09月21日10：23：59.xlsx` #42 写成 10s，摘录已带出下一行 `P3 peak torque (@480A@10s`；#64 空着，当份充电功率行是 `250A/100kW\@400V 50min；250A/180kW\@720V 30min`。逆变器 SR #103 值对，摘录是页脚 `Motor/Gearbox Same Content`。

## 反事实

- 不拒 shall：`_value_fits_field("Boost输出性能")` 只要摘录有 `boost` 就过，下次 #61 继续整句功能描述。
- 用规则写死 450 V、不从「升压器的目标输出电压」取值：回到堆专家稿。
- `_peak_power_row_window` 仍向后看两行：Markdown 同行粘了扭矩 `@10s`，#42 继续过满。
- 充电功率只认 `充电功率 |`：Word 折行或 `kW\@` 时 #64 继续空。
- 不刮页脚摘录：寿命格值对、人对表看到的是套话。

## 二级依据

- DHTS 6.5.4：`Target output voltage of booster / 升压器的目标输出电压 | 450 | V`。shall 句是「能否升压」，清单 #61 要输出侧电压/功率。交叉 `2026-09-16-boost-output-performance-not-efficiency`。
- SuperEvo 2.3.2：`P3 peak drive power | ≥300kw @800V` 无时长；`@10s` 在 `P3 peak torque (@480A@10s@870V)`。交叉已有 `test_p3_duration_not_from_peak_kw_only`。
- SuperEvo 充电表第 8 行：`250A/100kW@400V 50min；250A/180kW@720V 30min`。交叉 `2026-09-07-charge-boost-table-fills-ripple`。
- 逆变器 p41：`2.2.3 Product Life Item Warranty Life Target : 15 years 300,000 km`；`Motor/Gearbox Same Content` 是页脚。

## 闸门

- `_value_fits_field("Boost输出性能", shall 整句, shall 整句)` 为 False；`450 V` + 目标输出电压行仍为 True。
- `_value_fits_field("P3峰值功率持续时间", "10s", 功率行+扭矩@10s)` 为 False。
- `充电功率\\n250A/100kW\\@400V 50min；250A/180kW\\@720V 30min` 规则抽出含 100kW/180kW。
- 寿命格摘录不得只剩 `Motor/Gearbox Same Content`。
