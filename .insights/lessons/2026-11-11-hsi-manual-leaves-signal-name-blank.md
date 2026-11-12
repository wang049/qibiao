# 2026-11-11 手册出表不写旧端口名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`、`test_first_issue_drops_template_history_and_unmatched_names`）

## 代价

没有原理图时，手册出表仍把模板里对上的端口名写进 Pin Definition，并把上一份项目的中文说明写进 Pin Function Description。`P00.0` 会带上 `GM驱动芯片故障反馈信号`。使用的人会把上一份项目的说明当成这次的结果。

## 反事实

继续把模板端口名写进 Pin Definition，下一份按手册生成的表仍会带上 `GM驱动芯片故障反馈信号`。Pin Definition 一直空着，就看不出手册给出的推荐功能。封面和旧变更若留着，下一份 TC38x 仍会写着上一项目的修改人。

## 二级依据

- 会议口径：没有原理图时不写上一项目的端口名和中文说明。Pin Definition 写「手册推荐」加当份手册的分类和第一条复用。Pin Function Description 仍空。
- 功能列写手册分类。复用仍来自手册。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 的 Pin Definition 以「手册推荐：ADC」开头，不含 `IA_S`。`P02.1` 以「手册推荐：PWM」开头，不含 `PWM_M_AH`。两行的 Pin Function Description 都为空。封面修改人和 v1.0–v1.3 变更不再留下，新的一条是按芯片手册重出。
