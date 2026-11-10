# 2026-11-10 ICD 差异文字居中

- 状态：superseded
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_same_signal_without_pin_number_is_not_a_new_pin`）

## 代价

本表小结和差异明细靠左。表很宽时，引脚定义贴在格子左边，上一版、当版看起来空一半。

## 反事实

小结和明细继续靠左，下一份宽表里「1-N-IN」仍贴在左缘，和居中的表头对不齐。

## 二级依据

- 出表后的连接器表小结：上一版引脚定义靠左，用户要求居中。
- 同一格里既有「删除 0」「上一版」，也有多行引脚定义，水平对齐要一致。

## 闸门

`test_same_signal_without_pin_number_is_not_a_new_pin`：本表小结那一格的水平对齐是 `center`。
