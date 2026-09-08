# 2026-09-07 整数 kg 也是总成重量

- 状态：active
- 条目：#73 控制器重量；#101 重量要求
- 闸门：`electrical/tests/test_extract_quality.py`（`test_superevo_rules`、`SuperEvoQualityGateTests.test_integer_kg_stores_through_value_fits`）；`electrical/extract.py` `_parse_pcm_mass_kg`、`_value_fits_field("重量")` 允许 BOM 整数 kg

## 代价

SuperEvo BOM `可拓展动力域控制模块_总成 | 12 | 1 | 12` 规则已匹配 12kg，入库时 `_value_fits_field` 要求摘录必须有小数 `\d+[.．]\d+`，整数 12 被丢掉。#73/#101 标未检索到。

## 反事实

不放开「总成/单件目标重量」下的整数 kg，下次仍会把当份已经印出的 12kg 漏掉，只收下 14.9 这种带小数的写法。

## 二级依据

- 清单 #73/#101：控制器/重量要求，值为当份总成重量。
- SuperEvo 重量表：`可拓展动力域控制模块_总成` 单件目标重量 12 kg（两行配置均为 12）。
- 不得用包装毛重或 20.2/18.5 含 OD 上限顶替该行。

## 闸门

- `_parse_pcm_mass_kg`：匹配 `可拓展动力域控制模块_总成 | 12 | 1 | 12` 及 `单件目标重量/kg`。
- `_value_fits_field("重量")`：小数 kg，或摘录含总成/单件目标重量且为 10–25 的整数。
- 回归：该 BOM 行经 `_store_cell` 后 #73/#101 均为 12kg。
