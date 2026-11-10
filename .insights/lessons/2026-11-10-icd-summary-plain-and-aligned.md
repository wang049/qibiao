# 2026-11-10 ICD 小结不改原表列宽，匹配栏用白话

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_different_sheet_name_and_plain_pin_still_compare`、`test_same_signal_without_pin_number_is_not_a_new_pin`、`test_previous_file_marks_add_remove_and_change`）

## 代价

本表小结写进连接器原表的 A 到 E 列，并把 D、E 列撑到 42。型号、镀层被拉宽，新增、修改、删除的数字落在宽窄不一的列里，看起来对不齐。版本差异把文件名和「对象」放在同一列，文件名把这一列撑到 48。匹配栏写成「当版有，上一版无」「同一字段已对上，取值不同」。

## 反事实

再把小结塞进原表列并加大列宽，下一份高压接口的型号列仍会被撑开，删除的数字仍漂在宽列中间。文件名仍和对象共用一列时，对象列继续被文件名撑满。匹配栏仍用「已对上、取值不同」时，表上还是那套对照腔。

## 二级依据

- 甲方要在每个连接器表下看到新增、修改、删除，原表格式保留。
- `ICD引脚清单-20261110-201604.xlsx`：高压接口 D、E 列宽 42；版本差异 B 列宽 48；匹配栏是「当版有，上一版无」和「同一字段已对上，取值不同」。版本列是出表时间，裁切后只剩开头的 2。
- 同一文件的变更记录版本是 V3.5 和 V3.12，版本列应写这个版本，不写一长串出表时间。

## 闸门

`test_different_sheet_name_and_plain_pin_still_compare`：原表 A 列宽保持 14、D 列宽保持 9。版本差异前两行含文件名和 V3.11、V3.12。对象列宽不超过 20。
`test_same_signal_without_pin_number_is_not_a_new_pin`：版本差异里这条是引脚号变更，当版含信号。匹配栏是「写的不一样」，没有「同一字段已对上，取值不同」。原表不再写本表小结。
`test_previous_file_marks_add_remove_and_change`：匹配栏只有「上一版没有」「本版没有」「写的不一样」。
