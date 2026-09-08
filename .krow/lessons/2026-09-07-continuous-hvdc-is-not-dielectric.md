# 2026-09-07 Continuous HVDC 950V 不是绝缘耐电压

- 状态：active
- 条目：#14 / #19 高压安全-耐电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_continuous_hvdc_withstand_is_not_dielectric`、`test_dielectric_prefers_insulation_hipot_not_continuous_hvdc`）；`electrical/extract.py` `_looks_like_operating_voltage_withstand`、`_dielectric_score` 对 Continuous HVDC 减分，禁止臆造条款 `6.6.3`

## 代价

把 `Continuous HVDC withstand voltage 连续高压直流耐压`（母线持续供电最大 950V / 500V、无永久性损坏）填进绝缘耐电压，并硬编码条款 6.6.3。SuperEvo 当份没有 6.6.3；真耐压是 GB/T 18488 表1、1min、无击穿、漏电流≤5mA。

## 反事实

不把 Continuous HVDC / 「不得产生 950VDC」当 hipot、不删 6.6.3 标题映照，下次仍会用工作耐压顶掉 18488/ISO 6469 工频耐压，并给未印号的标题发明条款号。

## 二级依据

- 清单 gloss：#14/#19 是绝缘耐电压（工频/直流 hipot、漏电流、击穿），不是 HVDC 母线持续供电上限。
- SuperEvo：`耐电压要求（电控）` 写 GB/T 18488-2024 表1、1min、≤5mA；Continuous HVDC 是 950V 母线持续供电。
- 当份全文无 `6.6.3`。印了 `6.10.3.2` / ISO 6469 1min 的才是耐压条款。

## 闸门

- Continuous HVDC 标题不再 `add()` 耐电压格；`_looks_like_operating_voltage_withstand` 视为工作耐压并拒填。
- `_HEADING_CLAUSE` 不再把该标题映成 `6.6.3`。
- `_dielectric_score`：Continuous HVDC −12，18488/漏电流/工频 +6。
- 回归：仅 Continuous HVDC 段时 #14 空；与 ISO 6469 1min 同段时填 ISO 6469，条款不得为 6.6.3。
