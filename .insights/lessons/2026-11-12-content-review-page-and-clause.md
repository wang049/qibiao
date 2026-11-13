# 2026-11-12 正文审查标出页码和条款号

- 状态：active
- 条目：当份正文审查（不填格）
- 闸门：`electrical/tests/test_doc_qa.py`（`test_bilingual_and_template_issues_warn_without_filling_or_skipping`、`test_conflict_uses_the_page_of_that_clause`）；`electrical/tests/test_review_table.py` `test_cover_writes_content_review_sheet_without_fill_values`

## 代价

03_正文审查把问题写成「5.2.5 h 中英数字不一致：英文 20、30h，中文 32h」。同一处 202601202 写了两遍。页码和条款号没有单独的列，工程师要自己从句子里拆。

## 反事实

句子里不带命中点之前的 `## 第 N 页` 和条款标题，下一份审查表仍然只有类型和一句说明，对不上原文。同一串异常日期继续连写两遍。没有印页的 Word 若用目录页去填，页码会编出来。

## 二级依据

- 当份 DHTS160：5.2.5 小时数中英不一致；6.2.3.2 功率中英不一致；P1 交流电流中文 ±180A、英文 ±600A，所在节是 6.3.3.1。
- 页码只取命中点之前最近的 `## 第 N 页`。正文没有这个标记时页码留空。
- 占位符 `<<SYSTEM/COMPONENT>>`、日期 `202601202`、Volvo 模板句仍要报出来，同一日期只写一次。

## 闸门

`test_conflict_uses_the_page_of_that_clause`：5.2.5 的小时冲突页码是 32，6.2.3.2 的功率冲突页码是 44。
`test_bilingual_and_template_issues_warn_without_filling_or_skipping`：±180A 落在 6.3.3.1、页码 10；202601202 只出现一次。
`test_cover_writes_content_review_sheet_without_fill_values`：审查表有页码列和条款号列，第一列不是 P0。
