# 2026-09-07 未印条款号时勿抄上一节，#8/#12 按接通/断开分节

- 状态：active
- 条目：#8 直流母线纹波电压要求；#12 高压安全-纹波电压；#21 低压功耗要求；#22 静态电流
- 闸门：`electrical/tests/test_extract_quality.py`（`test_ripple_from_generated_not_boost`、`test_ripple_clause_from_switched_on_off_rows`、`test_lv_clause_is_6_5_2_not_protection`、`test_lv_clause_from_table_after_protection_no_heading`）；`electrical/extract.py` `_HEADING_CLAUSE`、`_lock_field_semantics`

## 代价

DHTS160 专家第一版把 #8 和 #12 都写成条款 `2.3.3.3.4`（相对当时误绑 Boost 页的纠偏）。规则侧 #8 已对上 `2.3.3.3.3`，#12 值对但条款号常空；#21/#22 值对（18W@14V@WLTC、≤0.5mA）却挂上上一节 `6.4.2.4 Protection`，因为正文标题 `LV power consumption 低压功耗` 未印 6.5.2。

## 反事实

不按接通/断开分节、不把无编号的低压功耗标题映到 6.5.2，下次仍会：#12 条款空着或跟 #8 抢同一个号；#8 被改成专家随手写的 3.4；低压表跟在 Protection 后面就被填成 6.4.2.4。

## 二级依据

- 清单 gloss：#8 是峰值/额定工况纹波，排除电池连接/断开（→#12）；#12 才是电池连接/断开。
- 原文：`2.3.3.3.3 Generated voltage ripple` 是高压电池接通（额定 16 / 峰值 30）；`2.3.3.3.4 Generated voltage ripple UDC control` 是高压电池断开（30）。修订记录写「修改 6.5.2 低压功耗要求」，正文标题未印该号。
- 专家格子：#8/#12 印页 27–28 指向纹波正文（不是 Boost）；低压功耗/静态电流口径是 6.5.2，不是臆造 6.5.1。#8 不得改成 3.4。

## 闸门

- `_HEADING_CLAUSE`：关闭/switched off / UDC control → `2.3.3.3.4`；接通/switched on / `2.3.3.3.3 Generated voltage ripple` → `2.3.3.3.3`；`LV power consumption 低压功耗` / `未唤醒@仅低压上电` / `唤醒@IGBT开管` → `6.5.2`，但 `_pick_clause` 仅当当份 chunk/摘录含字面 `6.5.2`（修订记录即可）才采用，避免把 DHTS 目录套到 SuperEvo。
- 回归：纹波表无印号时 #8=`2.3.3.3.3`、#12=`2.3.3.3.4`；前文有 `6.4.2.4 Protection` 且片段含「修订记录：修改 6.5.2」时低压条款仍为 `6.5.2`。无 `6.5.2` 字样的 SuperEvo 低压片段条款留空。高压范围表抄 Protection 见 `2026-09-07-hvdc-range-is-not-protection-clause`。

