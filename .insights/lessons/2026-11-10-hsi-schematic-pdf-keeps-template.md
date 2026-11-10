# 2026-11-10 原理图 PDF 归档只改对上的格子

- 状态：active
- 条目：HSI 出表
- 闸门：`tests/test_hsi.py`（`test_schematic_pdf_updates_matched_rows_and_keeps_others`、`test_schematic_pdf_reads_pin_and_ball_on_the_symbol`）

## 代价

有原理图 PDF 时仍整表清空端口行，并清掉封面修改人、变更记录和其他页示例。工程师无法直接拿模板原样归档。

## 反事实

若继续 `_clear_below` 再重写，下一份 PDF 出表会丢掉未出现在原理图上的端口行（如 `AN0`），ADC 页示例和封面修改说明也会被清掉，和「无需修改的内容直接复制」相反。

## 二级依据

- 会议口径：有原理图时 HSI 与模板一致，不改的复制，改的由原理图更新。
- 白板：符号脚（如 `P2.1`）对到模板行；499/387/399 各按模板；SPI 支路也只更新对上的行。
- EDIF 接插件路径仍按旧规则重写端口并清模板身份（见 `2026-11-03-hsi-schematic-drops-template-identity.md`），与 PDF 归档路径分开。

## 闸门

`test_schematic_pdf_updates_matched_rows_and_keeps_others`：原理图只带 `P14.0` 时，模板 `AN0` 行与 Function/端口名保留；`P14.0` 球号与复用更新；封面修改人与变更记录 `v1.3` 保留，并追加本次时间戳；ADC 示例信号名保留。
