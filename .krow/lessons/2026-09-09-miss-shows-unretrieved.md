# 2026-09-09 没检索到就显示未检索到

- 状态：active
- 条目：#72 最大散热能力；#99 存储相对湿度；企标已挂方法号的其他空项
- 闸门：`electrical/tests/test_extract_quality.py`（`StdRefWhenDprMissingTests`）；`electrical/tests/test_review_table.py`（`test_std_ref_miss_displays_unretrieved`）；`electrical/tests/test_retrieval_status.py`（`test_method_note_without_value_stays_miss`）；`electrical/extract.py` `_fill_std_ref_when_dpr_missing`；`electrical/schema.py` `finalize_retrieval_statuses`

## 代价

空项抽出值写成「参考 Q/JLP 030600-11」并标局部对应。专家对表时把它当成已给出的规格，核对状态也不是未检索到。

## 反事实

不把空项抽出值和核对状态改回未检索到、仍把方法号写进抽出值，下次 #72/#99 仍显示「参考 标准号」橙底局部对应。不得用 6.17 kW / 8000 小时 / 13.5 V 填格。

## 二级依据

- 专家：没检索到的时候就显示没检索到。#72 最大散热能力、#99 存储相对湿度当份 DPR 未给出。
- 清单 #72/#99：抽出值来自当份；企标 7.3 / 6.22 只是试验方法对照。交叉 `2026-09-08-enterprise-std-is-method-not-fill`。取代 `2026-09-09-std-ref-empty-writes-method`、`2026-09-08-std-ref-partial-when-dpr-missing`。

## 闸门

- `_fill_std_ref_when_dpr_missing`：空格不写抽出值，状态未检索到；方法号只进复核备注「企标方法对照」。
- `finalize` / 出表：空值加企标方法备注不得抬成局部对应；抽出值列显示「未检索到」黄底。
- 回归：#72/#99/#13 抽出值为空、状态未检索到、备注含方法号、不得出现 6.17 / 8000；已有当份值不覆盖。
