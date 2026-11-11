# 2026-11-11 手册出表不写旧端口名

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`、`test_first_issue_drops_template_history_and_unmatched_names`）

## 代价

没有原理图时，手册出表仍把模板里对上的端口名写进 Pin Definition，并把上一份项目的中文说明写进 Pin Function Description。`P00.0` 会带上 `GM驱动芯片故障反馈信号`。使用的人会把上一份项目的说明当成这次的结果。

## 反事实

继续写入，下一份按 TC39x 手册生成的端口表，Pin Function Description 仍是 `GM驱动芯片故障反馈信号`。有原理图时若也留空，读到的导线网络名就不再进入 Pin Definition。

## 二级依据

- 会议口径：没有原理图时信号名列不存在，空着。旧的端口名和每个项目自己的功能说明都会误导。有原理图才有信号名。
- 功能列仍写对上的 Analog、PWM 等用法。复用仍来自手册。Pin Definition 和 Pin Function Description 不写。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 和 `P02.1` 的 Pin Definition、Pin Function Description 都为空。Function 仍是 Analog、PWM。
`test_first_issue_drops_template_history_and_unmatched_names`：端口表不再写入 `KEEP_ME`。
