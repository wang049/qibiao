# 2026-11-12 TC499 模板不带项目信号

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_tc499_template_keeps_the_pin_map_and_drops_the_project`）

## 代价

选 TC499 时打开的是 DHTE400 项目表。端口名 `IA_S/M_TM`、星驱网络、Superevo 和 ATOM 分配会跟着模板进到下一份 HSI。

## 反事实

继续用 DHTE400 当 TC499 模板，下一次原理图出表会把对不上的项目信号、油温和热泵原样留在表里。

## 二级依据

- 确认口径：TC499 模板只留芯片管脚图。项目网络、端口名、阈值和 ATOM 分配不写在模板里。
- DHTE400 端口表 `AN0` 原值是球号 `W13`、功能 `Analog`、端口名 `IA_S/M_TM`。通用模板把球号放在 Ball 列、符号放在 Pin_Symbol 列，端口名为空，并补齐 BGA436 的 436 个球号。
- 选 TC499 时读 `electrical_krow/templates/TC499-HSI.xlsx`。DHTE400 仍是 387、399 的默认底稿。

## 闸门

`test_tc499_template_keeps_the_pin_map_and_drops_the_project`：TC499 模板文件名含 TC499，且不是 DHTE400。端口表有 436 个球号。`AN0` 在 Pin_Symbol 列，球号 `W13` 在 Ball 列，功能仍是 `Analog`，端口名和原理图网络为空。表内不再出现星驱、Superevo、DHTE400、`IA_S/M_TM`、ATOM。
