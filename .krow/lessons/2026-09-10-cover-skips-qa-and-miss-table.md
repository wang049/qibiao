# 2026-09-10 说明页不摊质检摘要和未给出表

- 状态：active
- 条目：核对表「说明」页
- 闸门：`electrical/tests/test_review_table.py`（`test_rewrite_keeps_values_and_adds_review_columns`、`test_std_ref_miss_displays_unretrieved`、`test_cover_records_file_qa_without_fill_values`、`test_cover_writes_content_review_sheet_without_fill_values`）；`electrical/write_excel.py`

## 代价

说明页在条数下面再抄「文件质检 / 质检说明 / 内容审查」，并把企标方法空项摊成「未给出（方法见备注）」表。对表的人先看到扫描花字和未检索清单，来源和条数被挤到后面；方法号其实已经写在各行复核备注里，「文件审查」页也已有中英冲突明细。

## 反事实

不把这几块从说明页拿掉，下次出表仍会在首页列出 68 最大散热能力、95 存储相对湿度等未检索项，并把「需注意」「扫描花成 #3.0」写进说明。

## 二级依据

- 说明页只回答：这份表从哪来、抽了多少、怎么看颜色。中英冲突写在「文件审查」页。企标方法号写在该行「复核备注」，抽出值仍为未检索到。
- 交叉 `2026-09-09-cover-skips-process-copy`、`2026-09-09-miss-shows-unretrieved`、`2026-09-09-doc-qa-content-review`。

## 闸门

- 说明页有源文件、文档类型、知识库版本、已检索到/未检索到/局部对应、用法。
- 说明页不含「文件质检」「质检说明」「内容审查」「未给出（方法见备注）」「未检索到（方法见备注）」。
- 「文件审查」页仍写出内容审查；#72 等空项抽出值仍为未检索到，复核备注仍含企标方法对照。
