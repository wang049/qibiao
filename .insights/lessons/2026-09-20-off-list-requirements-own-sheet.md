# 2026-09-20 清单外需求单独成页，不进 120 项覆盖率

- 状态：active
- 条目：清单外（对不上 1–120 的当份要求）
- 闸门：`electrical/tests/test_review_table.py::WorkbookTests.test_off_list_sheet_keeps_template_coverage`；`electrical/tests/test_extract_quality.py::OffListRequirementTests`；`electrical/extract.py::_collect_off_list_requirements`；`electrical/write_excel.py::_write_off_list_sheet`

## 代价

DPR 里常有对不上电机控制需求清单的条款。原先模型只补空缺清单项，对不上的句子丢掉；`extra` 白名单又只收封面字段。设计 SOR 时看不到这批当份要求。若把它们写进主表，覆盖率会被清单外条数带偏。

## 反事实

不把清单外要求和 120 项主表拆开、不拦「已入清单 / TBD / 目录 / 流程语」，下次仍会：主表混进无序号行；已检索到/未检索到把封面或重复句算进去；或把主动放电等已填清单项再抄一页。

## 二级依据

清单仍是源表 1–120（核对表需求序号 1–116）。抽出值只来自当份原文。标题、目录、TBD、待供应商提供等流程语不是可设计 SOR 的要求。能被清单强别名认条的句子应留在主表，不进「清单外需求」。

## 闸门

主表与说明页覆盖率只数 `not extra`。清单外页只写名称/抽出值/页码/条款号/原文摘录；封面 extra 不进该页。收集器对已用摘录、模板别名、TBD/流程语直接丢弃。
