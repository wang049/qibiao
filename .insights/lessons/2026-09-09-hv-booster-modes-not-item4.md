# 2026-09-09 6.5.4 HV Booster 三种模式不是 #4

- 状态：active
- 条目：#3 驱动升压；#4 行车升压（充电范围）；#67 升压输出电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hv_booster_modes_fill_output_voltage_not_item4`）；`electrical/extract.py` `_hv_booster_output_voltage_from_modes` / `_value_fits_field`

## 代价

DHTS `6.5.4 HV Booster` 写的是 HVDC 较低时升压以改善 TM，同一节还有 Boost/bypass/BUCK 和 BUCK Max 85kW@200V-400V。规则把三种模式和 85kW 写成 #4「行车升压」，与 #3 抢同一节。充电定义若在 `Charging Buck/Boost`，#4 不该用升压器模式顶。

## 反事实

不把 6.5.4 三种模式改进行 #67、不让 #4 只认 Charging Buck/Boost / 充电升压/降压，下次仍会把 HV Booster 的 bypass/BUCK/85kW 填进充电范围格。不得用清单示例「否」或 85kW 顶替当份未给出的充电定义。

## 二级依据

- 当份 `6.5.4`：`boost the HV input … improve the TM performance` → #3。
- 清单 #67：升压输出电压范围及工作模式（Boost/Bypass/Buck）。
- 清单 #4 排除：三种模式 / BUCK 85kW（→#67）；boost control 产品说明（→#3）。充电拓扑/电压/电流/时长见 #115。交叉 `2026-09-08-item4-renamed-traction-boost`、`2026-09-09-item3-drive-boost-needs-conclusion`、`2026-09-04-115-connector-is-not-charge-definition`、`2026-09-11-item4-traction-boost-from-hv-input`。

## 闸门

- `_hv_booster_output_voltage_from_modes`：三种模式写入 #67（可带当份 450V、85kW），不写 #4。
- `_value_fits_field`：#4 拒值里的三种模式 / 单独 85kW；仍认 Charging Buck/Boost 与 6.5.4 HVDC/TM 结论。
- 回归：6.5.4 段 #3/#4 有 TM 结论，值中无 85kW；#115 空，#67 含 450 与三种模式。
