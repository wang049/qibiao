# 2026-09-07 Continuous HVDC 950V 不是绝缘耐电压

- 状态：active（DHTS 无 18488 时 #14 改认 Continuous HVDC，见 `2026-09-21-hipot-clause-printed-663`）
- 条目：#14 / #19 高压安全-耐电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_hipot_clause_iso6469_stays_on_printed_section`、`test_continuous_supply_500v_is_not_dielectric`）；`electrical/extract.py` `_dielectric_score` 18488 > Continuous HVDC；「不得产生」/ 无标题的 continuous supply 仍拒填

## 代价

SuperEvo 有 GB/T 18488 表1 时，用 Continuous HVDC 950V 或「不得产生 950VDC」顶掉工频耐压。DHTS 无 18488 时的配对见 `2026-09-21-hipot-clause-printed-663`。

## 反事实

不让 18488 优先于 950V 连续耐压、不把「不得产生」挡在门外，下次 SuperEvo #14 仍会变成母线持续供电上限。

## 二级依据

- SuperEvo：`耐电压要求（电控）` 写 GB/T 18488-2024 表1、1min、≤5mA；同份 Continuous HVDC 是 950V 母线持续供电。
- 「不得产生高于 / Maximum allowed generated HVDC」是发电上限，不是耐电压试验。

## 闸门

- `_dielectric_score`：18488 > Continuous HVDC；无标题的 continuous supply、「不得产生」仍拒填。
- 回归：18488 与 Continuous HVDC 同段时填 18488，条款不得为 6.6.3。
