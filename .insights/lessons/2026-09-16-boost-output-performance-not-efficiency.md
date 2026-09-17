# 2026-09-16 #65 Boost输出性能不得抄 #66 升压效率整段

- 状态：active
- 条目：#65 Boost输出性能（核对表序号 61）；相邻 #66 升压效率（核对表序号 62）
- 闸门：`electrical/extract.py` `_value_fits_field` Boost输出性能分支（效率+% 拒收）；`electrical/tests/test_extract_quality.py::JunkAndFitTests.test_boost_output_performance_rejects_efficiency_block`；`electrical/examples/golden/dhts160_dpr.json` #61 `value_must_not: ["效率","efficiency"]`；`docs/clause_lexicon.yaml` #65 `exclude` 加效率一行

## 代价

`DHTS160_DPR_2026年09月16日13：26：45.xlsx` 序号 61 抽出值是 `最高效率：99.5%@直通，99%@升压；输入功率5-50kW，效率≥99.1%@300V直通；…`，与序号 62 升压效率逐字相同。状态、条款 6.5.4 都对，黄金比对只报 WARN 不报 FAIL，闸门放行了「填邻条内容」。专家认可稿（09-15 11:16）该格是 `450 V`。

## 反事实

- 不加守卫：#61 会随并行段返回顺序在「450 V」和「效率整段」之间漂。跨条目同值去重 `value_owner` 只认先入库者为主人，这次 #61 所在段先返回，#62 反而成了被拒的那个（有规则兜底才没丢）。顺序相关的去重不能当保证。
- 只改 prompt 措辞：效率段里有「输入功率 5-50kW」，现有放行条件「含 kW/功率/电流/boost 任一」照样过，模型也照样会把它当「输出性能」。
- 不在黄金加 `value_must_not`：下次再抄效率仍只是 WARN，无人会看。
- 不得反向用规则把 #61 硬填成 450 V：那是回到「规则堆专家稿」的路；守卫拒收后交给补抽，抽不到就诚实「未检索到」。

## 二级依据

- 词典 #65 `gloss`：升压输出侧综合性能——输出电压范围、功率、响应时间；`unit_cues`：V 范围 + kW + ms。效率的量纲是 %，不在其中。
- 清单 D 列「需明确 Boost 输出电压范围、功率、响应时间」；#66 D 列「需明确 Boost 模式转换效率」——同一份清单已把效率单列。
- DHTS 6.5.4 表：`Target output voltage of booster | 450 | V` 是输出侧行；`BOOST efficiency target | 最高效率…| ％` 是效率行，表头单位列已分开。
- 交叉 `2026-09-16-select-chunks-by-gap-and-split-retry`（#61 之前是漏，本次是混）、`2026-09-11-boost-power-peak-and-steady-labels`（#64 已承担功率，#61 不必再拼）。

## 闸门

- `_value_fits_field("Boost输出性能", 效率整段, …)` 为 False；`450V（升压器目标输出）`、`峰值 180kW（450V×400A@10s）` 仍为 True；同一效率段对「升压效率」仍为 True。
- 黄金 #61 值含「效率/efficiency」直接 FAIL。
- 词典 YAML 写 `→#66` 时不要在 `#` 前留空格，否则 PyYAML 当注释截断（本次 build 时踩到一次）。
