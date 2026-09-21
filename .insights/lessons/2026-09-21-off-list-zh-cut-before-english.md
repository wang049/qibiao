# 2026-09-21 清单外中文摘录不得粘后随英文

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_names_come_from_spec_chinese`；`electrical/extract.py::_off_list_following_zh` / `_maps_to_template_field`

## 代价

DHTS160 规则核：对照中文已进名称，摘录却是「微控制器单元应具有…数据库 The MCU shall incorporate a floating point unit」。冷却条件、ISO 6469 class B、供应商提供功耗、MTBF 仍占清单外。

## 反事实

对照中文不在句号或下一句 `The` 处切开、twin 之后不再用主表针拦一遍，下次摘录仍中英粘连，主表已有的冷却/耐压和交付语再占清单外。

## 二级依据

有英中对照时摘录只留当份中文句。ISO 6469 class B / 冷却条件走主表。供应商应提供功耗、MTBF 是交付与预测，不是前期可填指标。

## 闸门

对照稿 MCU excerpt 含「微控制器单元应具有最小的32位寄存器和数据库」，不得含 `The MCU shall` / `floating point`。`class B voltage` + ISO 6469 → 主表。冷却条件 / 功耗数据 / MTBF → 不进 extra。
