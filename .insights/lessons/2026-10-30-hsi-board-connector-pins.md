# 2026-10-30 功率板按自己的接插件脚出表

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`）

## 代价

功率板网表被拿去对 DHTE400 的 `P02.1`、`AN0`。对不上就整表不改，对上名字又会改错板。

## 反事实

仍先对 MCU 引脚符号，下一次 `DHT160OF_PU_B3V2.EDF` 要么报未修改，要么把 `PWM_M/D_AH_GM` 写进 `P02.1` 那一行。接插件 `J402` 第 20 脚不会自己成为一行。

## 二级依据

- `DHT160OF_PU_B3V2.EDF` 是功率板网表。接插件位号以 J 开头，脚号在 `PortRef`。`J402` 第 20 脚所在网络为 `PWM_M/D_AH_GM`。
- 该文件没有 `P02.1`、`AN0`。DHTE400 只提供表头和封面，端口数据改按接插件脚重写。
- 接到 `GND` 的电阻写成下拉。接到 `5V` 开头网络的电阻写成上拉。方向、球号、复用留空，待人工复核。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：结果里有 `J402.20` 和网络 `PWM_M/D_AH_GM`、下拉 68kΩ；模板原有的 `P02.1`、`AN0` 不再留在端口数据里。
