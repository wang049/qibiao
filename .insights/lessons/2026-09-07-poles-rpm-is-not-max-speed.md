# 2026-09-07 极对数×转速不是最高工作转速定义

- 状态：active
- 条目：#35 P1最高工作转速；#52 P3最高工作转速
- 闸门：`electrical/tests/test_extract_quality.py`（`test_poles_rpm_is_partial_not_max_speed`、`test_explicit_max_speed_table_is_found`、`test_llm_high_conf_cannot_upgrade_poles_or_connector`）；`electrical/extract.py` `_lock_field_semantics`；`finalize_retrieval_statuses` 不得把局部对应抬成已检索到

## 代价

DHTS160 `6.5.7.5` / `6.5.8.5` 写的是交流基频满性能假设（`Req based on 8 poles and 16000/20000 Rpm`），不是转速表。规则把 P3 的 20000 标成已检索到；P1 的 16000 整格空着。专家第一版对 #35 是局部对应、置信度偏低。

## 反事实

不把 `8 poles and 16000/20000` 降成局部对应，下次仍会把基频假设当成最高工作转速定义；裸 `Max 20000` 若再以 0.82 无备注入库，会盖过局部对应。明确转速表（`the max speed of Pl@640V`）若被一起降级，又会漏掉真定义。

## 二级依据

- 清单 gloss：#35/#52 是 P1/P3 最高工作转速；排除反电势@rpm 里的 rpm，勿当最高转速。
- 原文：`AC Fundamental frequency PEI P1/P3` — `Req based on 8 poles and 16000/20000 Rpm, … full performance in the following range of the fundamental electrical frequency`。
- 专家格子：#35 16000 局部对应；转速表写法（最高转速/随转/出电功率）才标已检索到。

## 闸门

- `8 poles and 16000/20000`：值可保留，confidence 0.72 + 备注「交流基频满性能假设」→ 局部对应。
- `the max speed of P1/P3`、随转/出功率表：仍已检索到，不得被极对数行覆盖。
- 交流基频附近的裸 `Max 20000` 不得把 #52 抬成已检索到。
