# 2026-09-10 逆变器效率要最高也要区间/平均，2.3.2 表两行合并

- 状态：active
- 条目：#41 P1逆变器效率指标；#56 P3逆变器效率指标（核对表序号 37 / 52）
- 闸门：`electrical/tests/test_extract_quality.py`（`test_pcm_table_eta_keeps_max_and_interval`，并保留 `test_p3_efficiency_reads_combined_not_p1_average`）；`electrical/extract.py` `_iter_pcm_table_eta`、`_join_inverter_eta`、`_value_fits_field`、`_better`

## 代价

DHTS160 的 6.8.4.1 / 6.8.4.2 已经能抽出最高+平均、最高+区间/综合。4LDHT260 / SuperEvo 把同一件事写在 2.3.2 性能表两行：`PCM maximum efficiency` 和 `PCM Px efficiency / 区间效率`。规则只认最高那一行，`_better` 再按分数选边，区间行把最高盖掉或最高把区间盖掉。14:10 的 4LDHT 核对表 #37/#52 只剩 ≥99.5% / ≥99.9%。

## 反事实

不抽 2.3.2 的 `PCM P1/P3 efficiency`（区间效率）行、仍让最高与区间互斥覆盖，下次 4LDHT260 / SuperEvo 仍只有最高效率。若把 DHTS 的 98.2% 平均或清单示例填进 P3，会再次踩 `2026-09-09-p3-eta-combined-not-p1-average`。当份 OCR 若没有区间句，最高可留，不得用别份数字补。

## 二级依据

- 清单 #41 / #56 gloss：至少最高效率、区间效率及测试边界（母线电压/扭矩/转速）。#56 排除 P1 平均（→#41）。
- 4LDHT260 扫描件印页 23：最高 `P1:≥99.5%; P3:≥99.9%`；P1 区间 `-40 ~ -80Nm@4000-8000rpm ≥98.5%`；P3 区间1/2/3 + 总考核目标效率≥97.67%。
- DHTS160 6.8.4.1 平均 98.2%、6.8.4.2 综合 ≥98.25%@340V：已有闸门，本篇不回退。

## 闸门

- `_iter_pcm_table_eta`：只在 `PCM Px efficiency / 区间效率` 表方言下抽区间行；不把 DHTS `P1逆变器效率` 标题当区间表。
- `_join_inverter_eta` / `_better`：同格合并最高与区间，P3 仍丢掉未跟 5 的 98.2%。
- 回归：SuperEvo 表 P1 含 99.5 且 98.6/单挡，P3 含 99.8 且区间1；4LDHT OCR P1 含 99.5 且 98.5，P3 含 99.9、区间1、97.67；P1 不得收 96.9/总考核，P3 不得收 P1 的 −40Nm 带。
