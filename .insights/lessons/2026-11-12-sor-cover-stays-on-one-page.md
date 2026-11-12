# 2026-11-12 封面不冻窗，文件信息紧挨计数

- 状态：active
- 条目：01_封面
- 闸门：`electrical/tests/test_review_table.py` `test_rewrite_keeps_values_and_adds_review_columns`

## 代价

封面冻在第 6 行、缩放 130%。一滚动，源文件、文档类型、对照清单、知识库版本滑到计数后面，屏幕上从「清单外需求」直接跳到「清单条目」，中间空出一块。

## 反事实

封面继续冻在 A6，下一份打开后稍一滚动，源文件又会从计数和清单条目中间消失。

## 二级依据

- 当份 DHTS160 封面第 6 行是源文件 `DHTS160_DPR.docx`，第 10 行才是清单条目 116。冻窗把第 6 到第 9 行挡住了。
- 键仍在第一列，数仍在第二列。标题仍是「电控设计需求核对」。

## 闸门

`test_rewrite_keeps_values_and_adds_review_columns`：封面不冻窗，A6 是源文件，B6 是文件名。
