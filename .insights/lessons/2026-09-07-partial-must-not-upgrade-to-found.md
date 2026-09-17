# 2026-09-07 规则标了局部对应，不得抬成已检索到

- 状态：active
- 条目：#35 P1最高工作转速；#52 P3最高工作转速；#115 升压充电功能；#21 低压功耗要求；#22 静态电流
- 闸门：`electrical/tests/test_extract_quality.py`（`test_llm_high_conf_cannot_upgrade_poles_or_connector`、`test_lv_clause_from_table_after_protection_no_heading`）；`electrical/tests/test_retrieval_status.py` `test_finalize_does_not_upgrade_partial`；`finalize_retrieval_statuses` 遇 PARTIAL 直接保留；`_lock_field_semantics`

## 代价

第二版 DHTS160：#35/#52 摘录仍是 `8 poles and 16000/20000`，却标已检索到（0.85/0.9）；#115 仍是「有高压慢充连接器」已检索到 0.82；#21/#22 值对，条款挂 `6.4.2.4 Protection`。先前规则已 `add(..., PARTIAL)`，被同值更高置信度覆盖后 `finalize` 抬成已检索到。

## 反事实

不定稿时保留局部对应、不按条目锁条款，下次仍会：基频假设当最高转速、连接器当充电定义、低压表抄上一节保护条款号。

## 二级依据

- 专家格子：#35/#52 局部对应、置信度偏低；#115「关键在充电定义」；#21/#22 条款 6.5.2。
- 既有复盘：`2026-09-07-poles-rpm-is-not-max-speed`、`2026-09-04-115-connector-is-not-charge-definition`、`2026-09-07-ripple-lv-unnumbered-headings`。

## 闸门

- `finalize_retrieval_statuses`：已是局部对应则不得改成已检索到。
- `_better`：抽出值折合相同、一侧已是局部对应 → 保留局部对应。
- `_lock_field_semantics`：极对数句、慢充连接器、低压表（条款 6.5.2）、断开纹波（条款 2.3.3.3.4）、高压电压表拒绝 6.4.2.x。
- 回归：规则填完再叠 0.82–0.9 无备注格子，#35/#52/#115 仍局部对应；无「低压功耗」标题、前文是 `6.4.2.4` 时 #21/#22 条款仍为 6.5.2。
