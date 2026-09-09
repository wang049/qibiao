# 2026-09-09 P3 逆变器效率要收综合/区间，不抄 P1 平均

- 状态：active
- 条目：#56 P3逆变器效率指标；#41 P1逆变器效率指标
- 闸门：`electrical/tests/test_extract_quality.py`（`test_p3_efficiency_reads_combined_not_p1_average`、`test_p3_efficiency_does_not_copy_p1_average_when_p3_has_max_only`、`test_expert_marked_fields`）；`electrical/extract.py` `_dhts_inverter_eta_parts`、`_value_fits_field`；`tests/test_clause_lexicon.py`（`test_p3_efficiency_excludes_p1_average`）

## 代价

#56 只写出「最高效率＞99%」。清单要最高效率、区间效率和测试边界。P3 节自己有三个工况区间和加权综合效率，规则窗口停在最高效率句，平均/区间没进格。

## 反事实

不把 P3 窗口做到综合效率句、不闸掉把 P1「平均效率至少 98.2%」抄进 #56，下次仍会：#56 只有最高；或把 6.8.4.1 的平均填进 P3。不得用清单示例 99%/98% 顶替当份区间和综合效率。

## 二级依据

- 清单 #56 gloss：最高效率、区间效率及测试边界（母线电压/扭矩/转速）。排除 P1 平均效率（→#41）、升压效率（→#66）。
- DHTS 6.8.4.2：最高＞99%；区间 1/2/3 @340V；综合效率 ≥98.25%@340V。6.8.4.1 的 Average 98.2% 只属于 #41。

## 闸门

- `_dhts_inverter_eta_parts`：从 6.8.4.2 起切条款窗口，P3 收最高、区间、综合；P1 收最高和当份平均。
- `_value_fits_field`：#56 不得只带 P1 的 98.2%、不得用 6.8.4.1 摘录。
- 回归：P3 抽出值含 98.25 和区间 1，不得出现未跟 5 的 98.2；P3 节只有最高时不得抄 P1 平均。
