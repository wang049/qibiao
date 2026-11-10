# 2026-11-10 ICD 本表小结从 A 列往下写，文字靠左

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`）

## 代价

本表小结写在原表已用列的右侧，五列全部居中。打开连接器表时，小结不在表的下方，短字浮在格子中间。

## 反事实

小结继续从最右列起写、格子继续居中，下一份高压接口的小结仍在 R 列一带，不在表下从 A 列开始。

## 二级依据

- `ICD引脚清单-20261110-213418.xlsx`：高压接口小结在第 6 行第 18 列，对齐是 center。低压连接器小结在第 115 行第 22 列。
- 原表已有列宽不改。A 列宽 14、D 列宽 9 仍要保持。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：「本表小结」在第 1 列，水平对齐是 left。下一行 A 列是「差异」。A 列宽 14、D 列宽 9。
