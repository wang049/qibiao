# 2026-10-27 HSI 分两条生成路径

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_revise_hsi_from_schematic_keeps_unmatched_rows`、`test_schematic_writes_net_and_external_pull_for_review`）

## 代价

有原理图时仍要先选芯片手册，生成按钮不亮。没有原理图时也不能只填 MCU 型号新建。

## 反事实

两条路径不分开，下一次只选 `DHT160OF_PU_B3V2.EDF` 仍无法修改 HSI。按 MCU 型号新建若没有单独入口，就会把原理图修改和手册出表混成同一步。

## 二级依据

- 会议口径：已有原理图时修改 HSI，再人工复核。没有原理图时，输入 MCU 型号（如 TC399、TC387、TC324）后按手册新建。
- 按原理图修改不重写整张端口表。对得上的才改网络名和外部电阻，其余行保持原值，并标待人工复核。
- 按 MCU 型号新建仍读当份手册和所选封装，不使用原理图。

## 闸门

`test_revise_hsi_from_schematic_keeps_unmatched_rows`：只改对上的 `PWM_M_AH_GM`，`IA_S/M_TM` 的网络名不动。
`test_schematic_writes_net_and_external_pull_for_review`：下拉、上拉和串联电阻的区分仍有效。
