# 2026-11-12 两段条款号的原文摘录要带上标题后的中英文

- 状态：active
- 条目：#102 阻燃要求
- 闸门：`electrical/tests/test_extract_quality.py`（`test_flame_heading_4_6_not_ageing_4_3_3`）

## 代价

`4.6` 只有两段数字，标题和正文之间还有空行。摘录停在标题 `## 4.6 Flame Retardance Requirement阻燃要求`。后面的英文 According 句和中文「并提供阻燃报告」没有写入原文摘录。页码也空着。同样停在标题上的还有母线电流、堵转电流这些条。

## 反事实

两段条款号仍不当成一条的标题，下一份 4.6 阻燃的原文摘录仍只有标题。`12.5 kW` 若被当成标题，转速或电容那一条会带上错误的条款号。

## 二级依据

- 当份 `DHTS160 DPR` 条款 4.6：标题后是 `According Q/JLY J7110335C-2022 Limit requirements and test methods for flame retardant automotive non-metallic materials.`，接着是「根据Q/JLY J7110335C-2022汽车非金属材料阻燃性限值要求及试验方法，并提供阻燃报告。」
- 行首 `12.5 kW` 不是条款标题。

## 闸门

`test_flame_heading_4_6_not_ageing_4_3_3`：阻燃要求的原文摘录含 According 句和「并提供阻燃报告」，不含上一节老化文字。条款号是 4.6。
