# 2026-09-09 出表前先做文件质检，交叉检查不得填格

- 状态：active
- 条目：出表流水线（读完之后、抽取之前）
- 闸门：`electrical/tests/test_doc_qa.py`；`electrical/tests/test_review_table.py` `test_cover_records_file_qa_without_fill_values`；`tests/test_jobs.py` 回传 `qa_summary`；`electrical/doc_qa.py`

## 代价

没有文件质检时，空页、扫描花字、目录页会直接进抽取，格子里出现不可靠的值或整表空着却不说明原因。若把知识库交叉做成「缺什么就用库补」，又会把企标典型值写进抽出值。

## 反事实

不先做文件本身质检、不把知识库交叉限制为「只报主题覆盖」，下次仍会：不可读文件被当电控 DPR 硬抽；或对照库之后把 8000 小时、试验箱 13.5 V、J7110218 的 5.3.10 写进格子。

## 二级依据

- 作业路径：读文档 → 分流 → 文件质检（可交叉知识库主题，对照当份中英与内部逻辑，不填格）→ 规则先填 → 空缺项分段 JSON → Excel。
- 红线：`fill_from_kb` 恒为 false。交叉检查只回答当份正文覆盖了哪些清单主题，不提供取值。
- 扫描件说明要写出花字样本（见 `2026-09-07-ocr-excerpt-note-is-concrete`），不要只说「乱码」。

## 闸门

`inspect_document`：正文几乎抽不出字 → `fail` 且 `skip_extract`，空表标不适用。可读文件才做主题交叉和当份内容审查；报告不得出现 8000 小时 / 15 年 / 13.5 V / 5.3.10。核对表「说明」页写来源和条数，不抄文件质检/内容审查摘要；中英冲突写在「文件审查」页。工位完成页只在需注意/不可读时显示花字等文件质检，不摊主题清单和方法号。工位进度增加 `qc` 步。交叉 `2026-09-09-doc-qa-content-review`、`2026-09-09-cover-skips-process-copy`、`2026-09-10-cover-skips-qa-and-miss-table`。
