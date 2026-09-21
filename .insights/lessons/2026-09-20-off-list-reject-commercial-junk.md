# 2026-09-20 清单外不收商务交付和半截主语

- 状态：active
- 条目：清单外
- 闸门：`electrical/tests/test_extract_quality.py::OffListRequirementTests.test_off_list_skips_cad_deliverables_and_splits_item`；`electrical/extract.py::_is_off_list_process` / `_off_list_value_ok` / `_OFF_LIST_BAD_NAME`

## 代价

DHTS160 2026-09-20 11:37 核对表「清单外需求」80 行：3D/损耗模型/认证/样件/备件/专用工具/电池指令，以及 There / unit / If there is 这类半截英文主语。不像一条指标一个答案。

## 反事实

不把供应商提交、CAD/热模型、采购样件、售后工具、认证注册当流程语丢掉，不要求抽出值带打印/标准号/带单位数字或「禁止」短句，下次仍会堆满商务页，并把 There shall / 下表规定 收成空答案。

## 二级依据

清单外是给设计 SOR 看的当份电控/产品指标，不是 DPR 商务与交付章节。主表已覆盖纹波、dV/dt、放电等。抽出值只来自当份原句里可核对的答案。

## 闸门

`There shall`、`shall be described`、`Table below` 无数字、专用工具、向吉利提交测试结果 → split 为 None。
