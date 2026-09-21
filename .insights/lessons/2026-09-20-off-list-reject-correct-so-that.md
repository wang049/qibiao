# 2026-09-20 清单外不收「必须正确以便」半截答案

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_skips_cad_deliverables_and_splits_item`；`electrical/extract.py::_off_list_value_ok` / `_OFF_LIST_DELIVERABLE`

## 代价

DHTS160 2026-09-20 13:44 清单外：`连接器的尺寸 / 正确，以便在故障情况下…验证方法1A0010`。一眼就是拆句失败，不是可核对指标。

## 反事实

不把「正确 / 以便 / shall be correct」当废答案丢掉，下次仍会把目的从句收成抽出值，并靠 1A0010 里的 A 当成带单位数字放行。

## 二级依据

清单外抽出值须是当份原句里可核对的答案（禁止回料、打印位置、32-bit、135%）。「尺寸必须正确以便…」是目的说明，不是指标。

## 闸门

`连接器的尺寸必须正确，以便…` → `_split_off_list_item` 为 None；`必须正确以便` 视为流程语。
