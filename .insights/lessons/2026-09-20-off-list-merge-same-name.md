# 2026-09-20 清单外同一名称只占一行

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_merges_same_name_answers`；`electrical/extract.py::_off_list_same_item` / `_prefer_off_list_cell`

## 代价

DHTS160 2026-09-20 13:44 清单外 MCU 三行：32-bit / 4 cores lock-step / 8 CAN buses。名称相同，像三条重复指标。

## 反事实

不把相同名称收成一行、不把不同答案用分号拼进抽出值，下次同一主语多条 shall 仍会占满三格。

## 二级依据

清单外是一条指标一个格子。同一主语（MCU）的多条答案写在同一抽出值里，开发 CAN 等不同名称仍分行。抽出值只来自当份原句。

## 闸门

三句 `The MCU shall …` 收集后名称 MCU 仅 1 行，抽出值同时含 32-bit、4 cores、8 CAN；`development CAN bus` 不并进 MCU。
