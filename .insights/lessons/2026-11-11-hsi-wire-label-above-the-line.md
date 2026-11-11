# 2026-11-11 导线上方的网络名仍算这只脚的

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_net_label_above_the_wire_still_attaches`、`test_schematic_net_follows_the_wire_on_the_pin_side`）

## 代价

网络名写在导线上方时，字心离脚的文字超过 1.6 pt，这只脚的网络名就是空的。ADC、SPI、CAN 因此保持模板原文。

## 反事实

继续只认和脚文字同一高度的字，下一份 `P00.0` 旁边导线上的 `RDY_M_H_GM` 仍读不到。把 5 pt 以外的 `OTHER_M_NET` 也算进来，会配到上一行的网络名。

## 二级依据

- 原理图字号大约 6 pt，网络名贴在导线上时，字心比导线高大约 3 pt。上下两行大约相距 5.3 pt。
- 先找离这只脚 3.2 pt 以内的导线，再在这根导线上下 3.2 pt 里取脚这一侧的网络名。
- 没有 `_` 或 `/` 的字、球号、脚号、另一行的网络名，仍然不采用。读不到时格子保持模板原文。

## 闸门

`test_net_label_above_the_wire_still_attaches`：导线上方的 `RDY_M_H_GM` 记在 `P00.0` 上。更远的 `OTHER_M_NET` 不记。
`test_schematic_net_follows_the_wire_on_the_pin_side`：`P00.0` 仍是 `RDY_M_H_GM`，`P00.8` 仍是 `CSN3_M/T_SPI3`，不取另一侧的名字。
