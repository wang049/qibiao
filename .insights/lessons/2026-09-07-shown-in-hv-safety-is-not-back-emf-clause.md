# 2026-09-07 「详见 2.3.12.2 HV safety」不是反电势表条款

- 状态：active
- 条目：#37 P1反电动势（Back EMF）；#54 P3 反电动势（Back EMF）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_back_emf_table_skips_shown_in_hv_safety_cite`）；`electrical/extract.py` `_is_external_clause_cite`、`_UNNUMBERED_PEI_HEADING`、`_attach`

## 代价

SuperEvo 电机参数表已给出 P1＜1200V@16500rpm、P3＜1400V@20000rpm，条款列却写成 `2.3.12.2`。现场按该号打开，看到的是瞬态脉冲「详见 HV safety」，不是反电势表。

## 反事实

不把 `as shown in` / `详见…HV safety` 当外部引用跳过、不把未印号的「反电动势导致的过压」当分节、数值表赢了定性句时仍接手条款号，下次仍会把高压安全章的指向号挂到 #37/#54。

## 二级依据

- SuperEvo 反电势抽出值来自电机参数表 `P1/P3 Back EMF(@peek speed@20℃)`，该表未印条款号。
- 正文 `as shown in 2.3.12.2` / `详见2.3.12.2 HV safety 高压安全章节` 是瞬态脉冲对高压安全章的指向，不是反电势表所在节。
- 其后未印号标题 `Overvoltage due to generated back-emf反电动势导致的过压` 只要求开关承受反电势最大值，没有印出 1200V/1400V。交叉 `2026-09-07-no-printed-652-no-external-5310`（引用号不是本份章节）。

## 闸门

- `_is_external_clause_cite`：跳过 `as shown in` / `shown in` / `see section|chapter|clause` / `详见`。
- `_UNNUMBERED_PEI_HEADING` 含 `Overvoltage due to generated back-emf` / `反电动势导致的过压`；命中点在该节时条款留空。
- `_attach`：反电势格已是 `xxxV` 表值时，不得从无电压的定性过压句接手条款号。
- 回归：电机表 1200V/1400V 已检索到，条款不是 `2.3.12.2`、且为空。
