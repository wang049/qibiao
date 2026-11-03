# 2026-11-03 空框上的黑线清掉

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

清掉模板文字以后，空着的合并单元格还画着黑框。`4-SPI总线` 波特率下面、`5_PMIC-TLF4D985` 的 Function 下面、`6_CAN` 的大片空白区都像还有一张空表。

## 反事实

只处理 SPI、PMIC、ADC 这三处，下一次 `6_CAN` 的 `C2:F28`、`11_Eddy Sense&Diag` 的 `H6:R10`、油温页和低边驱动页的空合并区仍带着黑框。

## 二级依据

- 确认口径：没有字的黑框清掉。有字的表头边框留下。
- `HSI--20261103.xlsx`（20:26）里，空合并区还包括 `6_CAN` 的 `B2:B28` 和 `C2:F28`，`7_Dead Time` 的 `I4:O4`，`13_HVDC` 的 `A7:I7`，`17_变速器油温`、`18_热泵温度传感器`、`23-低边驱动`、`24_充电升压继电器控制`、`25_锁切一体控制`、`26_PSS`、`22_3041寄存器配置表`。
- 这些框来自模板，不是 EDF 或手册读出来的。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：SPI 的 `G4:G8` 不再合并，第 4 行波特率格没有左边框，`PIN` 仍有边框；PMIC 的 `B3:B6` 不再合并，`Function` 仍有边框；CAN 的 `C2:F28` 不再合并。
