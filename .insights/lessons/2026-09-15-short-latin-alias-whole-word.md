# 2026-09-15 短缩写别名只认整词，不认子串

- 状态：active
- 条目：#76 EMC等级（RE/CE/CI/RI）；#13 绝缘电阻（IR）；#95 电机类型（IM）；#81 功能安全（STO）；#93 电机温度采样精度（NTC）；#10 母线直流电流检测（Idc）；#106 阻燃（V-1）；#17 Y电容
- 闸门：`tests/test_knowledge.py::KnowledgePublishTests::test_short_latin_alias_needs_whole_word`；`tests/test_knowledge.py::KnowledgeEvalTests`（题集 `docs/knowledge/eval/clause_routing.yaml` 的 `short-abbrev-noise`、`poles-rpm-not-speed`、`insulation-13`、`p3-efficiency-56`、`storage-humidity-99`）；`electrical_krow/knowledge.py` `_short_latin_hit`

## 代价

编认条召回题集时发现：`keyword_hits` 对折叠后的别名做子串匹配，`RE`/`CE`/`IR`/`IM`/`STO`/`NTC`/`cy` 这类 2–3 字母缩写会落在几乎任何英文句子里。`Req based on 8 poles and 16000 Rpm` 认到 #76 EMC，`Insulation resistance` 同时认到 #13 和 #76，`storage humidity` 拖进 #81 功能安全，`P3 efficiency` 拖进 #17 Y电容。这份索引正要导出给公司知识库做检索，误召回会直接变成错的命中卡片。

## 反事实

不给短拉丁缩写加整词边界，导出给公司知识库的 `keyword_index` / `query_aliases` 每句英文都会多带 #76、#13、#81、#95 等噪音条目；下游若按命中数或 +55 别名分排序，EMC 会常年排在前面，把真正的认条挤下去。只删这几个缩写又会丢掉 `EMC RE CE`、`NTC`、`Idc` 这类真实写法。

## 二级依据

- 条款词典 meta `alias_levels.strong`：强别名定义为「整词、跨条目唯一，可直接计分」，子串匹配违背了这一条。
- 清单 #76 EMC 等级的 RE/CE/CI/RI 是发射/抗扰缩写，只在 EMC 语境作为独立词出现；#13 的 IR、#95 的 IM、#81 的 STO 同理。
- 出表运行时不走 `keyword_hits`（`electrical` 侧按条款词典整词认条），故本次只影响 `electrical_krow.knowledge` 与导出包，不改核对表结果。

## 闸门

- `keyword_hits`：长度 ≤4 的纯拉丁/数字键改为 `(?<![a-z0-9])key(?![a-z0-9])` 整词匹配；中文与长别名保持折叠子串匹配。
- 题集 `short-abbrev-noise` 要求普通英文句子零召回；`emc-76`、`ntc-93` 保证真实缩写仍能命中。
- 导出包沿用同一索引；把题集交给公司知识库回归，他们的检索层若用子串或 n-gram 也会被同一批题抓出来。
