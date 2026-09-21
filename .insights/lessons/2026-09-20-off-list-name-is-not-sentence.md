# 2026-09-20 清单外需求必须是一条指标一个答案

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_collects_unlisted_shall_not_template_or_process`；`test_off_list_skips_cad_deliverables_and_splits_item`；`electrical/extract.py::_split_off_list_item` / `_is_off_list_process`

## 代价

第一版把整句 shall 截 40 字当名称、整句再当抽出值。DPR 1.3.1 的 3D/2D 交付、集成支持、中英各抄一行，看起来不像指标表。

## 反事实

不拆「名称 = 主语/条目标题、抽出值 = shall/应 后面的答案」，下次仍会名称≈抽出值；不把供应商提供 3D/2D、ESOW 转引、集成支持当流程语丢掉，清单外页仍会堆交付说明。

## 二级依据

主表口径是一条需求条目对应一个抽出值，摘录才是整句。3D 模型 / 2D 图纸 / 向吉利提供 / 为集成提供支持 / 符合吉利标准 是交付与职责，不是电控指标。抽出值仍只来自当份原句里 shall/应 之后的部分。

## 闸门

名称不得含 shall/must/应；名称与抽出值不得相同；3D/2D/供应商必须提供类句子 `_split_off_list_item` 返回 None。
