# 2026-11-04 球号和引脚符号按表头写入

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_ball_and_symbol_follow_the_column_headers`、`test_dhte400_keeps_atom_port_name_cover_and_history`）

## 代价

DHTE400 表头 B 列是 `BGA436\Ball`，C 列是 `Pin_Symbol`。写出的 `P00.0` 在 B 列，`M6` 在 C 列，和表头相反。

## 反事实

继续按模板正文的位置写，下一次 `P00.0` 仍在球号列下面，`M6` 仍在引脚符号列下面。读模板若改成按表头，`AN0` 会被当成球号，`IA_S/M_TM` 对不上。

## 二级依据

- 确认口径：B、C 两列填反了，按表头互换。B 列是球号，C 列是引脚符号。
- 模板 `DHTE400-HSI-V1.3-20261023.xlsx` 第 3 行 B 为 `BGA436\Ball`、C 为 `Pin_Symbol`。第 4 行正文仍是 `AN0`、`W13`。读这张模板时按正文。
- 生成稿按表头写。`AN0` 的球号 `W13` 在 B 列，符号在 C 列。

## 闸门

`test_ball_and_symbol_follow_the_column_headers`：表头为球号和 Pin_Symbol 时，`M6` 在 B 列，`P00.0` 在 C 列。换成 `TC38x`、`BGA516` 后，标题、`MCU_` 和球号列表头跟着变，不再留着 `TC499`、`BGA436`。
`test_dhte400_keeps_atom_port_name_cover_and_history`：读模板仍得到 `AN0` 和球号 `W13`。写出后 B 列为 `W13`、`F5`，C 列为 `AN0`、`P02.1`。符号上的跳转在 C 列。
