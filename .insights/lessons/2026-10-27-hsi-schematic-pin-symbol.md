# 2026-10-27 功率板网表不按端口名改 HSI

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`、`test_schematic_writes_net_and_external_pull_for_review`）

## 代价

DHT160 功率板网表里的 `PWM_M/D_AH_GM` 被写成 DHTE400 端口 `PWM_M_AH_GM` 的网络名。两份材料不是同一张图。

## 反事实

仍按端口名把网表套进 HSI，下一次再选 `DHT160OF_PU_B3V2.EDF`，TC499 端口表仍会被改掉 17 行。网表里没有 `P02.1` 这类引脚符号时，端口表应保持原样。

## 二级依据

- `DHT160OF_PU_B3V2.EDF` 是 Altium 功率板网表，没有 `P02.1`、`AN0` 这类 MCU 引脚符号。
- DHTE400 端口表的引脚符号在 B 列。只有网表里出现同一引脚符号，才写入该行的网络名和外部电阻。
- 端口名 `PWM_M_AH_GM` 与网络名 `PWM_M/D_AH_GM` 相近，不能当作同一只引脚。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：网表只有 `PWM_M/D_AH_GM`、没有引脚符号时，不改 `DPO_DRV_UH_M1`，并说明未修改端口表。
`test_schematic_writes_net_and_external_pull_for_review`：网表脚名是 `P02.1`、`P33.13` 时，才写入对应行的网络名和外部电阻。
