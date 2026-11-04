# 2026-11-04 端口名和手册分类写入格子

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`、`test_first_issue_drops_template_history_and_unmatched_names`）

## 代价

标记说明里已经有「模板有端口名」和「手册分类」，Function 和 Pin Definition 仍空着，人要自己抄到格子里。

## 反事实

分类仍只写在 W 列标记说明，下一次 `AN0` 的 Function 仍空，`IA_S/M_TM` 仍不在 L 列。人改端口名时关联页也没有可跟的格子。

## 二级依据

- 确认口径：对得上的模板端口名和手册分类直接写入格子，不对的由人改。
- L 列写模板端口名，如 `IA_S/M_TM`。同一符号有多个名字时不写 L，仍记在标记说明。Function 改写模板用法 Analog、Digital、PWM、SPI、CAN，见 `2026-11-04-hsi-function-uses-template-category`。
- 电源、地的分类仍在标记说明，行继续隐藏。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 的 Direction 为 `Input`，端口名为 `IA_S/M_TM`；`P02.1` 的端口名为 `PWM_M_AH_GM`。Function 见 `2026-11-04-hsi-function-uses-template-category`。
`test_first_issue_drops_template_history_and_unmatched_names`：对得上的 `P00.0` 端口名格为 `KEEP_ME`；对不上的 `P00.1` 仍空。
