# 2026-10-27 原理图网表改 HSI 网络名和外部电阻

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_writes_net_and_external_pull_for_review`）

## 代价

有原理图时，HSI 的网络名和外部上拉、下拉仍是模板原值，人要自己对网表。

## 反事实

不读 Altium EDIF，下一次 `PWM_M_AH_GM` 的 K 列仍是 `DPO_DRV_UH_M1`，看不到原理图网络 `PWM_M/D_AH_GM`。把串在信号上的 100Ω 也当成上拉或下拉，会把串联电阻写成外部上下拉。写成已确认，人就不再复核。

## 二级依据

- 会议口径：已有原理图时，由程序改 HSI，再由人工复核。改的是原理图网络名，以及外部上拉、下拉。
- 网表 `DHT160OF_PU_B3V2.EDF`：Altium EDIF。`PWM_M/D_AH_GM` 对端口名 `PWM_M_AH_GM`。`R822A` 为 68kΩ，另一端是 `GND`，是下拉。`R100` 一类 100Ω 另一端不是电源或地，是串联，不写入。
- `CSH_M/D_SPI_TM` 的 `R913A` 为 10kΩ，另一端是 `5V_P_LAC`，是上拉。
- 写入 K 列网络名和「电路外部硬件状态」列。标记说明写器件、阻值和「待人工复核」。对不上的端口名不改。

## 闸门

`test_schematic_writes_net_and_external_pull_for_review`：`PWM_M_AH_GM` 写成 `PWM_M/D_AH_GM` 和下拉 68kΩ，说明含 R822A 和待人工复核，不含 100Ω；`CSH_M_SPI_TM` 写成上拉 10kΩ；`IA_S/M_TM` 原网络名不动。
