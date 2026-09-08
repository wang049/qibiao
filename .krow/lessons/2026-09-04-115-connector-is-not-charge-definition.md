# 2026-09-04 #115 高压慢充连接器不是升压充电定义

- 状态：active
- 条目：#115 升压充电功能
- 闸门：`electrical/tests/test_extract_quality.py`（`test_expert_marked_fields`、`test_charge_boost_fn_*`、`test_llm_high_conf_cannot_upgrade_poles_or_connector`）；`electrical/extract.py` `_lock_field_semantics` 连接器保持局部对应，Charging Buck/Boost 优先

## 代价

DHTS160 把 `6.2.3.6 高压慢充连接器` 填进 #115，置信度 0.82、无备注，核对表标成「已检索到」。认条对，取值过满：连接器只证明有充电接口。

## 反事实

不把连接器降成局部对应、不让 Charging Buck/Boost 标题压过连接器，下次仍会把「有接口」当成「充电定义已齐」，专家按拓扑/电压/电流/时长核对时会判过满。三种 Boost/bypass/BUCK 若再写入 #115，会和 #4 串列。

## 二级依据

- 清单 gloss：是否需要升压充电，以及充电拓扑、电压、电流、时长；排除驱动升压（→#3）。
- 专家口径：关键在充电的定义，不在「有没有连接器」。
- 原文：`6.2.3.6` 是接口；`Charging Buck/Boost Function Requirements` /「充电升压/降压功能需求」才是功能定义。

## 闸门

- 只命中连接器：抽出值可保留「有高压慢充连接器」，confidence 0.72 + 备注 → 局部对应/需人工复核。
- 有 Charging Buck/Boost 标题：#115 用该定义，连接器不得覆盖。
- 三种工作模式不写入 #115。
- 回归：含「慢充」、不含「三种」；连接器场景 PARTIAL；定义标题场景 FOUND。
