# 2026-09-16 词典弱别名要传到出表侧：找页、认条可用，计分填值不可用

- 状态：active
- 条目：#73 控制器重量 / #101 重量要求；#74 防腐等级 / #102 防腐要求；#78 扭矩控制精度 / #89 转矩控制精度
- 闸门：`electrical/tests/test_extract_quality.py::test_weak_aliases_let_weight_and_corrosion_pages_be_found`；`electrical/schema.py::FieldSpec.weak_aliases / unit_cues`；`electrical_krow/clause_lexicon.py::weak_aliases_for_seq`；`electrical/extract.py::_spec_alias_pool / _capped_weak_tokens`

## 代价

仅模型体检（关规则，模拟新文档）里重量 ×2、防腐 ×2 一直「未检索到」，三次基线都一样。查下去发现不是模型没读到，是选段根本认不出这几页：`electrical` 侧 `FieldSpec.aliases` 只装词典 `aliases`（strong 层），而这六条因为两两同槽（#73/#101 同值、#74/#102 互补、#78/#89 口径不同）别名跨条目不唯一，全部落在 `weak_aliases`，strong 层为空。出表侧从没读过 weak 层，等于这六条没有别名。生产态靠原文规则填上了，换一份规格书就漏。

## 反事实

- 把「重量 / weight / kg」硬塞进 strong：违反词典 `alias_levels.strong`「跨条目唯一」的定义，#73/#101 会互相抢；下游公司知识库按 strong 计分也会双命中。
- 给 `_field_needles` 再加一行 `("重量", ["weight", "kg"])`：又是为一份文档写死针，词典里现成的 20 条弱别名继续闲置。
- 弱别名不加约束直接当强命中：`质量`（quality/mass）、`涂层`、`表面处理`、单词 `weight/mass` 在供应商质量、标签、涂装页旁边都挨着数字，会把无关页认成给值页（复现里块 64「高压警示标签」就被认成重量页）。

## 二级依据

- 词典 meta `alias_levels.weak`：「整词但多条目共享，须配合判别词或单位闸门才计分」——本次只用弱别名**找页**和**把条目列进 prompt**，不进 prompt 别名提示、不计分、不填值，符合该层定义。
- `.insights/AGENTS.md`：抽出值只来自当份材料；弱别名只影响模型看到哪几页、被问到哪几条，值仍由模型从原文摘出并经 excerpt 校验。
- 词典 #73 notes：「#73 与 #101 数值不同口径可能不同，不应强制对齐」——因此仍分两条各自抽，只是共用一套找页针。

## 闸门

- `FieldSpec` 新增 `weak_aliases`、`unit_cues`，两侧 `clause_lexicon.py` 各加 `weak_aliases_for_seq / unit_cues_for_seq`；`_spec_alias_pool` = strong + weak，再过 `_shared_coverage_tokens`（3 条以上共享的仍剔除）。
- `_capped_weak_tokens`：弱别名若不含条目名的核心二字（重量 / 防腐 / 扭矩 / 精度…）且不是英文多词短语，命中强度上限 1，不能凭旁边有数字算给值页。
- `_chunk_fields` 弱别名命中 +2，只决定条目是否列进 prompt；`format_prompt_field` 仍只用 strong 别名。
- 效果：仅模型体检 96 → 102/116，重量 ×2、防腐 ×2 全部对上专家值（20.2/18.5 kg、F3、Q/JL J160003-2024），0 错填，0 段失败，9.7 分钟。
