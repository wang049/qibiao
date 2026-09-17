# 2026-09-16 二字条目名（速比）只能靠强别名列进 prompt；选段认得的页，prompt 也要问

- 状态：active
- 条目：#75 速比（词典 seq 79）；连带任何仅靠词典强别名认条、条目名切不出三字整词的条目
- 闸门：`electrical/extract.py::_chunk_fields` 名称分词零分时按词典强别名整词补分；`_strong_alias_present` 英文别名整词（允许 s/es 复数），中文按子串。`electrical/tests/test_extract_quality.py::ScanDprFixTests.test_chunk_fields_lists_two_char_name_by_strong_alias` / `test_strong_alias_latin_is_whole_word` / `test_ratio_value_passes_guards`

## 代价

- `4LDHT260_DPR_扫描件_2026年09月16日14：36：57.xlsx` #75 速比「未检索到」，而 OCR 原文 2.3.3 驾驶性目标表写明 `变速箱速比 ICE: 7.119/4.881/3.689/2.941；主减 3.462；P3: 12.830`。
- `SuperEvo_1000V__DPR_2026年09月16日14：11：08.xlsx` #75 同样漏，原文有速比表。
- 两份都是模型能答、守卫能收（`_value_fits_field` / `_store_cell` 实测放行），却从没被问到的静默漏项。

## 根因

- 选段（`_select_chunks` → `_coverage_tokens`）用「条目名分词 + 词典强/弱别名」找页，把含「速比」的页选进了预算（4LDHT260 第 2 段、SuperEvo 第 2/7/9 段）。
- 列 prompt 条目（`_chunk_fields`）只用 `whole_name_tokens`（三字及以上中文 / 英文代号）+ 弱别名 + `_FIELD_EN`。「速比」二字切不出整词，`_name_match_tokens("速比") == []`，全表唯一一个；词典强别名 `速比 / 传动比 / gear ratio` 根本不参与。于是页进了模型、条目却不在「仍空缺条目」里，prompt 明写「只抽出下面仍空缺的条目」，模型照做不答。
- 两侧认条口径不一致，选段为它花的名额白花。

## 反事实

- 只给「速比」加特判：等下一个二字名或名称与原文写法完全不同的条目再漏一次。按强别名补分是对整表生效的通则，且只在名称分词零分时补，不改已有条目的排序。
- 直接把 `_token_present` 全局改整词：会改 `_select_chunks` 覆盖计算和弱别名判定，DHTS160 选段结果会动；这次只在新增的强别名通路用整词判定，选段零变化。
- 英文别名子串匹配（首版）：`creep`（滑膜起步）认到 `creepage`（爬电距离），把 #113 列进爬电距离页。改整词后消失。
- 不能因此放松 `_value_fits_field`：新列进 prompt 的 电机类型（词典含 电气间隙/爬电距离）、主动保险（含 熔断器/fuse）、网络安全（含 安全启动）在三份文档上守卫实测全部拒格，只有速比放行。

## 二级依据

- 4LDHT260 OCR 第 25 印页 `Table4 Drivability Targets 表4驾驶性目标`：`ICE: 7.119/4.881/3.689/2.941 变速箱速比（转化为阶差） 1 主减：3.462 Ratio Step 1st\2nd\3rd P3: 12.830`。
- 词典 #79 速比：别名 速比/传动比/减速比/P1传动比/P3传动比/主减速比/gear ratio…，单位提示「无量纲 x.xx（分 P1/P3）」，排除 占空比/弱磁比/功率比。
- deepseek-v4-pro 对该段（整段 125 s、拆半 165 s）两次都返回 `seq 79 速比 = ICE 7.119/4.881/3.689/2.941；主减 3.462；P3 12.830`，excerpt 为原文行。
- 交叉 `2026-09-16-select-chunks-by-gap-and-split-retry`（选段按空缺找页）、`2026-09-16-weak-aliases-reach-extract-side`（词典别名要传到抽取侧）。

## 闸门

- 三份文档（4LDHT260 扫描、DHTS160、SuperEvo）逐段比对修前修后 prompt 条目：没有条目被挤出 top40；新增列入 速比（4LDHT260 段 2；SuperEvo 段 2/7/9）及少数词典本就含该别名的条目，DHTS160 只多列 电机类型/主动保险 各一段，黄金里两条均为未检索到、守卫实测拒格。
- `_chunk_fields("变速箱速比…P3: 12.830", 空行)` 必含「速比」；该条已填后不再列。
- `_strong_alias_present("creep", "creepage …")` 必为 False；撤掉 `_LATIN_ALIAS` 整词判定即红。
- 待做：4LDHT260 / SuperEvo 重启后整份重跑，#75 应为已检索到，值含 `12.830`；专家确认填法（整组还是只 P3）后再冻进黄金。
