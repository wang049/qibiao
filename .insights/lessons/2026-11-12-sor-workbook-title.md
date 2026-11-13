# 2026-11-12 核对表标题用工作名，不用清单原名

- 状态：active
- 条目：SOR 出表
- 闸门：`electrical/tests/test_review_table.py`（`test_rewrite_keeps_values_and_adds_review_columns`）

## 代价

封面和需求表的大标题写成「XCM控制器前期设计最小化输入清单」。这是 116 条对照清单的原名，打开的人会把它当成这份规格书的标题。

## 反事实

大标题继续用清单原名，下一份 DHTS160 的核对表抬头仍不是这份文件要做的事。

## 二级依据

- 确认口径：封面和「02_需求核对」的大标题写「电控设计需求核对」。清单原名放在封面「对照清单」一行。
- 本次封面大标题是清单原名，源文件是 `DHTS160 DPR.docx`。

## 闸门

`test_rewrite_keeps_values_and_adds_review_columns`：封面和需求核对的 A1 都是「电控设计需求核对」。
