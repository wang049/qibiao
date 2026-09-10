# 2026-09-09 说明页不重复填格禁令

- 状态：active
- 条目：核对表「说明」页
- 闸门：`electrical/tests/test_review_table.py`（`test_rewrite_keeps_values_and_adds_review_columns`、`test_cover_records_file_qa_without_fill_values`、`test_std_ref_miss_displays_unretrieved`）；`electrical/write_excel.py`

## 代价

说明页把「库不提供取值」「不写入抽出值」「质检口径」「页码列」和各列用法抄了多遍。对表的人先看到内部禁令，来源、条数和质检结论被挤到后面。内容审查摘要又和「文件审查」页重复。

## 反事实

不把填格禁令和列说明从说明页拿掉，下次出表仍会把知识库口径、知识库交叉、原则、质检口径写进首页；质检说明还会把「文件审查」条数再抄一遍。

## 二级依据

- 说明页回答：这份表从哪来、抽了多少。列怎么用写在「电控设计需求」表头批注。中英冲突细节写在「文件审查」页。
- 交叉 `2026-09-09-std-chip-is-not-fill-disclaimer`、`2026-09-09-doc-qa-before-extract`。

## 闸门

- 说明页有源文件、知识库版本、已检索到/未检索到、用法。
- 说明页不含「知识库口径」「不提供取值」「知识库交叉」「知识库闭环」「页码列」「质检口径」「不写入抽出值」。
- 有企标方法的空项不在说明页再摊「未给出」表；方法号只写该行复核备注。交叉 `2026-09-10-cover-skips-qa-and-miss-table`。
