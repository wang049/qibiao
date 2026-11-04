# 2026-11-03 方向列写手册上的输入或输出

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_dhte400_keeps_atom_port_name_cover_and_history`、`test_opposite_direction_is_marked_and_not_confirmed`）

## 代价

手册已经给出 Input 或 Output，Direction 列仍是空的。人要到标记说明里找「手册方向为 Input」。

## 反事实

Direction 继续留空，下一次 TC499 的 `P00.0` 仍看不出手册写的是输入还是输出。若把 `Timer` 写进 Function，会和模板里的 `Analog`、`Digital`、`PWM` 混成一类。

## 二级依据

- 确认口径：Direction 写手册给出的 Input 或 Output。手册没写的留空。模板方向不抄。Function 写手册分类，见 `2026-11-04-hsi-fill-name-and-class`。
- `HSI-TC499-BGA436-1-202611031.xlsx`：435 行里 Direction、Function 都是空的。`P00.0` 的缓冲是 `FAST`，标记说明有「手册分类：Timer」。
- 模板 `DHTE400-HSI-V1.3-20261023.xlsx` 的 Function 抽样是 `Analog`、`Digital`、`PWM`，不是手册分类。

## 闸门

`test_dhte400_keeps_atom_port_name_cover_and_history`：`AN0` 的 Direction 为 `Input`，`P02.1` 为 `Output`。Function 见 `2026-11-04-hsi-fill-name-and-class`。
`test_opposite_direction_is_marked_and_not_confirmed`：方向格为手册的 `Input`，标记说明仍含模板方向 `Output`。
