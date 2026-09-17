# 2026-09-16 选段按空缺找，失败段拆半重试

- 状态：active
- 条目：#18 低压电源电压范围、#19 低压功耗、#20 静态电流、#21 备份电源、#69/#97 重量、#70/#98 防腐、#71 振动、#103 寿命、#1 OD 集成（DHTS160 仅模型路径漏项）
- 闸门：`electrical/tests/test_extract_quality.py::test_select_chunks_by_gap_reaches_general_requirement_pages`、`test_short_latin_alias_only_whole_word_in_coverage`、`test_token_strength_prefers_value_bearing_page`；`electrical/tests/test_doc_qa.py::SplitRetryTests`；`electrical/README.md` 泛化体检基线

## 代价

DHTS160 DPR 专家认可版 116 条里 115 条来自原文规则。关掉规则只走「词典认条 → 分段模型」（新文档会走的路），96/116：0 错填、17 漏、3 表格列缺失。说明页写着 8 个分段识别失败。漏的都在第 2/4/5 章「通用要求」（重量、寿命、防腐、振动、低压电源），24 万字只送 14 段，`_select_chunks` 按电压/电流/功率词打分，这些章永远排不进前 14。

## 反事实

- 不改选段而加段数：14 → 28 段模型调用翻倍、时间翻倍，通用要求页在旧打分下依然靠后，多出的段大多是重复的 HVDC 表格。
- 只改打分权重把「振动/寿命」加进 `_KEEP_PAGE`：又是为 DHTS 一份文档写词，下一份规格书换了写法照样漏。
- 不做拆半重试：8 段失败即 8 段原文对模型不存在，这些段里正好有低压表（18W、0.5mA、KL30）。

## 二级依据

- `.insights/AGENTS.md`：出表路径是「规则先填 → 空缺项分段」，空缺项才是分段要服务的对象，选段应以空缺为纲而非以性能词为纲。
- 条款词典 meta `alias_levels.strong`：强别名整词唯一可直接计分，因此可拿来判定「这一页给不给某条目值」；`RE/IR/OD` 短缩写沿用 2026-09-15 整词规则。
- `electrical/README.md` 泛化体检：仅规则 vs 仅模型的差就是新文档会掉的分，任何选段改动都用同一命令回归。

## 闸门

- `_select_chunks(markdown, max_chunks, rows)`：传 rows 时对空缺条目做贪心覆盖，收益 = Σ(条目命中强度提升)，强度 2 = 别名旁有数字单位或在标题行，1 = 顺带提及；不传 rows 保持旧行为。DHTS160 有段可读条目 92 → 99，强命中 85 → 96，段数不变。
- `run_batch` 对 `_parse_failed` 且 ≥1800 字的段调用 `_split_chunk_halves` 在页标/标题/空行处切半重试一次，两半各自重算空缺条目；两半再失败才计入 `chunk_failures`。
- 「六条别名为空」的判断错了一半：词典里这六条的别名都在 `weak_aliases`（#73/#101、#74/#102、#78/#89 两两同槽共享，按 `alias_levels.strong`「跨条目唯一」的定义进不了 strong），是 `electrical` 侧只读 `aliases` 把弱别名整层丢了。词典不改；`FieldSpec` 新增 `weak_aliases` / `unit_cues`，找页（`_block_covers`）和 prompt 认条（`_chunk_fields`）用上弱别名，prompt 别名提示仍只给强别名，取值仍只认当份原文。`质量 / 涂层 / 表面处理 / weight / mass` 这类不含条目核心字的弱别名由 `_capped_weak_tokens` 压到「顺带提及」，避免 IATF 质量体系页冒充重量页。闸门 `test_weak_aliases_let_weight_and_corrosion_pages_be_found`。
- 泛词闸门：`_shared_coverage_tokens` 把 3 条以上条目共用的针（P1 / P3 / BOOST / 升压 / 纹波…）排除在覆盖依据外。反例已出现：生产态 2026-09-16 10:12 那次，`Boost` 在 2.3 零件号表里挨着数字，把 #61 记成已覆盖，真正的 6.5.4 升压页被挤掉，450 V 漏填；修后复现选段 6.5.4 回到第 2 段。
- 名额闸门：覆盖贪心最多占 2/3，性能词打分至少留 1/3，`test_select_chunks_by_gap_reaches_general_requirement_pages` 同时要求通用要求页进段、已填条目不再找段。
- 超时口径：CLI `DEFAULT_TIMEOUT` 90 → 180 s 与工位一致。仅模型基线里 8 段失败是 90 s 超时造成的（deepseek-v4-pro 中位 3.9k、p90 10k 输出 token），不是选段问题；生产态工位一直是 180 s，0 段失败。
- 生产态 2026-09-16：114/116（#53 当时记「黄金集保守」，后查明是摘录定位 bug，见 `2026-09-16-excerpt-index-twin-prefix-p1-p3`；#61 已修）。仅模型新基线见 `electrical/README.md`。
