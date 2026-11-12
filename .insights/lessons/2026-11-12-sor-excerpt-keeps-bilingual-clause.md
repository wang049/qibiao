# 2026-11-12 编号条款的原文摘录要带上英文整段和中文整段

- 状态：active
- 条目：#10 母线直流电流检测
- 闸门：`electrical/tests/test_extract_quality.py`（`test_numbered_clause_excerpt_keeps_english_and_chinese`）

## 代价

核对表第 10 条原文摘录只有标题「HVDC current sensor 高压直流电流传感器」。规格书里同一条的英文要求和中文译文没有写进格子，工程师对着摘录核对不出抽出值。

## 反事实

命中停在标题、空行就收束时，下一份 6.10.2.7 仍只有标题。英文句号一到就停，同一段后面的「升压XCM的重量不得超过20.2公斤」仍不在摘录里。条款正文超过 900 字就整段放弃时，6.5.11.1 仍只剩标题。收到下一条 6.10.2.8 时，交流电流传感器会写进直流电流这一条。

## 二级依据

- 当份 `DHTS160 DPR.docx` 条款 6.10.2.7：标题后是英文整段 `The XCM shall have a HVDC current sensor monitoring the HVDC current. The AUX current should not be included in the measured HVDC current. The HVDC current sensor shall fulfill ASIL C according to ISO 26262-2018.`，接着是中文整段「控制器应该有一个高压直流电流传感器监测高压直流电流。辅助高压电流不应包括在测量的高压直流电流中。高压直流电流传感器应符合ISO 26262-2018的ASIL C标准。」
- 下一条标题是 6.10.2.8 HVAC current sensor，不属于这一条。
- 当份 2.3.1 重量句写在同一段：英文 `The weight of the XCM shall be less than 20.2kg(With OD Module)` 后面就是「升压XCM的重量不得超过20.2公斤（含OD模块）」。英文句号不能把这句中文截掉。

## 闸门

`test_numbered_clause_excerpt_keeps_english_and_chinese`：母线直流电流检测的原文摘录含 6.10.2.7 标题、英文 AUX 句和中文「辅助高压电流不应包括」，不含 6.10.2.8。`test_same_line_chinese_stays_after_the_english_period`：2.3.1 英文句号后的「升压XCM的重量不得超过20.2公斤」留在摘录里，不把后面的表头带进去。
