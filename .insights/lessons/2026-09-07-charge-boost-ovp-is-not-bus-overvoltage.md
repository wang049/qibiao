# 2026-09-07 充电 Boost 允许过压不是直流母线过压

- 状态：active
- 条目：#9 直流电压过压保护；#62 BOOST最高工作电压
- 闸门：`electrical/tests/test_extract_quality.py`（`test_overvoltage_circuit_analysis_rejected`、`SuperEvoChargeMisbindTests`）；`electrical/extract.py` `_value_fits_field` 拒「允许过压保护」，`add()` 不再把 `高压侧：＞1066V` 写入 #9，#62 只记 `1066V（高压侧满功率上限）`

## 代价

SuperEvo 充电 Boost 表「允许过压保护 高压侧：＞1066V」被填进直流母线过压；「满功率工作 1056V＜U≤1066V」整段进了 BOOST最高。母线工作到 1150V，现场按过压阈值核对会对不上。

## 反事实

不把充电 Boost 过压行从 #9 拿掉、不把 #62 收成满功率上限，下次仍会把桩侧/高压侧充电保护当成整机直流母线过压，并把工作区间误当成最高工作电压定义。

## 二级依据

- 清单 gloss：#9 是直流母线过压保护阈值；充电 Boost「允许过压保护」是充电工况高压侧保护，不是母线过压。
- 用户格子 / SuperEvo DPR：母线工作到 1150V；充电表满功率上限 1066V、允许过压 ＞1066V。
- 原文：`Charging Buck/Boost` 表第 2 行允许过压、第 3 行满功率工作。

## 闸门

- `_value_fits_field("直流电压过压保护")`：摘录含「允许过压保护」→ 拒填。
- `_value_fits_field("BOOST最高")`：值本身是「允许过压保护」或未写上限的 `1056V＜U≤1066` → 拒填。
- 回归：该行不得进 #9；#62 为 `1066V（高压侧满功率上限）`。
