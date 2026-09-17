# 2026-09-11 #4 行车升压要从 6.5.4 HVDC/TM 结论写出

- 状态：active
- 条目：#4 设计范围是否包含行车升压功能（核对表序号 4）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hv_booster_modes_fill_output_voltage_not_item4`、`test_drive_boost_scope_writes_conclusion`、`test_item4_prefers_charging_buck_over_hv_input`、`test_scan_env_and_boost_scope`）；`electrical/extract.py` `_value_fits_field` / `_item4_scope_score`

## 代价

DHTS160 核对表第 4 行「设计范围是否包含行车升压功能」写成未检索到。同份 `6.5.4` 已写：HVDC 较低时把高压输入升到更高电压，以改善 TM 性能；第 3 行驱动升压已抽出该结论。旧闸门只认 `Charging Buck/Boost`，DHTS 没有充电升压/降压章，第 4 行就空。三种模式和 BUCK 85kW 仍不能进第 4 行。

## 反事实

不让 6.5.4 的 HVDC/TM 结论写入 #4，下次 DHTS 第 4 行仍空，对表的人会当成漏抽。若把 Boost/bypass/BUCK 或 85kW 填进 #4，又会和 #67 抢同一节。boost control 产品说明仍不得进 #4。同份已有 Charging Buck/Boost 时，充电范围判断优先于 HVDC/TM 句。

## 二级依据

- 用户核对表 `DHTS160_DPR_2026年09月11日15：42：35.xlsx` 序号 4：未检索到。
- 当份 `6.5.4`：`boost the HV input … improve the TM performance`。清单正式名 #4「行车升压」。交叉 `2026-09-09-hv-booster-modes-not-item4`（三种模式仍进 #67）、`2026-09-09-item3-drive-boost-needs-conclusion`、`2026-09-08-item4-renamed-traction-boost`。

## 闸门

- 命中 shall boost HV input 时，#3 与 #4 都写「是；HVDC…以改善 TM 性能」。
- `_value_fits_field`：#4 认该结论；值里的三种模式 / 85kW 仍拒；boost control 仍拒。
- 同份 Charging Buck/Boost 与 6.5.4 并存时，#4 保留「是（含充电 Boost/Buck 功能）」。
- PCM 仅写 boost control 的扫描稿仍不填 #4。
