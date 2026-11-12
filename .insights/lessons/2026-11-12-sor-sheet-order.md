# 2026-11-12 核对表按工程师打开的顺序排页

- 状态：active
- 条目：SOR 出表
- 闸门：`electrical/tests/test_review_table.py`（`test_rewrite_keeps_values_and_adds_review_columns`、`test_cover_writes_content_review_sheet_without_fill_values`）

## 代价

五张表的名字是「说明、电控设计需求、文件审查、清单外需求、清单口径」。页签看不出先核对哪一张。需求表滚到原文时，序号和条目被卷走。人工填写列和抽出值长得一样。

## 反事实

页签仍用原来的名字，下一份打开后仍要猜「清单口径」是不是本份抽出值。需求表仍从 A 列冻结，看原文摘录时看不到条目名。

## 二级依据

- 确认口径：页签按使用顺序。`01_封面`、`02_需求核对`、`03_提取质量审查`、`04_清单外`、`05_条目说明`。需求表冻结到条目名。人工填写列用绿色表头。条目说明写明不是本份抽出值。
- 旧表名仍能读回，已经出过的核对表不用改名也能打开。

## 闸门

`test_rewrite_keeps_values_and_adds_review_columns`：四张表的名字是封面、需求核对、清单外、条目说明。`test_cover_writes_content_review_sheet_without_fill_values`：有正文差异时，第三张是 `03_提取质量审查`，第一列不是 P0。
