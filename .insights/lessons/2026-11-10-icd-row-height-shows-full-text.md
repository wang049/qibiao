# 2026-11-10 ICD 长句按列宽撑开行高

- 状态：active
- 条目：ICD 出表
- 闸门：`tests/test_icd.py`（`test_long_note_row_is_tall_enough_to_show_the_text`）

## 代价

差异行高只按换行符计算，并且最高 120。没有换行的长句在窄列里折行后被格子裁掉，下一行字只露出一条边。

## 反事实

行高仍按换行符、仍封顶 120，下一份「4路LIN总线，具体每一个LIN挂在哪个总线暂不考虑」仍只看见前半句。

## 二级依据

- 出表截图：修改行里「暂不考」被裁断，底边还露出「LIN按的SDEC加工」。
- 格子里的原文没有删。行高要按列宽能排下的行数计算，Excel 行高上限是 409。

## 闸门

`test_long_note_row_is_tall_enough_to_show_the_text`：信号全文仍在版本差异的当版格里，该行行高至少 40。原表行数不增加。
