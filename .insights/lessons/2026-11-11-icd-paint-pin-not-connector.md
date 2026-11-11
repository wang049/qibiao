# 2026-11-11 引脚涂色不带到接插件信息

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_new_pin_does_not_paint_connector_info`、`test_different_sheet_name_and_plain_pin_still_compare`）

## 代价

低压连接器左边是接插件信息，右边是引脚，写在同一行。新引脚整行涂绿后，厂家、型号、料号也变绿，看起来像接插件新增。本表小结里并没有这条新增。

## 反事实

仍按整行涂色，下一份「4-整车低压连接器」里 PIN30 所在行的 Molex、厂家仍是绿色。料号若只改了一个字符，这一格的黄色也会被整行绿色盖住。引脚表从 A 列开始的表若不再涂信号列，`PIN1` 的修改会从原表上消失。

## 二级依据

- 引脚从「引脚号」那一列涂到行尾。左边的接插件信息不跟着涂。
- 接插件只涂改过的那一格：厂家、型号、供应商料号、镀层。整端新增或删除时涂这一端的四格。
- 高压接口一行就是一条记录，仍涂整行。只有引脚号、没有左边接插件的表，引脚列从 A 列起，效果仍是整行。

## 闸门

`test_new_pin_does_not_paint_connector_info`：PIN30 和信号是绿色，电器端供应商料号是黄色。Molex、线束端厂家、表头「厂家」不是绿色。
`test_different_sheet_name_and_plain_pin_still_compare`：引脚表从 A 列开始时，信号列仍是黄色。
