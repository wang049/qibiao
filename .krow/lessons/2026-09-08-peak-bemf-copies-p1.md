# 2026-09-08 #11 反电动势峰值可引用当份 P1 反电势

- 状态：active
- 条目：#11 反电动势峰值；#37 P1反电动势（Back EMF）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_peak_bemf_copies_p1_when_blank`、`test_back_emf_table_skips_shown_in_hv_safety_cite`、`test_superevo_rules`）；`electrical/extract.py` `_fill_peak_bemf_from_motors`、P1 Back EMF 表同时 `add` #11

## 代价

规格只印 `P1 Back EMF | Vdc | …`，#37 已填，#11 总条目标「未检索到」。现场按总项核对会以为反电势没写。

## 反事实

不在 P1 反电势表写入 #11、出表结束时空着的 #11 不引用当份 #37，下次仍会：P1 有 1200V/#37 已检索到，总项空白。不得用清单示例 820Vpp 补格，也不得把 P3 1400V 盖过已抽出的 P1。

## 二级依据

- 清单 gloss：#11 是总条目，P1/P3 各有子项；句中含 P1→#37，本条空时引用当份已出现的 P1 反电势。
- SuperEvo 电机表：`P1 Back EMF(@peek speed@20℃)` 反电势＜1200V@16500rpm。交叉 `2026-09-07-shown-in-hv-safety-is-not-back-emf-clause`（表值不是 HV safety 指向号）。

## 闸门

- `_fill_peak_bemf_from_motors`：#11 空白时复制当份 P1 反电势；P1 无电压才用 P3。
- P1 Back EMF 表规则同时写入 #11。
- 回归：表值 1200V 进 #11；#11 不写 1400V；仅有 P1 时总项不再空白。
