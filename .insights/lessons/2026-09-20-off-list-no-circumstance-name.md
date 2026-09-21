# 2026-09-20 清单外名称不能是「在…过程中」

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_skips_cad_deliverables_and_splits_item`；`electrical/extract.py::_clean_off_list_name` / `_off_list_name_from_value`

## 代价

DHTS160 清单外：`在最终组装过程中 / 不得在零件上添加胶水/润滑剂`。名称是状语，不是指标。

## 反事实

不把「在…过程中 / during」当废名称丢掉、不从「添加X」回填条目名，下次仍会把组装场合写成名称。

## 二级依据

清单外名称是指标主语，抽出值是 shall/不得 后面的答案。场合状语不是条目。当份原句「不得在零件上添加胶水/润滑剂」的对象是胶水/润滑剂。

## 闸门

`在最终组装过程中，不得在零件上添加胶水/润滑剂。` → 名称 `胶水/润滑剂`，抽出值以「不得」开头。
