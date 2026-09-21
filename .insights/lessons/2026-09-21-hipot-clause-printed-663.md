# 2026-09-21 DHTS #14 的 6.6.3 是连续高压直流耐压

- 状态：active
- 条目：#14 高压安全-耐电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_continuous_hvdc_withstand_is_dielectric_663`、`test_continuous_hvdc_body_without_heading_still_stores`、`test_dielectric_prefers_continuous_hvdc_over_iso6469`、`test_hipot_clause_iso6469_stays_on_printed_section`）；`electrical/extract.py` `_is_continuous_hvdc_withstand` 认正文句，扩句丢掉标题后仍进 #14

## 代价

把 DHTS #14 写成 ISO 6469-3 工频（1min、50–60Hz、(2U+1000) VAC）。规则已抽到 500V 连续耐压，扩句丢掉 `Continuous HVDC` 标题后被当成工作耐压扔掉，6.10.3.2 工频又填回去。6.6.3 正文是母线最大 500V 连续供电、无永久性损坏、ISO 16750-1 最低 C。

## 反事实

条款号 6.6.3 却填 ISO 6469，或继续用 6.10.3.2 工频顶掉 500V 连续耐压，下次 DHTS 格文与条款对不上。有 GB/T 18488 表1 的 SuperEvo 若也改成 6.6.3/950V，又会盖掉当节 6.9.3.2 工频。

## 二级依据

- 当份 6.6 节第三段：`Continuous HVDC withstand voltage 连续高压直流耐压`，`maximum 500V on the HVDC bus without any permanent damages`，`功能状态等级应为最低C`（ISO 16750-1）。
- 同份 ISO 6469-3 工频写在 `6.10.3.2 HV insulation`，不是 6.6.3。
- SuperEvo 印出 `6.6.3 Continuous HVDC`（950V），但 #14 有 18488 时仍用当节 6.9.3.2。交叉 `2026-09-07-continuous-hvdc-is-not-dielectric`（18488 优先；「不得产生」不是本格）。

## 闸门

- 无 18488 时，`Continuous HVDC withstand voltage` + 最大 nV + 无永久性损坏 → #14，条款号 6.6.3。
- 同段再有 ISO 6469 1min 也不改填工频。
- 仅有 ISO 6469 时条款号用当节（如 6.10.3.2），不改成 6.6.3。
- 18488 表1 已填时不覆盖；`_dielectric_score` 18488 > Continuous HVDC > ISO 6469。
