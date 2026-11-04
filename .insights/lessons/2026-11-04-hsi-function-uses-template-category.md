# 2026-11-04 Function 写模板用法

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_function_column_uses_template_category`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

Function 写成手册分类 `ADC`、`Timer`。模板这一列是项目用法 `Analog`、`Digital`、`PWM`、`SPI`、`CAN`。`FLTB_M_H_GM` 在模板里是 PWM，生成表写成 Timer。

## 反事实

继续写手册分类时，下一次 `AN0` 的 Function 仍是 `ADC`，`P02.1` 仍是 `Timer`。模板里这两行是 `Analog` 和 `PWM`。

## 二级依据

- 确认口径：Function 按模板这一列改。模板用 Analog、Digital、PWM、SPI、CAN、LIN、SENT、JTAG。
- DHTE400 端口表：`AN0` 方向 Input、功能 Analog、端口名 `IA_S/M_TM`。`P00.0` 功能 PWM、端口名 `FLTB_M_H_GM`。`P02.1` 功能 PWM、端口名 `PWM_M_AH_GM`。
- 同一只脚对上的模板功能是同一个词才写入。对不上，或模板给出两个不同功能，Function 留空。Direction 仍写手册的 Input 或 Output。

## 闸门

`test_function_column_uses_template_category`：对上的功能是 `Analog` 时，Function 为 `Analog`，不是 `ADC`。两个不同模板功能时不取其中一个。
`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 的 Function 为 `Analog`，`P02.1` 为 `PWM`。
