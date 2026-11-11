# 2026-11-11 只填复用时不把整行标成待人工复核

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_symbol_follows_body_when_header_is_swapped`、`test_template_highlight_clears_and_written_cell_is_green`）

## 代价

原理图符号上的功能名填进原来空着的复用之后，符号、球号和核对状态一起涂绿，并写成待人工复核。球号、网络名、信号名都没变，打开后像整行都被改过。

## 反事实

继续把复用填写当成整行复核，下一份 `P00.0` 的球号 `K4` 和信号名仍是模板原文，却和 `CAN10_TXD` 一起标绿。球号或网络名真的变了若不标待人工复核，`E19` 和 `NET_A` 就没有核对状态。

## 二级依据

- 流程图：这一行改球号和导线上的网络名。空的复用可以填上，只标这一格。
- 复用原来是空的，并且读到的是功能名而不是脚号时，写入复用并只把这一格标绿。
- 球号变了、网络名变了，或端口名和导线网络名不一致时，才把符号、球号标绿，核对状态写成待人工复核。

## 闸门

`test_schematic_symbol_follows_body_when_header_is_swapped`：空的复用写成 `ERAY0_RXDA2` 并标绿。符号和球号不上绿。核对状态和标记说明为空。端口名仍是 `PWM_M_AH_GM`。
`test_template_highlight_clears_and_written_cell_is_green`：球号改成 `E19`、网络名写成 `NET_A` 时，符号、球号、网络名标绿，核对状态是待人工复核。
