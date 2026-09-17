# 2026-09-09 文件质检要对照当份中英冲突和内部打架

- 状态：active
- 条目：出表流水线（文件质检，不填格）
- 闸门：`electrical/tests/test_doc_qa.py`（`test_bilingual_and_template_issues_warn_without_filling_or_skipping`、`test_internal_logic_flags_weight_can_and_power_map`、`test_content_conflicts_still_extract_and_do_not_fill`、`test_matching_bilingual_numbers_are_not_a_conflict`）；`electrical/tests/test_review_table.py` `test_cover_writes_content_review_sheet_without_fill_values`；`electrical/doc_content_qa.py`

## 代价

质检只看能不能读、主题覆盖了没有时，中英并列数字打架、Volvo 模板残留、封面 `<<…>>`、重量表超过正文限值，都要等到抽格或人工翻页才看见。#90 相电流冲突会写进抽出值，但休眠电流、重量、水道耐压、等电位「at least / 小于」不会出现在审查说明里。

## 反事实

不在抽取前对照当份中英数字、语义相反和模板残留，下次仍会只在个别格子里看到安培冲突，签核前当份内部打架被漏掉。若把审查里的 600A / 16kg 写进抽出值，又会拿冲突数字去填格。

## 二级依据

- 作业路径：读文档 → 分流 → 文件质检（可交叉知识库主题，对照当份中英与内部逻辑，不填格）→ 规则先填 → 空缺项分段 JSON → Excel。
- 当份 DPR 中英并列常见：同一条款英文一个安培/公斤/微安，中文另一个；英文 at least 1A 对中文「小于 1A」。
- 交叉 `2026-09-09-doc-qa-before-extract`（先质检、交叉不填格）、`2026-09-09-bilingual-conflict-needs-review`（#90 抽出值写两侧并复核，不等于质检阶段用冲突值填其它格）。

## 闸门

`inspect_document` 在可读之后做内容审查：中英数字冲突、语义相反 → P0；内部限值打架、P=UI 对不上、Volvo / `<<…>>` / 异常日期 / 空表 → P1。发现写入「文件审查」页；说明页不抄条数摘要。`skip_extract` 仍仅不可读。报告不得出现 8000 小时 / 15 年 / 13.5 V / 5.3.10。工位完成页只出条数摘要，不摊主题清单。交叉 `2026-09-10-cover-skips-qa-and-miss-table`。
