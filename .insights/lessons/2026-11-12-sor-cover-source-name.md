# 2026-11-12 说明页源文件用上传时的文件名

- 状态：active
- 条目：SOR 出表
- 闸门：`electrical/tests/test_review_table.py`（`test_cover_source_drops_the_storage_prefix`）

## 代价

说明页「源文件」写成 `d56df42e_DHTS160_DPR.docx`。前面 8 位是落盘时加的记号，不是这份规格书的文件名。

## 反事实

继续把落盘路径的文件名写进说明页，下一份仍会显示 `d56df42e_` 这种前缀，工程师对不上自己交上去的 `DHTS160_DPR.docx`。

## 二级依据

- 确认口径：说明页源文件写上传时的文件名。落盘名 `8位十六进制_` 前缀去掉。
- 本次说明页格子是 `d56df42e_DHTS160_DPR.docx`，上传文件是 `DHTS160_DPR.docx`。

## 闸门

`test_cover_source_drops_the_storage_prefix`：传入 `d56df42e_DHTS160_DPR.docx`，说明页源文件是 `DHTS160_DPR.docx`。
